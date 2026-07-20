"""`analyze` and the `Ast` input path — neither of which the shared corpus touches.

There is no `analyze.json`, so nothing here is machine-checked against the other engines.
That is the same shape of gap that let `#include` ship with five surviving mutations, so
every expectation below is a **measurement** from `@spintax/core` 0.3.0, taken by running
both engines over the same 32 templates and diffing `refs`/`sets`/`defs`/`includes`,
diagnostic codes and the full census. All 32 agreed.

Two of those measurements contradicted what reading the code suggested, and both are
pinned here by name:

- `#include "x"` twice counts **one**, not two. The census counts distinct targets, not
  occurrences — the same as `set`, though it arrives from the extractor's deduplicated
  list rather than from a map.
- `#def` is not counted at all. `defs: ["d"]` appears in the extraction beside a census
  with no `def` key. That looks like an upstream oversight from when `#def` arrived in AST
  version 2, and this port reproduces it deliberately rather than diverging alone.
"""

from __future__ import annotations

import pytest

from spintax_core import Ast, AstVersionError, analyze, extract, parse, validate


def nonzero(constructs: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in constructs.items() if v}


# ── the census ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("", {}),
        ("plain text", {}),
        ("%a%", {"variable": 1}),
        ("%a% %b% %a%", {"variable": 3}),
        ("{x|y}", {"enumeration": 1}),
        ("[p|q]", {"permutation": 1}),
        ("{?V?t|f}", {"conditional": 1}),
        ("{plural 1: a|b}", {"plural": 1}),
        # Nested nodes count — the census walks the whole tree, not the top level.
        ("{a|{b|c}}", {"enumeration": 2}),
        ("[p|[q|r]]", {"permutation": 2}),
        ("{?V?{x|y}|f}", {"conditional": 1, "enumeration": 1}),
        ("{a|b} nested {c|{d|e}} and [f|[g|h]]", {"enumeration": 3, "permutation": 2}),
        ("{?V?{x|y}|[p|q]}", {"conditional": 1, "enumeration": 1, "permutation": 1}),
        # A malformed conditional is an enumeration by the time the census sees it.
        ("{?BAD}", {"enumeration": 1}),
        # Nothing unparsed counts: an unmatched brace is literal text, not a node.
        ("{a|b", {}),
        ("a|b}", {}),
        # Comments are gone before the tree is built.
        ("/# comment #/{x|y}", {"enumeration": 1}),
    ],
)
def test_the_census_counts_what_was_written(template: str, expected: dict[str, int]) -> None:
    assert nonzero(dict(analyze(template).constructs)) == expected


def test_set_counts_distinct_names_not_directives() -> None:
    """A redefinition is one name. The map has already collapsed it, and the census reads
    the map."""
    assert nonzero(dict(analyze("#set %a% = 1\n%a%").constructs)) == {"set": 1, "variable": 1}
    assert nonzero(dict(analyze("#set %a% = 1\n#set %a% = 2\n%a%").constructs)) == {
        "set": 1,
        "variable": 1,
    }
    assert nonzero(dict(analyze("#set %a% = 1\n#set %b% = 2\n%a%%b%").constructs)) == {
        "set": 2,
        "variable": 2,
    }


def test_include_counts_distinct_targets_not_occurrences() -> None:
    """The measurement that contradicted the obvious reading. Two `#include "x"` lines are
    one include, because the count comes off the extractor's deduplicated ref list."""
    assert nonzero(dict(analyze('#include "x"').constructs)) == {"include": 1}
    assert nonzero(dict(analyze('#include "x"\n#include "y"').constructs)) == {"include": 2}
    assert nonzero(dict(analyze('#include "x"\n#include "x"').constructs)) == {"include": 1}


def test_definitions_are_extracted_but_not_counted() -> None:
    """A suspected upstream bug, reproduced on purpose.

    `constructs` is a mapping a host iterates, so emitting a key TypeScript does not would
    break the one-mental-model argument this port keeps choosing. If definitions should be
    counted, all three engines should count them — which starts upstream.
    """
    result = analyze("#def %d% = 1\n%d%")
    assert result.extraction.defs == ("d",)
    assert "def" not in result.constructs
    assert nonzero(dict(result.constructs)) == {"variable": 1}


def test_the_census_keys_are_always_present_even_at_zero() -> None:
    """A host reading `constructs["plural"]` must not have to guard for absence."""
    constructs = analyze("plain").constructs
    for key in ("enumeration", "permutation", "variable", "conditional", "plural", "set", "include"):
        assert constructs[key] == 0


# ── analyze composes the other three ──────────────────────────────────────────


def test_analyze_carries_the_extraction_and_the_diagnostics() -> None:
    template = '#set %a% = {x|y}\n#def %b% = 1\n%a% {p|q} [r|s] {?V?t} {plural 1: u|v}\n#include "z"'
    result = analyze(template)

    assert sorted(result.extraction.refs) == ["a", "v"]
    assert result.extraction.sets == ("a",)
    assert result.extraction.defs == ("b",)
    assert result.extraction.includes == ("z",)
    assert [d.code for d in result.diagnostics] == ["variable.undefined"]
    assert nonzero(dict(result.constructs)) == {
        "enumeration": 1, "permutation": 1, "variable": 1,
        "conditional": 1, "plural": 1, "set": 1, "include": 1,
    }


def test_analyze_reports_the_same_diagnostics_validate_would() -> None:
    for template in ("{a|b", "a|b}", "%undefined_one%", "#set %s% = %s%"):
        assert [d.code for d in analyze(template).diagnostics] == [
            d.code for d in validate(template)
        ]


def test_analyze_passes_its_options_through() -> None:
    """`known_variables` suppresses the undefined warning, and must reach the validator."""
    assert [d.code for d in analyze("%runtime_only%").diagnostics] == ["variable.undefined"]
    assert analyze("%runtime_only%", known_variables=["runtime_only"]).diagnostics == ()


# ── the Ast input path, which is why Ast is public at all ────────────────────


PARSE_ONCE = [
    "plain",
    "{a|b} %v% [c|d]",
    "{a|b",
    "#set %a% = 1\n#def %b% = 2\n%a%%b%",
    '#include "x"',
    "%undefined_one%",
    "#set %s% = %s%",
]


@pytest.mark.parametrize("template", PARSE_ONCE)
def test_a_handle_answers_the_same_as_its_source(template: str) -> None:
    """Spec §4 opens by promising a host can parse once and reuse. Until this milestone
    three of the five entry points refused a handle outright."""
    ast = parse(template)
    assert extract(ast) == extract(template)
    assert [d.code for d in validate(ast)] == [d.code for d in validate(template)]
    assert analyze(ast).constructs == analyze(template).constructs


def test_a_handle_carries_positions_from_the_original_source() -> None:
    """Not just the codes — a diagnostic off a handle must point where the author looks."""
    template = "line one\n{a|b\nline three"
    from_source = validate(template)
    from_handle = validate(parse(template))
    assert [(d.code, d.line, d.column) for d in from_handle] == [
        (d.code, d.line, d.column) for d in from_source
    ]


@pytest.mark.parametrize("entry", [validate, extract, analyze])
def test_a_bare_ast_is_refused_by_every_entry_point(entry: object) -> None:
    """`Ast()` is constructible and carries nothing. Rejected rather than tolerated,
    because the quiet alternative is a plausible empty answer."""
    with pytest.raises(AstVersionError):
        entry(Ast())  # type: ignore[operator]


def test_a_stale_handle_is_refused() -> None:
    """The version guard's real target: a handle from before `AST_VERSION` 2 has no `#def`
    map, so using it would silently drop every definition."""
    from spintax_core._ast import ParsedAst

    fresh = parse("{a|b}")
    assert isinstance(fresh, ParsedAst)
    # Constructed rather than `replace`d: `parse` is typed to return the opaque `Ast`, so a
    # dataclass helper cannot see the fields. Building one directly is also closer to what
    # the guard defends against — a handle from another version of this shape.
    stale = ParsedAst(
        source=fresh.source,
        set_defs=fresh.set_defs,
        def_defs=fresh.def_defs,
        nodes=fresh.nodes,
        ast_version=1,
    )
    with pytest.raises(AstVersionError):
        validate(stale)
    with pytest.raises(AstVersionError):
        analyze(stale)
    with pytest.raises(AstVersionError):
        extract(stale)
