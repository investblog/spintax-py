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

from . import _charclasses, _directives, _plurals, _source
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
#: this file already fixed.
_S = _charclasses.JS_SPACE

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

#: `#include "slug"`. The whitespace class is the contract's six ASCII characters,
#: spelled out — no engine's `\s` is this set (Python's and PCRE2-under-`/u`'s are each
#: a different Unicode; the plugin's WAS `\s` until spintax-js#55 measured the drift).
#: The corpus pins the class character by character (`extract/include-*`).
#:
#: Anchored with the JavaScript line boundaries and matched over ``Source.text_exact``,
#: NOT the normalised scanning view. This is the one rule whose class carries `\n`
#: INSIDE it, so normalisation feeds the anchors by poisoning the class: a U+2028
#: rewritten to `\n` became gap whitespace, and `#include "x"` was an include to
#: this scan while the reference — and this port's own renderer — printed it verbatim.
#: `_render.py` documents the same trap from the other end; it is why the pattern
#: cannot simply keep `re.MULTILINE` and the normalised text.
_INCLUDE_RE = re.compile(
    _charclasses.JS_LINE_START
    + r'[ \t]*#include[ \t\n\r\f\x0b]+"([^"]+)"[ \t\n\r\f\x0b]*'
    + _charclasses.JS_LINE_END
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

    __slots__ = ("code", "data", "length", "message", "offset", "severity")

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

    ``text`` must be ``Source.text_exact``, not the normalised scanning view: the
    reference splits on LF ALONE, so a lone CR or U+2028 is line CONTENT, and the
    normalised copy invents line starts the reference never checks (corpus:
    validate/directive-check-cr-does-not-split and -ls-does-not-split). And the shape
    test is a `/m` regex TEST, not an anchored match — a well-formed directive after a
    CR inside the line anchors on `JS_LINE_START` and satisfies it, which is why the
    malformed-looking head in -cr-survivor-satisfies is not reported. `search`, not
    `match`, reproduces that.
    """
    offset = 0
    for raw_line in text.split("\n"):
        stripped = raw_line.lstrip(" \t")
        kind = next(
            (k for k in ("#set", "#def") if stripped.startswith((k + " ", k + "\t"))),
            None,
        )
        if kind is not None and not _directives.DIRECTIVE_RE.search(stripped):
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

    for root, root_refs in refs.items():
        if colour.get(root, _WHITE) != _WHITE:
            continue
        colour[root] = _GREY
        reaches[root] = False
        stack: list[tuple[str, Iterator[str]]] = [(root, iter(root_refs))]

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


#: Passes, not occurrences — each one substitutes EVERY reference, as the renderer's
#: expansion does. Counting occurrences instead let a form list with 51 references exhaust
#: the budget and go unjudged. Deliberately NOT claimed to match a renderer's own limit
#: (they differ: 50 here and in JS, 51 in both PHP engines); it only has to terminate, and
#: a chain deeper than this is suppressed rather than judged, which is the safe direction.
_FORM_EXPANSION_PASSES = 51

#: How far the form list may GROW under expansion, in characters.
#:
#: Passes alone do NOT bound the work: ``#set %a% = %b% %b%`` over ``#set %b% = %a% %a%``
#: doubles the text every pass, so 51 of them is 2**51 -- a 62-character template took
#: ``validate()`` out with an out-of-memory crash in every engine of the family.
#:
#: Growth, not total size, and the difference is a verdict: ``{plural 2: one|<65 KB of
#: ordinary text>}`` is plainly two forms and must keep earning ``plural.arity`` under
#: ``ru``. A ceiling on total length called that unknowable and flipped it to valid -- a
#: real regression, caught in review before it shipped. Expansion that ADDS this much is a
#: graph exploding; a long form list is just long.
_FORM_EXPANSION_MAX_GROWTH = 64 * 1024

#: Any bracket at all — all four, and conditionals too.
#:
#: Conditionals: one resolves before plurals, so it is not "unresolved at plural time",
#: but its branches can differ in top-level pipes (``{?flag?a|b|c}`` freezes as ``a`` or as
#: ``b|c``), and counting is about invariance rather than stage order. Closing brackets: a
#: ``#set %x% = ]`` balances against a ``[`` elsewhere, so the bracket checker stays quiet,
#: and every renderer's plural guard is ``[{}\[\]]`` — a stray closer is rejected exactly
#: like an opener.
#:
#: Construct-free is a SUFFICIENT condition for invariance, deliberately not a necessary
#: one: ``{a|b}`` really does always freeze to one form. It is the property this validator
#: elects to prove, because an invariant construct cannot be told from a varying one
#: without evaluating it.
_ANY_BRACKET = re.compile(r"[\[\]{}]")
_CONDITIONAL_OPEN = re.compile(r"\{\?")


def _expand_forms_for_counting(
    forms_raw: str,
    defs: dict[str, str],
    macros: dict[str, str],
    host_names: frozenset[str],
) -> tuple[int, bool, bool]:
    """How many forms the plural stage will receive: (forms, unresolved, direct_macro_spintax).

    ``render`` expands ``%variables%`` and only THEN splits the form list, while this
    validator used to split the raw source — so any reference inside a form list was judged
    on the wrong number, in both directions (spintax-js#66).

    The rule is deliberately narrow, and the narrowness IS the correction. A first version
    tried to predict the roll, counting pipes at bracket depth 0 on the theory that a
    construct always collapses to one form. It does not::

        #set %flag% =
        #def %x% = {?flag?a|b|c}     # the false branch freezes as `b|c`: TWO forms
        {plural 1: one|%x%}          # renders fine under ru; the guess said arity error

    So a value is counted only when its form count is the same WHATEVER the roll does —
    when it carries no construct at all. Anything else, any name the host may supply, and
    any reference the template does not define suppress the count-based verdicts.

    ``direct_macro_spintax`` is the one prediction that survives, because it is not one: a
    ``#set`` named DIRECTLY in the form slot is substituted verbatim and is still spintax
    when the plural is decided. Reached through a ``#def`` it is rolled first.
    """
    # Which brackets reach the form slot VERBATIM: follow the #set chain out of the raw
    # slot. "Direct" is a property of the PATH, not of one hop — `#set %a% = %b%` with
    # `#set %b% = {a|b}` never crosses a #def, so the macro text arrives whole.
    seen_macro: set[str] = set()

    def _refs_of(text: str) -> list[str]:
        return [m.group(1).lower() for m in _VARIABLE_RE.finditer(text)]

    def _walk_macros(source: str) -> str:
        """Pre-order depth-first walk of the ``#set`` graph, in source order.

        Iterative, and the order is load-bearing: the FIRST non-clean answer wins, so a
        graph holding both an opaque macro and a brackety one gives different diagnostics
        depending on which is met first. A cheaper order would be a different contract.

        Written recursively it cost one frame per link and raised ``RecursionError`` on a
        long acyclic ``#set`` chain -- about 1000 links, a 20 KB template -- while the PHP
        engines returned a verdict. ``validate()`` answering with an exception is neither a
        verdict nor parity. ``seen_macro`` already bounds total work to the number of
        distinct macros, so no step budget is needed on top.
        """
        stack: list[tuple[list[str], int]] = [(_refs_of(source), 0)]

        while stack:
            refs, i = stack[-1]
            if i >= len(refs):
                stack.pop()
                continue
            stack[-1] = (refs, i + 1)
            name = refs[i]
            # A #def rolls it and a host value replaces it — either way the macro text
            # does not arrive verbatim, so this path says nothing.
            if name in defs or name in host_names:
                continue
            macro = macros.get(name)
            if macro is None or name in seen_macro:
                continue
            seen_macro.add(name)
            # A conditional is where the engines themselves disagree: both PHP renderers
            # resolve one that expansion introduces INSIDE a form list, this port and JS
            # do not. Until that is settled, decline to judge rather than pick a side.
            if _CONDITIONAL_OPEN.search(macro):
                return "opaque"
            if _ANY_BRACKET.search(macro):
                return "brackets"
            stack.append((_refs_of(macro), 0))

        return "clean"

    verbatim = _walk_macros(forms_raw)
    if verbatim == "brackets":
        return 0, True, True
    if verbatim == "opaque":
        return 0, True, False

    text = forms_raw
    budget = len(forms_raw) + _FORM_EXPANSION_MAX_GROWTH
    for _ in range(_FORM_EXPANSION_PASSES):
        bailed = False
        saw_reference = False
        # Built by hand rather than with ``sub()`` because the budget has to be enforced
        # DURING the pass: ``sub()`` materializes the whole next generation before anyone
        # can measure it, so a single pass over 60 KB of self-reference allocates ~900 MB
        # and a check downstream never runs.
        parts: list[str] = []
        total = 0
        cursor = 0

        # EVERY reference per pass, as the renderer's expansion does. `_VARIABLE_RE` is the
        # shared ASCII class, not `\w`: Python's `\w` is Unicode, so `%é%` would count as a
        # reference here and as literal text everywhere else — the exact divergence this
        # port spent #55/#56 removing.
        for m in _VARIABLE_RE.finditer(text):
            saw_reference = True
            name = m.group(1).lower()
            # Runtime context outranks a definition of the same name, so a host-declared
            # name makes the count unknowable even where the template defines one locally.
            value = None if name in host_names else defs.get(name, macros.get(name))
            # A construct in the value: what it rolls to may or may not carry a top-level
            # pipe, so no single count is true of every render.
            if value is None or _ANY_BRACKET.search(value):
                bailed = True
                break
            parts.append(text[cursor : m.start()])
            parts.append(value)
            total += m.start() - cursor + len(value)
            cursor = m.end()
            if total > budget:
                return 0, True, False

        if bailed:
            return 0, True, False
        parts.append(text[cursor:])
        total += len(text) - cursor
        if total > budget:
            return 0, True, False
        text = "".join(parts)

        if not saw_reference:
            # No construct can be left, so the plain split is what the renderer does too.
            return len(text.split("|")), False, False

    # A cycle, or a chain deeper than this bothers to follow.
    return 0, True, False


def check_plurals(
    text: str,
    locale: str | None,
    known_variables: list[str] | None,
    out: list[Finding],
) -> None:
    """Count-slot macros, brackets in a form slot, and form count against the locale."""
    # Guard on the NORMALIZED base: a non-empty locale that normalizes to nothing
    # (`"_en"`) skips the arity check rather than guessing at it.
    base = _plurals.normalize_base_lang(locale) if locale else ""
    expected = _plurals.arity(base) if base else 0

    tainted = _macro_tainted_names(text)
    directives = _directives.extract(text)
    defs, macros = directives.def_defs, directives.set_defs
    # Names the host says it will supply: runtime context outranks a definition of the
    # same name, so one of these makes a form count unknowable however the template
    # defines it.
    host_names = frozenset(name.lower() for name in (known_variables or ()))

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

        # The form list AS THE RENDERER WILL SEE IT (spintax-js#66).
        got, unresolved, macro_spintax = _expand_forms_for_counting(
            block.forms_raw, defs, macros, host_names
        )

        # A #set whose value carries spintax lands in the form list verbatim and is still
        # unresolved when the plural is decided — the same fact plural.count-macro states
        # for the count slot, and exactly what this message already describes.
        if macro_spintax:
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
            continue

        # A reference the template does not define has no static form count. Judging it
        # would repeat the mistake #65 fixed: a verdict on a fact nobody claimed.
        if unresolved:
            continue

        if expected > 0:
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
        elif got != _plurals.DEFAULT_ARITY:
            # No locale ⇒ no arity VERDICT: the template may well be correct for the
            # locale it will be rendered with, and calling it invalid here would fail a
            # good template for a fact the caller never claimed. But `render` has no such
            # luxury — it defaults to 2 forms — so silence sends a 3-form block straight
            # to the fullwidth-brace fallback in finished text (spintax-js#65: a pipeline
            # shipped ｛plural …｝ to live pages because validate stayed quiet). A warning
            # says the one true thing: this resolves only if a matching locale arrives at
            # render time.
            out.append(
                Finding(
                    "warning",
                    "plural.locale-missing",
                    f"{{plural ...}}: {got} forms, but no locale was supplied. render "
                    f"defaults to {_plurals.DEFAULT_ARITY} forms and leaves this block "
                    f"unresolved — pass the locale you will render with.",
                    block.start,
                    length,
                    {"got": got, "defaultArity": _plurals.DEFAULT_ARITY},
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
    # Exact terminators, like the include scan below — the LF-only line split and the
    # JS-anchored shape test both need the author's CR/U+2028 kept, and the 1:1
    # normalisation means every offset agrees between the two views.
    check_directives(source.text_exact, findings)
    check_permutation_configs(source.text, findings)
    check_plurals(source.text, locale, known_variables, findings)
    check_variable_references(source.text, known_variables, findings)
    if known_includes:
        # Exact terminators, not the normalised view — see _INCLUDE_RE. Offsets agree
        # between the two views, so the findings' positions need nothing special.
        check_include_targets(source.text_exact, known_includes, findings)
    return source, findings
