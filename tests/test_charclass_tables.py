"""The baked Unicode tables must cover every character the running interpreter has.

`_charclasses` carries four generated ranged classes, each standing in for a property
Python's `re` cannot name:

- `Nl`+`No`, subtracted from `[^\\W\\d_]` to land exactly on `\\p{L}`;
- `Ll`, which has no table-free predicate at all;
- `Mn`+`Pc`, added to `\\w` to make PCRE2's UCP `\\w`;
- `Lu`+`Lt`, subtracted from `\\p{L}` to make `\\p{Ll}\\p{Lm}\\p{Lo}` — the one-case TLD of
  spintax-js#79 — and from `\\p{L}\\p{N}` for its body class.

They are baked because building them means walking all 1.1M code points, which costs about
a quarter of a second and has no business happening at `import`.

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
to Unicode after that interpreter's tables were cut.

Surplus is tolerated because of what the tables are FOR, not because such characters
cannot appear — `chr(0x2FE0)` is a perfectly ordinary Python string either way. It is
tolerated because the table tracks the reference's Unicode version rather than Python's,
so being a version ahead is the intended state; a newer letter classified as a letter is
the answer the reference would give.

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


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


#: Is the running interpreter's Unicode older than the one the tables were baked from?
_TABLES_ARE_AHEAD = _version(unicodedata.unidata_version) < _version(
    _charclasses.TABLES_UNICODE_VERSION
)


def _assert_covers(matched: set[int], want: set[int], label: str) -> None:
    """The baked class must cover every ASSIGNED character of its category.

    THREE outcomes, kept apart because they mean different things.

    A *surplus* code point is only a bug when it is assigned here — otherwise it is a
    character from a newer Unicode than this interpreter carries, which no text here can
    contain.

    A *missing* one is a bug when this interpreter is at or ahead of the Unicode the tables
    were baked from (`TABLES_UNICODE_VERSION`): the table then genuinely does not know a
    character it should. On an interpreter that is BEHIND, missing is the expected state
    instead, and not only for characters that did not exist yet — a category can shrink.
    U+1734 HANUNOO SIGN PAMUDPOD is `Mn` in Unicode 13 and `Mc` from 14 on, so Python 3.10
    puts it in PCRE2's UCP `\\w` and the table, tracking the reference, does not. Found by
    CI on 3.10 after this file's two-case model called it a bug.

    The tolerance is narrow on purpose. It applies only where a version gap makes
    disagreement expected, and the interpreters whose Unicode matches the tables still
    assert exactly — so a table generated wrong is still caught, just not on 3.10.
    """
    missing = want - matched
    surplus = matched - want
    assigned_surplus = {cp for cp in surplus if unicodedata.category(chr(cp)) != "Cn"}
    if _TABLES_ARE_AHEAD:
        missing = set()

    def sample(cps: set[int]) -> str:
        return ", ".join(
            f"U+{cp:04X} ({unicodedata.category(chr(cp))})" for cp in sorted(cps)[:8]
        )

    context = (
        f"{label}: unicodedata {unicodedata.unidata_version} on Python "
        f"{sys.version_info.major}.{sys.version_info.minor}, tables baked from "
        f"{_charclasses.TABLES_UNICODE_VERSION}"
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


def test_the_recorded_table_version_keeps_one_job_asserting_exactly() -> None:
    """`TABLES_UNICODE_VERSION` must name a Unicode some CI interpreter actually carries.

    The tolerance above is keyed on it, so a constant that overstated the tables' version
    would switch the exact assertions off everywhere and leave this file asserting nothing.
    The matrix carries 13.0 (3.10), 14.0 (3.11), 15.0 (3.12) and 15.1 (3.13); the recorded
    version is 15.0, so the 3.12 job runs the exact path and is what actually gates the
    tables. **When you regenerate them, set the constant to the generating interpreter's
    `unicodedata.unidata_version`** — and to one the matrix runs.
    """
    recorded = _version(_charclasses.TABLES_UNICODE_VERSION)
    assert len(recorded) == 3, "expected a full X.Y.Z Unicode version"
    if unicodedata.unidata_version == _charclasses.TABLES_UNICODE_VERSION:
        assert not _TABLES_ARE_AHEAD, (
            "this interpreter matches the tables' Unicode, so it must assert exactly"
        )


def test_ucp_word_is_exactly_what_pcre2_calls_a_word_character() -> None:
    """PCRE2's UCP `\\w` — `L u N u Mn u Pc`. Python's own `\\w` is `L u N u _`, so the
    marks and the remaining connectors come from the baked table.

    This is the class the post-process `\\b` is built from, and reading it as ASCII is how
    `и т.д.` rendered `и т. Д.` in every tree-walk engine (spintax-js#81).
    """
    _assert_covers(
        _codepoints_matching(f"[{_charclasses.UCP_WORD}]"),
        _codepoints_in(LETTER_CATEGORIES | NUMBER_CATEGORIES | frozenset({"Mn", "Pc"})),
        "UCP_WORD",
    )


def test_the_tld_case_classes_partition_the_letters() -> None:
    """`\\p{Ll}\\p{Lm}\\p{Lo}` and `\\p{Lu}\\p{Lt}\\p{Lm}\\p{Lo}` — the two readings of a TLD.

    Python cannot union a category into `[…]`, so each is the whole of `\\p{L}` with the
    other case subtracted by a lookahead. Asserted against the categories themselves, not
    against each other: the two deliberately OVERLAP on `Lm` and `Lo`, which is what lets
    `例子.中国` be a domain under either reading (spintax-js#79).
    """
    lower = _charclasses.NOT_UPPERCASE_LETTER + _charclasses.JS_LETTER
    upper = _charclasses.NOT_LOWERCASE_LETTER + _charclasses.JS_LETTER
    _assert_covers(
        _codepoints_matching(lower),
        _codepoints_in(frozenset({"Ll", "Lm", "Lo"})),
        "NOT_UPPERCASE_LETTER + JS_LETTER",
    )
    _assert_covers(
        _codepoints_matching(upper),
        _codepoints_in(frozenset({"Lu", "Lt", "Lm", "Lo"})),
        "NOT_LOWERCASE_LETTER + JS_LETTER",
    )


def test_the_tld_body_classes_keep_the_numbers() -> None:
    """The same two readings with `\\p{N}` and `-` added, as the TLD's body class has them."""
    lower = f"(?:-|{_charclasses.NOT_UPPERCASE_LETTER}{_charclasses.JS_LETTER_OR_NUMBER})"
    upper = f"(?:-|{_charclasses.NOT_LOWERCASE_LETTER}{_charclasses.JS_LETTER_OR_NUMBER})"
    hyphen = {ord("-")}
    _assert_covers(
        _codepoints_matching(lower),
        _codepoints_in(frozenset({"Ll", "Lm", "Lo"}) | NUMBER_CATEGORIES) | hyphen,
        "TLD lower body",
    )
    _assert_covers(
        _codepoints_matching(upper),
        _codepoints_in(frozenset({"Lu", "Lt", "Lm", "Lo"}) | NUMBER_CATEGORIES) | hyphen,
        "TLD upper body",
    )


def test_the_ucp_space_class_and_its_character_set_agree() -> None:
    """`UCP_SPACE` is run as a regex and `UCP_SPACE_CHARS` is read by the lead scanner.

    Two hand-kept lists of the same characters drift, so this is the thing that keeps them
    honest. A character in one and not the other would make the lead scanner and the
    spacing patterns disagree about where a sentence begins.
    """
    assert _codepoints_matching(f"[{_charclasses.UCP_SPACE}]") == {
        ord(ch) for ch in _charclasses.UCP_SPACE_CHARS
    }


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
