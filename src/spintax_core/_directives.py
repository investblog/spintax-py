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

from . import _charclasses, _source

#: Re-exported for the modules that already reach for it here. The class and the reason it
#: is spelled out live in `_charclasses`; see also `tests/test_ascii_parity.py`.
ASCII_WORD = _charclasses.ASCII_WORD

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
    """Pull every directive line out of `text` and return the remaining body.

    Matching happens on a copy whose line terminators are normalised, because Python's
    `^`/`$` only know `\\n` while the engine's grammar is line-anchored at everything
    JavaScript calls a terminator. Without it a bare CR swallows the rest of the file
    into one `#set` value and the directive after it is never seen.

    The **body is cut from the text as given**, not from that copy. The renderer emits
    it verbatim, and the reference keeps the author's bytes:

        render("#set %x% = A\\r%x%")  ->  "\\rA"

    So the CR is a line break for the purpose of finding the directive and an ordinary
    character for the purpose of printing what is left. Normalising a copy is what lets
    it be both — and the substitution is length-preserving, so a span found in one
    string is the same span in the other.
    """
    scan = _source.normalize_terminators(text)

    set_defs: dict[str, str] = {}
    def_defs: dict[str, str] = {}
    occurrences: list[Occurrence] = []
    spans: list[tuple[int, int]] = []

    for m in DIRECTIVE_RE.finditer(scan):
        kind, raw_name, value = m.group(1), m.group(2), m.group(3)
        name = raw_name.lower()
        occurrences.append(
            Occurrence(
                kind=kind,
                name=name,
                value=value,
                line=scan.count("\n", 0, m.start()) + 1,
                offset=m.start(),
            )
        )
        # Last definition wins in the maps; `occurrences` is what remembers the rest.
        (def_defs if kind == "def" else set_defs)[name] = value
        spans.append((m.start(), m.end()))

    kept: list[str] = []
    cursor = 0
    for start, end in spans:
        kept.append(text[cursor:start])
        cursor = end
    kept.append(text[cursor:])

    return Directives(
        body=_BLANK_RUN_RE.sub("\n\n", "".join(kept)),
        set_defs=set_defs,
        def_defs=def_defs,
        occurrences=tuple(occurrences),
    )
