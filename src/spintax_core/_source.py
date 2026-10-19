"""Source text as the parser sees it, and positions that still point at the original.

Validation runs over the parser's projection — comments removed, `/! … !/` spans encoded
as tokens (`_verbatim`) — which is what the other engines do, and why a construct split
by a comment is seen as one construct and a bracket inside a span is not seen at all. But
the projection moves every offset after a comment or a span, so a diagnostic computed on
it would report a position the author cannot find.

The reference engine accepts that: its positions are explicitly best-effort and are
not parity-gated. Here they are exact instead, which costs one list of segments.
Being *more* accurate is safe precisely because position is not part of the
cross-engine contract — but it is part of the public `Diagnostic`, and an editor
underlining the wrong span is a real defect to its user.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from . import _verbatim
from ._verbatim import Projection

#: JavaScript's `m` flag ends a line at `\r`, U+2028 and U+2029 as well as `\n`;
#: Python's ends it only at `\n`, and its `.` happily matches a bare `\r`. Left alone, a
#: file using bare CR line endings has its entire remainder swallowed into one `#set`
#: value — the directive after it is never seen at all.
#:
#: Substituting these for `\n` is safe precisely because it is length-preserving: every
#: offset, and therefore every position and every span, is unchanged. `\r\n` is excluded
#: because JavaScript treats the pair as ONE terminator, and rewriting the `\r` would
#: turn it into two blank lines.
_LINE_TERMINATORS_RE = re.compile("\\r(?!\\n)|\\u2028|\\u2029")


def normalize_terminators(text: str) -> str:
    """Rewrite every JavaScript line terminator to `\\n`, preserving length.

    For *matching* only. Anything that renders text back to a user must work from the
    original: the reference keeps the author's bytes, so `render("a\\rb")` is `"a\\rb"`
    and not `"a\\nb"`. Because the substitution is one character for one, a span found
    in the normalised copy is the same span in the original.
    """
    return _LINE_TERMINATORS_RE.sub("\n", text)


@dataclass(frozen=True, slots=True)
class Source:
    """The original text, its projection, and the map between them.

    ``text`` is the **scanning** view: the projection (comments removed, `/! … !/` spans
    encoded as tokens — see `_verbatim`) with line terminators normalised. It is what the
    validator and `extract` read, and neither of them returns template text to a caller. A
    renderer must not emit from it — see `normalize_terminators`.
    """

    original: str
    text: str
    #: The projection with the author's terminators INTACT. For the one rule whose
    #: character class carries `\n` inside it — `#include`'s gap — the normalised view is a
    #: trap: a U+2028 rewritten to `\n` for anchoring becomes gap whitespace, and
    #: `#include "x"` turns into an include the reference calls plain text. Normalisation is
    #: one character for one, so offsets here and in ``text`` are the same offsets;
    #: ``to_original`` serves both.
    text_exact: str
    #: The scan this view came from: the offset map, the span count, the unclosed `/!`.
    projection: Projection
    #: Offsets of every line start in `original`, for position lookup.
    _line_starts: tuple[int, ...]

    def to_original(self, offset: int) -> int:
        """Map an offset in `text` back to its offset in `original`."""
        return self.projection.to_source(offset)

    def position(self, offset: int) -> tuple[int, int]:
        """1-based (line, column) in the ORIGINAL source for an offset in `text`."""
        return self.position_in_original(self.to_original(offset))

    def position_in_original(self, offset: int) -> tuple[int, int]:
        offset = max(0, min(offset, len(self.original)))
        line = bisect_right(self._line_starts, offset) - 1
        return line + 1, offset - self._line_starts[line] + 1


def read(src: str) -> Source:
    """Project `src` (see `_verbatim.project`), keeping a map back to the original offsets."""
    projection = _verbatim.project(src)

    # Count lines over the SAME terminator set the scanning text is normalised to. Doing
    # it on `\n` alone would leave the engine treating a bare CR as a line break for the
    # rules — it finds the second directive — while reporting every diagnostic on line 1
    # with an ever-growing column. The substitution is length-preserving, so offsets in
    # this string are still offsets in `src`.
    for_lines = _LINE_TERMINATORS_RE.sub("\n", src)
    line_starts = [0]
    for i, ch in enumerate(for_lines):
        if ch == "\n":
            line_starts.append(i + 1)

    return Source(
        original=src,
        text=_LINE_TERMINATORS_RE.sub("\n", projection.text),
        text_exact=projection.text,
        projection=projection,
        _line_starts=tuple(line_starts),
    )
