"""Name and target enumeration for `extract()`.

A raw-text scan, like the validator and for the same reason: it is *complete*. An AST
walk would miss a `%var%` in a `{plural <count>: …}` count slot and anything inside a
`[…]` permutation body, both of which the tree leaves as raw strings.

Variable names are lower-cased because variable identity is case-insensitive, so
cross-referencing `sets` against `refs` works. Include slugs are left exactly as
authored — the host resolves those, and it may well care about case.
"""

from __future__ import annotations

import re

from . import _directives, _source
from ._validator import _CONDITIONAL_REF_RE, _INCLUDE_RE, _VARIABLE_RE

_W = _directives.ASCII_WORD

_SET_DEF_RE = re.compile(r"^[ \t]*#set[ \t]+%(" + _W + r"+)%[ \t]*=", re.MULTILINE)
_DEF_DEF_RE = re.compile(r"^[ \t]*#def[ \t]+%(" + _W + r"+)%[ \t]*=", re.MULTILINE)
#: The `#set`/`#def … =` left-hand side. Dropped before collecting refs so a definition
#: target is not counted as a reference to itself — miss the `#def` half and every
#: definition name comes back as a phantom ref.
_DEFINITION_LHS_RE = re.compile(r"^[ \t]*#(?:set|def)[ \t]+%" + _W + r"+%[ \t]*=", re.MULTILINE)


def _collect(text: str, pattern: re.Pattern[str], fold: bool) -> tuple[str, ...]:
    seen: dict[str, None] = {}  # insertion-ordered, de-duplicated
    for m in pattern.finditer(text):
        value = m.group(1)
        if value:
            seen.setdefault(value.lower() if fold else value, None)
    return tuple(seen)


def extract(src: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return `(refs, sets, defs, includes)`."""
    text = _source.read(src).text

    sets = _collect(text, _SET_DEF_RE, fold=True)
    defs = _collect(text, _DEF_DEF_RE, fold=True)
    includes = _collect(text, _INCLUDE_RE, fold=False)

    body = _DEFINITION_LHS_RE.sub("", text)
    refs: dict[str, None] = {}
    for pattern in (_VARIABLE_RE, _CONDITIONAL_REF_RE):
        for m in pattern.finditer(body):
            if m.group(1):
                refs.setdefault(m.group(1).lower(), None)

    return tuple(refs), sets, defs, includes
