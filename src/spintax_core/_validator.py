"""Static validation — a raw-text scan, deliberately not an AST walk.

The AST is lenient: an unbalanced bracket is not represented in it at all, it just
becomes literal text, and a construct inside a `[…]` permutation body is left as a
raw string. A validator built on the tree therefore cannot see a large part of what
it exists to report. Both sibling engines scan the text for the same reason.

`code` (and severity) is the parity-gated contract; wording and position are not.
"""

from __future__ import annotations

import re

from . import _directives, _source
from ._source import Source

# Only these four keys are accepted inside a `[<…>]` config block.
_KNOWN_CONFIG_KEYS = frozenset({"minsize", "maxsize", "sep", "lastsep"})

# `\w`, `\d` and `\b` are Unicode-aware in Python and ASCII-only in JavaScript, so each one is
# spelled out. Deliberately left alone: `\s`, which is Unicode in both — narrowing it (which
# `re.ASCII` would have done for the whole pattern) would be a divergence of its own.
_W = _directives.ASCII_WORD

_CONFIG_PREFIX_RE = re.compile(r"\[<([^>]*?)>")
_LOOKS_LIKE_CONFIG_RE = re.compile(_W + r"+\s*=")
_CONFIG_KEY_RE = re.compile("(" + _W + r"+)\s*=")
_MINSIZE_RE = re.compile(r"minsize\s*=\s*([^;>\s]+)", re.IGNORECASE)
_MAXSIZE_RE = re.compile(r"maxsize\s*=\s*([^;>\s]+)", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^[0-9]+$")
# JS ends the word at any non-ASCII-word character, so `#includeя` matches there; Python's `\b`
# would treat the Cyrillic letter as part of the word and miss it.
_INCLUDE_IN_VALUE_RE = re.compile(r"#include(?!" + _W + ")")


class Finding:
    """A diagnostic before it becomes a public `Diagnostic`.

    Kept separate so the checks can report offsets into the scanned text and let one
    place translate them into positions in the original source.
    """

    __slots__ = ("severity", "code", "message", "offset", "length", "data")

    def __init__(
        self,
        severity: str,
        code: str,
        message: str,
        offset: int,
        length: int = 1,
        data: dict[str, object] | None = None,
    ) -> None:
        self.severity = severity
        self.code = code
        self.message = message
        self.offset = offset
        self.length = length
        self.data = data


def _error(code: str, message: str, offset: int, length: int = 1, **data: object) -> Finding:
    return Finding("error", code, message, offset, length, dict(data) or None)


# ── structural: brackets ───────────────────────────────────────────────


_CLOSES = {"{": "}", "[": "]"}


def check_brackets(text: str, out: list[Finding]) -> None:
    """Balance `{}` and `[]` over the raw text.

    Reported per offending bracket rather than per template: a file with three stray
    closers should say so three times, and an unclosed opener must point at the
    opener, not at the end of the file where the imbalance is noticed.
    """
    stack: list[tuple[str, int]] = []

    for i, ch in enumerate(text):
        if ch in _CLOSES:
            stack.append((ch, i))
        elif ch in ("}", "]"):
            if not stack:
                out.append(
                    _error("bracket.unexpected-closing", f"Unexpected closing {ch!r}.", i, 1, bracket=ch)
                )
                continue
            opener, _ = stack.pop()
            if _CLOSES[opener] != ch:
                out.append(
                    _error(
                        "bracket.mismatched",
                        f"{opener!r} closed by {ch!r}.",
                        i,
                        1,
                        open=opener,
                        close=ch,
                    )
                )

    for opener, at in stack:
        out.append(_error("bracket.unclosed", f"Unclosed {opener!r}.", at, 1, bracket=opener))


# ── directives ─────────────────────────────────────────────────────────


def check_directives(text: str, out: list[Finding]) -> None:
    """Shape, uniqueness, and the `#include`-in-a-`#def` rule.

    Shape is tested with the parser's own grammar rather than a private copy. The
    reference engine carried a second regex here that differed in two ways, and one
    of them was a live defect: it required a non-empty value, so `#set %x% =` — which
    the parser accepts, defining an empty string — was reported malformed unless a
    trailing space happened to be present.
    """
    offset = 0
    for raw_line in text.split("\n"):
        stripped = raw_line.lstrip(" \t")
        kind = next(
            (k for k in ("#set", "#def") if stripped.startswith(k + " ") or stripped.startswith(k + "\t")),
            None,
        )
        if kind is not None and not _directives.DIRECTIVE_RE.match(stripped):
            indent = len(raw_line) - len(stripped)
            code = "def.malformed" if kind == "#def" else "set.malformed"
            out.append(
                _error(
                    code,
                    f"Malformed {kind}. Expected: {kind} %name% = value",
                    offset + indent,
                    max(1, len(stripped)),
                )
            )
        offset += len(raw_line) + 1  # +1 for the newline split consumed

    extracted = _directives.extract(text)
    first_seen: dict[str, int] = {}

    for occurrence in extracted.occurrences:
        # A name defined twice is an error whichever directives are involved — and a
        # `#set`/`#def` pair sharing a name is worse than a plain duplicate, since the
        # two carry opposite semantics. The maps cannot see this; `occurrences` can.
        previous = first_seen.get(occurrence.name)
        if previous is not None:
            out.append(
                _error(
                    "definition.duplicate-name",
                    f"Variable {occurrence.name!r} is defined more than once "
                    f"(first on line {previous}). A name belongs to one directive, once.",
                    occurrence.offset,
                    1,
                )
            )
        else:
            first_seen[occurrence.name] = occurrence.line

        # Includes resolve after a definition is frozen, so one rolled into a `#def`
        # value would survive as literal text. Inside a `#set` it is fine: the macro is
        # substituted verbatim and its `#include` reaches the include stage in the body.
        if occurrence.kind == "def" and _INCLUDE_IN_VALUE_RE.search(occurrence.value):
            out.append(
                _error(
                    "def.include-in-value",
                    f"#include cannot appear in a #def value ({occurrence.name!r}): "
                    "includes resolve after the value is frozen. Use #set, or put the "
                    "#include in the body.",
                    occurrence.offset,
                    1,
                )
            )


# ── permutation config ─────────────────────────────────────────────────


def check_permutation_configs(text: str, out: list[Finding]) -> None:
    """`[<config>]` prefixes: known keys only, sizes must be digit runs.

    A leading `<…>` is only a config when it looks like `key=value`; otherwise it is a
    separator (`[<and>a|b]`) or content, and complaining about it would reject valid
    templates.
    """
    for m in _CONFIG_PREFIX_RE.finditer(text):
        config = m.group(1) or ""
        if not _LOOKS_LIKE_CONFIG_RE.search(config):
            continue
        base = m.start() + 2  # past "[<"

        for km in _CONFIG_KEY_RE.finditer(config):
            key = km.group(1)
            if key.lower() not in _KNOWN_CONFIG_KEYS:
                out.append(
                    _error(
                        "permutation.unknown-key",
                        f"Unknown permutation config key: {key!r}.",
                        base + km.start(1),
                        len(key),
                        key=key,
                    )
                )

        for pattern, code, label in (
            (_MINSIZE_RE, "permutation.minsize-not-integer", "minsize"),
            (_MAXSIZE_RE, "permutation.maxsize-not-integer", "maxsize"),
        ):
            sm = pattern.search(config)
            if sm and not _DIGITS_RE.match(sm.group(1)):
                out.append(
                    _error(
                        code,
                        f"{label} must be a positive integer, got {sm.group(1)!r}.",
                        base + sm.start(),
                        len(sm.group(0)),
                        value=sm.group(1),
                    )
                )


# ── entry point (wired into the public API once every check exists) ────


def run(src: str) -> tuple[Source, list[Finding]]:
    """Run the implemented checks over `src`. Not yet the full validator."""
    source = _source.read(src)
    findings: list[Finding] = []
    check_brackets(source.text, findings)
    check_directives(source.text, findings)
    check_permutation_configs(source.text, findings)
    return source, findings
