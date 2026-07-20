"""Cases a self-review found passing against a broken implementation.

Each of these was added because a mutation survived the existing suite. They are
grouped by what the mutation was, so a future reader can see what the assertion is
actually holding — a test whose reason is not written down is the next thing to be
"simplified" away.
"""

from __future__ import annotations

import sys

import pytest

import spintax_core as engine
from spintax_core import _directives, _plurals, _source


def codes(src: str, **kw: object) -> list[str]:
    return [d.code for d in engine.validate(src, **kw)]  # type: ignore[arg-type]


# ── recursion: the reference's shape overflows Python's stack ──────────


def test_a_long_acyclic_alias_chain_does_not_raise() -> None:
    """`validate()` must not blow up on a template with nothing wrong with it.

    The obvious recursive cycle-walk overflowed at ~996 links — well inside what a
    generated template could reach, and Node's deeper stack hides the same shape. The
    chain here is far past any recursion limit.
    """
    depth = sys.getrecursionlimit() * 5
    src = "".join(f"#set %v{i}% = %v{i + 1}%\n" for i in range(depth)) + f"#set %v{depth}% = x\n"
    assert codes(src) == []


def test_a_cycle_is_still_found_at_depth() -> None:
    """Iteration must not have traded the crash for a miss."""
    depth = 200
    src = "".join(f"#set %v{i}% = %v{i + 1}%\n" for i in range(depth)) + f"#set %v{depth}% = %v0%\n"
    assert "variable.circular-reference" in codes(src)


def test_a_wide_dependency_graph_stays_fast() -> None:
    """A diamond fan-out must not be walked once per path.

    Without memoisation this shape is exponential: 24 levels took over half a minute.
    """
    levels = 24
    src = "".join(f"#set %d{i}% = %d{i + 1}%%d{i + 1}%\n" for i in range(levels))
    src += f"#set %d{levels}% = x\n"
    assert codes(src) == []


# ── line terminators JavaScript honours and Python does not ───────────


@pytest.mark.parametrize("terminator", ["\r", " ", " "])
def test_directives_are_line_anchored_at_every_javascript_terminator(terminator: str) -> None:
    """A bare CR would otherwise swallow the rest of the file into one `#set` value.

    Measured against the reference: all three of these are line breaks there, so the
    second directive is a duplicate rather than part of the first one's value.
    """
    assert codes(f"#set %x% = a{terminator}#set %x% = b") == ["definition.duplicate-name"]


@pytest.mark.parametrize("terminator", ["\r", " ", " "])
def test_extract_sees_both_sides_of_an_unusual_terminator(terminator: str) -> None:
    got = engine.extract(f"#set %a% = 1{terminator}#set %b% = 2")
    assert sorted(got.sets) == ["a", "b"]
    assert got.refs == ()


def test_crlf_is_one_terminator_not_two() -> None:
    """Rewriting the CR of a CRLF pair would turn every line break into a blank line."""
    assert _source.read("a\r\nb").text == "a\r\nb"


def test_a_directive_value_does_not_keep_a_trailing_cr() -> None:
    """Both directive patterns must agree on CRLF, or they capture different values."""
    assert _directives.extract("#set %x% = a\r\n").set_defs == {"x": "a"}


# ── spans, which no fixture asserts ────────────────────────────────────


def test_self_reference_underlines_the_whole_token() -> None:
    (diag,) = engine.validate("#set %longname% = %longname%")
    assert (diag.column, diag.end_column) == (6, 16)


def test_circular_reference_underlines_the_whole_token() -> None:
    diags = [d for d in engine.validate("#set %alpha% = %beta%\n#set %beta% = %alpha%")
             if d.code == "variable.circular-reference"]
    assert (diags[0].column, diags[0].end_column) == (6, 13)


def test_end_position_is_exclusive_and_one_past_the_span() -> None:
    (diag,) = engine.validate("%undefined_name%")
    assert (diag.column, diag.end_column) == (1, 17)  # 16 characters
    assert diag.line == diag.end_line == 1


def test_diagnostic_data_survives_to_the_caller() -> None:
    (diag,) = engine.validate("%missing%")
    assert diag.data is not None and diag.data["name"] == "missing"


def test_duplicate_name_reports_the_first_line_in_original_coordinates() -> None:
    """A comment above the directives moves the stripped text out of step with the file.

    The first-definition line therefore has to be translated, not counted where the
    check happens to be standing.
    """
    src = "/# one\ntwo\nthree\n#/\n#set %x% = a\n#set %x% = b\n"
    (diag,) = [d for d in engine.validate(src) if d.code == "definition.duplicate-name"]
    assert diag.line == 6
    assert diag.data is not None and diag.data["first_line"] == 5


# ── nested brackets really do suppress the arity report ───────────────


def test_nested_brackets_suppress_arity_on_a_distinguishing_input() -> None:
    """The earlier test could not tell: `{plural 1: {a|b}|c}` splits into 3 parts, so a
    three-form locale would have been silent either way. These cannot be silent by
    accident — the pipe counts are wrong for the locale in every one.
    """
    assert codes("{plural 1: {a|b}}", locale="ru") == ["plural.nested-brackets"]
    assert codes("{plural 1: {a|b}|c|d}", locale="ru") == ["plural.nested-brackets"]
    assert codes("{plural 1: {a|b}|c}", locale="en") == ["plural.nested-brackets"]


# ── locale normalization ───────────────────────────────────────────────


def test_locale_matching_is_case_insensitive() -> None:
    assert _plurals.normalize_base_lang("RU") == "ru"
    assert codes("{plural 1: a|b}", locale="RU") == ["plural.arity"]


def test_three_letter_tags_are_not_mapped() -> None:
    """`srp` is Serbian to a human and not to the engine — documented, so pinned."""
    assert _plurals.normalize_base_lang("srp") == "srp"
    assert codes("{plural 1: a|b}", locale="srp") == []


# ── comments: not one corpus fixture contains a `/#` ──────────────────


def test_comment_matching_is_not_greedy() -> None:
    """A greedy match would swallow everything between the first `/#` and the last `#/`,
    taking the template with it."""
    assert _source.read("/# one #/keep/# two #/").text == "keep"


def test_a_directive_inside_a_comment_is_not_a_directive() -> None:
    assert _directives.extract("/# #set %x% = a #/").set_defs == {}


# ── the body the renderer will consume (dead until P2, so pinned here) ─


def test_directive_lines_are_removed_but_their_newlines_remain() -> None:
    """Measured against the reference: the text goes, the line break stays."""
    assert _directives.extract("#set %x% = A\n%x%").body == "\n%x%"


def test_three_or_more_blank_lines_collapse_to_two() -> None:
    """Not a property of stripping — it runs even with no directives at all, which is
    why a three-directive template shows two blank lines and not three."""
    assert _directives.extract("\n\n\nX").body == "\n\nX"
    assert _directives.extract("#set %a% = A\n#set %b% = B\n#set %c% = C\nX").body == "\n\nX"


# ── argument shapes ────────────────────────────────────────────────────


def test_a_bare_string_is_rejected_where_a_sequence_is_meant() -> None:
    """`known_includes="hero"` type-checks and would silently mean four one-letter slugs."""
    with pytest.raises(TypeError):
        engine.validate('#include "hero"', known_includes="hero")
    with pytest.raises(TypeError):
        engine.validate("%x%", known_variables="x")
