"""Structural diagnostics: brackets, directive shape, permutation config.

These run before `validate()` is wired into the public API. The corpus reports by
*op*, so a half-wired validator would turn 40 cases red rather than reporting them
as not-yet-built — the whole point of the xfail bookkeeping. So the checks are
proved here first and the public entry point flips once, when every code exists.
"""

from __future__ import annotations

from spintax_core import _validator


def codes(src: str) -> list[str]:
    _source, findings = _validator.run(src)
    return [f.code for f in findings]


def positions(src: str) -> list[tuple[str, tuple[int, int]]]:
    source, findings = _validator.run(src)
    return [(f.code, source.position(f.offset)) for f in findings]


# ── brackets ───────────────────────────────────────────────────────────


def test_balanced_text_is_clean() -> None:
    assert codes("{a|b} and [c|d]") == []


def test_unclosed_opener() -> None:
    assert codes("{a|b") == ["bracket.unclosed"]


def test_stray_closer() -> None:
    assert codes("a|b}") == ["bracket.unexpected-closing"]


def test_mismatched_pair() -> None:
    assert codes("{a|b]") == ["bracket.mismatched"]


def test_every_offender_is_reported_not_just_the_first() -> None:
    """Three stray closers are three findings — a per-template report hides work."""
    assert codes("a}b}c}") == ["bracket.unexpected-closing"] * 3


def test_unclosed_points_at_the_opener_not_the_end_of_file() -> None:
    """The imbalance is noticed at EOF; the author needs the brace that caused it."""
    assert positions("ok\n  {a|b\nmore\n") == [("bracket.unclosed", (2, 3))]


def test_brackets_inside_a_comment_are_not_counted() -> None:
    assert codes("/# { #/ text") == []


# ── directive shape ────────────────────────────────────────────────────


def test_well_formed_directives_are_clean() -> None:
    assert codes("#set %x% = a\n#def %y% = b\n%x%%y%") == []


def test_empty_value_is_legal() -> None:
    """`#set %x% =` defines an empty string. The reference once called this malformed
    unless a trailing space happened to be present — a live defect, not a rule."""
    assert codes("#set %x% =") == []
    assert codes("#def %x% =") == []


def test_malformed_set_and_def_report_their_own_code() -> None:
    assert codes("#set %x = a") == ["set.malformed"]
    assert codes("#def %x = a") == ["def.malformed"]


def test_a_directive_must_be_line_anchored() -> None:
    """Mid-line it is ordinary text, so there is nothing to call malformed."""
    assert codes("text #set %x = a") == []


def test_indented_directive_is_still_a_directive() -> None:
    assert codes("   #set %x = a") == ["set.malformed"]
    assert positions("   #set %x = a")[0][1] == (1, 4)


def test_define_looks_like_a_directive_but_is_not() -> None:
    """`#define` is not `#def` — the keyword needs its whitespace, and this must not
    be reported as a malformed `#def`."""
    assert codes("#define %x% = 1") == []


def test_keyword_is_case_sensitive() -> None:
    assert codes("#DEF %x% = 1") == []


# ── uniqueness and #include-in-a-#def ──────────────────────────────────


def test_duplicate_name_across_directives() -> None:
    assert codes("#set %x% = a\n#def %x% = b\n%x%") == ["definition.duplicate-name"]


def test_duplicate_name_same_directive() -> None:
    """The maps flatten this to last-wins before anyone can see it; occurrences are
    what make it reportable at all."""
    assert codes("#set %x% = a\n#set %x% = b\n%x%") == ["definition.duplicate-name"]


def test_duplicate_detection_is_case_insensitive() -> None:
    assert codes("#set %X% = a\n#set %x% = b\n%x%") == ["definition.duplicate-name"]


def test_include_in_a_def_value_is_an_error() -> None:
    assert codes('#def %x% = #include "hero"\n%x%') == ["def.include-in-value"]


def test_include_in_a_set_value_is_fine() -> None:
    """A macro is substituted verbatim, so its `#include` reaches the include stage."""
    assert codes('#set %x% = #include "hero"\n%x%') == []


# ── permutation config ─────────────────────────────────────────────────


def test_known_keys_are_clean() -> None:
    assert codes('[<minsize=2;maxsize=3;sep=", ";lastsep=" and ">a|b|c]') == []


def test_unknown_key() -> None:
    assert codes("[<nope=1>a|b]") == ["permutation.unknown-key"]


def test_non_integer_sizes() -> None:
    assert codes("[<minsize=x>a|b]") == ["permutation.minsize-not-integer"]
    assert codes("[<maxsize=y>a|b]") == ["permutation.maxsize-not-integer"]


def test_a_leading_separator_is_not_a_config() -> None:
    """`[<and>a|b]` is a separator. Treating every `<…>` as config would reject it."""
    assert codes("[<and>a|b]") == []


def test_html_in_a_permutation_is_not_a_config() -> None:
    assert codes("[<li>one</li>|<li>two</li>]") == []


def test_unknown_key_points_at_the_key() -> None:
    assert positions("[<nope=1>a|b]") == [("permutation.unknown-key", (1, 3))]
