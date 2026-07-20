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
    f"{NOT_AFTER_WORD}(?:minsize|maxsize|sep|lastsep){JS_SPACE}*=", re.IGNORECASE
)
_MINSIZE_RE = re.compile(f"minsize{JS_SPACE}*={JS_SPACE}*({ASCII_DIGIT}+)", re.IGNORECASE)
_MAXSIZE_RE = re.compile(f"maxsize{JS_SPACE}*={JS_SPACE}*({ASCII_DIGIT}+)", re.IGNORECASE)
#: The lookbehind is what keeps `lastsep="…"` from also matching as `sep`.
_SEP_RE = re.compile(f'(?<!last)sep{JS_SPACE}*={JS_SPACE}*"([^"]*)"', re.IGNORECASE)
_LASTSEP_RE = re.compile(f'lastsep{JS_SPACE}*={JS_SPACE}*"([^"]*)"', re.IGNORECASE)


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


def parse_sequence(text: str) -> tuple[Node, ...]:
    """Parse a run of text into a node sequence — constructs only.

    No comment stripping and no directive extraction, because the renderer calls this on
    the *value* of a variable it has just substituted. A `#set` inside such a value is
    already gone by then; running the pre-passes again here would be a second, different
    parse of the same text.
    """
    nodes: list[Node] = []
    literal: list[str] = []
    i = 0

    def flush() -> None:
        if literal:
            nodes.append(LiteralNode(value="".join(literal)))
            literal.clear()

    while i < len(text):
        ch = text[i]

        if ch == "{":
            end = find_matching_close(text, i, "{", "}")
            if end == -1:
                literal.append(ch)
                i += 1
                continue
            flush()
            nodes.append(_parse_brace_construct(text[i + 1 : end]))
            i = end + 1
            continue

        if ch == "[":
            end = find_matching_close(text, i, "[", "]")
            if end == -1:
                literal.append(ch)
                i += 1
                continue
            flush()
            nodes.append(_parse_permutation(text[i + 1 : end]))
            i = end + 1
            continue

        if ch == "%":
            m = _VARIABLE_RE.match(text, i)
            if m is not None:
                flush()
                nodes.append(VariableNode(name=m.group(1)))
                i = m.end()
                continue

        literal.append(ch)
        i += 1

    flush()
    return tuple(nodes)


def _parse_brace_construct(content: str) -> Node:
    """Decide what a `{…}` is: conditional, plural, or — by default — an enumeration."""
    if content.startswith("?"):
        conditional = _try_parse_conditional(content)
        if conditional is not None:
            return conditional
        # Malformed conditional falls through to enumeration, matching the plugin, where
        # a bad `{?…}` survives the conditional pass and the enumeration pass then eats it.
    elif content.startswith(_PLURAL_PREFIX) and ":" in content[len(_PLURAL_PREFIX) :]:
        return _parse_plural(content[len(_PLURAL_PREFIX) :])

    return EnumerationNode(
        options=tuple(parse_sequence(option) for option in split_top_level(content))
    )


def _try_parse_conditional(content: str) -> Node | None:
    """Parse `?VAR?then|else` / `?!VAR?then`, or `None` when malformed."""
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

    return ConditionalNode(
        name=name,
        inverted=inverted,
        then=parse_sequence(then_raw),
        otherwise=parse_sequence(else_raw),
    )


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


def _parse_permutation(raw_inner: str) -> Node:
    config, content = _extract_permutation_config(raw_inner)
    return PermutationNode(
        config=config, options=_extract_per_element_separators(split_top_level(content))
    )


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
    closing = re.compile(f"</{re.escape(tag_name)}{JS_SPACE}*>", re.IGNORECASE)
    return closing.search(remaining) is not None


def _extract_per_element_separators(raw_parts: list[str]) -> tuple[PermOption, ...]:
    """Attach each trailing `<sep>` to the element that FOLLOWS it.

    A separator is written after the element it comes behind, so `a<, >b` means "join a
    and b with ', '" — the separator found on part *i* belongs to element *i+1*. Empty
    elements drop out entirely.
    """
    options: list[PermOption] = []
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
            options.append(PermOption(nodes=parse_sequence(trimmed), separator=pending_sep))
        pending_sep = trailing_sep

    return tuple(options)


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
