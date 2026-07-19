"""Comment stripping, and positions that survive it.

The corpus asserts no position at all, so nothing here is gated by it. That is
exactly why these exist: an offset map that quietly drifts would be invisible until
someone integrates an editor.
"""

from __future__ import annotations

from spintax_core import _source


def test_comments_are_removed() -> None:
    s = _source.read("a/# note #/b")
    assert s.text == "ab"


def test_multiline_comment_is_removed_whole() -> None:
    s = _source.read("a/# one\ntwo #/b")
    assert s.text == "ab"


def test_unterminated_comment_is_not_a_comment() -> None:
    """`/#` with no `#/` stays literal — the engine is lenient, not clever."""
    s = _source.read("a/# never closed")
    assert s.text == "a/# never closed"


def test_position_after_a_comment_points_at_the_original() -> None:
    src = "a/# note #/{"
    s = _source.read(src)
    brace = s.text.index("{")
    assert s.text == "a{"
    assert brace == 1
    # Naively this is column 2; in the file the brace is the 12th character.
    assert s.position(brace) == (1, 12)
    assert src[s.to_original(brace)] == "{"


def test_position_across_a_multiline_comment_keeps_the_line_number() -> None:
    src = "x\n/# a\nb\nc #/{\n"
    s = _source.read(src)
    brace = s.text.index("{")
    # Line 4 begins at offset 9 ("c #/{"), and the brace is its 5th character. A
    # stripped-text line count would have said line 2 — the comment's three lines
    # are gone from `text` but not from the file the author is reading.
    assert s.position(brace) == (4, 5)
    assert src[s.to_original(brace)] == "{"


def test_positions_are_exact_for_every_offset() -> None:
    """Differential check: every surviving character maps back to itself."""
    src = "one /# c1 #/ two\nthree /# c2\nstill c2 #/ four\n{"
    s = _source.read(src)
    for i, ch in enumerate(s.text):
        assert src[s.to_original(i)] == ch, f"offset {i} ({ch!r}) mapped wrong"


def test_line_and_column_are_one_based() -> None:
    s = _source.read("ab\ncd")
    assert s.position(0) == (1, 1)
    assert s.position(1) == (1, 2)
    assert s.position(3) == (2, 1)


def test_empty_source_has_a_usable_origin() -> None:
    s = _source.read("")
    assert s.text == ""
    assert s.position(0) == (1, 1)


def test_source_that_is_only_a_comment() -> None:
    s = _source.read("/# all of it #/")
    assert s.text == ""
    assert s.position(0) == (1, 1)
