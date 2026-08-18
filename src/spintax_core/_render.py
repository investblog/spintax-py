"""Tree-walk renderer with the plugin's staged semantics layered on.

Not a naive walk. The stages run in a fixed order that the plugin established and three
engines now depend on:

1. `#set` values go into the variable map RAW — a macro, re-parsed and re-rendered at
   every reference, so its brackets re-roll each time.
2. Runtime context overlays them and wins.
3. `#def` values are rendered ONCE, in dependency order, against that full map. A
   definition can therefore read globals and runtime variables; a runtime variable of the
   same name outranks it, and the definition is then never rolled at all.
4. The tree is walked. A variable whose value contains constructs is re-parsed and
   rendered in place, which is how conditionals and plurals introduced *by a value* get
   resolved without a separate pass.
5. `#include` is resolved last, as a string pass over the rendered text, matching the
   plugin's post-enumeration `resolve_includes`.

Two deliberate divergences from the plugin, both recorded upstream: enumerations render
outer-first and lazily (only the picked branch draws), and plural forms re-enter the
pipeline after the bucket is chosen.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from . import _parser, _plurals
from ._ast import (
    ConditionalNode,
    EnumerationNode,
    LiteralNode,
    Node,
    ParsedAst,
    PermConfig,
    PermutationNode,
    PluralNode,
    VariableNode,
)
from ._charclasses import (
    ASCII_DIGIT,
    ASCII_WORD,
    JS_LINE_END,
    JS_LINE_START,
    JS_NOT_SPACE,
    PHP_TRIM_CHARS,
)
from ._errors import IncludeResolverError
from ._rng import Rng

#: How many times a variable value may be re-expanded before the renderer stops.
MAX_VARIABLE_DEPTH = 50

#: Characters a single render may produce by expanding ``%variables%`` (spintax-js#69).
#:
#: Depth alone does not bound expansion, only its height: ``#set %a% = %b% %b%`` over
#: ``#set %b% = %a% %a%`` replaces one reference with two every level, so 50 levels is
#: 2**50 and a 62-character template ended the process in every engine of the family.
#: Acyclic doubling does the same, so the cycle guard never sees it.
#:
#: Deliberately far above any real document -- the point is to end an explosion, not to
#: ration ordinary output.
MAX_EXPANSION_CHARS = 1024 * 1024


class _Budget:
    """Expansion allowance, shared by every branch of one render.

    A mutable object rather than a field on ``_Walk`` because ``_Walk`` is rebuilt with
    ``replace()`` on the way down; a plain int would give each branch its own allowance and
    bound nothing.
    """

    __slots__ = ("left",)

    def __init__(self, left: int) -> None:
        self.left = left

#: Line-anchored `#include "ref"`. Two classes here are deliberately narrow:
#:
#: - the whitespace around the ref is ASCII, because that is what PHP's `\s` matches under
#:   `/u`; widening it would make an NBSP after `#include` legal here and illegal in the
#:   plugin;
#: - the anchors are JavaScript's, spelled out, and the text is NOT normalised first.
#:   Normalising terminators to `\n` before matching lets the trailing `[ \t\n\r\f\x0b]*`
#:   swallow a rewritten U+2028 — a character the reference's own class cannot match, so
#:   the reference leaves it in place. Measured: `#include "a" ` renders as
#:   `"C "` there and used to render as `"C"` here.
_INCLUDE_LINE_RE = re.compile(
    JS_LINE_START + r'[ \t]*#include[ \t\n\r\f\x0b]+"([^"]+)"[ \t\n\r\f\x0b]*' + JS_LINE_END
)

_VARIABLE_RE = re.compile(f"%({ASCII_WORD}+)%")
#: `\Z` rather than `$`: the reference has no `m` flag here, so it anchors at the very end
#: and must not accept a trailing newline.
_INTEGER_RE = re.compile(f"-?{ASCII_DIGIT}+\\Z")
_NOT_BLANK_RE = re.compile(JS_NOT_SPACE)
_HAS_CONSTRUCT_RE = re.compile(r"[{\[%]")
_HAS_BRACKET_RE = re.compile(r"[{}\[\]]")


@dataclass(frozen=True, slots=True)
class PluralIssue:
    """A `{plural …}` the renderer could not resolve.

    Observation only — the render degrades exactly as it would without an observer, and
    the host decides whether a report is fatal. `plural.count` is the one code with no
    `validate()` counterpart, and cannot have one: an unresolved count is a fact about a
    runtime value, invisible to static analysis.
    """

    code: str
    message: str
    #: The construct as the renderer saw it, AFTER variable expansion.
    construct: str
    #: Normalized base language the arity was judged against.
    locale: str
    expected: int | None = None
    got: int | None = None


@dataclass(frozen=True, slots=True)
class RenderCtx:
    """Document-level context. Threads through nested `#include` resolution."""

    runtime_context: Mapping[str, str]
    rng: Rng
    locale: str
    resolver: Callable[[str], str | None] | None
    max_depth: int
    #: The `#include` ref chain, for circular-reference detection.
    include_stack: tuple[str, ...]
    on_plural_error: Callable[[PluralIssue], None] | None


@dataclass(frozen=True, slots=True)
class _Walk:
    """What a single tree walk needs. Rebuilt with `replace()` when depth or vars change."""

    vars: Mapping[str, str]
    rng: Rng
    locale: str
    depth: int
    on_plural_error: Callable[[PluralIssue], None] | None
    budget: _Budget


def render_ast(ast: ParsedAst, ctx: RenderCtx) -> str:
    text = _render_body(ast, ctx)
    return _resolve_includes(text, ctx) if ctx.resolver else text


def _render_body(ast: ParsedAst, ctx: RenderCtx) -> str:
    """Everything except `#include` splicing: variables, `#def`, the tree walk.

    Split out so include resolution can be a flat loop over rendered bodies rather than a
    recursion through `render_ast`.
    """
    base = build_vars(ast.set_defs, ctx.runtime_context)
    walk = _Walk(
        vars=base,
        rng=ctx.rng,
        locale=ctx.locale,
        depth=0,
        on_plural_error=ctx.on_plural_error,
        budget=_Budget(MAX_EXPANSION_CHARS),
    )
    # Rolled here rather than inside `build_vars` because a definition renders against the
    # FULL context — globals and runtime included — so it has to wait for that to exist.
    if ast.def_defs:
        rolled = roll_definitions(ast.def_defs, base, ctx.runtime_context, walk)
        walk = replace(walk, vars={**base, **rolled})

    return render_nodes(ast.nodes, walk)


def build_vars(
    set_defs: Mapping[str, str], context: Mapping[str, str]
) -> dict[str, str]:
    """Merge `#set` values and the runtime context, context winning. Keys lower-cased.

    Nothing is resolved here. A `#set` is a macro: its value is re-parsed and re-rendered
    at every reference, so brackets inside it re-roll every time. (Before engine 3.0.0
    this collapsed enumeration-valued `#set`s once; that behaviour is what `#def` is now.)
    """
    merged: dict[str, str] = dict(set_defs)
    for name, value in context.items():
        merged[name.lower()] = value
    return merged


def roll_definitions(
    def_defs: Mapping[str, str],
    variables: Mapping[str, str],
    context: Mapping[str, str],
    walk: _Walk,
) -> dict[str, str]:
    """Render each `#def` value once and freeze the result for every reference."""
    outranked = {key.lower() for key in context}
    rolled: dict[str, str] = {}

    # The alias map is every macro value a definition can see, MINUS the definitions about
    # to be rolled: a `#def` shadows a same-named global, and hopping through the shadowed
    # value would compute the wrong dependency graph. A definition the runtime outranks
    # stays in, because it is never rolled — the runtime value is what gets substituted,
    # so the graph has to follow that instead.
    aliases = {
        name: value
        for name, value in variables.items()
        if not (name in def_defs and name not in outranked)
    }

    for name in _order_definitions(def_defs, aliases):
        if name in outranked:
            continue
        value = def_defs.get(name, "")
        rolled[name] = render_nodes(
            _parser.parse_sequence(value), replace(walk, vars={**variables, **rolled})
        )

    return rolled


def _order_definitions(
    def_defs: Mapping[str, str], aliases: Mapping[str, str]
) -> list[str]:
    """Definition names, dependencies first. A cycle cannot be ordered, so it goes last."""
    names = list(def_defs)
    blocked: dict[str, set[str]] = {}
    for name in names:
        reached = _referenced_names(def_defs.get(name, ""), aliases)
        blocked[name] = {candidate for candidate in names if candidate in reached}

    ordered: list[str] = []
    pending = names
    while pending:
        ready = [
            name
            for name in pending
            if not any(dep != name and dep in pending for dep in blocked.get(name, ()))
        ]
        if not ready:
            return [*ordered, *pending]
        ordered.extend(ready)
        ready_set = set(ready)
        pending = [name for name in pending if name not in ready_set]

    return ordered


def _referenced_names(value: str, aliases: Mapping[str, str]) -> set[str]:
    """Every variable name a value reaches, hopping through macro values to a fixpoint.

    The hop is what makes a `#def` able to depend on another `#def` *through* a `#set`:
    the alias is substituted at reference time, so it never appears in the first
    definition's own text.
    """
    seen: set[str] = set()
    queue = _direct_references(value)
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        alias = aliases.get(name)
        if alias is not None:
            queue.extend(_direct_references(alias))
    return seen


def _direct_references(text: str) -> list[str]:
    """The `%var%` names written literally in a string, lower-cased."""
    return [m.group(1).lower() for m in _VARIABLE_RE.finditer(text)]


@dataclass(slots=True)
class _Seq:
    """A half-finished walk of one node sequence, writing into `out`."""

    nodes: Sequence[Node]
    out: list[str]
    walk: _Walk
    i: int = 0


@dataclass(slots=True)
class _JoinPermutation:
    """Runs once a permutation's elements are all rendered: draw, shuffle, join."""

    out: list[str]
    parts: list[list[str]]
    separators: list[str | None]
    config: PermConfig
    rng: Rng


def render_nodes(nodes: Sequence[Node], walk: _Walk) -> str:
    """Walk a node sequence to a string.

    **Iterative, and for the same reason the parser is.** The parser was made iterative
    after it raised `RecursionError` at ~350 levels of nesting; a recursive renderer over
    the same tree simply moved the failure, dying at ~300 on input the parser now handles
    happily. Nothing bounds nesting before either of them — `max_depth` guards the
    `#include` stack alone.

    **The draw order is the hard constraint here, not the traversal.** It differs per
    node type and the corpus asserts it exactly:

    - an enumeration draws its pick FIRST, then renders only the branch it chose;
    - a permutation renders EVERY element first, then draws the size, then shuffles;
    - a conditional draws nothing.

    So a construct pushes this walk back (already advanced past itself), then whatever it
    needs. LIFO makes the children run before the resumed parent, and a permutation's
    join step sits between the two so its draws land after its children's and before
    anything that follows.
    """
    root: list[str] = []
    stack: list[_Seq | _JoinPermutation] = [_Seq(nodes=nodes, out=root, walk=walk)]

    while stack:
        job = stack.pop()

        if isinstance(job, _JoinPermutation):
            job.out.append(_finish_permutation(job))
            continue

        suspended = False
        while job.i < len(job.nodes):
            node = job.nodes[job.i]
            job.i += 1  # advanced BEFORE any suspend, so the resume starts after it

            if isinstance(node, LiteralNode):
                job.out.append(node.value)
                continue

            if isinstance(node, VariableNode):
                text, children = _resolve_variable(node.name, job.walk)
                if children is None:
                    job.out.append(text)
                    continue
                stack.append(job)
                stack.append(
                    _Seq(
                        nodes=children,
                        out=job.out,
                        walk=replace(job.walk, depth=job.walk.depth + 1),
                    )
                )
                suspended = True
                break

            if isinstance(node, EnumerationNode):
                if not node.options:
                    continue
                picked = node.options[_random_int(job.walk.rng, 0, len(node.options) - 1)]
                stack.append(job)
                stack.append(_Seq(nodes=picked, out=job.out, walk=job.walk))
                suspended = True
                break

            if isinstance(node, ConditionalNode):
                branch = _conditional_branch(node, job.walk)
                stack.append(job)
                stack.append(_Seq(nodes=branch, out=job.out, walk=job.walk))
                suspended = True
                break

            if isinstance(node, PermutationNode):
                if not node.options:
                    continue
                parts: list[list[str]] = [[] for _ in node.options]
                stack.append(job)
                stack.append(
                    _JoinPermutation(
                        out=job.out,
                        parts=parts,
                        separators=[o.separator for o in node.options],
                        config=node.config,
                        rng=job.walk.rng,
                    )
                )
                for option, part in reversed(list(zip(node.options, parts, strict=True))):
                    stack.append(_Seq(nodes=option.nodes, out=part, walk=job.walk))
                suspended = True
                break

            text, children = _render_plural(node, job.walk)
            if children is None:
                job.out.append(text)
                continue
            stack.append(job)
            stack.append(_Seq(nodes=children, out=job.out, walk=job.walk))
            suspended = True
            break

        if suspended:
            continue

    return "".join(root)


def _random_int(rng: Rng, minimum: int, maximum: int) -> int:
    """`min == max` short-circuits WITHOUT consuming the RNG.

    Load-bearing, not an optimisation. Draw *count* is the only thing that distinguishes
    `#set` from `#def`, so a needless draw here shifts every later one. A default-config
    permutation clamps its size pick to `min == max`, and calling the rng anyway breaks
    exactly the pair of fixtures that tell the two directives apart — as a
    shuffle-order failure, which is not where anyone would look.
    """
    return minimum if minimum == maximum else rng(minimum, maximum)


def _resolve_variable(name: str, walk: _Walk) -> tuple[str, Sequence[Node] | None]:
    """Resolve a `%var%`. An unknown name stays verbatim, brackets and all.

    Returns either finished text, or the nodes the caller should walk next — the split
    that keeps the re-expansion of a value on the caller's stack rather than this one's.
    """
    value = walk.vars.get(name.lower())
    if value is None:
        return f"%{name}%", None
    # At the cap, stop expanding and return what we have. Lenient by contract: partial
    # output, never an exception — the plugin throws here and resolves to empty.
    if walk.depth >= MAX_VARIABLE_DEPTH or not _HAS_CONSTRUCT_RE.search(value):
        return value, None
    # Out of budget ⇒ the reference stays literal, exactly as an undefined name does. No
    # new output shape, and the promise that render never raises on content survives.
    if walk.budget.left <= 0:
        return f"%{name}%", None
    walk.budget.left -= len(value)
    # `parse_sequence`, NOT `parse_template`: a value must not be comment-stripped or
    # directive-extracted a second time. Those are one-time passes over the body.
    return "", _parser.parse_sequence(value)


def _expand_vars_only(text: str, walk: _Walk) -> str:
    """Substitute `%var%` to a fixpoint, leaving enumerations and permutations literal.

    Plurals run after variable expansion but before enum/perm, so their checks have to see
    the same half-resolved state the plugin sees.
    """
    out = text
    for _ in range(MAX_VARIABLE_DEPTH):
        changed = False

        def substitute(m: re.Match[str]) -> str:
            nonlocal changed
            value = walk.vars.get(m.group(1).lower())
            if value is None:
                return m.group()
            # Same purse as _resolve_variable: a plural slot is not a separate allowance.
            if walk.budget.left <= 0:
                return m.group()
            walk.budget.left -= len(value)
            changed = True
            return value

        out = _VARIABLE_RE.sub(substitute, out)
        if not changed:
            break
    return out


def _takes_then(name: str, inverted: bool, walk: _Walk) -> bool:
    """Truthy = the RAW value exists and holds a non-blank char."""
    value = walk.vars.get(name.lower())
    truthy = value is not None and _NOT_BLANK_RE.search(value) is not None
    return not truthy if inverted else truthy


def _conditional_branch(node: ConditionalNode, walk: _Walk) -> Sequence[Node]:
    """Which branch renders."""
    return node.then if _takes_then(node.name, node.inverted, walk) else node.otherwise


def _resolve_count_conditionals(text: str, walk: _Walk) -> str:
    """Resolve conditionals in the plural COUNT slot, textually (spintax-js#67).

    The plugin runs its conditional stage over the whole text before plurals, so
    ``#set %n% = {?flag?1|2}`` reaches the count slot as a plain number and the block
    renders. This engine expands VARIABLES only into the raw count slot, so the
    conditional survived, failed the numeric test, and the block was ERASED -- while
    ``validate()`` reported nothing and ``plural.count-macro`` documents conditionals as
    exempt *because* they resolve before plurals. Valid input, silently deleted output.

    The branch is substituted, never rendered: enumerations and permutations resolve
    AFTER plurals, so a branch yielding ``{a|b}`` must reach the numeric test intact and
    erase the block, exactly as the plugin does. The FORM slot is deliberately untouched
    -- there the engines genuinely disagree and no side has been chosen yet.

    Iterative, over spans, for two reasons paid for in review. Recursing into the taken
    branch raised ``RecursionError`` at ~1000 levels of nesting -- a 5 KB template, and
    ``render`` never raises on content; ``tests/test_parser_depth.py`` records the same
    lesson being learned for ``parse_sequence``. And re-scanning for the matching brace
    per ``{?`` was quadratic: an unbalanced count slot is legal, because only the whole
    ``{plural …}`` block has to balance and the slot is cut at the first ``:``. Both are
    reachable from template text through the live public Worker.
    """
    if "{?" not in text:
        return text

    close = _match_braces(text)
    out: list[str] = []
    # Spans of ``text`` still to emit, in order. A taken branch is a SPAN of the same
    # string, never a copy, and the untaken one is skipped -- so every character is
    # visited at most once.
    pending: list[tuple[int, int]] = [(0, len(text))]

    while pending:
        i, seg_end = pending.pop()

        while i < seg_end:
            open_at = text.find("{?", i)
            # A `{?` found past this span belongs to the text around it, not to it.
            if open_at < 0 or open_at + 1 >= seg_end:
                out.append(text[i:seg_end])
                break

            # A close outside the span is no close at all: the branch it would reach
            # into is not ours to read.
            shut = close[open_at]
            head = None if shut < 0 or shut >= seg_end else _parser.recognize_conditional(text, open_at + 1, shut)
            if head is None:
                # Unclosed, or a `{?` that is not a conditional -- a malformed one is an
                # enumeration to the parser, and enumerations are not this pass's business.
                out.append(text[i : min(open_at + 2, seg_end)])
                i = open_at + 2
                continue

            out.append(text[i:open_at])
            if _takes_then(head.name, head.inverted, walk):
                branch = (head.body_start, shut if head.sep_index < 0 else head.sep_index)
            else:
                branch = (shut if head.sep_index < 0 else head.sep_index + 1, shut)
            # Continuation first, branch second: the stack pops the branch back out
            # ahead of it, which is what keeps the output in source order.
            pending.append((shut + 1, seg_end))
            pending.append(branch)
            break

    return "".join(out)


def _match_braces(text: str) -> list[int]:
    """Match `{` to `}` across the whole string in ONE pass -- the index of the closing
    brace for every opening one, or -1.

    Equivalent to walking to the matching brace per `{`, and that is the point: the
    per-brace walk rescans to the end of the string every time it fails to match.
    """
    close = [-1] * len(text)
    opens: list[int] = []

    for i, ch in enumerate(text):
        if ch == "{":
            opens.append(i)
        elif ch == "}" and opens:
            close[opens.pop()] = i

    return close


def _render_plural(node: PluralNode, walk: _Walk) -> tuple[str, Sequence[Node] | None]:
    """Order matters: bracket check, then numeric erase, then arity, then the pick.

    Returns finished text, or the nodes of the picked form for the caller to walk.
    """
    count_raw = _resolve_count_conditionals(_expand_vars_only(node.count_raw, walk), walk)
    forms_raw = _expand_vars_only(node.forms_raw, walk)
    base = _plurals.normalize_base_lang(walk.locale)

    def report(issue: PluralIssue) -> None:
        if walk.on_plural_error is not None:
            walk.on_plural_error(issue)

    if _HAS_BRACKET_RE.search(forms_raw):
        report(
            PluralIssue(
                code="plural.nested-brackets",
                message=(
                    "Plural form slot contains nested spintax brackets; extract via #def "
                    "first — a #set is substituted verbatim and would put the brackets "
                    "straight back."
                ),
                construct=_raw_construct(count_raw, forms_raw),
                locale=base,
            )
        )
        return _fullwidth_verbatim(count_raw, forms_raw), None

    count = count_raw.strip(PHP_TRIM_CHARS)
    if not _INTEGER_RE.fullmatch(count):
        # Erasing leaves no trace in the output, so this report is the only way a host can
        # tell a deliberately empty sentence from an unsubstituted %Var%.
        report(
            PluralIssue(
                code="plural.count",
                message=f"Plural count slot is empty or non-numeric ({count!r}); block erased.",
                construct=_raw_construct(count_raw, forms_raw),
                locale=base,
            )
        )
        return "", None

    forms = [f.strip(PHP_TRIM_CHARS) for f in forms_raw.split("|")]
    expected = _plurals.arity(base)
    if len(forms) != expected:
        report(
            PluralIssue(
                code="plural.arity",
                message=f'Plural has {len(forms)} form(s); locale "{base}" takes {expected}.',
                construct=_raw_construct(count_raw, forms_raw),
                locale=base,
                expected=expected,
                got=len(forms),
            )
        )
        return _fullwidth_verbatim(count_raw, forms_raw), None

    # The picked form re-enters the pipeline — its own enums and perms resolve after this.
    picked = _plurals.plural_for(base, int(count), forms)
    return "", _parser.parse_sequence(picked)


def _raw_construct(count_raw: str, forms_raw: str) -> str:
    return f"{{plural {count_raw}:{forms_raw}}}"


def _fullwidth_verbatim(count_raw: str, forms_raw: str) -> str:
    """Re-emit with fullwidth braces so no later pass mistakes it for markup again."""
    return _raw_construct(count_raw, forms_raw).replace("{", "｛").replace("}", "｝")


@dataclass(slots=True)
class _Element:
    text: str
    sep: str | None


def _finish_permutation(job: _JoinPermutation) -> str:
    """Choose how many elements to keep, shuffle, join. Runs AFTER they are all rendered.

    That ordering is the RNG contract, not an implementation detail: children draw first,
    then the size pick, then the shuffle. It matches the plugin exactly, which is why the
    permutation rng-strategy fixtures can assert exact output.
    """
    elements = [
        _Element(text="".join(part), sep=sep)
        for part, sep in zip(job.parts, job.separators, strict=True)
    ]
    total = len(elements)
    if total == 0:
        return ""

    config = job.config
    if config.minsize is not None and config.maxsize is not None:
        minimum, maximum = config.minsize, config.maxsize
    elif config.minsize is not None:
        minimum, maximum = config.minsize, total
    elif config.maxsize is not None:
        minimum, maximum = 1, config.maxsize
    else:
        # No config: every element, every time. This is the clamp that makes the default
        # case spend zero draws on its size pick.
        minimum = maximum = total

    minimum = max(1, min(minimum, total))
    maximum = max(minimum, min(maximum, total))

    pick = _random_int(job.rng, minimum, maximum)
    _shuffle(elements, job.rng)
    lastsep = config.lastsep if config.lastsep is not None else config.sep
    return _join_with_separators(elements[:pick], config.sep, lastsep)


def _shuffle(elements: list[_Element], rng: Rng) -> None:
    """Fisher-Yates exactly as the plugin walks it: i from n-1 down to 1, j in [0, i]."""
    for i in range(len(elements) - 1, 0, -1):
        j = _random_int(rng, 0, i)
        elements[i], elements[j] = elements[j], elements[i]


def _join_with_separators(
    elements: Sequence[_Element], global_sep: str, global_lastsep: str
) -> str:
    if not elements:
        return ""
    if len(elements) == 1:
        return elements[0].text

    out = [elements[0].text]
    last = len(elements) - 1
    for i in range(1, len(elements)):
        element = elements[i]
        sep = element.sep
        if sep is None:
            sep = global_lastsep if i == last else global_sep
        out.append(_pad_separator(sep) + element.text)
    return "".join(out)


def _pad_separator(sep: str) -> str:
    """A purely alphabetic separator gets spaces around it; anything else passes through.

    `str.isalpha()` stands in for the reference's `\\p{L}+`, which Python's `re` has no
    escape for. Measured equal across the whole Unicode range: `isalpha()` is true for
    exactly the general categories `Lu Ll Lt Lm Lo`, with no disagreements.
    """
    trimmed = sep.strip(PHP_TRIM_CHARS)
    if trimmed == "":
        return sep
    if trimmed.isalpha():
        return f" {trimmed} "
    return sep


@dataclass(slots=True)
class _Splice:
    """One text whose `#include` lines still have to be replaced, and where it goes."""

    text: str
    ctx: RenderCtx
    out: list[str]


def _resolve_includes(text: str, ctx: RenderCtx) -> str:
    """Replace each line-anchored `#include "ref"` with the resolved child template.

    The child inherits the runtime context but NOT the parent's `#set` locals, matching
    the plugin's `for_child_render`. A cycle or a runaway chain resolves to empty rather
    than raising — cycles are detected by the ref STRING, since the engine has no template
    identity beyond what the host supplies, so two aliases for one template are not seen
    as a cycle and simply recurse until `max_depth`.

    **Iterative, like everything else that follows nesting in this engine.** Include depth
    is bounded by `max_depth`, which is a caller-supplied number with no ceiling, and the
    recursive form raised `RecursionError` from `max_depth = 331` — breaking both the
    lenient contract and the docstring paragraph directly above this one. The default of
    20 is nowhere near it, so this only ever bit a caller who raised the budget.
    """
    root: list[str] = []
    stack: list[_Splice] = [_Splice(text=text, ctx=ctx, out=root)]

    while stack:
        job = stack.pop()
        cursor = 0
        # Children are collected first, then pushed in reverse, so they splice in source
        # order once the stack unwinds.
        pending: list[_Splice] = []

        for match in _INCLUDE_LINE_RE.finditer(job.text):
            job.out.append(job.text[cursor : match.start()])
            slot: list[str] = []
            job.out.append(slot)  # type: ignore[arg-type]
            child = _open_include(match.group(1), job.ctx)
            if child is not None:
                pending.append(_Splice(text=child[0], ctx=child[1], out=slot))
            cursor = match.end()

        job.out.append(job.text[cursor:])
        stack.extend(reversed(pending))

    return _flatten(root)


def _flatten(parts: list[str]) -> str:
    """Join a tree of nested slot lists, depth-first.

    A slot is appended to its parent at the position the include occupied, and filled in
    later — so the parent holds a list where a string will eventually be. Flattening at the
    end is what keeps the order right without any of it living on the call stack.
    """
    out: list[str] = []
    stack: list[object] = [parts]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(reversed(item))
        else:
            out.append(str(item))
    return "".join(out)


def _open_include(ref: str, ctx: RenderCtx) -> tuple[str, RenderCtx] | None:
    """Resolve and render one include's BODY, without touching its own includes.

    Returns the rendered child plus the context its includes must be spliced under, or
    `None` when the include resolves to nothing — a cycle, a depth breach, or a resolver
    that reported no such template.
    """
    if ref in ctx.include_stack or len(ctx.include_stack) >= ctx.max_depth:
        return None
    try:
        included = ctx.resolver(ref) if ctx.resolver else None
    except Exception as cause:
        raise IncludeResolverError(f'include_resolver threw for "{ref}"') from cause
    if included is None:
        return None

    child_ctx = replace(ctx, include_stack=(*ctx.include_stack, ref))
    # `parse_template` strips stray sentinels from the included author markup itself.
    ast = _parser.parse_template(included)
    return _render_body(ast, child_ctx), child_ctx
