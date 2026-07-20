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
from bisect import bisect_left
from dataclasses import dataclass

from . import _charclasses

#: Re-exported for the modules that already reach for it here. The class and the reason it
#: is spelled out live in `_charclasses`; see also `tests/test_ascii_parity.py`.
ASCII_WORD = _charclasses.ASCII_WORD

#: The shared grammar: line-anchored, optional indent, `%name%` of ASCII word characters, `=`,
#: then the value to end of line. An empty value is legal — `#set %x% =` defines an empty
#: string, it is not malformed.
#:
#: The anchors and the value class are JavaScript's, spelled out. Python's `^`/`$` know only
#: `\n` and its `.` matches `\r`, U+2028 and U+2029 — so the value group would run past the
#: end of its own line, which is how a bare-CR file used to have its whole remainder
#: swallowed into one `#set`.
DIRECTIVE_RE = re.compile(
    _charclasses.JS_LINE_START
    + r"[ \t]*#(set|def)[ \t]+%("
    + ASCII_WORD
    + r"+)%[ \t]*=[ \t]*("
    + _charclasses.JS_DOT
    + r"*?)[ \t]*\r?"
    + _charclasses.JS_LINE_END
)

#: One line break, counting `\r\n` as a single one. Everything JavaScript calls a
#: terminator ends a line, so counting `\n` alone would report every diagnostic in a
#: bare-CR file on line 1.
_LINE_BREAK_RE = re.compile(f"\\r\\n|[{_charclasses.JS_LINE_TERMINATORS}]")


def _line_break_offsets(text: str) -> list[int]:
    """Where every line break starts, once, so the lookup below is a bisect.

    Counting breaks from the start of the file per directive is O(offset) each, which is
    quadratic over a file of directives — it took one test from 0.2 s to 19 s. Scanning
    once and bisecting is O(n) + O(log n), and unlike an incremental counter it cannot be
    tripped by a directive that begins between the `\\r` and the `\\n` of a CRLF.
    """
    return [m.start() for m in _LINE_BREAK_RE.finditer(text)]


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

    Matched on the text AS GIVEN. `DIRECTIVE_RE` carries JavaScript's line anchors and its
    `.` spelled out, so a bare CR, U+2028 or U+2029 ends a directive line here exactly as
    it does in the reference, and the body keeps the author's bytes:

        render("#set %x% = A\\r%x%")  ->  "\\rA"

    An earlier version matched on a copy with terminators normalised to `\\n`. That works
    for anchoring alone and breaks the moment the pattern also carries an explicit
    terminator beside the anchor — the trailing `\\r?` could never fire on the copy,
    because every bare `\\r` had already become `\\n`, so `"#set %a% = v\\r\\rX"` kept one
    CR too many. Measured against the reference, which returns `"\\rX"`.
    """
    set_defs: dict[str, str] = {}
    def_defs: dict[str, str] = {}
    occurrences: list[Occurrence] = []
    spans: list[tuple[int, int]] = []
    breaks = _line_break_offsets(text)

    for m in DIRECTIVE_RE.finditer(text):
        kind, raw_name, value = m.group(1), m.group(2), m.group(3)
        name = raw_name.lower()
        occurrences.append(
            Occurrence(
                kind=kind,
                name=name,
                value=value,
                line=bisect_left(breaks, m.start()) + 1,
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
