"""Spintax engine for Python — the public API surface.

P0 status: every entry point is declared with its final signature and raises
``NotImplementedError``. That is deliberate. The golden-corpus suite runs against
this module from the very first commit, so each fixture is reported as an
*expected failure* rather than being skipped — the count of what is not yet built
is visible on every test run, and a fixture can never be quietly forgotten.

Milestones fill these in: P1 parse/validate, P2 render, P3 extract/analyze/neutralize.
See ``docs/spec-python-port.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "Analysis",
    "Ast",
    "Diagnostic",
    "Extraction",
    "analyze",
    "extract",
    "neutralize",
    "parse",
    "render",
    "validate",
]

Severity = Literal["error", "warning"]


class Ast:
    """Opaque, versioned parse handle.

    An in-memory performance handle, not a serialization format: do not persist it
    across engine versions. Kept a class rather than an alias so the opacity is
    enforced by the type checker instead of by a docstring.
    """

    __slots__ = ()


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


def parse(src: str) -> Ast:
    """Parse once into a reusable handle."""
    raise NotImplementedError("parse: P1")


def render(
    input: str | Ast,
    *,
    context: Mapping[str, str] | None = None,
    seed: int | str | None = None,
    locale: str | None = None,
    include_resolver: Callable[[str], str | None] | None = None,
    post_process: bool = True,
    max_depth: int = 20,
) -> str:
    """Render to a single string.

    Lenient by contract: never raises on malformed markup — a bad block is emitted
    verbatim in fullwidth braces, and a too-deep or circular ``#include`` resolves
    to an empty string.
    """
    raise NotImplementedError("render: P2")


def validate(
    input: str | Ast,
    *,
    locale: str | None = None,
    known_includes: Sequence[str] | None = None,
    known_variables: Sequence[str] | None = None,
) -> list[Diagnostic]:
    """Return diagnostics. Valid ⇔ no diagnostic with ``severity == "error"``."""
    raise NotImplementedError("validate: P1")


def extract(input: str | Ast) -> Extraction:
    """List variable references, ``#set`` / ``#def`` names, and ``#include`` targets."""
    raise NotImplementedError("extract: P3")


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
    raise NotImplementedError("neutralize: P3")
