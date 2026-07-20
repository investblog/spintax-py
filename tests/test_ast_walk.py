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


def test_sibling_branches_are_visited_in_source_order() -> None:
    """The test above cannot see a reversal bug, and this one can.

    Rewriting a recursive walk with an explicit stack means pushing children in reverse
    so they pop in order, and getting that backwards is the single most likely mistake in
    the rewrite. It stays invisible to every assertion that uses one option per
    container, or compares a set: three separate reversal mutations were checked against
    the rest of this file and all three survived it.

    So: two branches per container, and an ordered comparison. `then` must precede
    `otherwise`, option 1 must precede option 2, element 1 must precede element 2.
    """
    tree: tuple[Node, ...] = (
        EnumerationNode(
            options=((LiteralNode("e1"),), (LiteralNode("e2"),), (LiteralNode("e3"),))
        ),
        ConditionalNode(
            name="V",
            inverted=False,
            then=(LiteralNode("t1"), LiteralNode("t2")),
            otherwise=(LiteralNode("f1"), LiteralNode("f2")),
        ),
        PermutationNode(
            config=PermConfig(minsize=None, maxsize=None, sep=", ", lastsep=None),
            options=(
                PermOption(nodes=(LiteralNode("p1"),), separator=None),
                PermOption(nodes=(LiteralNode("p2"),), separator=", "),
                PermOption(nodes=(LiteralNode("p3"),), separator=", "),
            ),
        ),
    )
    literals = [n.value for n in _collect(tree) if isinstance(n, LiteralNode)]
    assert literals == [
        "e1", "e2", "e3",
        "t1", "t2", "f1", "f2",
        "p1", "p2", "p3",
    ]


def test_deep_nesting_does_not_exhaust_the_stack() -> None:
    """A tree this deep is not hypothetical — an ordinary template builds one.

    An earlier version of this docstring claimed nesting was capped at parse time. It is
    not: `max_depth` guards the `#include` stack and never reaches the parser, so any
    string can nest as deep as its author likes. The recursive parser that preceded the
    current one died at 350 levels on a 701-character template, and a recursive `walk`
    would die on the same input.
    """
    depth = sys.getrecursionlimit() * 3
    node: Node = LiteralNode("core")
    for _ in range(depth):
        node = EnumerationNode(options=((node,),))
    assert len(_collect((node,))) == depth + 1
