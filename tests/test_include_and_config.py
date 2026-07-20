"""The three surfaces the shared corpus can never reach.

`packages/conformance/schema/fixture.schema.json` has no field for an include resolver,
so **no fixture can ever cover `#include`** — the spec lists it under §5.2 "ungated", and
it shipped anyway. Five separate mutations of the include code passed the whole suite:
never splicing a child at all, an off-by-one on the depth guard, no cycle detection, no
terminator handling, and no sentinel stripping on the child. Two include tests existed and
both asserted on the *absence* of a child, so both survived "includes never splice".

The other two are corpus gaps rather than schema gaps. Every permutation fixture uses the
default `<config>`, so the whole `minsize`/`maxsize`/`sep`/`lastsep` clamp table and the
separator padding were unguarded; and the plural fixtures cover the two erasing paths but
neither of the two that re-emit with fullwidth braces.

Every expectation here is a measurement from `@spintax/core` 0.3.0 driven by the same
fixed draw source, not a reading of this port's own code. That distinction earned itself:
the first draft derived its expectations by reading, and eighteen were wrong — eighteen
expectations, no implementation. Three that read plausibly and are false: a `first` draw
source does NOT leave a permutation in source order (Fisher-Yates still runs), `[%p%]` is
a permutation rather than a bracketed literal, and a `<sep>` counts only at the END of a
part.

Exotic terminators are built with `chr()`. Written literally they are invisible in a diff,
and tooling that normalises escapes has already rewritten them once.
"""

from __future__ import annotations

import pytest

from spintax_core import PluralIssue, render, render_with

LS = chr(0x2028)  # LINE SEPARATOR
PS = chr(0x2029)  # PARAGRAPH SEPARATOR
SENTINEL = chr(0xE000)


def first(lo: int, _hi: int) -> int:
    return lo


def render_inc(
    template: str,
    mapping: dict[str, str],
    *,
    context: dict[str, str] | None = None,
    max_depth: int = 20,
) -> str:
    """Render with a resolver backed by `mapping`. Missing ref means no such template."""

    def resolve(ref: str) -> str | None:
        return mapping.get(ref)

    return render(
        template,
        include_resolver=resolve,
        context=context,
        max_depth=max_depth,
        post_process=False,
    )


# ── #include: does it splice at all ───────────────────────────────────────────


def test_an_include_is_replaced_by_its_child() -> None:
    """The assertion that was missing. Without it, an include subsystem that returns the
    empty string for everything passes the entire suite."""
    assert render_inc('#include "a"', {"a": "CHILD"}) == "CHILD"


def test_each_include_resolves_independently() -> None:
    """The `\\n` between them survives, though a trailing one at end of input does not.

    Not an inconsistency — it falls out of the trailing whitespace class being greedy and
    then backtracking. Between two includes it eats the `\\n`, finds `#` where the anchor
    needs a terminator or end-of-input, gives the `\\n` back, and the lookahead then
    matches on it. At end of input there is nothing to give back to. Both measured.
    """
    assert render_inc('#include "a"\n#include "b"', {"a": "A", "b": "B"}) == "A\nB"
    assert render_inc('#include "a"\n', {"a": "A"}) == "A"


def test_a_child_is_rendered_not_pasted() -> None:
    """The child goes through the whole pipeline — its own markup resolves."""
    assert render_inc('#include "a"', {"a": "{q|q}"}) == "q"


def test_an_include_may_be_indented() -> None:
    assert render_inc('   #include "a"', {"a": "C"}) == "C"


def test_an_include_must_start_its_line() -> None:
    """Line-anchored: text before it on the same line means it is not a directive."""
    assert render_inc('x #include "a"', {"a": "C"}) == 'x #include "a"'


def test_a_child_may_include_further() -> None:
    assert render_inc('#include "a"', {"a": '#include "b"', "b": "DEEP"}) == "DEEP"


# ── #include: the guards ──────────────────────────────────────────────────────


def test_a_cycle_resolves_to_empty_rather_than_hanging() -> None:
    """Detected by the ref STRING — the engine has no template identity beyond what the
    host supplies (§4.1), so two aliases for one template are not seen as a cycle."""
    out = render_inc('#include "a"', {"a": 'X\n#include "b"', "b": 'Y\n#include "a"'})
    assert out == "X\nY\n"


def test_a_self_include_resolves_to_empty() -> None:
    assert render_inc('#include "a"', {"a": 'S\n#include "a"'}) == "S\n"


def test_the_depth_guard_is_inclusive() -> None:
    """`max_depth=3` yields three levels, not four. An off-by-one here is silent — the
    output simply carries one line nobody counted."""
    chain = {str(i): f'L{i}\n#include "{i + 1}"' for i in range(8)}
    assert render_inc('#include "0"', chain, max_depth=3) == "L0\nL1\nL2\n"
    assert render_inc('#include "0"', chain, max_depth=1) == "L0\n"


def test_a_deep_include_chain_does_not_raise() -> None:
    """`max_depth` is a public parameter with no documented ceiling, and the recursive
    version of this raised `RecursionError` from 331 — breaking the lenient contract at a
    budget the caller is free to set."""
    chain = {str(i): f'L{i}\n#include "{i + 1}"' for i in range(2000)}
    out = render_inc('#include "0"', chain, max_depth=1500)
    assert out.startswith("L0\n")
    assert "L1499" in out


def test_a_sentinel_in_a_child_is_stripped() -> None:
    """A child is author markup too, so only `neutralize()` may put a sentinel into the
    stream. Otherwise the mandatory restore turns it into a brace nobody wrote."""
    assert render_inc('#include "a"', {"a": f"a{SENTINEL}b"}) == "ab"


# ── #include: scope ───────────────────────────────────────────────────────────


def test_a_child_inherits_the_runtime_context() -> None:
    assert render_inc('#include "a"', {"a": "%v%"}, context={"v": "RT"}) == "RT"


def test_a_child_does_not_see_the_parent_s_set() -> None:
    """Locals do not cross the boundary, matching the plugin's `for_child_render`, so
    `%p%` reaches the output unresolved.

    Angle brackets, not square ones: `[%p%]` is a PERMUTATION and would render as `%p%`
    whether or not the variable resolved, proving nothing.
    """
    assert render_inc('#set %p% = PARENT\n#include "a"', {"a": "<%p%>"}) == "\n<%p%>"


# ── #include: line terminators around the directive ───────────────────────────


@pytest.mark.parametrize(
    ("terminator", "expected"),
    [
        # In the pattern's trailing whitespace class, so they leave with the include line.
        ("\n", "C"),
        ("\r", "C"),
        ("\r\n", "C"),
        # NOT in that class. They end the line for the ANCHOR only, so the reference
        # leaves them standing — and this is the pair that caught a real bug: matching on
        # a copy with terminators normalised to \n let the trailing class eat a rewritten
        # U+2028, a character the reference's identical class can never match.
        (LS, "C" + LS),
        (PS, "C" + PS),
    ],
)
def test_a_terminator_after_an_include(terminator: str, expected: str) -> None:
    assert render_inc(f'#include "a"{terminator}', {"a": "C"}) == expected


# ── permutation <config>: the whole clamp table ───────────────────────────────


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        # A `first` draw source does NOT leave the elements in source order: the size pick
        # short-circuits, but Fisher-Yates still runs and j=0 each time rotates them.
        ("[a|b|c]", "b c a"),
        ('[<sep=", ">a|b|c]', "b, c, a"),
        # lastsep applies to the final join only.
        ('[<sep=", " lastsep=" and ">a|b|c]', "b, c and a"),
        # A purely alphabetic separator is space-padded; anything else passes through.
        ('[<sep="and">a|b|c]', "b and c and a"),
        ('[<sep="-">a|b|c]', "b-c-a"),
        # Sizes clamp to the element count, and never below one.
        ("[<maxsize=2>a|b|c]", "b"),
        ("[<minsize=2>a|b|c]", "b c"),
        ("[<minsize=2 maxsize=2>a|b|c]", "b c"),
        ("[<minsize=9 maxsize=9>a|b|c]", "b c a"),
        ("[<minsize=0>a|b|c]", "b"),
        # A per-element separator counts only at the END of a part, and then applies to
        # the element that follows it.
        ("[a<, >|b|c]", "b c a"),
        ("[a<, >|b<; >|c]", "b; c a"),
        ('[<sep=" & ">a<, >|b|c]', "b & c & a"),
    ],
)
def test_permutation_config(template: str, expected: str) -> None:
    """The corpus's permutation fixtures all use the default `<config>`, so none of this
    table was guarded: mutations that dropped the padding, ignored `lastsep`, or clamped
    the minimum to zero instead of one all passed the full suite."""
    assert render_with(template, first, post_process=False) == expected


# ── plural: the lenient fallbacks ─────────────────────────────────────────────


def test_an_arity_mismatch_re_emits_with_fullwidth_braces() -> None:
    """Fullwidth so no later pass reads it as markup again. The corpus covers the two
    paths that ERASE the block and neither of the two that re-emit it."""
    assert render("{plural 1: a|b|c}", locale="en", post_process=False) == "｛plural 1: a|b|c｝"


def test_nested_brackets_in_a_form_re_emit_with_fullwidth_braces() -> None:
    """EVERY brace widens, the nested ones included — the fallback rewrites the whole
    construct, so nothing inside it can be read as markup either."""
    out = render("{plural 1: {a|b}|c}", locale="en", post_process=False)
    assert out == "｛plural 1: ｛a|b｝|c｝"


def test_the_bracket_check_runs_before_the_numeric_check() -> None:
    """Order is load-bearing. With a non-numeric count AND nested brackets the reference
    re-emits; swapping the two checks erases the block instead, silently."""
    out = render("{plural zz: {a|b}|c}", locale="en", post_process=False)
    assert out == "｛plural zz: ｛a|b｝|c｝"


def test_the_count_is_php_trimmed() -> None:
    """`{plural  1 : a|b}` renders `a`, not empty: the count is trimmed before the numeric
    test. Without the trim it reads as non-numeric and the block is erased."""
    assert render("{plural  1 : a|b}", locale="en", post_process=False) == "a"


# ── plural: the observer is reachable ─────────────────────────────────────────


def test_a_host_can_observe_an_unresolvable_plural() -> None:
    """`on_plural_error` was plumbed through `_render` and `_pipeline` but not through the
    public API, so every report it makes was unreachable from outside.

    Erasing leaves no trace in the output, which makes this the ONLY way a host can tell a
    deliberately empty sentence from an unsubstituted `%Var%`.
    """
    seen: list[PluralIssue] = []
    out = render(
        "{plural %n%: one|few|many}",
        locale="ru",
        post_process=False,
        on_plural_error=seen.append,
    )
    assert out == ""
    assert [i.code for i in seen] == ["plural.count"]
    # The forms slot keeps the space after the colon: the split is on the first colon and
    # the report quotes what the renderer saw.
    assert seen[0].construct == "{plural %n%: one|few|many}"
    assert seen[0].locale == "ru"


def test_an_arity_report_carries_the_numbers() -> None:
    seen: list[PluralIssue] = []
    render("{plural 1: a|b|c}", locale="en", post_process=False, on_plural_error=seen.append)
    assert [(i.code, i.expected, i.got) for i in seen] == [("plural.arity", 2, 3)]


def test_no_observer_means_no_change_in_output() -> None:
    """Observation only: the render degrades identically whether anyone is listening."""
    watched = render(
        "{plural x: a|b}", locale="en", post_process=False, on_plural_error=lambda _i: None
    )
    assert watched == render("{plural x: a|b}", locale="en", post_process=False)
