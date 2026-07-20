"""The tree this parser builds must be the tree the reference builds.

The golden corpus gates *rendered output*. It is the stronger contract for users and the
weaker one for a parser: two trees can render identically for every fixture and still
differ in a corner the renderer has not reached yet — which is a bug that lands later,
somewhere else, looking like a renderer fault.

So this compares the trees directly, against a frozen dump of the reference's own
`parse()`. The templates are chosen to sit on the seams between the two regex dialects
and on the places the reference's own comments warn about:

- JavaScript's `\\w`, `\\d` and `\\b` are ASCII and Python's are not
- JS `\\s` and Python `\\s` disagree in BOTH directions (U+FEFF one way; U+001C–001F and
  U+0085 the other)
- PHP's `trim` is five characters, not Unicode whitespace
- `split_top_level` and the conditional pipe-split are deliberately different algorithms
- permutation config is extracted BEFORE the top-level split, so `sep="|"` is not a split
- a `<…>` that is really an HTML tag must not be eaten as config or as a separator
- the parser is lenient: malformed input degrades, it never raises

Verified to bite: with the corpus in place, reintroducing any one of those divergences in
`_charclasses` or `_parser` turns this red. The one exception is documented at
`_HTML_TAG_RE` — its `\\Z` is unreachable behind an upstream trim, and swapping it for
`$` provably changes nothing.

Regenerating the fixture is a deliberate act, not a refresh — see
`tests/data/generate_parser_parity.cjs`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spintax_core import _parser
from spintax_core._ast import (
    ConditionalNode,
    EnumerationNode,
    LiteralNode,
    Node,
    PermutationNode,
    PluralNode,
    VariableNode,
)

_FIXTURE = Path(__file__).resolve().parent / "data" / "parser_parity.json"
_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_CASES = _DATA["cases"]


def _node_to_reference_shape(node: Node) -> dict[str, Any]:
    """Rename our fields to the reference's. Deliberately dumb — nothing else changes.

    Anything cleverer here could absorb the very difference this test exists to find.
    """
    if isinstance(node, LiteralNode):
        return {"type": "literal", "value": node.value}
    if isinstance(node, VariableNode):
        return {"type": "variable", "name": node.name}
    if isinstance(node, EnumerationNode):
        return {
            "type": "enumeration",
            "options": [[_node_to_reference_shape(n) for n in o] for o in node.options],
        }
    if isinstance(node, ConditionalNode):
        return {
            "type": "conditional",
            "name": node.name,
            "inverted": node.inverted,
            "then": [_node_to_reference_shape(n) for n in node.then],
            # `else` is a Python keyword; `otherwise` is the only renamed field.
            "else": [_node_to_reference_shape(n) for n in node.otherwise],
        }
    if isinstance(node, PermutationNode):
        return {
            "type": "permutation",
            "config": {
                "minsize": node.config.minsize,
                "maxsize": node.config.maxsize,
                "sep": node.config.sep,
                "lastsep": node.config.lastsep,
            },
            "options": [
                {
                    "nodes": [_node_to_reference_shape(n) for n in o.nodes],
                    "separator": o.separator,
                }
                for o in node.options
            ],
        }
    if isinstance(node, PluralNode):
        return {"type": "plural", "countRaw": node.count_raw, "formsRaw": node.forms_raw}
    raise AssertionError(f"node type not covered by the comparison: {node!r}")


def _parse_to_reference_shape(src: str) -> dict[str, Any]:
    ast = _parser.parse_template(src)
    return {
        "astVersion": ast.ast_version,
        "source": ast.source,
        "setDefs": dict(ast.set_defs),
        "defDefs": dict(ast.def_defs),
        "nodes": [_node_to_reference_shape(n) for n in ast.nodes],
    }


@pytest.mark.parametrize(
    "case", _CASES, ids=[f"{i:03d}" for i in range(len(_CASES))]
)
def test_the_tree_matches_the_reference(case: dict[str, Any]) -> None:
    template = case["template"]
    assert _parse_to_reference_shape(template) == case["ast"], (
        f"tree differs from @spintax/core {_DATA['reference_version']} "
        f"for template {template!r}"
    )


def test_the_parser_never_raises() -> None:
    """Leniency is a contract, not a quality (§9.2), and it is the property the corpus
    is least able to check: fixtures assert what malformed input renders to, never that
    nothing was thrown on the way. Every template in the fixture is parsed here for the
    single purpose of not raising."""
    for case in _CASES:
        _parser.parse_template(case["template"])


def test_the_fixture_records_which_engine_built_it() -> None:
    """Without this the file is a set of magic numbers. With it, a parity failure after a
    dependency bump reads as 'regenerate me' rather than 'the parser broke'."""
    assert _DATA["reference_version"]
    assert len(_CASES) > 100, "corpus shrank — was the fixture regenerated from a stub?"
