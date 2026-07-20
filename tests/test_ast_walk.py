"""`walk` has to reach every node, and has to survive depth.

Both matter for the same reason: `walk` is what validate/extract/analyze use to census a
tree. A branch it silently skips becomes a construct the tooling reports as absent —
which is the failure mode where a diagnostic is missing rather than wrong, and nobody
notices until a user asks why their `%var%` was not listed.

Depth is here because this repository has already paid for it once: a recursive pass in
the validator hit `RecursionError` on a chain of 996 links and had to be rewritten
iteratively. `walk` was written iteratively from the start, and this pins that.
"""

from __future__ import annotations

import sys

from spintax_core._ast import (
    ConditionalNode,
    EnumerationNode,
    LiteralNode,
    Node,
    PermConfig,
    PermOption,
    PermutationNode,
    PluralNode,
    VariableNode,
    walk,
)


def _collect(nodes: tuple[Node, ...]) -> list[Node]:
    seen: list[Node] = []
    walk(nodes, seen.append)
    return seen


def test_it_descends_into_every_child_sequence() -> None:
    """One node of each container type, each hiding a distinctly-named variable. A
    container `walk` forgets to descend into loses its variable from this set."""
    tree: tuple[Node, ...] = (
        EnumerationNode(options=((VariableNode("in_enum"),), (LiteralNode("x"),))),
        ConditionalNode(
            name="V",
            inverted=False,
            then=(VariableNode("in_then"),),
            otherwise=(VariableNode("in_else"),),
        ),
        PermutationNode(
            config=PermConfig(minsize=None, maxsize=None, sep=", ", lastsep=None),
            options=(PermOption(nodes=(VariableNode("in_perm"),), separator=None),),
        ),
    )
    names = {n.name for n in _collect(tree) if isinstance(n, VariableNode)}
    assert names == {"in_enum", "in_then", "in_else", "in_perm"}


def test_the_container_itself_is_visited_too() -> None:
    """Not only the leaves — a census counts enumerations, not just what is inside them."""
    tree: tuple[Node, ...] = (EnumerationNode(options=((LiteralNode("a"),),)),)
    assert any(isinstance(n, EnumerationNode) for n in _collect(tree))


def test_plural_slots_are_not_walked() -> None:
    """Deliberate, not an oversight: a plural keeps both slots as raw strings because the
    renderer expands variables in them at render time. There are no child nodes to reach,
    and inventing some here would put this tree out of step with the reference."""
    tree: tuple[Node, ...] = (PluralNode(count_raw="%n%", forms_raw="one|few|many"),)
    assert len(_collect(tree)) == 1


def test_order_is_depth_first() -> None:
    tree: tuple[Node, ...] = (
        EnumerationNode(options=((LiteralNode("a"), LiteralNode("b")),)),
        LiteralNode("c"),
    )
    literals = [n.value for n in _collect(tree) if isinstance(n, LiteralNode)]
    assert literals == ["a", "b", "c"]


def test_deep_nesting_does_not_exhaust_the_stack() -> None:
    """Nesting this deep is guarded at parse time, so the tree below cannot come from a
    template — which is exactly why a recursive `walk` would look fine in every test that
    used real input, and blow up on the one caller that built a tree itself.
    """
    depth = sys.getrecursionlimit() * 3
    node: Node = LiteralNode("core")
    for _ in range(depth):
        node = EnumerationNode(options=((node,),))
    assert len(_collect((node,))) == depth + 1
