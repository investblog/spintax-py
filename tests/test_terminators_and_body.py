"""A line terminator is a line break for the rules and a character for the output.

`validate` and `extract` never hand template text back, so normalising terminators
before scanning was invisible to them. The renderer arriving at P2 does hand it back,
and the reference keeps the author's bytes:

    render("#set %x% = A\\r%x%", {postProcess: false})  ->  "\\rA"

Both halves of that are load-bearing. The CR ended the directive line — otherwise the
rest of the file would be part of `%x%`'s value and `%x%` itself would never resolve —
and it survived into the output unchanged.

So these pin the two things a P2 renderer could quietly get wrong: that the body is
cut from the text as authored, and that `_directives.extract` understands terminators
on its own rather than relying on a caller having normalised first.
"""

from __future__ import annotations

import pytest

from spintax_core import _directives, _source

TERMINATORS = ["\n", "\r", "\r\n", " ", " "]


@pytest.mark.parametrize("terminator", ["\n", "\r", "\u2028", "\u2029"])
def test_the_body_keeps_the_terminator_the_author_wrote(terminator: str) -> None:
    body = _directives.extract(f"#set %x% = A{terminator}%x%").body
    assert body == f"{terminator}%x%"


@pytest.mark.parametrize("terminator", TERMINATORS)
def test_extract_understands_terminators_without_help(terminator: str) -> None:
    """Called on raw source, not on a `Source.text` that was normalised for it.

    A P2 parser reaching for this module directly must not reintroduce the bug where a
    bare CR swallows the second directive into the first one's value.
    """
    got = _directives.extract(f"#set %a% = 1{terminator}#set %b% = 2")
    assert sorted(got.set_defs) == ["a", "b"]
    assert got.set_defs["a"] == "1"


@pytest.mark.parametrize("terminator", TERMINATORS)
def test_plain_text_is_never_rewritten(terminator: str) -> None:
    """No directive, nothing to strip — the body must come back byte for byte."""
    src = f"a{terminator}b"
    assert _directives.extract(src).body == src


def test_the_scanning_view_is_normalised_and_says_so() -> None:
    """`Source.text` is for matching. It is *supposed* to differ from the original —
    which is exactly why a renderer must not emit from it."""
    assert _source.read("a\rb").text == "a\nb"
    assert _source.read("a\rb").original == "a\rb"


def test_normalisation_preserves_length() -> None:
    """The whole design rests on this: a span found in the copy is a span in the original."""
    for src in ["a\rb", "a\r\nb", "a b", "a b", "mixed\r\n \rend"]:
        assert len(_source.normalize_terminators(src)) == len(src)


def test_a_crlf_loses_only_its_carriage_return() -> None:
    """CRLF is the one exception, and the grammar's doing rather than an accident.

    `DIRECTIVE_RE` ends `[ \t]*\r?$`, so the CR of a CRLF line ending belongs to the
    directive's own line and leaves with it; the newline stays. Measured on the
    reference: `render("#set %x% = A\r\n%x%")` is `"\nA"`, not `"\r\nA"`.
    """
    assert _directives.extract("#set %x% = A\r\n%x%").body == "\n%x%"


def test_a_crlf_in_plain_text_is_untouched() -> None:
    """Only a directive line consumes a CR; ordinary text keeps the pair intact."""
    assert _directives.extract("a\r\nb").body == "a\r\nb"
