"""The `/! … !/` verbatim span on the surfaces the corpus cannot gate (spintax-js#92, ADR 0001).

The corpus pins what a span renders, validates and extracts to. It has no field for
`analyze`, for the expansion budget, for diagnostic positions or for what the include
resolver is asked during a cycle — so every expectation here was MEASURED on the reference
(`@spintax/core` 0.14.0, `analyze`/`validate` from `src/index.ts`, `renderWith` from
`src/internal/pipeline.ts`, esbuild-bundled), not written by reading this port.
"""

from __future__ import annotations

import pytest

from spintax_core import _verbatim, analyze, render_with, validate


def first(lo: int, _hi: int) -> int:
    return lo


@pytest.mark.parametrize(
    ("template", "count"),
    [
        ("/!!/ a /!x!/ /!", 2),  # the empty span counts; the unclosed opener does not
        ("plain", 0),
        ("/# /!a!/ #/ /!b!/", 1),  # a span inside a comment is removed with it
        ("a /!x", 0),
        ("/!x!/\n#set %a% = /!y!/", 2),  # a span in a directive value counts too
    ],
)
def test_analyze_counts_spans(template: str, count: int) -> None:
    assert analyze(template).constructs["verbatim"] == count


def test_the_budget_charges_a_token_as_its_content() -> None:
    """Rule 7a. Three references to a 400 KiB span fit the 1 MiB budget by content; by
    the token's encoded length (two digits per code point) the third would stay literal."""
    big = "x" * (400 * 1024)
    out = render_with(f"#set %a% = /!{big}!/\n%a%|%a%|%a%", first, post_process=False)
    assert [part.strip() == big for part in out.split("|")] == [True, True, True]


@pytest.mark.parametrize("body", ['[<minsize=3;maxsize=3;sep="+">%a%|%a%|%a%]', "{%a%+%a%+%a%|z}"])
def test_a_re_read_construct_charges_a_token_as_its_content(body: str) -> None:
    """The same purse through the splice's fixpoint, a separate charging site."""
    big = "x" * (400 * 1024)
    out = render_with(f"#set %a% = /!{big}!/\n{body}", first, post_process=False)
    assert [part.strip() == big for part in out.split("+")] == [True, True, True]


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("/!xx!/ {a", [("bracket.unclosed", 1, 8, 1, 9)]),
        ("/!a\nb!/\n{a", [("bracket.unclosed", 3, 1, 3, 2)]),
        ("a /# c #/ /!q!/ }", [("bracket.unexpected-closing", 1, 17, 1, 18)]),
        ("/!x!/[a", [("bracket.unclosed", 1, 6, 1, 7)]),
        # The ref is underlined as written (the whole span), and named decoded.
        ('#include "/!a!/"', [("include.unknown-target", 1, 11, 1, 16)]),
        # Source order here, check order in the reference — a recorded divergence.
        ("x /!\n{ y", [("verbatim.unclosed", 1, 3, 1, 5), ("bracket.unclosed", 2, 1, 2, 2)]),
    ],
)
def test_positions_point_at_the_source_past_a_span(
    template: str, expected: list[tuple[str, int, int, int, int]]
) -> None:
    got = [
        (d.code, d.line, d.column, d.end_line, d.end_column)
        for d in validate(template, known_includes=["zz"])
    ]
    assert got == expected


def test_an_include_message_quotes_the_decoded_ref() -> None:
    [d] = validate('#include "/!a!/"', known_includes=["zz"])
    assert d.message == "#include target 'a' does not match any known template."
    assert d.data == {"target": "a"}


def test_the_include_cycle_check_compares_the_decoded_ref() -> None:
    """The body includes itself through a span: the resolver is asked once, for `{a}`,
    and the second include is a cycle."""
    calls: list[str] = []

    def resolver(ref: str) -> str | None:
        calls.append(ref)
        return '#include "/!{a}!/"\nbody' if ref == "{a}" else None

    out = render_with('#include "/!{a}!/"', first, post_process=False, include_resolver=resolver)
    assert (out, calls) == ("\nbody", ["{a}"])


def test_a_token_round_trips_every_code_point_width() -> None:
    # chr(), not escapes: tooling has rewritten an escaped separator into the raw character.
    controls = chr(0) + chr(13) + chr(10)
    content = (
        "a" + controls + chr(0x2028) + chr(0xE000) + chr(0xF0000) + chr(0x10FFFF) + chr(0x1F600)
    )
    assert _verbatim.decode(_verbatim.encode(content)) == content


def test_the_scan_is_linear_on_unclosed_openers() -> None:
    """The lazy `/#.*?#/` this replaces re-read the text from every `/#` once no `#/` was
    left; the scan searches each closer once."""
    src = "/# /! " * 50_000
    projection = _verbatim.project(src)
    assert projection.text == src
    assert projection.unclosed == 3
