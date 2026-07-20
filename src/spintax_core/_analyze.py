"""The construct census — the one thing `analyze` computes that nothing else does.

Best-effort and author-visible (§9.3): it counts what someone wrote, **not** how many
variants a template can produce. Those two numbers look interchangeable and are not — an
enumeration inside an unpicked branch still counts here, and two enumerations multiply
rather than add. Anything reading this as cardinality will be wrong by orders of magnitude.

Nested nodes count. Literals do not.
"""

from __future__ import annotations

from ._ast import (
    ConditionalNode,
    EnumerationNode,
    Node,
    ParsedAst,
    PermutationNode,
    PluralNode,
    VariableNode,
    walk,
)

#: The five node types worth counting, in the reference's key order.
_NODE_KEYS: dict[type, str] = {
    EnumerationNode: "enumeration",
    PermutationNode: "permutation",
    VariableNode: "variable",
    ConditionalNode: "conditional",
    PluralNode: "plural",
}


def count_constructs(ast: ParsedAst, include_count: int) -> dict[str, int]:
    """Census a parsed tree, plus the two counts that are not tree nodes.

    Both count DISTINCT names, not occurrences, though they arrive by different routes:
    `set` from a map that has already collapsed a redefinition, `include` from the
    extractor's deduplicated ref list. Measured, because the opposite reads just as
    plausibly: `#include "x"` twice counts **one**, exactly as `#set %a%` twice does.

    **`def` is deliberately absent, mirroring a suspected upstream bug.** The reference
    counts `setDefs` and not `defDefs` — measurable: a template with one `#set` and one
    `#def` reports `set: 1` and no `def` key at all, while `defs: ["b"]` shows up in the
    extraction beside it. That reads like an oversight left from `#def` arriving in AST
    version 2 rather than a decision. It is reproduced here anyway: `constructs` is a
    mapping a host iterates, and adding a key TypeScript does not emit would break the one
    mental model across three engines that this port keeps choosing. The fix belongs
    upstream, where all three can follow.
    """
    counts = {key: 0 for key in _NODE_KEYS.values()}

    def visit(node: Node) -> None:
        key = _NODE_KEYS.get(type(node))
        if key is not None:
            counts[key] += 1

    walk(ast.nodes, visit)

    counts["set"] = len(ast.set_defs)
    counts["include"] = include_count
    return counts
