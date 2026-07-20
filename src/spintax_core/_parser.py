"""Recursive-descent parser: template text to a tree.

**Lenient by contract (§9.2): this never raises on malformed markup.** An unmatched
bracket becomes literal text, a broken `{?…}` falls back to an enumeration, a bare `%`
stays a percent sign. Structural *diagnostics* are the validator's job, and it reads the
raw text precisely because a lenient tree cannot represent the problems it reports — an
unbalanced brace is not a node, it is just a character.

Two passes run before the tree is built, both line-anchored and both oblivious to braces:
comments are stripped, then `#set` / `#def` are pulled out globally. That is why a `#set`
alone on a line *inside* a group is a definition rather than an option's text. `#include`
is left alone here — the renderer resolves it as a post-tree string pass.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from . import _directives, _source
from ._ast import (
    AST_VERSION,
    ConditionalNode,
    EnumerationNode,
    LiteralNode,
    Node,
    ParsedAst,
    PermConfig,
    PermOption,
    PermutationNode,
    PluralNode,
    VariableNode,
)
from ._charclasses import (
    ASCII_DIGIT,
    ASCII_WORD,
    JS_SPACE,
    NOT_AFTER_WORD,
    PHP_TRIM_CHARS,
    js_ci_ascii,
    js_ci_unicode,
)

_VARIABLE_RE = re.compile(f"%({ASCII_WORD}+)%")
_CONDITIONAL_NAME_RE = re.compile(f"[A-Za-z_]{ASCII_WORD}*")
_PLURAL_PREFIX = "plural "

# `\Z`, not `$`, because Python's `$` also matches just before a trailing newline while
# the JavaScript original — no `m` flag — matches only at the very end.
#
# Defensive rather than load-bearing, and measured as such: the only caller trims with
# PHP's charlist first, and that includes `\n`, so no trailing newline can survive to
# reach the anchor. Swapping `\Z` for `$` provably changes nothing today. Kept because it
# is the faithful translation, and because the property holding depends on a trim that
# lives in another function — narrow the charlist there and this would start to matter
# silently.
_HTML_TAG_RE = re.compile(f"^([a-zA-Z][a-zA-Z0-9-]*)(?:{JS_SPACE}+[^>]*)?/?\\Z")
_PER_ELEM_HTML_RE = re.compile(f"^[a-zA-Z][a-zA-Z0-9]*{JS_SPACE}")

_CONFIG_KEY_RE = re.compile(
    f"{NOT_AFTER_WORD}(?:{js_ci_ascii('minsize')}|{js_ci_ascii('maxsize')}"
    f"|{js_ci_ascii('sep')}|{js_ci_ascii('lastsep')}){JS_SPACE}*="
)
_MINSIZE_RE = re.compile(
    f"{js_ci_ascii('minsize')}{JS_SPACE}*={JS_SPACE}*({ASCII_DIGIT}+)"
)
_MAXSIZE_RE = re.compile(
    f"{js_ci_ascii('maxsize')}{JS_SPACE}*={JS_SPACE}*({ASCII_DIGIT}+)"
)
#: The lookbehind is what keeps `lastsep="…"` from also matching as `sep`.
_SEP_RE = re.compile(
    f'(?<!{js_ci_ascii("last")}){js_ci_ascii("sep")}{JS_SPACE}*={JS_SPACE}*"([^"]*)"'
)
_LASTSEP_RE = re.compile(
    f'{js_ci_ascii("lastsep")}{JS_SPACE}*={JS_SPACE}*"([^"]*)"'
)


def parse_template(src: str) -> ParsedAst:
    """Parse a full template: strip comments, extract directives, build the tree."""
    # Comments are stripped WITHOUT the offset map `_source.read` builds. That map exists
    # so the validator can point a diagnostic at the author's text; the parser feeds a
    # renderer, which must emit the author's bytes — including line terminators the
    # scanning view normalises away.
    stripped = _source.COMMENT_RE.sub("", src)
    directives = _directives.extract(stripped)
    return ParsedAst(
        source=src,
        set_defs=directives.set_defs,
        def_defs=directives.def_defs,
        nodes=parse_sequence(directives.body),
        ast_version=AST_VERSION,
    )


@dataclass(slots=True)
class _Scan:
    """A half-finished scan of one run of text. Resumable, which is the whole point."""

    text: str
    out: list[Node]
    i: int = 0
    literal: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Assemble:
    """Build one construct once its children are parsed, and hand it to the parent."""

    out: list[Node]
    parts: list[list[Node]]
    build: Callable[[list[list[Node]]], Node]


def parse_sequence(text: str) -> tuple[Node, ...]:
    """Parse a run of text into a node sequence — constructs only.

    No comment stripping and no directive extraction, because the renderer calls this on
    the *value* of a variable it has just substituted. A `#set` inside such a value is
    already gone by then; running the pre-passes again here would be a second, different
    parse of the same text.

    **Iterative, over an explicit stack, and that is not a stylistic preference.** The
    recursive form this replaced died with `RecursionError` at about 350 levels of
    nesting — a 701-character template — because each level costs three Python frames.
    The reference parses 1000 levels of the same input happily. Nothing bounds nesting
    before this point: `max_depth` reads like a parse guard and is not one, it is checked
    only against the `#include` stack, so ordinary string input reaches here at whatever
    depth it likes.

    The scan of any single run of text is flat; only construct *bodies* need more work.
    So a construct pushes: this scan (to resume after the closing bracket), an assemble
    step, then one scan per child. LIFO order means the children run first, the assemble
    step appends the finished node, and the parent then resumes — leaving nodes in the
    order they were written.
    """
    root: list[Node] = []
    stack: list[_Scan | _Assemble] = [_Scan(text=text, out=root)]

    while stack:
        job = stack.pop()

        if isinstance(job, _Assemble):
            job.out.append(job.build(job.parts))
            continue

        suspended = False
        while job.i < len(job.text):
            ch = job.text[job.i]

            if ch in "{[":
                close = "}" if ch == "{" else "]"
                end = find_matching_close(job.text, job.i, ch, close)
                if end == -1:
                    job.literal.append(ch)
                    job.i += 1
                    continue

                _flush(job)
                inner = job.text[job.i + 1 : end]
                children, build = (
                    _plan_brace_construct(inner) if ch == "{" else _plan_permutation(inner)
                )
                job.i = end + 1

                parts: list[list[Node]] = [[] for _ in children]
                stack.append(job)
                stack.append(_Assemble(out=job.out, parts=parts, build=build))
                for child_text, child_out in reversed(list(zip(children, parts, strict=True))):
                    stack.append(_Scan(text=child_text, out=child_out))
                suspended = True
                break

            if ch == "%":
                m = _VARIABLE_RE.match(job.text, job.i)
                if m is not None:
                    _flush(job)
                    job.out.append(VariableNode(name=m.group(1)))
                    job.i = m.end()
                    continue

            job.literal.append(ch)
            job.i += 1

        if not suspended:
            _flush(job)

    return tuple(root)


def _flush(job: _Scan) -> None:
    if job.literal:
        job.out.append(LiteralNode(value="".join(job.literal)))
        job.literal.clear()


#: What a construct hands back to the scanner: the child texts still to be parsed, and a
#: function turning their finished node lists into the node itself. Splitting planning
#: from building is what keeps the descent on the heap instead of the call stack.
_Plan = tuple[list[str], Callable[[list[list[Node]]], Node]]


def _plan_brace_construct(content: str) -> _Plan:
    """Decide what a `{…}` is: conditional, plural, or — by default — an enumeration."""
    if content.startswith("?"):
        conditional = _plan_conditional(content)
        if conditional is not None:
            return conditional
        # Malformed conditional falls through to enumeration, matching the plugin, where
        # a bad `{?…}` survives the conditional pass and the enumeration pass then eats it.
    elif content.startswith(_PLURAL_PREFIX) and ":" in content[len(_PLURAL_PREFIX) :]:
        return _plan_plural(content[len(_PLURAL_PREFIX) :])

    def build(parts: list[list[Node]]) -> Node:
        return EnumerationNode(options=tuple(tuple(p) for p in parts))

    return split_top_level(content), build


def _plan_conditional(content: str) -> _Plan | None:
    """Plan `?VAR?then|else` / `?!VAR?then`, or `None` when malformed."""
    p = 1  # past the leading '?'
    inverted = content[p : p + 1] == "!"
    if inverted:
        p += 1

    m = _CONDITIONAL_NAME_RE.match(content, p)
    if m is None:
        return None
    name = m.group()
    p = m.end()

    if content[p : p + 1] != "?":  # the '?' after the name is required
        return None
    p += 1

    body = content[p:]
    sep = _first_top_level_pipe(body)
    then_raw = body if sep < 0 else body[:sep]
    else_raw = "" if sep < 0 else body[sep + 1 :]

    def build(parts: list[list[Node]]) -> Node:
        return ConditionalNode(
            name=name,
            inverted=inverted,
            then=tuple(parts[0]),
            otherwise=tuple(parts[1]),
        )

    return [then_raw, else_raw], build


def _plan_plural(after_prefix: str) -> _Plan:
    """A plural has no children — both slots stay raw for the renderer to expand."""
    node = _parse_plural(after_prefix)

    def build(_parts: list[list[Node]]) -> Node:
        return node

    return [], build


def _parse_plural(after_prefix: str) -> Node:
    """Split `<count>: forms` on the first colon, keeping both halves raw.

    Raw because either may hold a `%var%`, and the renderer expands variables in them
    before splitting the forms.
    """
    colon = after_prefix.index(":")
    return PluralNode(count_raw=after_prefix[:colon], forms_raw=after_prefix[colon + 1 :])


# ── permutations ──────────────────────────────────────────────────────────────


def _default_perm_config() -> PermConfig:
    return PermConfig(minsize=None, maxsize=None, sep=" ", lastsep=None)


def _plan_permutation(raw_inner: str) -> _Plan:
    config, content = _extract_permutation_config(raw_inner)
    elements = _extract_per_element_separators(split_top_level(content))
    separators = [sep for _text, sep in elements]

    def build(parts: list[list[Node]]) -> Node:
        return PermutationNode(
            config=config,
            options=tuple(
                PermOption(nodes=tuple(nodes), separator=sep)
                for nodes, sep in zip(parts, separators, strict=True)
            ),
        )

    return [text for text, _sep in elements], build


def _extract_permutation_config(content: str) -> tuple[PermConfig, str]:
    """Split a leading `<config>` off the body.

    Runs BEFORE the top-level split, which is the whole point: a `|` inside a quoted
    separator (`sep="|"`) would otherwise be read as an option boundary.
    """
    trimmed = content.lstrip(PHP_TRIM_CHARS)
    if not trimmed.startswith("<"):
        return _default_perm_config(), content

    end = _find_config_end(trimmed)
    if end == -1:
        return _default_perm_config(), content

    config_str = trimmed[1:end]
    remaining = trimmed[end + 1 :]
    if _looks_like_html_start_tag(config_str, remaining):
        return _default_perm_config(), content
    return _parse_config_string(config_str), remaining


def _find_config_end(text: str) -> int:
    """Index of the `>` closing a `<…>` config, ignoring one inside quotes; -1 if none."""
    in_quote = False
    for i in range(1, len(text)):
        ch = text[i]
        if ch == '"':
            in_quote = not in_quote
        if ch == ">" and not in_quote:
            return i
    return -1


def _parse_config_string(text: str) -> PermConfig:
    if not _CONFIG_KEY_RE.search(text):
        # No recognised key: the single-separator form, where the whole string is the
        # separator and doubles as the last separator.
        return PermConfig(minsize=None, maxsize=None, sep=text, lastsep=text)

    minsize = _MINSIZE_RE.search(text)
    maxsize = _MAXSIZE_RE.search(text)
    sep = _SEP_RE.search(text)
    lastsep = _LASTSEP_RE.search(text)
    return PermConfig(
        minsize=int(minsize.group(1)) if minsize else None,
        maxsize=int(maxsize.group(1)) if maxsize else None,
        sep=sep.group(1) if sep else " ",
        lastsep=lastsep.group(1) if lastsep else None,
    )


def _looks_like_html_start_tag(tag_text: str, remaining: str) -> bool:
    """Is this `<…>` an HTML tag rather than permutation config?

    A `<li>` opening a list must not be eaten as a separator declaration. Self-closing
    tags count on sight; a plain tag counts only when its closing tag appears later.
    """
    trimmed = tag_text.strip(PHP_TRIM_CHARS)
    if trimmed == "":
        return False
    m = _HTML_TAG_RE.match(trimmed)
    if m is None:
        return False
    if trimmed.endswith("/"):
        return True
    tag_name = (m.group(1) or "").lower()
    closing = re.compile(f"</{js_ci_unicode(re.escape(tag_name))}{JS_SPACE}*>", re.IGNORECASE)
    return closing.search(remaining) is not None


def _extract_per_element_separators(raw_parts: list[str]) -> list[tuple[str, str | None]]:
    """Attach each trailing `<sep>` to the element that FOLLOWS it.

    A separator is written after the element it comes behind, so `a<, >b` means "join a
    and b with ', '" — the separator found on part *i* belongs to element *i+1*. Empty
    elements drop out entirely.

    Returns unparsed element text rather than nodes, so the caller can hand the texts to
    the scanner's stack instead of recursing into them here.
    """
    elements: list[tuple[str, str | None]] = []
    pending_sep: str | None = None

    for i, part in enumerate(raw_parts):
        text = part
        trailing_sep: str | None = None
        if i < len(raw_parts) - 1:
            extracted = _extract_trailing_sep(part)
            if extracted is not None:
                text, trailing_sep = extracted

        trimmed = text.strip(PHP_TRIM_CHARS)
        if trimmed != "":
            elements.append((trimmed, pending_sep))
        pending_sep = trailing_sep

    return elements


def _extract_trailing_sep(part: str) -> tuple[str, str] | None:
    """Pull a trailing `<sep>` off a part, or `None` if there is not one.

    Returns `None` for anything that looks like HTML — a closing tag, a self-closing tag,
    or a tag with attributes — so markup in a permutation survives intact.
    """
    trimmed = part.rstrip(PHP_TRIM_CHARS)
    if not trimmed.endswith(">"):
        return None

    open_pos = -1
    for i in range(len(trimmed) - 2, -1, -1):
        ch = trimmed[i]
        if ch == "<":
            open_pos = i
            break
        if ch == ">":
            return None  # nested or complex; leave it alone
    if open_pos == -1:
        return None

    inner = trimmed[open_pos + 1 : len(trimmed) - 1]
    inner_trimmed = inner.strip(PHP_TRIM_CHARS)
    if (
        inner_trimmed.startswith("/")
        or inner_trimmed.endswith("/")
        or _PER_ELEM_HTML_RE.match(inner_trimmed)
    ):
        return None
    return trimmed[:open_pos], inner


# ── shared scanning helpers ───────────────────────────────────────────────────


def find_matching_close(text: str, open_pos: int, open_ch: str, close_ch: str) -> int:
    """Index of the `close_ch` matching the `open_ch` at `open_pos`, or -1.

    Tracks only this bracket pair's depth, so a `]` inside `{…}` is invisible here.
    """
    depth = 0
    for i in range(open_pos, len(text)):
        ch = text[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_top_level(inner: str) -> list[str]:
    """Split on `|` at nesting depth zero.

    Brace and bracket depths are tracked INDEPENDENTLY and decremented UNCONDITIONALLY,
    so either may go negative, and a split happens only when both are exactly zero. The
    consequence is deliberate: in `a]|b` the stray `]` drives the bracket depth to -1, the
    pipe is therefore not top level, and the whole thing stays one option.

    Not interchangeable with `_first_top_level_pipe` — see its docstring.
    """
    parts: list[str] = []
    brace = 0
    bracket = 0
    current: list[str] = []

    for ch in inner:
        if ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket -= 1

        if ch == "|" and brace == 0 and bracket == 0:
            parts.append("".join(current))
            current.clear()
        else:
            current.append(ch)

    parts.append("".join(current))
    return parts


def _first_top_level_pipe(body: str) -> int:
    """Index of the first `|` at depth zero in a conditional body, or -1.

    **A different algorithm from `split_top_level`, on purpose.** This uses ONE counter
    covering both bracket kinds, CLAMPED at zero, mirroring the plugin's conditional
    split. So a stray `]` cannot push the count negative and suppress a later pipe the
    way it does in an enumeration. The two look like they should be one function and are
    not; unifying them would change what `{?V?a]|b}` means.
    """
    depth = 0
    for j, ch in enumerate(body):
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            if depth > 0:
                depth -= 1
        elif ch == "|" and depth == 0:
            return j
    return -1
