"""The baked Unicode tables must still match the interpreter running them.

`_charclasses` carries two generated ranged classes — categories `Nl`+`No` (to subtract
from `[^\\W\\d_]` and land exactly on `\\p{L}`) and category `Ll`. They are baked because
building them means walking all 1.1M code points, which costs about a quarter of a second
and has no business happening at `import`.

The price of baking is that they are frozen to one Unicode version, and Python 3.10 and
3.13 do not ship the same one. This rebuilds both from the running `unicodedata` and fails
if they have drifted — so the four-interpreter CI matrix turns a silent wrong answer about
some superscript into a named test failure with instructions.

If this fails: regenerate the constants, read the diff, and say in the commit which
Unicode version moved and what it moved.
"""

from __future__ import annotations

import re
import sys
import unicodedata

import pytest

from spintax_core import _charclasses

LETTER_CATEGORIES = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo"})
NUMBER_CATEGORIES = frozenset({"Nd", "Nl", "No"})


def _codepoints_matching(pattern: str) -> set[int]:
    rx = re.compile(pattern)
    return {cp for cp in range(sys.maxunicode + 1) if rx.fullmatch(chr(cp))}


def _codepoints_in(categories: frozenset[str]) -> set[int]:
    return {
        cp
        for cp in range(sys.maxunicode + 1)
        if unicodedata.category(chr(cp)) in categories
    }


def _report(missing: set[int], extra: set[int]) -> str:
    def sample(cps: set[int]) -> str:
        return ", ".join(
            f"U+{cp:04X} ({unicodedata.category(chr(cp))})" for cp in sorted(cps)[:8]
        )

    return (
        f"unicodedata {unicodedata.unidata_version} on Python "
        f"{sys.version_info.major}.{sys.version_info.minor} disagrees with the baked table. "
        f"missing {len(missing)}: {sample(missing)}; extra {len(extra)}: {sample(extra)}"
    )


def test_js_letter_is_exactly_the_letter_categories() -> None:
    """`\\p{L}`. The tempting `[^\\W\\d_]` is off by 1151 code points, because Python's `\\w`
    includes `Nl` and `No` — under it, `²` and `½` are letters."""
    matched = _codepoints_matching(_charclasses.JS_LETTER)
    want = _codepoints_in(LETTER_CATEGORIES)
    assert matched == want, _report(want - matched, matched - want)


def test_js_letter_or_number_is_exactly_letters_and_numbers() -> None:
    """`[\\p{L}\\p{N}]`, which needs no table: Python's `\\w` decomposes as `L u N u _`, so
    `[^\\W_]` lands on it precisely."""
    matched = _codepoints_matching(_charclasses.JS_LETTER_OR_NUMBER)
    want = _codepoints_in(LETTER_CATEGORIES | NUMBER_CATEGORIES)
    assert matched == want, _report(want - matched, matched - want)


def test_js_lowercase_letter_is_exactly_category_ll() -> None:
    """`\\p{Ll}`. No table-free predicate exists — `str.islower()` accepts 311 code points
    outside `Ll`, and every repair built on `upper() != c` fails on U+0138 `ĸ`."""
    matched = _codepoints_matching(_charclasses.JS_LOWERCASE_LETTER)
    want = _codepoints_in(frozenset({"Ll"}))
    assert matched == want, _report(want - matched, matched - want)


@pytest.mark.parametrize(
    ("char", "is_letter"),
    [("a", True), ("Я", True), ("ß", True), ("ĸ", True), ("²", False), ("½", False),
     ("Ⅷ", False), ("5", False), ("_", False), (" ", False)],
)
def test_the_specific_characters_that_motivated_the_table(char: str, is_letter: bool) -> None:
    """Named cases, so a failure above is readable without decoding code points."""
    assert bool(re.fullmatch(_charclasses.JS_LETTER, char)) is is_letter


def test_the_js_word_boundary_needs_a_transition() -> None:
    """Not a one-sided lookaround. Both sides matter, and out-of-string counts as non-word.

    Getting this wrong shielded `приме.com` as a domain here while the reference left it
    alone — 64 differential failures from one line.
    """
    boundary = re.compile(_charclasses.JS_WORD_BOUNDARY)
    # A boundary exists between a word character and a non-word one, in either order.
    assert boundary.match("a.", 1)
    assert boundary.match(".a", 1)
    assert boundary.match("a", 0)
    assert boundary.match("a", 1)
    # And NOT between two non-word characters — which, for JavaScript, includes every
    # letter outside ASCII.
    assert not boundary.match("..", 1)
    assert not boundary.match("п.", 0)
    assert not boundary.match(".п", 1)
