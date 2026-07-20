"""Spintax engine for Python — the public API surface.

**Two things still raise ``NotImplementedError``, and one of them is on the default
path.** ``analyze`` is not built (P3). The cosmetic post-process stage is not built
either, so ``render(...)`` and ``render_with(...)`` raise unless you pass
``post_process=False`` — the flag defaults to on. That is deliberate rather than
convenient: the golden-corpus suite reports every unbuilt entry point as an *expected
failure* rather than skipping it, so what is left is visible on every test run and no
fixture can be quietly forgotten.

Note the interaction with the lenient contract below. "Never raises" is about template
CONTENT, and it holds — malformed markup degrades. An unbuilt stage is a different thing,
and it is a builtin ``NotImplementedError``, so it is NOT caught by ``except
SpintaxError``. It goes away when P2 step 7 lands.

Milestones: P1 validate/extract (done), P2 parse + rng + neutralize + render (post-process
outstanding), P3 analyze. See ``docs/plan-p2.md`` for why neutralize moved out of P3, and
``docs/spec-python-port.md`` for the contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from . import _extract, _neutralize, _parser, _pipeline, _validator
from ._ast import Ast
from ._errors import AstVersionError, IncludeResolverError, SpintaxError
from ._render import PluralIssue
from ._rng import Rng, make_rng as _make_rng

# Both are public types that happen to be DEFINED in private modules. Without this,
# `help()`, generated docs and every repr name `spintax_core._ast`, pointing users at a
# module the API tells them not to touch.
Ast.__module__ = __name__
PluralIssue.__module__ = __name__

__all__ = [
    "Analysis",
    "AstVersionError",
    "Ast",
    "Diagnostic",
    "Extraction",
    "IncludeResolverError",
    "PluralIssue",
    "Rng",
    "SpintaxError",
    "analyze",
    "extract",
    "make_rng",
    "neutralize",
    "parse",
    "render",
    "render_with",
    "validate",
]

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A validation finding.

    ``code`` is the parity-gated identifier; ``message`` wording is explicitly NOT
    part of the cross-engine contract, so consumers branch on ``code``.
    """

    severity: Severity
    code: str
    message: str
    line: int
    column: int
    end_line: int | None = None
    end_column: int | None = None
    data: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Extraction:
    """Names a template refers to or declares, plus its include targets."""

    refs: tuple[str, ...] = ()
    sets: tuple[str, ...] = ()
    defs: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Analysis:
    """``extract`` + ``validate`` + a best-effort census of constructs."""

    extraction: Extraction
    diagnostics: tuple[Diagnostic, ...] = ()
    constructs: Mapping[str, int] = field(default_factory=dict)


def _reject_bare_string(param: str, value: Sequence[str] | None) -> None:
    if isinstance(value, str):
        raise TypeError(f"{param} takes a sequence of strings, not a single string")


def parse(src: str) -> Ast:
    """Parse once into a reusable handle."""
    return _parser.parse_template(src)


def make_rng(seed: int | str | None) -> Rng:
    """Build the seeded PRNG. Same seed ⇒ same sequence, within this engine only.

    Cross-engine sequence parity is a deliberate non-goal (spec §3) — see ``_rng`` for
    why the reference's mulberry32 is not ported despite being fifteen lines.
    """
    return _make_rng(seed)


def render_with(
    input: str | Ast,
    rng: Rng,
    *,
    context: Mapping[str, str] | None = None,
    locale: str | None = None,
    include_resolver: Callable[[str], str | None] | None = None,
    post_process: bool = True,
    max_depth: int = 20,
    on_plural_error: Callable[[PluralIssue], None] | None = None,
) -> str:
    """Render with an explicitly injected choice source.

    This is the **only** renderer. ``render`` is a thin wrapper that builds an
    ``Rng`` and calls this, so the corpus and real callers exercise one pipeline
    rather than two that can drift apart. The seam exists because the corpus
    needs to control *how many draws* a template takes: with a fixed ``first``
    strategy, `#set` (a macro, re-rolled per reference) and `#def` (rolled once)
    produce identical output and the distinction is untestable. A sequence RNG is
    what makes the difference observable.
    """
    return _pipeline.render_with(
        input,
        rng,
        context=context,
        locale=locale,
        include_resolver=include_resolver,
        post_process=post_process,
        max_depth=max_depth,
        on_plural_error=on_plural_error,
    )


def render(
    input: str | Ast,
    *,
    context: Mapping[str, str] | None = None,
    seed: int | str | None = None,
    locale: str | None = None,
    include_resolver: Callable[[str], str | None] | None = None,
    post_process: bool = True,
    max_depth: int = 20,
    on_plural_error: Callable[[PluralIssue], None] | None = None,
) -> str:
    """Render to a single string.

    Lenient by contract: never raises on malformed markup — a bad block is emitted
    verbatim in fullwidth braces, and a too-deep or circular ``#include`` resolves
    to an empty string.

    That promise is about the TEMPLATE. Two things can still raise, and neither is about
    what the template says: a foreign ``Ast`` (``AstVersionError``), a host resolver that
    threw (``IncludeResolverError``) — and, until P2 step 7 lands, the default
    ``post_process=True`` path, which raises ``NotImplementedError``.
    """
    return render_with(
        input,
        make_rng(seed),
        context=context,
        locale=locale,
        include_resolver=include_resolver,
        post_process=post_process,
        max_depth=max_depth,
        on_plural_error=on_plural_error,
    )


def validate(
    input: str | Ast,
    *,
    locale: str | None = None,
    known_includes: Sequence[str] | None = None,
    known_variables: Sequence[str] | None = None,
) -> list[Diagnostic]:
    """Return diagnostics. Valid ⇔ no diagnostic with ``severity == "error"``."""
    if not isinstance(input, str):
        raise NotImplementedError("validate(Ast): P2 — pass the source string for now")
    # A bare `str` satisfies `Sequence[str]`, so `known_includes="hero"` type-checks and
    # then silently means the four slugs 'h', 'e', 'r', 'o'. The TypeScript signature
    # rejects it outright; here only a runtime check can.
    _reject_bare_string("known_includes", known_includes)
    _reject_bare_string("known_variables", known_variables)

    source, findings = _validator.run(
        input,
        locale=locale,
        known_includes=list(known_includes) if known_includes else None,
        known_variables=list(known_variables) if known_variables else None,
    )
    out: list[Diagnostic] = []
    for f in findings:
        line, column = source.position(f.offset)
        # The end is exclusive, so it is one past the last character of the span. The
        # last character is at `offset + length - 1`; a zero-length finding collapses
        # to the start rather than reaching backwards.
        end_line, end_column = source.position(f.offset + max(0, f.length - 1))
        data = f.data

        # Offsets are the only coordinate the checks speak. Anything a message wants to
        # say about *another* place in the file is translated here, where the Source is —
        # a check that formatted its own line number would be quoting a position in the
        # comment-stripped text while its diagnostic reported one in the original.
        if data is not None and "first_offset" in data:
            first_line, _ = source.position(int(data["first_offset"]))  # type: ignore[call-overload]
            data = {k: v for k, v in data.items() if k != "first_offset"}
            data["first_line"] = first_line

        out.append(
            Diagnostic(
                severity="warning" if f.severity == "warning" else "error",
                code=f.code,
                message=f.message,
                line=line,
                column=column,
                end_line=end_line,
                end_column=end_column + 1,
                data=data,
            )
        )

    # Source order — a reader walks the template top to bottom instead of in whatever
    # order the checks happened to run. This is a deliberate divergence from the
    # reference, which emits in check order; see spec §3, "Allowed to diverge".
    # Python's sort is stable, so findings sharing a position keep check order.
    out.sort(key=lambda d: (d.line, d.column))
    return out


def extract(input: str | Ast) -> Extraction:
    """List variable references, ``#set`` / ``#def`` names, and ``#include`` targets."""
    if not isinstance(input, str):
        raise NotImplementedError("extract(Ast): P2 — pass the source string for now")
    refs, sets, defs, includes = _extract.extract(input)
    return Extraction(refs=refs, sets=sets, defs=defs, includes=includes)


def analyze(
    input: str | Ast,
    *,
    locale: str | None = None,
    known_includes: Sequence[str] | None = None,
    known_variables: Sequence[str] | None = None,
) -> Analysis:
    """``extract`` + ``validate`` + a construct census, for tooling."""
    raise NotImplementedError("analyze: P3")


def neutralize(value: str) -> str:
    """Shield untrusted text so it cannot be re-read as spintax markup.

    Text-safe, not HTML escaping. Its safety restore is mandatory and survives
    ``post_process=False`` — that flag skips cosmetics only.
    """
    return _neutralize.neutralize(value)
