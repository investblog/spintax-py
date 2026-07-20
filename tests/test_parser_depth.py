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

import pytest

from spintax_core import _parser, parse
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
