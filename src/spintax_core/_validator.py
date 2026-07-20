"""Static validation — a raw-text scan, deliberately not an AST walk.

The AST is lenient: an unbalanced bracket is not represented in it at all, it just
becomes literal text, and a construct inside a `[…]` permutation body is left as a
raw string. A validator built on the tree therefore cannot see a large part of what
it exists to report. Both sibling engines scan the text for the same reason.

`code` (and severity) is the parity-gated contract; wording and position are not.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from . import _directives, _plurals, _source
from ._source import Source

# Only these four keys are accepted inside a `[<…>]` config block.
_KNOWN_CONFIG_KEYS = frozenset({"minsize", "maxsize", "sep", "lastsep"})

# `\w`, `\d` and `\b` are Unicode-aware in Python and ASCII-only in JavaScript, so each one is
# spelled out rather than trusted.
_W = _directives.ASCII_WORD

#: `\s` is Unicode in both engines — but not the SAME Unicode. Python's includes
#: U+001C–U+001F and U+0085; JavaScript's includes U+FEFF and excludes those five. Six
#: characters, and U+FEFF is not exotic: it arrives by copy-paste. Leaving `\s` alone
#: was therefore not neutrality, it was a fourth divergence sitting beside the three
#: this file already fixed. Spelled out as JavaScript's set.
_S = "[\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]"

_CONFIG_PREFIX_RE = re.compile(r"\[<([^>]*?)>")
#: Redundant with the key loop below — every path into a diagnostic already requires a
#: word run before `=`. Kept because it states the intent (a `<…>` is only a config when
#: it looks like `key=value`) and mirrors the reference's structure.
_LOOKS_LIKE_CONFIG_RE = re.compile(_W + "+" + _S + "*=")
_CONFIG_KEY_RE = re.compile("(" + _W + "+)" + _S + "*=")
_MINSIZE_RE = re.compile("minsize" + _S + "*=" + _S + "*([^;>" + _S[1:-1] + "]+)", re.IGNORECASE)
_MAXSIZE_RE = re.compile("maxsize" + _S + "*=" + _S + "*([^;>" + _S[1:-1] + "]+)", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^[0-9]+$")
# JS ends the word at any non-ASCII-word character, so `#includeя` matches there; Python's `\b`
# would treat the Cyrillic letter as part of the word and miss it.
_INCLUDE_IN_VALUE_RE = re.compile(r"#include(?!" + _W + ")")

_VARIABLE_RE = re.compile("%(" + _W + r"+)%")
_CONDITIONAL_REF_RE = re.compile(r"\{\?!?([A-Za-z_]" + _W + r"*)\?")

#: Directive lines are single-line by design — `[ \t]`, never `\s`, so a malformed
#: directive split across lines is not read as a definition.
_DEFINITION_RE = re.compile(
    r"^[ \t]*#(?:set|def)[ \t]+%(" + _W + r"+)%[ \t]*=[ \t]*(.*?)[ \t]*\r?$", re.MULTILINE
)
_DEFINITION_LINE_RE = re.compile(
    r"^[ \t]*#(?:set|def)[ \t]+%" + _W + r"+%[ \t]*=[ \t]*.*?$", re.MULTILINE
)

#: `#include "slug"`. The whitespace class is spelled out as ASCII on purpose — the
#: plugin's is ASCII, and Python's `\s` would also match Unicode spaces here.
_INCLUDE_WS = r"[ \t\n\r\f\v]"
_INCLUDE_RE = re.compile(
    r'^[ \t]*#include' + _INCLUDE_WS + r'+"([^"]+)"' + _INCLUDE_WS + r"*$", re.MULTILINE
)

#: Spintax still unresolved when plural agreement runs: a `[`, or a `{` that does not
#: open a conditional. Stage order decides this, not bracket type — conditionals
#: resolve before plurals, enumerations and permutations after.
_UNRESOLVED_AT_PLURAL_TIME = re.compile(r"\[|\{(?!\?)")
_NESTED_BRACKET_RE = re.compile(r"[{}\[\]]")


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
                Finding(
                    "error",
                    "definition.duplicate-name",
                    f"Variable {occurrence.name!r} is defined more than once. "
                    "A name belongs to one directive, once.",
                    occurrence.offset,
                    len(occurrence.name) + 2,
                    # The first definition travels as an OFFSET, not a line number.
                    # `Occurrence.line` counts lines in the comment-stripped text, while
                    # the diagnostic's own line is mapped back to the original — quoting
                    # one inside the other mixes two coordinate systems, and a comment
                    # above the directives makes the two disagree.
                    {"first_offset": previous},
                )
            )
        else:
            first_seen[occurrence.name] = occurrence.offset

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
                    len(occurrence.name) + 2,
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


# ── variables ──────────────────────────────────────────────────────────


def _definitions(text: str) -> tuple[dict[str, str], dict[str, int]]:
    """name → value, and name → offset of its `%name%` token, for every directive line."""
    values: dict[str, str] = {}
    at: dict[str, int] = {}
    for m in _DEFINITION_RE.finditer(text):
        name = m.group(1).lower()
        values[name] = m.group(2)
        at[name] = m.start() + m.group(0).index("%")
    return values, at


_WHITE, _GREY, _BLACK = 0, 1, 2


def _names_reaching_a_cycle(refs: dict[str, list[str]]) -> set[str]:
    """Every defined name from which a circular reference is reachable.

    One depth-first pass over the whole graph, colouring nodes, rather than a fresh
    search per definition. Two reasons, both found by breaking it:

    * The obvious recursive form — which the reference uses — overflows Python's
      1000-frame stack on a long *acyclic* chain. Around 996 links of
      `#set %v0% = %v1%` … is enough to raise `RecursionError` out of `validate()`,
      on a template with nothing wrong with it. Node's stack is deep enough to hide
      the same shape, so this is a difference in what the two runtimes accept, not in
      the rule they implement.
    * Searching per definition and carrying the path as a list is quadratic in the
      chain and exponential on a fan-out: a 24-level diamond took over half a minute.
      Colouring visits each edge once.

    A grey node is on the current path, so an edge into one closes a loop. A black
    node is finished, so its answer is already known and is simply inherited.
    """
    colour: dict[str, int] = {}
    reaches: dict[str, bool] = {}

    for root in refs:
        if colour.get(root, _WHITE) != _WHITE:
            continue
        colour[root] = _GREY
        reaches[root] = False
        stack: list[tuple[str, Iterator[str]]] = [(root, iter(refs[root]))]

        while stack:
            node, it = stack[-1]
            advanced = False
            for ref in it:
                if ref == node or ref not in refs:
                    continue  # self-reference is its own diagnostic; unknown names are not edges
                state = colour.get(ref, _WHITE)
                if state == _GREY:
                    reaches[node] = True
                elif state == _BLACK:
                    if reaches[ref]:
                        reaches[node] = True
                else:
                    colour[ref] = _GREY
                    reaches[ref] = False
                    stack.append((ref, iter(refs[ref])))
                    advanced = True
                    break
            if advanced:
                continue
            stack.pop()
            colour[node] = _BLACK
            if stack and reaches[node]:
                reaches[stack[-1][0]] = True

    return {name for name, hit in reaches.items() if hit}


def check_variable_references(
    text: str, known: list[str] | None, out: list[Finding]
) -> None:
    """Self-reference and cycles (errors); undefined names (warnings).

    Undefined is a **warning**, not an error: a name the template does not define may
    well be supplied at render time. Reported once per name — an undefined `%brand%`
    used forty times is one problem, not forty.
    """
    known_set = {n.lower() for n in (known or [])}
    defs, def_at = _definitions(text)
    refs = {name: [m.group(1).lower() for m in _VARIABLE_RE.finditer(value)] for name, value in defs.items()}

    for name, value in defs.items():
        if f"%{name}%" in value.lower():
            # Underline the `%name%` token, not the character it starts at: an editor
            # that highlights one column is the defect this file's positions exist to
            # avoid. `+2` for the two per-cent signs.
            out.append(
                _error(
                    "variable.self-reference",
                    f"Variable {name!r} references itself.",
                    def_at[name],
                    len(name) + 2,
                )
            )
    for name in sorted(_names_reaching_a_cycle(refs), key=lambda n: def_at.get(n, 0)):
        out.append(
            _error(
                "variable.circular-reference",
                f"Variable {name!r} takes part in, or leads to, a circular reference.",
                def_at[name],
                len(name) + 2,
            )
        )

    # Blank the directive lines to same-length whitespace rather than removing them:
    # a definition's own `%name%` is not a reference, but deleting the line would shift
    # every later offset and put the remaining diagnostics in the wrong place.
    body = _DEFINITION_LINE_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)

    seen: set[str] = set()

    def _undefined(name: str, offset: int, length: int) -> None:
        key = name.lower()
        if key in defs or key in known_set or key in seen:
            return
        seen.add(key)
        out.append(
            Finding(
                "warning",
                "variable.undefined",
                f"Variable {name!r} is not defined — may be a runtime variable.",
                offset,
                length,
                {"name": name},
            )
        )

    for m in _VARIABLE_RE.finditer(body):
        _undefined(m.group(1), m.start(), len(m.group(0)))
    for m in _CONDITIONAL_REF_RE.finditer(body):
        _undefined(m.group(1), m.start(1), len(m.group(1)))


# ── plurals ────────────────────────────────────────────────────────────


def _macro_tainted_names(text: str) -> set[str]:
    """`#set` names whose value is still spintax when the plural pass runs.

    Only `#set` can be tainted: a `#def` is frozen to literal text before the body is
    walked, which is exactly the fix this diagnostic recommends.

    The fixed point is not decoration. A macro can reach unresolved spintax through a
    chain of other macros, and that reference is invisible in its own text — one pass
    catches `#set %n% = {1|4}` and misses `#set %n% = %m%` where `%m%` holds it.
    """
    macros = _directives.extract(text).set_defs
    tainted = {name for name, value in macros.items() if _UNRESOLVED_AT_PLURAL_TIME.search(value)}

    grew = True
    while grew:
        grew = False
        for name, value in macros.items():
            if name in tainted:
                continue
            if any(m.group(1).lower() in tainted for m in _VARIABLE_RE.finditer(value)):
                tainted.add(name)
                grew = True
    return tainted


def check_plurals(text: str, locale: str | None, out: list[Finding]) -> None:
    """Count-slot macros, brackets in a form slot, and form count against the locale."""
    # Guard on the NORMALIZED base: a non-empty locale that normalizes to nothing
    # (`"_en"`) skips the arity check rather than guessing at it.
    base = _plurals.normalize_base_lang(locale) if locale else ""
    expected = _plurals.arity(base) if base else 0

    tainted = _macro_tainted_names(text)

    for block in _plurals.find_blocks(text):
        length = block.end - block.start

        # The count is still unresolved spintax when the plural is decided, so the block
        # renders empty. Reported at the block, but the fix is at the directive: `#def`.
        for m in _VARIABLE_RE.finditer(block.count_slot):
            if m.group(1).lower() not in tainted:
                continue
            out.append(
                _error(
                    "plural.count-macro",
                    f"{{plural ...}}: the count {m.group(1)!r} is a #set macro, so it is still "
                    "unresolved spintax when the plural is decided and the block renders empty. "
                    "Define it with #def instead.",
                    block.start,
                    length,
                )
            )

        if _NESTED_BRACKET_RE.search(block.forms_raw):
            out.append(
                _error(
                    "plural.nested-brackets",
                    "{plural ...}: forms must not contain nested spintax brackets. Extract via "
                    "#def first — a #set is substituted verbatim and would put the brackets "
                    "straight back.",
                    block.start,
                    length,
                )
            )
            # No arity check on a block whose forms are already wrong: splitting on `|`
            # would count pipes belonging to the nested construct and report a second,
            # invented problem.
            continue

        if expected > 0:
            got = len(block.forms_raw.split("|"))
            if got != expected:
                out.append(
                    _error(
                        "plural.arity",
                        f"{{plural ...}}: expected {expected} forms, got {got}.",
                        block.start,
                        length,
                        expected=expected,
                        got=got,
                    )
                )


# ── includes ───────────────────────────────────────────────────────────


def check_include_targets(text: str, known: list[str], out: list[Finding]) -> None:
    """Unknown `#include` targets — only when the caller supplies a slug list.

    With no list every target is assumed to exist: the engine does not resolve
    includes, so it cannot tell an unknown slug from one the host will provide.
    """
    available = set(known)
    for m in _INCLUDE_RE.finditer(text):
        target = m.group(1)
        if target in available:
            continue
        out.append(
            _error(
                "include.unknown-target",
                f"#include target {target!r} does not match any known template.",
                m.start() + m.group(0).index('"') + 1,
                len(target),
                target=target,
            )
        )


# ── entry point ────────────────────────────────────────────────────────


def run(
    src: str,
    *,
    locale: str | None = None,
    known_includes: list[str] | None = None,
    known_variables: list[str] | None = None,
) -> tuple[Source, list[Finding]]:
    """Every check, over the comment-stripped text."""
    source = _source.read(src)
    findings: list[Finding] = []
    check_brackets(source.text, findings)
    check_directives(source.text, findings)
    check_permutation_configs(source.text, findings)
    check_plurals(source.text, locale, findings)
    check_variable_references(source.text, known_variables, findings)
    if known_includes:
        check_include_targets(source.text, known_includes, findings)
    return source, findings
