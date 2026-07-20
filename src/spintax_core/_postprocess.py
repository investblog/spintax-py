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
"""

from __future__ import annotations

import re

from ._charclasses import (
    ASCII_DIGIT,
    JS_LETTER,
    JS_LETTER_OR_NUMBER,
    JS_LOWERCASE_LETTER,
    JS_SPACE,
    JS_WORD_BOUNDARY,
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

_URL_RE = re.compile(f"(?:https?|ftp)://[^{_WS}<>\"')\\]]+", re.IGNORECASE)
#: `mailto:` and `tel:` have no `//` authority, so `_URL_RE` misses them. Shielded before
#: the email and domain passes, or the address is carved out from under its own prefix and
#: the bare `mailto:` left behind — then the "space after a colon" rule splits it.
_MAILTEL_RE = re.compile(f"(?:mailto|tel):[^{_WS}<>\"')\\]]+", re.IGNORECASE)
_EMAIL_RE = re.compile(f"[a-z0-9._%+\\-]+@{_DOMAIN_PART}{_B}", re.IGNORECASE)
_DOMAIN_RE = re.compile(f"{_B}{_DOMAIN_PART}{_B}", re.IGNORECASE)
_DECIMAL_RE = re.compile(f"{_B}{ASCII_DIGIT}+\\.{ASCII_DIGIT}+{_B}")
_MULTI_ABBR_RE = re.compile(f"{_B}(?:(?:{JS_LETTER}){{1,2}}\\.{_S}*){{2,}}")
_SINGLE_ABBR_RE = re.compile(
    f"(?<!{JS_LETTER_OR_NUMBER})(?:{'|'.join(SINGLE_ABBREVS)})\\.(?={_S}|\\Z|<)",
    re.IGNORECASE,
)
#: `\Z`, not `$`: the reference has no `m` flag, so it anchors at the very end.
_TRAILING_PUNCT_RE = re.compile(r"([.,;:!]+)\Z")

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
_CAP_FIRST_RE = re.compile(f"\\A({_LEAD})({JS_LOWERCASE_LETTER})")
_CAP_AFTER_SENTENCE_RE = re.compile(f"([.!?…])({_LEAD})({JS_LOWERCASE_LETTER})")
_CAP_AFTER_BLOCK_RE = re.compile(
    f"(</?(?:p|h[1-6]|li|blockquote|div|td|th)[^>]*>{_LEAD})({JS_LOWERCASE_LETTER})",
    re.IGNORECASE,
)
_CAP_AFTER_BREAK_RE = re.compile(f"(\\n{_LEAD})({JS_LOWERCASE_LETTER})")

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
    placeholders: dict[str, str] = {}
    counter = 0

    def store(value: str, prefix: str) -> str:
        nonlocal counter
        key = f"\x00{prefix}_{counter}\x00"
        placeholders[key] = value
        counter += 1
        return key

    def store_with_trailing_punct(value: str, prefix: str) -> str:
        m = _TRAILING_PUNCT_RE.search(value)
        if m:
            suffix = m.group(1)
            body = value[: len(value) - len(suffix)]
            return suffix if body == "" else store(body, prefix) + suffix
        return store(value, prefix)

    # 1-5: shield. mailto:/tel: before email and domain, so the whole URI survives.
    text = _URL_RE.sub(lambda m: store_with_trailing_punct(m.group(), "URL"), text)
    text = _MAILTEL_RE.sub(lambda m: store_with_trailing_punct(m.group(), "URI"), text)
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
    text = _CAP_FIRST_RE.sub(_capitalize, text, count=1)
    text = _CAP_AFTER_SENTENCE_RE.sub(_capitalize, text)
    text = _CAP_AFTER_BLOCK_RE.sub(_capitalize, text)
    text = _CAP_AFTER_BREAK_RE.sub(_capitalize, text)

    # 12: restore, then trim.
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return _JS_TRIM_RE.sub("", text)
