"""Deep nesting must not raise, because nothing stops a template from being deep.

`max_depth` looks like it covers this — the reference's own comment calls it a
"#include + parse-nesting guard" — but it is only ever compared against the include
stack. The parser has no depth limit at all, so a plain string reaches it at whatever
nesting its author wrote.

That gap shipped once. The first version of `parse_sequence` was recursive, cost three
Python frames per level, and raised `RecursionError` at about 350 levels — a 701-character
template. The reference parses 1000 of the same without complaint. No corpus fixture
covers nesting, so nothing else in this suite would have noticed.

These numbers are chosen to sit far above real templates and far below the point where
the shared O(n²) bracket matcher makes the test slow. They are a guard against the
failure returning, not a benchmark.
"""

from __future__ import annotations

import time

import pytest

from spintax_core import _parser, parse, render
from spintax_core._ast import EnumerationNode, LiteralNode, walk


@pytest.mark.parametrize(
    ("label", "opener", "closer"),
    [
        ("enumeration", "{", "}"),
        ("permutation", "[", "]"),
        ("conditional", "{?V?", "}"),
    ],
)
def test_nesting_far_past_the_recursion_limit_parses(
    label: str, opener: str, closer: str
) -> None:
    """1000 levels: what the reference handles, and four times what the recursive
    version managed."""
    depth = 1000
    template = opener * depth + "a" + closer * depth
    assert parse(template) is not None


def test_the_tree_really_is_as_deep_as_the_template() -> None:
    """Parsing without raising is not enough on its own — a parser that gave up quietly
    and returned the rest as literal text would also 'not raise'. This walks down to
    confirm the structure is there."""
    depth = 500
    ast = _parser.parse_template("{" * depth + "core" + "}" * depth)

    node = ast.nodes[0]
    levels = 0
    while isinstance(node, EnumerationNode):
        levels += 1
        node = node.options[0][0]

    assert levels == depth
    assert isinstance(node, LiteralNode)
    assert node.value == "core"


def test_a_deep_tree_can_still_be_walked() -> None:
    """The parser and `walk` have to clear the same bar, and each was written iteratively
    for this reason. A recursive walk over a tree only the iterative parser can build
    would move the failure rather than remove it."""
    depth = 1000
    ast = _parser.parse_template("{" * depth + "x" + "}" * depth)

    seen = 0

    def count(_node: object) -> None:
        nonlocal seen
        seen += 1

    walk(ast.nodes, count)
    assert seen == depth + 1  # one enumeration per level, plus the literal


def test_a_deep_conditional_in_a_plural_count_slot_renders() -> None:
    """The count slot is the one place a construct is walked by the RENDERER, not the parser.

    The first version of that pass recursed into the taken branch, cost one frame per
    level, and raised ``RecursionError`` at about 1000 levels -- a 5 KB template, and from
    inside a web framework's request handler it failed at 700. Same lesson as
    ``parse_sequence`` above, learned twice; it is iterative now.
    """
    depth = 3_000  # 3x the interpreter's frame limit, which is what the old pass hit
    template = "#set %V% = y\n{plural " + "{?V?" * depth + "1" + "}" * depth + ": one|two}"

    assert render(template, locale="en") == "One"


def test_an_unbalanced_plural_count_slot_stays_linear() -> None:
    """Legal input: only the whole ``{plural …}`` block has to balance, and the slot is cut
    at the first ``:``. Walking to the matching brace per ``{?`` rescanned to the end of the
    slot every time it failed, which made the pass quadratic. The ceiling is loose on
    purpose -- it is here to catch a return to quadratic, not to time the machine.
    """
    n = 100_000
    template = "{plural " + "{?a?" * n + ": one|two" + "}" * (n + 1)

    started = time.monotonic()
    assert "｛plural" in render(template, locale="en")
    assert time.monotonic() - started < 20
