"""A direct `%var%` inside `{…}`/`[…]` is spliced as TEXT before the split (spintax-py#3).

The 19 `splice/*` corpus fixtures gate the rule itself. This file pins what they cannot: the
hop-budget arithmetic in shapes the corpus does not carry, the expansion-budget door the
reference's review found, the PHP-consistent consequences that are new to a tree walk, the
`Ast` input path (an ungated surface — no fixture can reach it), and the parser's `raw`
decision on the seams.

**Every expected string below was measured on the reference** (`@spintax/core` 0.7.0, its
white-box `renderNodes` with the same injected RNG strategy), never by reading this port. The
26 deterministic cases were byte-identical to it; the one seeded case (neutralize) accepts the
reference's answer and this engine's, because cross-engine RNG parity is a non-goal.
"""

from __future__ import annotations

import re

import pytest
from rng_strategy import rng_from_strategy

import spintax_core as engine
from spintax_core import AstVersionError, _ast, _parser, parse, render, render_with

MIB = 1024 * 1024


def rw(template: str, rng: object = "first", context: dict[str, str] | None = None, locale: str = "") -> str:
    return render_with(
        template, rng_from_strategy(rng), context=context or {}, locale=locale, post_process=False
    )


def chain(n: int, start: int = 1) -> str:
    """`#set %a1% = %a2%` … n aliases in a row."""
    return "\n".join(f"#set %a{i}% = %a{i + 1}%" for i in range(start, start + n))


def doubling(n: int) -> str:
    """A reference that doubles n times: `%d11%` reaches `%x%` 2**12 times."""
    return "\n".join(
        f"#set %d{i}% = " + ("%x% %x%" if i == 0 else f"%d{i - 1}% %d{i - 1}%") for i in range(n)
    )


# ── the hop budget is 51 inside a bracket exactly as outside one ──────────────


def test_the_knot_leaves_51_pairs_inside_braces_as_at_top_level() -> None:
    """render/circular-set-accumulates-then-stops, moved inside `{…}`."""
    assert rw("#set %b% = x%b%y\n{%b%}") == "\n" + "x" * 51 + "%b%" + "y" * 51


def test_a_mutual_cycle_inside_braces_stops_at_the_leftover() -> None:
    assert rw("#set %a% = %b%\n#set %b% = %a%\n{%a%}") == "\n\n%b%"


def test_a_construct_reached_through_a_macro_has_already_spent_a_hop() -> None:
    """The fixpoint gets 50 passes here — the 51st hop overall. A flat 51 leaves %a52%."""
    template = "#set %v% = {%a1%|x}\n" + chain(59) + "\n#set %a60% = END\n%v%"
    assert rw(template) == "\n\n%a51%"


def test_the_51st_hop_reaches_the_body_as_text_and_is_split() -> None:
    """Fifty aliases and a terminal list: the plugin's 51 passes end with `{x|y}`. An engine
    that hands the last hop back as finished text renders `x|y` instead."""
    assert rw(chain(50) + "\n#set %a51% = x|y\n{%a1%}", "last") == "\n\ny"


def test_one_hop_deeper_the_leftover_is_frozen_not_spliced_a_52nd_time() -> None:
    assert rw(chain(51) + "\n#set %a52% = x|y\n{%a1%}", "last") == "\n\n%a52%"


def test_a_frozen_subtree_freezes_a_nested_construct_too() -> None:
    """The leftover of the cycle is frozen; the permutation next to it still renders its own
    direct reference, because that fixpoint converged before the cycle's did not."""
    assert rw("#set %a% = %b%\n#set %b% = %a%\n{%a%|[%L%]}", "last", {"L": "x|y"}) == "\n\nx y"


# ── the re-read tree IS the parsed tree when nothing structural came in ───────


def test_plain_values_render_exactly_as_before_the_splice_existed() -> None:
    """Same element count, same draws, same order — the untouched class is byte-identical."""
    assert rw("[%a%|%b%|c]", "first", {"a": "x", "b": "y"}) == "y c x"
    assert rw("{%a%|%b%}", {"sequence": [1]}, {"a": "x", "b": "y"}) == "y"


def test_a_nested_permutation_inside_an_enumeration_keeps_its_own_order() -> None:
    assert rw("{%L%|[%L%]}", "first", {"L": "a|b"}) == "a"


def test_the_untaken_branch_of_a_conditional_is_spliced_too() -> None:
    assert rw("[{?flag?%L%|none}|c]", "last", {"L": "x|y"}) == "none c"


def test_a_conditional_brought_in_by_a_value_is_resolved_textually_after_expansion() -> None:
    """Plugin Stage 6c: conditionals run AGAIN after the fixpoint, over text. So a branch a
    value brings in is trimmed at the element's edge like an authored one (`x b`, not
    ` x  b`), and a list inside it is cut at the conditional's own first `|` before the
    element split ever sees it (`x b`, not `x y b`). Both measured on the reference; the
    second pass is the only thing that makes the first case hold."""
    assert rw("[%C%|b]", "last", {"C": "{?flag? x |y}", "flag": "1"}) == "x b"
    assert rw("[%C%|b]", "last", {"C": "{?flag?x| y }"}) == "y b"
    assert rw("[%C%|b]", "last", {"C": "{?flag?%L%|none}", "flag": "1", "L": "x|y"}) == "x b"
    # An enumeration does not trim its options, so the padding survives there.
    assert rw("{%C%|z}", "first", {"C": "{?flag? x |y}", "flag": "1"}) == " x "


def test_a_conditional_nested_three_deep_is_still_direct() -> None:
    template = "{" + "{?flag?" * 3 + "%L%" + "}" * 3 + "|z}"
    assert rw(template, "last", {"flag": "1", "L": "x|y"}) == "z"


def test_an_undefined_name_beside_a_defined_one_stays_one_literal_element() -> None:
    assert rw("[%nope%|%L%]", "last", {"L": "x|y"}) == "%nope% x y"


def test_an_alias_through_a_macro_and_a_rolled_def_both_carry_the_pipe() -> None:
    assert rw("#set %K% = %L%\n{%K%}", "last", {"L": "x|y"}) == "\ny"
    assert rw("#def %d% = %L%\n[%d%|c]", "last", {"L": "x|y"}) == "\nx y c"


# ── PHP-consistent consequences, new to a tree walk ───────────────────────────


def test_an_element_that_becomes_empty_is_dropped_before_the_shuffle() -> None:
    """So every later draw shifts — the reference measured the same on both PHP engines."""
    assert rw("[%E%|b|c]", "first", {"E": ""}) == "c b"


def test_a_taken_branch_is_trimmed_at_an_elements_edge() -> None:
    """The branch's own padding is the ELEMENT's padding, so the element trim takes it.

    Re-measured at `@spintax/core` 0.9.0: this returned `' padded  b'` until spintax-js#80
    made a whole `{?…}` directly in `[…]` mark the construct for the re-read whatever its
    branches hold. The plugin resolves conditionals at Stage 6a, before any bracket is
    read, so the taken branch lands in the body ahead of the split and its edges are the
    element's edges.
    """
    assert rw("[{?flag? padded |x}|b]", "last", {"flag": "1"}) == "padded b"
    assert rw("[{?flag? padded |x}|b]", "first", {"flag": "1"}) == "b padded"


def test_a_value_that_is_only_a_pipe_yields_empty_options() -> None:
    assert rw("{%Z%}", "last", {"Z": "|"}) == ""


def test_a_value_with_both_bracket_kinds_and_a_pipe_resolves_in_place() -> None:
    assert rw("[%v%|c]", "last", {"v": "{p|q}|[r|s]"}) == "q r s c"


def test_an_unbalanced_value_degrades_as_the_plugins_innermost_regex_does() -> None:
    """The brackets go back on around the expanded body, so `{a}b}` is `a` plus literal `b}`."""
    assert rw("{%v%|z}", "last", {"v": "a}b"}) == "ab|z}"
    assert rw("{%v%|z}", "last", {"v": "a{b"}) == "{az"


def test_a_separator_value_carrying_a_pipe_is_text_inside_its_quotes() -> None:
    assert rw('[<sep="%S%">a|b]', "last", {"S": "|"}) == "a|b"


def test_a_plural_inside_a_triggered_body_is_a_node_again_after_the_re_read() -> None:
    assert rw("[%X%|{plural 2: one|many}]", "last", {"X": "x"}, "en") == "x many"


# ── the expansion budget: every substitution is charged (review finding) ──────


def test_a_bomb_inside_a_construct_dies_at_the_budget_and_never_raises() -> None:
    out = render("#set %a% = %b% %b%\n#set %b% = %a% %a%\n{%a%}", post_process=False)
    assert len(out) < 4 * MIB
    assert "%" in out


def test_a_reference_the_budget_cut_off_stays_literal_in_the_re_read_subtree() -> None:
    """2**12 references to a 1 KiB plain value through a doubling chain: the fixpoint charges
    the first ~1 MiB and leaves the rest literal. A plain-value shortcut that does not charge
    would then splice those leftovers for nothing — 4 MiB out of a 1 MiB allowance."""
    out = render(doubling(12) + "\n{%d11%}", context={"x": "a" * 1024}, post_process=False)
    assert len(out) < MIB + 64 * 1024
    assert "%x%" in out


def test_a_plain_value_is_not_a_free_leaf_at_top_level_either() -> None:
    out = render(doubling(12) + "\n%d11%", context={"x": "a" * 1024}, post_process=False)
    assert len(out) < MIB + 64 * 1024
    assert "%x%" in out


def test_deep_nesting_with_references_renders_instead_of_raising() -> None:
    deep = "{%x%|" * 5000 + "z" + "}" * 5000
    assert render(deep, context={"x": "a"}, seed=1, post_process=False) == "a"


def test_a_neutralized_value_keeps_its_brackets_but_is_still_split_on_its_pipe() -> None:
    """neutralize() shields the six structural characters; the pipe is deliberately not one of
    them, so inside an author's construct the value is still a list — in every engine."""
    out = render(
        '[<sep=", ">%v%]', context={"v": engine.neutralize("[a|b]")}, seed=1, post_process=False
    )
    assert re.fullmatch(r"\[a, b\]|b\], \[a", out), out


# ── the Ast input path, and the parser's `raw` decision ───────────────────────


@pytest.mark.parametrize(
    "template",
    ["[<minsize=3;maxsize=3;sep=\", \">%L%]", "{a|%L%}", "[{?flag?%L%|none}|c]", '[<sep="%S%">a|b]'],
)
def test_a_parsed_handle_renders_exactly_as_the_string_does(template: str) -> None:
    """No fixture can reach the `Ast` path (§5.2), and `raw` lives on the tree — a handle that
    lost it would render the old, wrong output while the string path renders the new."""
    context = {"L": "x|y|z", "S": ", ", "flag": "1"}
    for rng in ("first", "last"):
        assert render_with(parse(template), rng_from_strategy(rng), context=context, post_process=False) == rw(
            template, rng, context
        )


def test_a_handle_from_ast_version_2_is_refused() -> None:
    """A version-2 tree carries no `raw`, so rendering it would keep a pipe-joined value as ONE
    option — the very defect 0.4.0 fixed, silently back. The guard is the whole point."""
    stale = _ast.ParsedAst(source="{%L%}", set_defs={}, def_defs={}, nodes=(), ast_version=2)
    with pytest.raises(AstVersionError):
        render_with(stale, rng_from_strategy("first"))


def test_raw_is_kept_only_where_a_reference_is_direct() -> None:
    """The parity fixture pins the reference's answer on 24 templates; this is the readable
    summary — a plain construct pays nothing, a nested one splices at its own level."""

    def first_node(src: str) -> _ast.Node:
        return _parser.parse_sequence(src)[0]

    plain = first_node("{a|b}")
    assert isinstance(plain, _ast.EnumerationNode) and plain.raw is None
    direct = first_node("{a|%L%}")
    assert isinstance(direct, _ast.EnumerationNode) and direct.raw == "a|%L%"
    # A conditional is entered — its branch lands in the body before the split — so the
    # enumeration around it keeps its body too.
    branch = first_node("{a|{?flag?%L%}}")
    assert isinstance(branch, _ast.EnumerationNode) and branch.raw == "a|{?flag?%L%}"
    outer_with_branch = first_node("[{?flag?%L%|none}|c]")
    assert isinstance(outer_with_branch, _ast.PermutationNode)
    assert outer_with_branch.raw == "{?flag?%L%|none}|c"
    nested = first_node("[a|{%L%}]")
    assert isinstance(nested, _ast.PermutationNode) and nested.raw is None
    for sep_template in ('[<sep="%S%">a|b]', '[<lastsep="%S%">a|b|c]', "[a <%S%> | b]"):
        perm = first_node(sep_template)
        assert isinstance(perm, _ast.PermutationNode) and perm.raw == sep_template[1:-1]


def test_the_census_counts_the_parsed_tree_not_the_re_read_one() -> None:
    """`analyze` is a census of what the author wrote; a spliced list is a runtime fact."""
    counts = engine.analyze("{%L%}").constructs
    assert counts["enumeration"] == 1
    assert counts["variable"] == 1
