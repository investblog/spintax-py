"""What the corpus cannot check about the renderer.

The fixtures assert what a template renders to. Three things matter that they never look
at directly:

- **Leniency.** A fixture states the output for malformed input; it cannot state that
  nothing was raised on the way. A stage that throws where the contract says degrade is
  caught only where some fixture happens to cover that shape.
- **Depth.** No fixture nests deeply, and nothing bounds nesting before the renderer:
  `max_depth` guards the `#include` stack alone. The parser and the tree walk were both
  made iterative for this, and the renderer had to be too — a recursive one died at ~300
  on input the parser handles at 3000, which is moving the failure rather than fixing it.
- **The errors that are about the CALLER.** `AstVersionError` and `IncludeResolverError`
  are the two things this engine does raise, and no fixture asserts a throw.

Draw COUNT is covered by the corpus, but only just — two fixtures carry it — so it is
pinned here by name as well.
"""

from __future__ import annotations

import pytest

import spintax_core as engine
from spintax_core import Ast, AstVersionError, IncludeResolverError, make_rng, render, render_with


def first(_lo: int, hi: int) -> int:
    return _lo


# ── leniency ──────────────────────────────────────────────────────────────────

MALFORMED = [
    "{a|b",
    "a|b}",
    "[a|b",
    "{a|b]",
    "}{",
    "{?VAR}",
    "{??x|y}",
    "{plural: a|b}",
    "{plural x: a|b}",
    "{plural 1: {a|b}|c}",
    "[<minsize=x>a|b]",
    "%unclosed",
    "/# unterminated",
    "{?1BAD?x|y}",
]


@pytest.mark.parametrize("template", MALFORMED)
def test_malformed_markup_never_raises(template: str) -> None:
    """§9.2: render degrades, it does not throw. Asserting only that a string came back —
    what it says is the corpus's business."""
    assert isinstance(render(template, post_process=False), str)


# ── depth ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "opener", "closer"),
    [("enumeration", "{", "}"), ("permutation", "[", "]"), ("conditional", "{?V?", "}")],
)
def test_deep_nesting_renders(label: str, opener: str, closer: str) -> None:
    """Three times what a recursive renderer managed, on all three nesting constructs.

    `V` is supplied because a conditional on an undefined name is falsy and renders its
    empty else-branch — confirmed against the reference, which returns `""` for
    `{?V?core}` and `"core"` once `V` is set. Without it this case would pass on an empty
    string and prove nothing about depth.
    """
    depth = 1000
    out = render(
        opener * depth + "core" + closer * depth,
        context={"V": "1"},
        post_process=False,
    )
    assert "core" in out


# ── the caller's errors ───────────────────────────────────────────────────────


def test_a_foreign_ast_is_rejected_loudly() -> None:
    """A bare `Ast()` is constructible and carries no tree.

    Rejected rather than tolerated because the quiet alternative is worse: a handle from
    before AST_VERSION 2 has no `#def` map, so rendering it would drop every definition
    and return plausible output that is wrong.
    """
    with pytest.raises(AstVersionError):
        render_with(Ast(), first)


def test_a_resolver_that_raises_is_not_swallowed() -> None:
    """A resolver returning None means "no such template" and renders empty. A resolver
    that THROWS has a bug, and hiding it behind an empty string makes it undebuggable."""

    def explode(_ref: str) -> str:
        raise KeyError("boom")

    with pytest.raises(IncludeResolverError) as caught:
        render('#include "missing"', include_resolver=explode, post_process=False)
    assert isinstance(caught.value.__cause__, KeyError)


def test_a_resolver_returning_none_renders_empty() -> None:
    assert render('#include "gone"', include_resolver=lambda _r: None, post_process=False) == ""


# ── draw count ────────────────────────────────────────────────────────────────


def test_a_single_option_costs_no_draw() -> None:
    """`min == max` short-circuits before the rng is called.

    Draw count is the only thing separating `#set` from `#def`, so one needless draw
    shifts every later one. The corpus notices — but as a shuffle-order failure two
    fixtures away from the cause, which is not where anyone would look.
    """
    draws = 0

    def counting(lo: int, hi: int) -> int:
        nonlocal draws
        draws += 1
        return lo

    render_with("{only}", counting, post_process=False)
    assert draws == 0, "a one-option enumeration must not consume a draw"

    render_with("[a|b|c]", counting, post_process=False)
    assert draws == 2, "a default-config permutation draws for the shuffle, not the size"


def test_two_options_do_cost_a_draw() -> None:
    """The other side of the same coin — a short-circuit that fires too eagerly would
    freeze every enumeration on its first option and still look plausible."""
    draws = 0

    def counting(lo: int, hi: int) -> int:
        nonlocal draws
        draws += 1
        return lo

    render_with("{a|b}", counting, post_process=False)
    assert draws == 1


# ── variable scope ────────────────────────────────────────────────────────────


def test_the_runtime_context_outranks_a_global() -> None:
    """Scope priority is runtime > local > global, and the corpus never puts a `#set` and
    a runtime value of the same name against each other — so a build_vars that merged the
    two the other way round passed every fixture. Measured on the reference:
    `#set %x% = fromset` with `context={"x": "fromruntime"}` renders `fromruntime`.
    """
    out = render("#set %x% = fromset\n%x%", context={"x": "fromruntime"}, post_process=False)
    assert out.strip() == "fromruntime"


def test_context_lookup_ignores_case() -> None:
    assert render("%NAME%", context={"name": "v"}, post_process=False) == "v"
    assert render("%name%", context={"NAME": "v"}, post_process=False) == "v"


# ── truthiness sits on the JS/Python whitespace fault line ────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a", "yes"),
        (" ", "no"),
        ("", "no"),
        # U+FEFF is whitespace to JavaScript and NOT to Python; U+001C is the reverse.
        # Under Python's `\S` both of these flip, and nothing in the corpus would notice.
        # Both verified against the reference.
        ("﻿", "no"),
        ("\x1c", "yes"),
    ],
)
def test_truthiness_follows_javascript_s_idea_of_blank(value: str, expected: str) -> None:
    assert render("{?V?yes|no}", context={"V": value}, post_process=False) == expected


def test_an_undefined_name_is_falsy() -> None:
    assert render("{?NOPE?yes|no}", post_process=False) == "no"


# ── the mandatory final stage ─────────────────────────────────────────────────


def test_the_safety_restore_runs_even_with_post_process_off() -> None:
    """`post_process=False` turns off cosmetics, not correctness. Without the restore the
    caller would receive private-use code points."""
    shielded = engine.neutralize("{a|b}")
    out = render_with("%v%", first, context={"v": shielded}, post_process=False)
    assert out == "{a|b}"
    assert not any(0xE000 <= ord(c) <= 0xE005 for c in out)


def test_a_sentinel_in_author_markup_is_stripped_before_rendering() -> None:
    """Only `neutralize()` may introduce a sentinel. Otherwise the restore would turn a
    character the author typed into a brace they never wrote."""
    out = render_with("a" + chr(0xE000) + "b", first, post_process=False)
    assert out == "ab"


def test_a_seeded_render_is_reproducible() -> None:
    template = "{a|b|c} [x|y|z] {d|e}"
    assert render(template, seed=42, post_process=False) == render(
        template, seed=42, post_process=False
    )
    assert render_with(template, make_rng(1), post_process=False) is not None
