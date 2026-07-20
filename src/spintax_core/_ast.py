"""The parsed tree.

Six node types, and two things that are deliberately *not* nodes:

- **Directives.** `#set` and `#def` are line-anchored and pulled out of the whole text
  before the tree is built (`_directives.py`), which is why a `#set` on its own line
  *inside* a group is a global definition rather than an option's literal text. They
  live on the tree as two maps, kept separate because their semantics are opposite: a
  `#set` value is a macro substituted at every reference, so its brackets re-roll each
  time, while a `#def` value is rolled once per render and frozen.
- **`#include`.** Resolved by the renderer as a post-tree string pass, matching the
  plugin, where includes resolve after enumerations and permutations. It stays literal
  text in the tree.

`Ast` is the opaque public handle; `ParsedAst` is the internal shape. It is an in-memory
performance handle and **not** a serialization format — do not persist it across engine
versions, which is what `AST_VERSION` and the guard in the pipeline exist to enforce.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeGuard

from ._errors import AstVersionError

#: Bumped only on a breaking change to the node shape, independently of syntax version.
#:
#: 2 — `ParsedAst` gained `def_defs`. An `Ast` built by an older version carries no `#def`
#: map, so rendering it would silently drop every definition; the guard turns that into a
#: loud failure instead.
AST_VERSION = 2


class Ast:
    """Opaque, versioned parse handle.

    Kept a class rather than a type alias so the opacity is enforced by the type checker
    instead of by a docstring: callers can hold one and hand it back, and can reach
    nothing inside it.
    """

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class LiteralNode:
    """Verbatim text."""

    value: str


@dataclass(frozen=True, slots=True)
class VariableNode:
    """`%name%`. Stored verbatim; lookup is case-insensitive at render time."""

    name: str


@dataclass(frozen=True, slots=True)
class EnumerationNode:
    """`{a|b|c}` — pick one option. Each option is its own node sequence."""

    options: tuple[tuple[Node, ...], ...]


@dataclass(frozen=True, slots=True)
class PermConfig:
    """A permutation's `<config>` prefix. A `None` size means the default rules (§4.2)."""

    minsize: int | None
    maxsize: int | None
    sep: str
    lastsep: str | None


@dataclass(frozen=True, slots=True)
class PermOption:
    """One permutation element, plus the separator that preceded it, if any."""

    nodes: tuple[Node, ...]
    separator: str | None


@dataclass(frozen=True, slots=True)
class PermutationNode:
    """`[<config>a|b|c]` — select, shuffle, join."""

    config: PermConfig
    options: tuple[PermOption, ...]


@dataclass(frozen=True, slots=True)
class ConditionalNode:
    """`{?VAR?then|else}` / `{?!VAR?then}` — branch on whether VAR is truthy.

    `otherwise` rather than `else`, which is a Python keyword. A **malformed** `{?…}` is
    not represented here at all: the parser falls back to reading the braces as an
    enumeration, matching the plugin, where a bad conditional survives the conditional
    pass untouched and is then consumed by the enumeration pass.
    """

    name: str
    inverted: bool
    then: tuple[Node, ...]
    otherwise: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class PluralNode:
    """`{plural <count>: one|few|many}`, both slots kept RAW.

    Raw because either may hold a `%var%`: the renderer expands variables in them first
    (plurals run after variable expansion and before enum/perm), then splits, checks
    arity and picks. The lenient path — nested `{}`/`[]` in a form, or the wrong number
    of forms — re-emits the block with fullwidth braces instead of raising.
    """

    count_raw: str
    forms_raw: str


Node = (
    LiteralNode
    | VariableNode
    | EnumerationNode
    | PermutationNode
    | ConditionalNode
    | PluralNode
)


@dataclass(frozen=True, slots=True)
class ParsedAst(Ast):
    """The internal tree, plus what the raw-text passes found.

    `source` is carried so `validate(Ast)` can still run the checks that are raw-text by
    design — bracket balance is not representable in a lenient tree, because an
    unbalanced bracket simply becomes literal text.
    """

    source: str
    set_defs: Mapping[str, str]
    def_defs: Mapping[str, str]
    nodes: tuple[Node, ...]
    ast_version: int = field(default=AST_VERSION)


def is_parsed_ast(value: object) -> TypeGuard[ParsedAst]:
    """Was this produced by *this* engine version?

    Total by contract — it answers for any object, including a bare `Ast()` whose slots
    were never filled, because the pipeline's job is to turn a bad handle into a clean
    error rather than an `AttributeError` from inside a predicate.
    """
    return isinstance(value, ParsedAst) and getattr(value, "ast_version", None) == AST_VERSION


def require_parsed(value: Ast) -> ParsedAst:
    """Trust a handle, or refuse it loudly. The version guard, written once.

    Every public entry point takes `str | Ast`, so every one of them needs this rule and
    the same message for breaking it. Two copies would be two messages.
    """
    if is_parsed_ast(value):
        return value
    raise AstVersionError("Ast was not produced by this engine version.")


def source_of(value: str | Ast) -> str:
    """The template text behind a `str | Ast`.

    `validate` and `extract` are raw-text scanners by design — a lenient tree cannot
    represent an unbalanced bracket, so there is nothing in it for them to read. Handing
    them an `Ast` therefore means handing them the source it was parsed from, which is why
    `ParsedAst` carries it at all.
    """
    if isinstance(value, str):
        return value
    return require_parsed(value).source


def walk(nodes: Sequence[Node], visit: Callable[[Node], None]) -> None:
    """Depth-first over every node, descending into all child sequences.

    Iterative rather than recursive, and this is load-bearing rather than tidy.

    **Nothing bounds nesting before a tree reaches here.** `max_depth` reads like a parse
    guard — the reference's own comment calls it a "#include + parse-nesting guard" — but
    it is only ever checked against the `#include` stack. Ordinary string input therefore
    produces a tree as deep as the author cares to nest, which is exactly how the
    recursive parser that preceded this died at 350 levels on a 701-character template.
    A recursive walk would die the same way, on trees this engine really does build.

    Takes a `Sequence` rather than a tuple so a caller mid-construction can pass the list
    it is still building.
    """
    stack: list[Node] = list(reversed(nodes))
    while stack:
        node = stack.pop()
        visit(node)
        if isinstance(node, EnumerationNode):
            for branch in reversed(node.options):
                stack.extend(reversed(branch))
        elif isinstance(node, ConditionalNode):
            stack.extend(reversed(node.otherwise))
            stack.extend(reversed(node.then))
        elif isinstance(node, PermutationNode):
            for element in reversed(node.options):
                stack.extend(reversed(element.nodes))
