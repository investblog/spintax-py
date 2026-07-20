"""The baked Unicode tables must cover every character the running interpreter has.

`_charclasses` carries two generated ranged classes — categories `Nl`+`No` (to subtract
from `[^\\W\\d_]` and land exactly on `\\p{L}`) and category `Ll`. They are baked because
building them means walking all 1.1M code points, which costs about a quarter of a second
and has no business happening at `import`.

Python 3.10 ships Unicode 13.0.0, 3.11 ships 14.0.0, and 3.12+ ship 15.x, so the tables
cannot equal the running `unicodedata` on every supported interpreter — and **should not**.
The reference is JavaScript, whose Unicode version follows its own runtime, not Python's.
Matching whatever Python happens to carry would make the same library answer differently
on 3.10 and 3.13, which is worse than being a version ahead.

So the assertion is not equality. It is the property that actually matters:

    for every character that EXISTS on this interpreter, the baked table is right.

Concretely — nothing the running `unicodedata` calls `Ll` may be missing from the table,
and anything the table has in surplus must be **unassigned** here. Measured: 78 surplus
code points on Python 3.10 and 6 on 3.11, every one of them `Cn`. They are letters added
to Unicode after that interpreter's tables were cut, so no text on that interpreter can
contain them.

If a character that IS assigned turns up on either side, that is real drift: regenerate the
constants, read the diff, and say in the commit which Unicode version moved and what moved.
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


def _assert_covers(matched: set[int], want: set[int], label: str) -> None:
    """The baked class must cover every ASSIGNED character of its category.

    Two different failures, kept apart because they mean opposite things. A *missing* code
    point is always a bug: this interpreter has a character the table does not know. A
    *surplus* one is only a bug when it is assigned here — otherwise it is a letter from a
    newer Unicode than this interpreter carries, which no text here can contain.
    """
    missing = want - matched
    surplus = matched - want
    assigned_surplus = {cp for cp in surplus if unicodedata.category(chr(cp)) != "Cn"}

    def sample(cps: set[int]) -> str:
        return ", ".join(
            f"U+{cp:04X} ({unicodedata.category(chr(cp))})" for cp in sorted(cps)[:8]
        )

    context = (
        f"{label}: unicodedata {unicodedata.unidata_version} on Python "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
    assert not missing, (
        f"{context} has {len(missing)} character(s) the baked table is missing: "
        f"{sample(missing)}. Regenerate the constants."
    )
    assert not assigned_surplus, (
        f"{context} disagrees on {len(assigned_surplus)} ASSIGNED character(s) the baked "
        f"table claims: {sample(assigned_surplus)}. Regenerate the constants."
    )


def test_js_letter_is_exactly_the_letter_categories() -> None:
    """`\\p{L}`. The tempting `[^\\W\\d_]` is off by 1151 code points, because Python's `\\w`
    includes `Nl` and `No` — under it, `²` and `½` are letters."""
    _assert_covers(
        _codepoints_matching(_charclasses.JS_LETTER), _codepoints_in(LETTER_CATEGORIES), "JS_LETTER"
    )


def test_js_letter_or_number_is_exactly_letters_and_numbers() -> None:
    """`[\\p{L}\\p{N}]`, which needs no table: Python's `\\w` decomposes as `L u N u _`, so
    `[^\\W_]` lands on it precisely."""
    _assert_covers(
        _codepoints_matching(_charclasses.JS_LETTER_OR_NUMBER),
        _codepoints_in(LETTER_CATEGORIES | NUMBER_CATEGORIES),
        "JS_LETTER_OR_NUMBER",
    )


def test_js_lowercase_letter_is_exactly_category_ll() -> None:
    """`\\p{Ll}`. No table-free predicate exists — `str.islower()` accepts 311 code points
    outside `Ll`, and every repair built on `upper() != c` fails on U+0138 `ĸ`."""
    _assert_covers(
        _codepoints_matching(_charclasses.JS_LOWERCASE_LETTER),
        _codepoints_in(frozenset({"Ll"})),
        "JS_LOWERCASE_LETTER",
    )


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
