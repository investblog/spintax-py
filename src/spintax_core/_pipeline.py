"""The full render pipeline, assembled exactly once.

Order: project the source (comments, `/! … !/` spans, stray sentinels) → parse →
tree-walk (vars, `#def`, `#include`) → cosmetic post-process, if on → mandatory
safety-restore, always → decode the spans, always.

**Assembled once, here, and nowhere else.** Spec §5.1 records what it cost to do
otherwise: the PHP port's corpus test reproduces the pipeline by hand, so what it
certifies is that replica rather than the shipped orchestration, and the stage order now
exists in four places that can each rot separately. This port's test harness calls
`render_with` like any other caller. If a stage order ever appears somewhere else in this
repository, that is the defect.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from . import _neutralize, _parser, _postprocess, _render, _verbatim
from ._ast import Ast, ParsedAst, require_parsed
from ._render import MAX_EXPANSION_CHARS, PluralIssue, RenderCtx, _Budget
from ._rng import Rng

#: `#include` nesting cap. Reads like a parse-depth guard and is not one — it is only ever
#: compared against the include stack, which is why the parser and the tree walk both had
#: to be made iterative on their own account.
DEFAULT_MAX_DEPTH = 20


def render_with(
    source: str | Ast,
    rng: Rng,
    *,
    context: Mapping[str, str] | None = None,
    locale: str | None = None,
    include_resolver: Callable[[str], str | None] | None = None,
    post_process: bool = True,
    max_depth: int = DEFAULT_MAX_DEPTH,
    on_plural_error: Callable[[PluralIssue], None] | None = None,
) -> str:
    ctx = RenderCtx(
        runtime_context=_runtime_values(context),
        rng=rng,
        locale=locale or "",
        resolver=include_resolver,
        max_depth=max_depth,
        include_stack=(),
        on_plural_error=on_plural_error,
        # One allowance for the whole call. Created here rather than in the renderer
        # because includes re-enter it, and a budget made there is a budget per subtree.
        budget=_Budget(MAX_EXPANSION_CHARS),
    )

    out = _render.render_ast(_resolve_ast(source), ctx)

    if post_process:
        # Runs on the still-shielded form: neutralize sentinels are inert to it, which is
        # what lets the cosmetic pass reflow text without seeing a shielded brace as markup.
        out = _postprocess.post_process(out, ctx.locale)

    # Not conditional, and not cosmetic. `post_process=False` skips the pass above and
    # never this one — leaving it out would emit private-use code points to the caller.
    # Then the `/! … !/` spans come back, last of all, so neither stage saw their content
    # (ADR 0001 rule 7).
    return _verbatim.decode(_neutralize.safety_restore(out))


def _runtime_values(context: Mapping[str, str] | None) -> Mapping[str, str]:
    """The runtime context as the render sees it: the span range stripped from every value,
    so data cannot carry a ready-made token past the template's sanitising (ADR 0001 rule
    4). A value keeps the neutralize sentinels — those are how a host shields it."""
    if not context:
        return {}
    if all(_verbatim.strip_span_range(v) == v for v in context.values()):
        return context
    return {k: _verbatim.strip_span_range(v) for k, v in context.items()}


def _resolve_ast(source: str | Ast) -> ParsedAst:
    """A string is parsed fresh; a handle is checked before it is trusted."""
    if isinstance(source, str):
        # `parse_template` sanitises author markup itself now (see its docstring), so the
        # sentinel strip that used to live here — and only here, missing `parse()` — is
        # gone. One door, one rule.
        return _parser.parse_template(source)
    return require_parsed(source)
