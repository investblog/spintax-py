"""The full render pipeline, assembled exactly once.

Order: strip stray sentinels → parse → tree-walk (vars, `#def`, `#include`) → cosmetic
post-process, if on → mandatory safety-restore, always.

**Assembled once, here, and nowhere else.** Spec §5.1 records what it cost to do
otherwise: the PHP port's corpus test reproduces the pipeline by hand, so what it
certifies is that replica rather than the shipped orchestration, and the stage order now
exists in four places that can each rot separately. This port's test harness calls
`render_with` like any other caller. If a stage order ever appears somewhere else in this
repository, that is the defect.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from . import _neutralize, _parser, _postprocess, _render
from ._ast import Ast, ParsedAst, require_parsed
from ._render import PluralIssue, RenderCtx
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
        runtime_context=context or {},
        rng=rng,
        locale=locale or "",
        resolver=include_resolver,
        max_depth=max_depth,
        include_stack=(),
        on_plural_error=on_plural_error,
    )

    out = _render.render_ast(_resolve_ast(source), ctx)

    if post_process:
        # Runs on the still-shielded form: neutralize sentinels are inert to it, which is
        # what lets the cosmetic pass reflow text without seeing a shielded brace as markup.
        out = _postprocess.post_process(out)

    # Not conditional, and not cosmetic. `post_process=False` skips the pass above and
    # never this one — leaving it out would emit private-use code points to the caller.
    return _neutralize.safety_restore(out)


def _resolve_ast(source: str | Ast) -> ParsedAst:
    """A string is parsed fresh; a handle is checked before it is trusted."""
    if isinstance(source, str):
        # Stray sentinels come out of AUTHOR markup here so that only `neutralize()` can
        # introduce one. Otherwise the mandatory restore would rewrite a character the
        # author typed into a brace they never wrote.
        return _parser.parse_template(_neutralize.strip_sentinels(source))
    return require_parsed(source)
