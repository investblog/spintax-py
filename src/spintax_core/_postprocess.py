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

**Every pattern here is PHP's with `/u`, except one.** `/u` is PCRE2_UCP, so `\\s`, `\\d`,
`\\w` and `\\b` are Unicode classes: NBSP and the thin spaces are whitespace, a letter of
any script is a word character, and any `\\p{Nd}` is a digit. The one exception is the
decimal shield, which the plugin writes WITHOUT `/u` — byte mode, so its `\\b` and `\\d`
stay ASCII. Take the classes from `_charclasses`; the module docstring there has the rule.

This was written on the opposite belief until spintax-js#81 measured it, and that is how
`и т.д.` rendered `и т. Д.`, `пример.рф` split, and a no-break space neither spaced nor
capitalized like a space — in every tree-walk engine, while both PHP engines left them
intact.

**A TLD is a label in ONE case** (spintax-js#79). The bare-domain and email shields took
any `word.Word` for a domain, so a sentence glued to the next one kept its missing space
and its lower-case start: `kept compact.Game categories`, `конец.Начало`. On a production
host's stored content that shape was a sentence start 369 times in 56 tenants and a domain
never. A TLD is now all lower case or all upper case — letters without case (CJK, Arabic,
Thai) fit either — so `example.com`, `ASP.NET`, `info@Example.COM`, `ПРИМЕР.РФ`, `例子.中国`
and a punycode TLD in any case stay whole, while those sentences get their space and their
capital. The accepted cost, pinned by the corpus so nobody files it: `Yandex.Money` renders
`Yandex. Money`, and `info@example.Com` is no longer shielded as an email.

**Two case traps, both of which Python walks into by default.** The domain patterns
therefore carry NO `re.IGNORECASE` at all, and spell out the one part that is caseless —
the punycode prefix and class, U+017F and U+212A included, as PCRE2's caseless `[a-z]`
takes them:

1. **A Unicode property under a case-insensitive flag.** PCRE2 leaves `\\p{Ll}` alone under
   `/i`; Python folds it, as JavaScript does, so a `\\p{Ll}` under `re.IGNORECASE` matches
   capitals. The plugin writes the block-tag capitalizer `/ui` and its `\\p{Ll}` is still
   lower case only — hence `<p>ǅivot</p>` keeping its titlecase digraph. Here only the tag
   NAME is caseless; the letter test is a separate pattern with no flag.
2. **What a caseless `[a-z]` takes.** PCRE2: A–Z plus U+017F and U+212A, not U+0130 or
   U+0131. Python's `re.IGNORECASE` folds the two Turkish dotted/dotless forms in as well,
   so a class spelled that way needs them excluded — or, as here, no flag and both cases
   written out.

**The shields and the capitalizers are scanners, not `re.sub` calls.** `re` retries a
failed pattern from the next position, so a pattern that consumes a long run before failing
is quadratic in the run — and this stage is handed untrusted text, which a few hundred
bytes of macros can expand into. Measured here before the rewrite: `<p>` × 20 000 took
23.9 s, `"\\n "` × 20 000 took 30.9 s, 100 000 form feeds 25.8 s, 32 000 dots before a digit
12.0 s, and `"a."` × 2 000 412 ms. The UCP move widens three of those triggers — an NBSP or
U+3000 run was fast only because the ASCII class could not see it — and the one-case TLD
adds another, because rejecting `Game` turns `a.a.…a.Game` into a chain retried from every
label. Each scanner tries the same pattern at the same starts, in the same order, and skips
only starts that provably fail; every one of those shapes is milliseconds now.

(The 0.4.0 docstring recorded the domain re-scan as a won't-fix, on the grounds that
`@spintax/core` did not hit it and so had no answer to port. That premise is gone: the
reference hit it, and these scanners are its answer.)

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
contract to preserve, it is a corruption: `ABBR_1 т.д.URL_0ftp://f.org/z` comes back as
`ABBR_1 \x00ABBR_1ftp://f.org/zURL_0\x00`, with raw NULs. So the single pass is not
merely faster, and the fast path is chosen on the input rather than on the algorithm: it
runs whenever the input carries no `\x00`, which is all real input, and the loop survives
for the ambiguous corner where the delimiters no longer pair as the shield placed them.

**Why the guard is enough.** With no `\x00` in the input, every `\x00` in the working
text is one the shield placed, so the keys are well formed, uniquely numbered and
disjoint. Passes 6–11 cannot break one open either: the spacing rules match only whitespace
and `,;:!?.`, and the capitalization rules re-emit every character verbatim but one `Ll`
they upper-case — a key contains none of those. And nothing can inject text between the
check and the shield, because the check is the first statement of the function and
`_pipeline` calls it on fully rendered text.

Both branches are pinned against the reference in `tests/data/postprocess_parity.json`.
`@spintax/core` guards the same way, on the same condition. Measured over spintax-js#52's
shared 234 256-input sweep: 0 divergences from the reference; the guard is load-bearing at
7 955 unguarded, matching the reference's own count.

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
"""

from __future__ import annotations

import re
from array import array
from collections.abc import Callable
from typing import Literal, get_args

from ._charclasses import (
    ASCII_DIGIT,
    JS_LETTER,
    JS_LETTER_OR_NUMBER,
    JS_LOWERCASE_LETTER,
    JS_SPACE,
    JS_WORD_BOUNDARY,
    NOT_LOWERCASE_LETTER,
    NOT_UPPERCASE_LETTER,
    UCP_SPACE,
    UCP_SPACE_CHARS,
    UCP_WORD,
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

#: PCRE2 UCP whitespace — what `\s` means in every pattern of this stage.
_WS = UCP_SPACE
_S = f"[{_WS}]"

#: `\b` in front of a pattern that begins with a word character: the character before is
#: not one. Equivalent to PHP's leading `\b` there, and one lookbehind instead of two
#: alternatives.
_AFTER_NON_WORD = f"(?<![{UCP_WORD}])"
#: `\b` in general — a TLD can end in `-`, so the boundary after a domain can go either way.
_WORD_BOUNDARY = (
    f"(?:(?<=[{UCP_WORD}])(?![{UCP_WORD}])|(?<![{UCP_WORD}])(?=[{UCP_WORD}]))"
)

#: A punycode label as the plugin reads `xn--` under `i`: either case, and the two
#: non-ASCII letters that fold into `[a-z]` — U+017F LONG S and U+212A KELVIN SIGN. Spelled
#: out, because the domain patterns carry no `re.IGNORECASE` (see the module docstring).
_XN = "[xX][nN]--"
_LABEL = f"(?:{_XN})?{JS_LETTER_OR_NUMBER}+(?:-{JS_LETTER_OR_NUMBER}+)*"
#: `\p{Ll}\p{Lm}\p{Lo}` and `\p{Lu}\p{Lt}\p{Lm}\p{Lo}`, and each with `\p{N}` and `-` added
#: — unions Python cannot write inside `[…]`, so they are the whole letter (or letter-or-
#: number) class with the other case subtracted. See `_charclasses.NOT_UPPERCASE_LETTER`.
_TLD_LOWER = f"{NOT_UPPERCASE_LETTER}{JS_LETTER}"
_TLD_LOWER_BODY = f"(?:-|{NOT_UPPERCASE_LETTER}{JS_LETTER_OR_NUMBER})"
_TLD_UPPER = f"{NOT_LOWERCASE_LETTER}{JS_LETTER}"
_TLD_UPPER_BODY = f"(?:-|{NOT_LOWERCASE_LETTER}{JS_LETTER_OR_NUMBER})"
_TLD = (
    f"(?:{_XN}[a-zA-Z0-9\\-\\u017f\\u212a]{{2,59}}"
    f"|{_TLD_LOWER}{_TLD_LOWER_BODY}{{1,62}}"
    f"|{_TLD_UPPER}{_TLD_UPPER_BODY}{{1,62}})"
)
_DOMAIN_PART = f"(?:{_LABEL}\\.)+{_TLD}"

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

#: `[a-z0-9._%+-]` as the plugin's email pattern reads it under `iu`: both cases, and the
#: two non-ASCII letters that fold into the class.
_EMAIL_LOCAL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-ſK"
)
#: The domain half of the email shield, matched AT a given position (PHP's `\bDOMAIN\b`
#: after the `@`). Anchored by `re.match(text, pos)`, which is JavaScript's `y` flag.
_DOMAIN_AT_RE = re.compile(f"{_DOMAIN_PART}{_WORD_BOUNDARY}")
#: The bare-domain shield as ONE scanning pattern: it matches at exactly the starts the
#: plugin's `\bDOMAIN\b` is tried at (a word character not preceded by one — every label
#: begins with one); group 1 is a domain, and when there is none the whole match is the
#: chain of labels to skip past. An attempt that fails at the start of a chain `a.b-c.d…`
#: fails at every later start in that chain too, because prefixing the chain's own labels
#: to a match further in is a match here.
_DOMAIN_SCAN_RE = re.compile(
    f"{_AFTER_NON_WORD}(?:({_DOMAIN_PART}{_WORD_BOUNDARY})|(?:{_LABEL}\\.)*{_LABEL})"
)
#: Every domain holds a dot followed by the first character of a label; most prose holds none.
_DOMAIN_DOT_RE = re.compile(f"\\.{JS_LETTER_OR_NUMBER}")

#: The plugin's decimal shield is the ONE pattern of this stage without `/u` — byte mode,
#: so its `\b` and `\d` are ASCII, as JavaScript's are under any flag. Deliberately not
#: widened with the rest.
_DECIMAL_RE = re.compile(
    f"{JS_WORD_BOUNDARY}{ASCII_DIGIT}+\\.{ASCII_DIGIT}+{JS_WORD_BOUNDARY}"
)
_MULTI_ABBR_RE = re.compile(f"{_AFTER_NON_WORD}(?:(?:{JS_LETTER}){{1,2}}\\.{_S}*){{2,}}")
_SINGLE_ABBR_RE = re.compile(
    f"(?<!{JS_LETTER_OR_NUMBER})"
    f"(?:{'|'.join(js_ci_unicode(a) for a in SINGLE_ABBREVS)})\\.(?={_S}|\\Z|<)",
    re.IGNORECASE,
)

#: The run of `.,;:!` that a shielded value must give back. A loop, not `([.,;:!]+)\Z`: an
#: end-anchored run class is retried from every dot inside a long URL.
_TRAILING_PUNCT = ".,;:!"

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
#: The lead's single-character tokens, for the scanner that walks it.
_LEAD_CHARS = UCP_SPACE_CHARS | frozenset(SENTENCE_OPENERS)

_DOUBLE_SPACE_RE = re.compile(r"[ \t]{2,}")
#: A match may start only where a whitespace run starts. The same matches — every start
#: inside a run reaches the same end, so the run's first character is the leftmost match or
#: there is none — but a run NOT followed by punctuation is then scanned once instead of
#: once per character. 100 000 form feeds took 25.8 s without the guard, and the UCP class
#: gives NBSP and U+3000 runs the same trigger.
_SPACE_BEFORE_PUNCT_RE = re.compile(f"(?<!{_S}){_S}+([,;:!?.])")
#: `\d` is `\p{Nd}` in both dialects — the digit here is UCP, unlike the decimal shield's.
_SPACE_AFTER_COMMA_RE = re.compile(f"([,;:])(?!\\d)(?!{_S}|\\Z|<)")
#: A run of sentence punctuation is ONE sentence end. `...` and `?!` have to survive
#: intact, so the space goes after the whole run. The `(?![.!?])` is what completes the
#: run: a greedy `+` alone still backtracks INTO it to satisfy the lookaheads, turning
#: `Wow!!!` into `Wow!! !`. And `(?<![.!?])` is the run-start guard again — every start
#: inside a run reaches the same end and the same lookaheads, so a run followed by a digit
#: or a space was otherwise rejected once per mark: 32 000 dots before a digit took 12.0 s.
_SPACE_AFTER_SENTENCE_RE = re.compile(
    f"(?<![.!?])([.!?]+)(?![.!?])(?!\\d)(?!{_S}|\\Z|<)"
)
#: An opener binds to the word it opens: `¿ qué tal ?` becomes `¿qué tal?`. MUST run before
#: capitalization, so those rules see a letter rather than a space.
_SPACE_AFTER_OPENER_RE = re.compile(f"([{SENTENCE_OPENERS}]){_S}+")

#: `.`, `!`, `?` and `…` — the boundaries of the sentence capitalizer.
_SENTENCE_END_SCAN_RE = re.compile("[.!?…]")
#: Only the tag NAME is caseless. The `\p{Ll}` test is `_lower_re()`, a separate pattern
#: with no flag, because Python folds a property under `re.IGNORECASE` and PCRE2 does not.
_BLOCK_TAG_NAME_RE = re.compile(
    f"</?(?:p|h[1-6]|{js_ci_unicode('li')}|blockquote|{js_ci_unicode('div')}|td|th)",
    re.IGNORECASE,
)

#: The capitalization rules need an EXACT `\p{Ll}`, which is why `_charclasses` bakes the
#: table. Matching any letter and filtering in the callback is not equivalent: a broadened
#: match still CONSUMES its region, so reaching an uppercase letter through an HTML tag
#: swallows a lowercase one further in that the narrow pattern would have capitalised.
#: Found by differential fuzzing after that exact reasoning had been written down as safe.
#:
#: **Held as strings and compiled on first use.** Each embeds the 7,800-character `Ll`
#: class, and a consumer using only `validate()` (an editor, a linter) never renders and
#: should not pay for the cosmetic pass at import.
_CAP_FIRST_SRC = f"\\A({_LEAD})({JS_LOWERCASE_LETTER})"
_CAP_FIRST_RE: re.Pattern[str] | None = None
_LOWER_RE: re.Pattern[str] | None = None


def _cap_first_re() -> re.Pattern[str]:
    global _CAP_FIRST_RE
    if _CAP_FIRST_RE is None:
        _CAP_FIRST_RE = re.compile(_CAP_FIRST_SRC)
    return _CAP_FIRST_RE


def _lower_re() -> re.Pattern[str]:
    global _LOWER_RE
    if _LOWER_RE is None:
        _LOWER_RE = re.compile(JS_LOWERCASE_LETTER)
    return _LOWER_RE


#: JavaScript's `String.prototype.trim`, which strips its own whitespace set — not
#: Python's, and not the UCP set used everywhere else in this file. The final trim is the
#: one place this engine is a JavaScript port rather than a PHP one, and the reference
#: records it as its single remaining divergence from the PHP engines.
_JS_TRIM_RE = re.compile(f"\\A{JS_SPACE}+|{JS_SPACE}+\\Z")


def _trailing_punctuation_start(value: str) -> int:
    """Where the run of `.,;:!` that ends `value` starts."""
    cut = len(value)
    while cut > 0 and value[cut - 1] in _TRAILING_PUNCT:
        cut -= 1
    return cut


def _shield_emails(text: str, shield: Callable[[str], str]) -> str:
    """The plugin's `[a-z0-9._%+\\-]+@DOMAIN\\b`, run as a scanner.

    Every start inside one run of local-part characters reaches the same end — the class
    holds no `@` — so the run's first start matches or none does, and a failed run is
    skipped whole. That makes the `@` the thing to look for: the only run that can match is
    the one ending at it.
    """
    out: list[str] = []
    emitted = 0
    # Where the run search may resume: after the last shield, and past every `@` already tried.
    pos = 0
    at = text.find("@")
    while at != -1:
        # The run of local-part characters ending at this `@`, begun no earlier than the
        # scan could begin it.
        start = at
        while start > pos and text[start - 1] in _EMAIL_LOCAL_CHARS:
            start -= 1
        if start != at:  # a run ends here, so an attempt is made at it
            m = _DOMAIN_AT_RE.match(text, at + 1)
            if m is not None:
                out.append(text[emitted:start])
                out.append(shield(text[start : m.end()]))
                emitted = pos = m.end()
        at = text.find("@", max(at + 1, pos))
    if emitted == 0:
        return text
    out.append(text[emitted:])
    return "".join(out)


def _shield_domains(text: str, shield: Callable[[str], str]) -> str:
    """The plugin's `\\bDOMAIN\\b`, run as a scanner — see `_DOMAIN_SCAN_RE`."""
    if _DOMAIN_DOT_RE.search(text) is None:
        return text
    out: list[str] = []
    emitted = 0
    for m in _DOMAIN_SCAN_RE.finditer(text):
        found = m.group(1)
        if found is not None:
            out.append(text[emitted : m.start()])
            out.append(shield(found))
            emitted = m.start() + len(found)
    if emitted == 0:
        return text
    out.append(text[emitted:])
    return "".join(out)


#: Lead steps walked one character at a time before the lead index is built.
_LEAD_WALK = 32


class _Leads:
    """`lead_end[i]` — where the lead that starts at `i` ends — built once per text.

    What makes a scanner exact is that the lead has ONE reading. An opener or a whitespace
    character is a token of one character; a tag is `<`, at least one character that is not
    `>`, then the FIRST `>` — `[^>]+` cannot cross a `>`, so a tag ends where the next `>`
    is, and a `<` followed at once by `>`, or by no `>` at all, is no tag. Every shorter run
    of tokens ends before a `<`, an opener or a space, none of which is `\\p{Ll}`, so a start
    matches exactly when the character after its LONGEST lead is a lowercase letter.

    Built lazily and shared by the three passes: the passes only change the case of letters,
    and no uppercase mapping is shorter than its letter, so a text of the same length has
    every `<`, `>`, opener and space where the index saw them. A letter that GREW (`ß` → `SS`)
    invalidates it, which the length check catches.
    """

    __slots__ = ("_index", "_length")

    def __init__(self) -> None:
        self._index: array[int] | None = None
        self._length = -1

    def of(self, text: str) -> array[int]:
        if self._index is None or self._length != len(text):
            self._index = _index_leads(text)
            self._length = len(text)
        return self._index


def _index_leads(text: str) -> array[int]:
    """Where each position's lead ends, indexed from the right in one pass."""
    n = len(text)
    lead_end = array("i", [0]) * (n + 1)
    lead_end[n] = n
    gt = -1  # the first `>` after the position being indexed
    for i in range(n - 1, -1, -1):
        ch = text[i]
        token_end = -1
        if ch in _LEAD_CHARS:
            token_end = i + 1
        elif ch == "<" and gt > i + 1:
            token_end = gt + 1
        lead_end[i] = i if token_end == -1 else lead_end[token_end]
        if ch == ">":
            gt = i
    return lead_end


def _lead_end_from(text: str, i: int, leads: _Leads) -> int:
    """Where the lead starting at `i` ends.

    Openers and whitespace are one character each, so a short lead is walked; a tag, or a
    lead longer than `_LEAD_WALK`, is answered by the index, built once per text when first
    needed. Walking every lead in full would read a run of line breaks once per break —
    each one starts a lead that holds the rest.
    """
    n = len(text)
    j = i
    steps = 0
    while steps < _LEAD_WALK and j < n:
        ch = text[j]
        if ch == "<":
            return leads.of(text)[j]
        if ch not in _LEAD_CHARS:
            return j
        j += 1
        steps += 1
    return leads.of(text)[j] if j < n else j


#: A boundary finder answers "where does the lead start for the first boundary at or after
#: `frm`, and where should the search resume" — or `None` when there is no boundary left.
_Boundary = Callable[[str, int], "tuple[int, int] | None"]


def _after_sentence_end(text: str, frm: int) -> tuple[int, int] | None:
    m = _SENTENCE_END_SCAN_RE.search(text, frm)
    return None if m is None else (m.start() + 1, m.start() + 1)


def _after_line_break(text: str, frm: int) -> tuple[int, int] | None:
    at = text.find("\n", frm)
    return None if at == -1 else (at + 1, at + 1)


def _after_block_tag() -> _Boundary:
    """The block-tag pass asks for the first `>` after each tag name, at positions that
    only grow: one scan."""
    gt_from = -1
    gt = -1

    def nxt(text: str, frm: int) -> tuple[int, int] | None:
        nonlocal gt_from, gt
        lt = text.find("<", frm)
        while lt != -1:
            m = _BLOCK_TAG_NAME_RE.match(text, lt)
            if m is not None:
                name_end = m.end()
                if gt_from == -1 or name_end < gt_from or (gt != -1 and name_end > gt):
                    gt_from = name_end
                    gt = text.find(">", name_end)
                if gt != -1:
                    return (gt + 1, lt + 1)
            lt = text.find("<", lt + 1)
        return None

    return nxt


def _capitalize_after(text: str, next_boundary: _Boundary, leads: _Leads) -> str:
    """One capitalizer pass: for each boundary `next_boundary` finds, upper-case the
    `\\p{Ll}` at the end of the lead after it.

    After a match the search resumes behind the letter, as a global replace does. The
    passes find their boundaries natively — a punctuation scan, a `<` scan, a `\\n` scan —
    instead of testing every character, which is what keeps the lead out of the pattern:
    `.<` repeated with no `>` to close a tag, or `<p>` repeated with no letter after, made
    the regex form rescan the lead from every start.
    """
    lower = _lower_re()
    out: list[str] = []
    emitted = 0
    frm = 0
    n = len(text)
    while True:
        boundary = next_boundary(text, frm)
        if boundary is None:
            break
        lead_start, frm = boundary
        at = _lead_end_from(text, lead_start, leads)
        if at >= n:
            continue
        ch = text[at]
        if lower.match(ch) is None:
            continue
        out.append(text[emitted:at])
        out.append(ch.upper())
        emitted = at + 1
        frm = emitted
    if emitted == 0:
        return text
    out.append(text[emitted:])
    return "".join(out)


def _capitalize_first(match: re.Match[str]) -> str:
    """Upper-case the last group, keeping everything the pattern matched before it.

    No category check here — the pattern already guarantees the letter is `Ll`. `str.upper`
    rather than `str.capitalize` because a single character can upper-case to two, and `ß`
    becoming `SS` is what the reference does too.
    """
    return match.group(1) + match.group(2).upper()


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
        cut = _trailing_punctuation_start(value)
        if cut == len(value):
            return store(value, prefix)
        return value if cut == 0 else store(value[:cut], prefix) + value[cut:]

    def store_uri(m: re.Match[str]) -> str:
        prefix: ShieldPrefix = "URI" if _MAILTEL_PREFIX_RE.match(m.group()) else "URL"
        return store_with_trailing_punct(m.group(), prefix)

    # 1-5: shield. URIs in one pass, and before email and domain so the whole one survives.
    text = _URI_RE.sub(store_uri, text)
    text = _shield_emails(text, lambda m: store(m, "EMAIL"))
    text = _shield_domains(text, lambda m: store(m, "DOM"))
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

    # 8: capitalize the first letter (skipping leading HTML tags and sentence openers).
    # `count=1` mirrors a JavaScript `replace` without `/g`. Redundant under the `\A`
    # anchor, and kept because the anchor is what makes it redundant.
    text = _cap_first_re().sub(_capitalize_first, text, count=1)
    # 9-11: capitalize after sentence punctuation, after a block-level tag, after a line
    # break. One lead index serves all three.
    leads = _Leads()
    text = _capitalize_after(text, _after_sentence_end, leads)
    text = _capitalize_after(text, _after_block_tag(), leads)
    text = _capitalize_after(text, _after_line_break, leads)

    # 12: restore, then trim. See the module docstring for why this is two restores.
    if caller_wrote_nul:
        for key, value in placeholders.items():
            text = text.replace(key, value)
    else:
        text = _PLACEHOLDER_RE.sub(lambda m: placeholders.get(m.group(), m.group()), text)
    return _JS_TRIM_RE.sub("", text)
