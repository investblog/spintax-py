"""Cosmetic post-process — a faithful port of the plugin's `Parser::post_process`.

**Order is the whole design.** URLs, email addresses, domains, decimals and abbreviations
are shielded to `\\x00…\\x00` placeholders FIRST, so the spacing and capitalization passes
cannot corrupt them, and restored at the end. A domain reached by the "space after a full
stop" rule would become `example. com`; a decimal would become `3. 14`.

This is the COSMETIC stage, gated by `post_process`. The neutralize safety-restore is a
different thing entirely and always runs — see `_pipeline`.

The shielding here uses `\\x00`, and neutralize uses the Private Use Area, precisely so
the two cannot collide. This pass runs while neutralize sentinels are still in place, and
must leave them alone; it must equally leave alone the fullwidth `｛…｝` a lenient plural
emits, which is why that fallback widens its braces rather than keeping ASCII ones.

**The restore is two restores** (step 12, and issue #1). The reference form is one
whole-text replace PER KEY, and every URL, URI, email, domain, decimal and abbreviation
mints a key — so on shield-heavy text the placeholder count grows with the text and the
restore is O(text × placeholders). Measured here: 13 s on 418 KB, 44 s on 950 KB.

One left-to-right pass over the token shape is O(text), and is NOT the same function. A
per-key `str.replace` is a repeated SUBSTRING substitution, not a token substitution: it
rewrites every occurrence of a key, including one that was never minted. Three ways that
shows:

1. the caller's own text spells a key the shield then mints, and is substituted;
2. an unpaired `\x00` from the input pairs with a real placeholder's delimiter;
3. **two real placeholders sandwich caller text that spells a key** — in
   `\x00ABBR_2\x00URL_0\x00URI_1\x00` the closing `\x00` of one token and the opening
   `\x00` of the next make a third occurrence of `\x00URL_0\x00`, which the loop
   substitutes, destroying both real tokens.

(3) needs **no `\x00` in the input at all** — only prose that happens to contain
`ABBR_1` and `URL_0`, which any document about this engine does. There the loop is not a
contract to preserve, it is a corruption: `ABBR_1т.д.URL_0ftp://f.org/z` comes back as
`ABBR_1\x00ABBR_1ftp://f.org/zURL_0\x00`, with raw NULs. So the single pass is not
merely faster, and the fast path is chosen on the input rather than on the algorithm: it
runs whenever the input carries no `\x00`, which is all real input, and the loop survives
for the ambiguous corner where the delimiters no longer pair as the shield placed them.

**Why the guard is enough.** With no `\x00` in the input, every `\x00` in the working
text is one the shield placed, so the keys are well formed, uniquely numbered and
disjoint. Passes 6–11 cannot break one open either: the spacing rules match only ASCII
whitespace and `,;:!?.`, and the capitalization rules re-emit every group verbatim and
upper-case a single `Ll` character — a key contains none of those. And nothing can inject
text between the check and the shield, because the check is the first statement of the
function and `_pipeline` calls it on fully rendered text.

Both branches are pinned against the reference in `tests/data/postprocess_parity.json`.
`@spintax/core` guards the same way, on the same condition — but as unreleased work on top
of 0.3.1, which is why the fixture records a commit as well as a version. Measured over
spintax-js#52's shared 234 256-input sweep: 0 divergences from the reference; the guard is
load-bearing at 7 955 unguarded, matching the reference's own count.

Case (3) is a **deliberate** behaviour change, not a preserved one, and it is the family's
one open seam here — spintax-py#2, spintax-js#54. #52 first recorded "on `\x00`-free input
the single pass is the loop — 50 625 inputs, zero divergences" as a contract; it is a
property of that probe set, whose 15 NUL-free fragments contain nothing that spells a
placeholder key. Add a bare `URL_0` and the zero goes away.

An earlier draft here declined the fast path on case (3) too, to keep the fast path a pure
optimisation. That made this engine the only one returning the loop's wreckage, so it was
dropped: the guard is the input's `\x00` and nothing else, which is what `@spintax/core`
and `spintax/core` do (spintax-php#1). The published PHP, JS and Object Pascal releases
still give the old answer, so this corner is unpinned by the shared corpus and pinned here
instead.

Neither branch rescans a value it inserted, which is what makes them agree even if a stored
value ever came to contain another key. On `\x00`-free input none can: `_URI_BODY` excludes
`\x00` and every other shield class is letters, digits and dots, so no match can span a
placeholder (spintax-js#53). Worth stating because it is the property an ordering change
would quietly take away.

**A second O(n²) remains, and it is not the restore.** `_DOMAIN_RE` and `_EMAIL_RE` are the
cost now, on a long run of dotted labels (`"a."` repeated). A single match attempt is
linear — 5 ms at 12.5 KB — so this is not catastrophic backtracking within a match; it is
`re.sub` re-scanning. The greedy `(?:…\\.)+` in `_DOMAIN_PART` consumes to the end before
failing, and `re.sub` retries that from every word boundary, so O(n) starts × O(n) consume
= O(n²): the whole pass takes ~1.1 s at 3.2 KB (0.85 s in `_DOMAIN_RE`, 0.29 s in
`_EMAIL_RE`), and step 12 no longer figures.

Not fixed here, and the usual fix does not apply: atomic groups / possessive quantifiers
cut *within-match* backtracking, which is already linear, and need Python 3.11 besides
(3.10 is supported). Removing the re-scan means rewriting `_DOMAIN_PART`, which is
parity-pinned to `@spintax/core`'s `DOMAIN_PART` character-for-character — a change that
must be measured against the reference, not reasoned. `@spintax/core` does not hit this at
all (V8's regex engine does not re-scan the same way), so there is no reference answer to
port. The shape is machine-generated, not prose; a host feeding the engine such text should
cap the input or render with `post_process=False`.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

from ._charclasses import (
    ASCII_DIGIT,
    JS_LETTER,
    JS_LETTER_OR_NUMBER,
    JS_LOWERCASE_LETTER,
    JS_SPACE,
    JS_WORD_BOUNDARY,
    NOT_TURKIC,
    js_ci_unicode,
)

#: Single-token abbreviations that would otherwise look like a sentence end. Multi-dot
#: forms (`т.д.`) are handled by `_MULTI_ABBR_RE` instead.
SINGLE_ABBREVS = [
    # Russian editorial / address / unit shorthands.
    "соц", "эл", "см", "ср", "ст", "ул", "пр", "пер", "г", "р", "руб", "коп",
    "тыс", "млн", "млрд", "трлн", "доп", "напр", "прим", "изд", "обл", "респ",
    "стр", "табл", "рис", "мин", "макс", "тел", "факс",
    # English titles / business suffixes / editorial.
    "etc", "vs", "Mr", "Mrs", "Ms", "Dr", "Prof", "Sr", "Jr", "Inc", "Ltd", "Co",
    "Corp", "No", "St", "Ave", "Blvd",
]

#: ASCII whitespace, spelled out. PHP's `\s` and `\b` under `/u` (no PCRE_UCP) are ASCII,
#: so using a Unicode class here would diverge around NBSP and thin spaces.
_WS = " \\t\\r\\n\\f\\x0b"
_S = f"[{_WS}]"

#: JavaScript's `\b`, both ends. A real boundary, not a one-sided lookaround — see
#: `_charclasses.JS_WORD_BOUNDARY` for what checking only one side costs.
_B = JS_WORD_BOUNDARY

_DOMAIN_PART = (
    f"(?:(?:(?:xn--)?{JS_LETTER_OR_NUMBER}+(?:-{JS_LETTER_OR_NUMBER}+)*)\\.)+"
    f"(?:xn--[a-z0-9\\-]{{2,59}}|{JS_LETTER}(?:{JS_LETTER_OR_NUMBER}|-){{1,62}})"
)

#: URIs — `https?`/`ftp` with a `//` authority, and `mailto:`/`tel:` without one — shielded
#: in ONE pass, deliberately, and always before the email and domain passes so the whole
#: address survives (`mailto:` carved out from under its own prefix leaves a bare `mailto:`
#: that the "space after a colon" rule then splits — spintax-js#41).
#:
#: They were two passes until spintax-js#53. A URI body runs to the first delimiter, so the
#: two match sets OVERLAP whenever one URI contains the other's scheme, and the second pass
#: then ran into a placeholder the first had already minted: `mailto:a@x.com?body=see%20
#: https://shop.x.com/cart` shielded the URL, then stored a `mailto:` value with `URL_0`'s
#: key inside it. Neither restore rescans a value it inserted, so a raw U+0000 reached the
#: caller — illegal in XML, U+FFFD to an HTML parser, rejected by Postgres `text`, and a
#: live key again the moment an edit detaches it from the prefix that was shielding it.
#:
#: Neither pass ORDER fixes that: whichever runs second is the one that gets split, and
#: putting `mailto:` first only moves the damage onto a URL whose path carries a `mailto:`
#: (`https://x.io/a.mailto:…` losing its dot to the punctuation pass). One alternation has
#: no second pass to damage — the leftmost match takes the whole token, whichever scheme it
#: is. Measured upstream: the alternation changes 3 212 of the 50 625 NUL-free sweep inputs,
#: exactly the number that leaked before, where reordering changes 4 818.
#:
#: `\x00` stays out of the body class regardless. Nothing is shielded yet when this pass
#: runs, so on ordinary input it never bites; it is there for a caller-supplied U+0000,
#: which would otherwise let a URI match run through the delimiters of a placeholder minted
#: after it.
_URI_BODY = f"[^\\x00{_WS}<>\"')\\]]"
_URI_RE = re.compile(
    f"(?:(?:https?|ftp)://|(?:{js_ci_unicode('mailto')}|tel):){_URI_BODY}+", re.IGNORECASE
)
#: Which prefix a match gets. Kept distinct even though one pass mints both: `URL` and `URI`
#: are what the corpus fixtures and `_PLACEHOLDER_RE` speak.
_MAILTEL_PREFIX_RE = re.compile(f"\\A(?:{js_ci_unicode('mailto')}|tel):", re.IGNORECASE)
# `NOT_TURKIC` on the class, `js_ci` on the literals: under `re.IGNORECASE` an `[a-z]`
# range accepts U+0130 and U+0131, which JavaScript's `/iu` never folds into it.
_EMAIL_RE = re.compile(
    f"(?:{NOT_TURKIC}[a-z0-9._%+\\-])+@{_DOMAIN_PART}{_B}", re.IGNORECASE
)
_DOMAIN_RE = re.compile(f"{_B}{_DOMAIN_PART}{_B}", re.IGNORECASE)
_DECIMAL_RE = re.compile(f"{_B}{ASCII_DIGIT}+\\.{ASCII_DIGIT}+{_B}")
_MULTI_ABBR_RE = re.compile(f"{_B}(?:(?:{JS_LETTER}){{1,2}}\\.{_S}*){{2,}}")
_SINGLE_ABBR_RE = re.compile(
    f"(?<!{JS_LETTER_OR_NUMBER})"
    f"(?:{'|'.join(js_ci_unicode(a) for a in SINGLE_ABBREVS)})\\.(?={_S}|\\Z|<)",
    re.IGNORECASE,
)
#: `\Z`, not `$`: the reference has no `m` flag, so it anchors at the very end.
_TRAILING_PUNCT_RE = re.compile(r"([.,;:!]+)\Z")

#: Every prefix the shield can mint. `store` is typed against it and `_PLACEHOLDER_RE` is
#: built from it, so the two stay in step by construction rather than by memory: a new
#: shield pass whose prefix the restore does not know would otherwise emit a raw
#: `\x00…\x00` to the caller on the fast path, silently and with nothing to catch it.
ShieldPrefix = Literal["URL", "URI", "EMAIL", "DOM", "NUM", "ABBR"]
SHIELD_PREFIXES: tuple[ShieldPrefix, ...] = get_args(ShieldPrefix)

#: Exactly the token shape `store` mints. Anchored on `\x00` at BOTH ends, and never
#: "anything between two `\x00`": on a failed match that shape consumes the whole span and
#: loses sync with the delimiters, which rewrites text no restore should touch — 50× more
#: divergence than this pattern, on the sweep in issue #1.
_PLACEHOLDER_RE = re.compile(rf"\x00(?:{'|'.join(SHIELD_PREFIXES)})_\d+\x00")

#: The inverted marks that OPEN a Spanish question or exclamation.
#:
#: Every other European language only ever CLOSES with punctuation, which is why the
#: spacing and capitalization rules were written as if a sentence begins with a letter. In
#: Spanish it does not: `¿cómo estás?` begins with `¿`, and a capitalizer that upper-cases
#: the first character after a boundary hits a mark with no uppercase form and leaves the
#: real first letter alone.
#:
#: Deliberately NOT widened to quotes, brackets or `«»`: those open AND close, so
#: capitalizing after them would mangle list markers — `Elige. (a) primero` becoming
#: `(A) primero`. This encodes Spanish punctuation, not a general skip-the-non-letters rule.
SENTENCE_OPENERS = "¿¡"

#: Everything that can sit between a sentence boundary and the first letter: HTML tags,
#: sentence openers and whitespace, in any order and any number.
#:
#: One optional opener is not enough. `¡¿Qué haces?!` — the RAE form for a sentence that is
#: both a question and an exclamation — opens with TWO marks, and the opened word is
#: routinely wrapped in markup, which puts a tag after the opener. Whatever the lead misses
#: silently keeps a lowercase first letter.
_LEAD = f"(?:<[^>]+>|[{SENTENCE_OPENERS}]|{_S})*"

_DOUBLE_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(f"{_S}+([,;:!?.])")
_SPACE_AFTER_COMMA_RE = re.compile(f"([,;:])(?!{ASCII_DIGIT})(?!{_S}|\\Z|<)")
#: A run of sentence punctuation is ONE sentence end. `...` and `?!` have to survive
#: intact, so the space goes after the whole run. The `(?![.!?])` is what completes the
#: run: a greedy `+` alone still backtracks INTO it to satisfy the lookaheads, turning
#: `Wow!!!` into `Wow!! !`.
_SPACE_AFTER_SENTENCE_RE = re.compile(
    f"([.!?]+)(?![.!?])(?!{ASCII_DIGIT})(?!{_S}|\\Z|<)"
)
#: An opener binds to the word it opens: `¿ qué tal ?` becomes `¿qué tal?`. MUST run before
#: capitalization, so those rules see a letter rather than a space.
_SPACE_AFTER_OPENER_RE = re.compile(f"([{SENTENCE_OPENERS}]){_S}+")

#: The capitalization rules need an EXACT `\p{Ll}`, which is why `_charclasses` bakes the
#: table. Matching any letter and filtering in the callback is not equivalent: a broadened
#: match still CONSUMES its region, so reaching an uppercase letter through an HTML tag
#: swallows a lowercase one further in that the narrow pattern would have capitalised.
#: Found by differential fuzzing after that exact reasoning had been written down as safe.
#:
#: **Held as strings and compiled on first use.** Each embeds the 7,800-character `Ll`
#: class, and compiling the four costs 27 ms — 27 of the 31 ms this module took at import,
#: on a package that imports in 130. A consumer using only `validate()` (an editor, a
#: linter) never renders and should not pay for the cosmetic pass.
_CAP_SOURCES = (
    f"\\A({_LEAD})({JS_LOWERCASE_LETTER})",
    f"([.!?…])({_LEAD})({JS_LOWERCASE_LETTER})",
    f"(</?(?:p|h[1-6]|{js_ci_unicode('li')}|blockquote|{js_ci_unicode('div')}|td|th)"
    f"[^>]*>{_LEAD})({JS_LOWERCASE_LETTER})",
    f"(\\n{_LEAD})({JS_LOWERCASE_LETTER})",
)
_CAP_FLAGS = (0, 0, re.IGNORECASE, 0)
_CAP_RULES: tuple[re.Pattern[str], ...] | None = None


def _cap_rules() -> tuple[re.Pattern[str], ...]:
    """The four capitalization patterns, compiled once, on the first render that needs them."""
    global _CAP_RULES
    if _CAP_RULES is None:
        _CAP_RULES = tuple(
            re.compile(src, flags) for src, flags in zip(_CAP_SOURCES, _CAP_FLAGS, strict=True)
        )
    return _CAP_RULES

#: JavaScript's `String.prototype.trim`, which strips its own whitespace set — not
#: Python's, and not the ASCII set used everywhere else in this file.
_JS_TRIM_RE = re.compile(f"\\A{JS_SPACE}+|{JS_SPACE}+\\Z")


def _capitalize(match: re.Match[str]) -> str:
    """Upper-case the last group, keeping everything the pattern matched before it.

    No category check here — the pattern already guarantees the letter is `Ll`. `str.upper`
    rather than `str.capitalize` because a single character can upper-case to two, and `ß`
    becoming `SS` is what the reference does too.
    """
    groups = match.groups()
    return "".join(groups[:-1]) + groups[-1].upper()


def post_process(text: str) -> str:
    # Decided BEFORE shielding, and this is the only place it can be decided: once the
    # placeholders are in, a `\x00` the caller wrote is indistinguishable from one the
    # shield placed. See the module docstring for what it buys.
    caller_wrote_nul = "\x00" in text

    placeholders: dict[str, str] = {}
    counter = 0

    def store(value: str, prefix: ShieldPrefix) -> str:
        nonlocal counter
        key = f"\x00{prefix}_{counter}\x00"
        placeholders[key] = value
        counter += 1
        return key

    def store_with_trailing_punct(value: str, prefix: ShieldPrefix) -> str:
        m = _TRAILING_PUNCT_RE.search(value)
        if m:
            suffix = m.group(1)
            body = value[: len(value) - len(suffix)]
            return suffix if body == "" else store(body, prefix) + suffix
        return store(value, prefix)

    def store_uri(m: re.Match[str]) -> str:
        prefix: ShieldPrefix = "URI" if _MAILTEL_PREFIX_RE.match(m.group()) else "URL"
        return store_with_trailing_punct(m.group(), prefix)

    # 1-5: shield. URIs in one pass, and before email and domain so the whole one survives.
    text = _URI_RE.sub(store_uri, text)
    text = _EMAIL_RE.sub(lambda m: store(m.group(), "EMAIL"), text)
    text = _DOMAIN_RE.sub(lambda m: store(m.group(), "DOM"), text)
    text = _DECIMAL_RE.sub(lambda m: store(m.group(), "NUM"), text)
    text = _MULTI_ABBR_RE.sub(lambda m: store(m.group(), "ABBR"), text)
    text = _SINGLE_ABBR_RE.sub(lambda m: store(m.group(), "ABBR"), text)

    # 6: collapse duplicate spaces and tabs.
    text = _DOUBLE_SPACE_RE.sub(" ", text)

    # 7: punctuation spacing.
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_AFTER_COMMA_RE.sub(r"\1 ", text)
    text = _SPACE_AFTER_SENTENCE_RE.sub(r"\1 ", text)
    # 7a: an opener binds to its word. Before capitalization, deliberately.
    text = _SPACE_AFTER_OPENER_RE.sub(r"\1", text)

    # 8-11: capitalization — first letter, after sentence punctuation, after a block-level
    # tag, after a line break.
    cap_first, cap_after_sentence, cap_after_block, cap_after_break = _cap_rules()
    # `count=1` mirrors a JavaScript `replace` without `/g`. Redundant under the `\A`
    # anchor, and kept because the anchor is what makes it redundant.
    text = cap_first.sub(_capitalize, text, count=1)
    text = cap_after_sentence.sub(_capitalize, text)
    text = cap_after_block.sub(_capitalize, text)
    text = cap_after_break.sub(_capitalize, text)

    # 12: restore, then trim. See the module docstring for why this is two restores.
    if caller_wrote_nul:
        for key, value in placeholders.items():
            text = text.replace(key, value)
    else:
        text = _PLACEHOLDER_RE.sub(lambda m: placeholders.get(m.group(), m.group()), text)
    return _JS_TRIM_RE.sub("", text)
