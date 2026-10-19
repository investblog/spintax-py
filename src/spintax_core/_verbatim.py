"""Block constructs of author source — `/# … #/` comments and `/! … !/` verbatim spans
(spintax-js#92, ADR 0001) — and the span token codec.

`project` is the one scan of author source, before anything else reads it: comments are
removed, each span is replaced where it stands by a self-contained TOKEN that carries its
content, and the reserved ranges are stripped from everything outside spans. Every later
pass — directives, the tree, the validator, `extract` — reads that projection, so none of
them can see into a span, and the token rides along wherever text goes (a `#set` value, an
`#include` body, the #78 splice, a reused `parse()`).

The token: U+F0000, then one pair of digits U+F1000+n per code point of the content
(`c >> 12`, `c & 0xFFF`), then U+F0001 — all in Supplementary Private Use Area-A, which no
pass reads as a letter, a digit, whitespace, punctuation or markup (`str.isalnum` and
`str.isspace` are both false there). Defined per code point, so this engine's tokens are
the reference's: a Python `str` indexes by code point, where JavaScript walks UTF-16 pairs.
`decode` turns tokens back into their content as the very last step of a render, after the
post-process and the neutralize safety-restore.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

_OPEN = 0xF0000
_CLOSE = 0xF0001
_DIGIT = 0xF1000

#: Reserved code points stripped from author text outside spans: the neutralize sentinels
#: (U+E000–U+E005; only `neutralize()` may introduce one) and the span range, so an author
#: cannot type a ready-made token. Inside a span they are content.
_RESERVED_RE = re.compile("[\ue000-\ue005\U000f0000-\U000f1fff]")
#: The span range alone — what a runtime context value is stripped of (ADR 0001 rule 4).
_SPAN_RANGE_RE = re.compile("[\U000f0000-\U000f1fff]")
#: A well-formed token. `re.sub` never rescans what it emitted, which is rule 7's
#: "decodes once": a span whose content is itself a token decodes to that token and stays.
_TOKEN_RE = re.compile("\U000f0000((?:[\U000f1000-\U000f1fff]{2})*)\U000f0001")


def encode(content: str) -> str:
    """Encode a span's content as a token."""
    digits = "".join(
        chr(_DIGIT + (ord(ch) >> 12)) + chr(_DIGIT + (ord(ch) & 0xFFF)) for ch in content
    )
    return chr(_OPEN) + digits + chr(_CLOSE)


def _decode_token(m: re.Match[str]) -> str:
    digits = m.group(1)
    # `chr` cannot overflow: only `encode` mints a token — author text and runtime values
    # are both stripped of the range — so every pair is one it wrote from a real code point.
    return "".join(
        chr(((ord(digits[i]) - _DIGIT) << 12) | (ord(digits[i + 1]) - _DIGIT))
        for i in range(0, len(digits), 2)
    )


def decode(text: str) -> str:
    """Replace every well-formed token by its content — once, never re-reading what it
    emitted."""
    if _SPAN_RANGE_RE.search(text) is None:
        return text
    return _TOKEN_RE.sub(_decode_token, text)


def budget_length(value: str) -> int:
    """What a value costs the expansion budget: its length with every token counted as
    its content (ADR 0001 rule 7a), so the encoding does not move the point where a bounded
    expansion stops."""
    return len(decode(value))


def strip_span_range(value: str) -> str:
    """Strip the span range from a runtime value, so data cannot carry a token (rule 4)."""
    return _SPAN_RANGE_RE.sub("", value)


@dataclass(frozen=True, slots=True)
class Projection:
    """The scan of author source: the text every later pass reads, and how to map back."""

    #: Comments removed, spans encoded, reserved ranges stripped outside spans.
    text: str
    #: Spans found, the empty `/!!/` included.
    spans: int
    #: Source offset of the first `/!` with no closer after it, or -1.
    unclosed: int
    #: One segment per run of the projection, in order: (text_start, src_start, src_end,
    #: is_token). A token's length differs from the source it stands for, so it cannot be
    #: mapped by offset arithmetic; every other run is the source, one for one.
    segments: tuple[tuple[int, int, int, bool], ...]
    #: Each segment's `text_start`, for the bisect.
    starts: tuple[int, ...]

    def to_source(self, offset: int) -> int:
        """Map an offset in `text` to the source. Inside a token, to the token's last
        source character (the `/` of `!/`), so an end computed as last-character-plus-one
        lands just past the span."""
        i = bisect_right(self.starts, offset) - 1
        if i < 0:
            return 0
        text_start, src_start, src_end, token = self.segments[i]
        delta = offset - text_start
        if delta <= 0:
            return src_start
        if token:
            return src_end - 1
        return min(src_start + delta, src_end)


def project(src: str) -> Projection:
    """Scan author source once, left to right.

    The next `/#` or `/!`, whichever comes first, runs to the first matching closer searched
    from the END of the opener, so `/!/` does not close itself. A comment is removed; a span
    is encoded, an empty one removed. An opener with no closer is two characters of text
    and the scan goes on after it — the reading of `/\\/#[\\s\\S]*?#\\/|\\/![\\s\\S]*?!\\//g`
    (no nesting; whichever opener comes first wins). Do not `break` at a missing closer as a
    comment-only loop could: a comment after an unclosed `/!` is still a comment.

    Linear, where the lazy regex this replaces was not: retried from every `/#` once no
    `#/` was left, it read to the end of the text from each of them. Once a closer is
    missing from some offset on, it is missing from every later one, so each kind's opener
    and closer are searched for at most once past any point.
    """
    segments: list[tuple[int, int, int, bool]] = []
    out: list[str] = []
    out_len = 0
    spans = 0
    unclosed = -1

    def push(src_start: int, src_end: int, piece: str, token: bool) -> None:
        nonlocal out_len
        segments.append((out_len, src_start, src_end, token))
        out.append(piece)
        out_len += len(piece)

    def copy(start: int, end: int) -> None:
        frm = start
        for m in _RESERVED_RE.finditer(src, start, end):
            if m.start() > frm:
                push(frm, m.start(), src[frm : m.start()], False)
            frm = m.end()
        if frm < end:
            push(frm, end, src[frm:end], False)

    frm = 0  # first source offset not yet emitted
    at = 0  # where the next opener is searched from
    next_comment = -2
    next_span = -2
    comment_closer_gone = False
    span_closer_gone = False
    while True:
        if next_comment != -1 and next_comment < at:
            next_comment = src.find("/#", at)
        if next_span != -1 and next_span < at:
            next_span = src.find("/!", at)
        if next_comment == -1 and next_span == -1:
            break
        is_span = next_comment == -1 or (next_span != -1 and next_span < next_comment)
        opener = next_span if is_span else next_comment
        gone = span_closer_gone if is_span else comment_closer_gone
        close = -1 if gone else src.find("!/" if is_span else "#/", opener + 2)
        if close == -1:
            if is_span:
                span_closer_gone = True
                if unclosed == -1:
                    unclosed = opener
            else:
                comment_closer_gone = True
            at = opener + 2
            continue
        copy(frm, opener)
        if is_span:
            spans += 1
            if close > opener + 2:
                push(opener, close + 2, encode(src[opener + 2 : close]), True)
        frm = at = close + 2
    copy(frm, len(src))

    return Projection(
        text="".join(out),
        spans=spans,
        unclosed=unclosed,
        segments=tuple(segments),
        starts=tuple(s[0] for s in segments),
    )
