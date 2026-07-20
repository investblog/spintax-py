"""Line-anchored `#set` / `#def` extraction.

Directives are **not** tree nodes. They are pulled out of the whole text before
anything else looks at it, regardless of brace nesting — so a `#set` on its own
line inside an enumeration is a global definition, not an option's literal text.
The corpus has a fixture for that (`set/global-scope-inside-group`) but it is a RENDER
case, so it stays xfail until P2 — until then the rule is held by local tests only.

`occurrences` keeps every directive line, including the duplicates the two maps
flatten to last-wins. That is not bookkeeping for its own sake: a validator cannot
report a collision it can no longer see, which is how the PHP pass lost duplicate
detection (spec §5.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: JavaScript's `\w` is ASCII-only — always, `u` flag included — while Python's matches any
#: Unicode letter. Spelling the class out keeps the accepted syntax identical to the reference
#: instead of silently widening it. See `tests/test_ascii_parity.py`.
ASCII_WORD = "[A-Za-z0-9_]"

#: The shared grammar: line-anchored, optional indent, `%name%` of ASCII word characters, `=`,
#: then the value to end of line. An empty value is legal — `#set %x% =` defines an empty
#: string, it is not malformed.
DIRECTIVE_RE = re.compile(
    r"^[ \t]*#(set|def)[ \t]+%(" + ASCII_WORD + r"+)%[ \t]*=[ \t]*(.*?)[ \t]*\r?$",
    re.MULTILINE,
)

#: Runs of three or more newlines collapse to two once the directive lines are gone.
#: This runs even when there were no directives at all, so it is a property of the
#: body, not of stripping — `"\n\n\nX"` renders as `"\n\nX"` with post-processing off.
_BLANK_RUN_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One directive line, in source order."""

    kind: str  # "set" | "def"
    name: str  # lower-cased: variable identity is case-insensitive
    value: str
    line: int
    offset: int  # into the text it was extracted from


@dataclass(frozen=True, slots=True)
class Directives:
    body: str
    set_defs: dict[str, str]
    def_defs: dict[str, str]
    occurrences: tuple[Occurrence, ...]


def extract(text: str) -> Directives:
    """Pull every directive line out of `text` and return the remaining body."""
    set_defs: dict[str, str] = {}
    def_defs: dict[str, str] = {}
    occurrences: list[Occurrence] = []

    def _take(m: re.Match[str]) -> str:
        kind, raw_name, value = m.group(1), m.group(2), m.group(3)
        name = raw_name.lower()
        occurrences.append(
            Occurrence(
                kind=kind,
                name=name,
                value=value,
                line=text.count("\n", 0, m.start()) + 1,
                offset=m.start(),
            )
        )
        # Last definition wins in the maps; `occurrences` is what remembers the rest.
        (def_defs if kind == "def" else set_defs)[name] = value
        return ""

    stripped = DIRECTIVE_RE.sub(_take, text)
    return Directives(
        body=_BLANK_RUN_RE.sub("\n\n", stripped),
        set_defs=set_defs,
        def_defs=def_defs,
        occurrences=tuple(occurrences),
    )
