"""Locale plural rules and `{plural …}` block scanning.

Shared by the validator's arity check now and by the renderer's bucket pick at P2,
so it lives on its own rather than inside either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PREFIX = "{plural "

#: The three-form family: East Slavic plus BCS, which reuses the same integer rule
#: character for character. CLDR names BCS's third bucket "other" rather than "many";
#: positionally it is the same slot, so a template written for Russian arity works.
_THREE_FORM = frozenset({"ru", "uk", "be", "sr", "hr", "bs"})

_TAG_SPLIT_RE = re.compile(r"[-_]")


@dataclass(frozen=True, slots=True)
class Block:
    start: int
    end: int  # exclusive — one past the closing `}`
    count_slot: str
    forms_raw: str


def find_blocks(text: str) -> list[Block]:
    """Brace-aware scan for `{plural …}` over the raw text.

    Raw, not AST-based, so it also finds blocks nested inside a `[…]` permutation —
    which the tree leaves unparsed. A block with no `:` is not a plural at all; it
    falls through to the enumeration path.
    """
    blocks: list[Block] = []
    i = 0
    while i < len(text):
        start = text.find(PREFIX, i)
        if start == -1:
            break

        depth = 1
        j = start + len(PREFIX)
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1

        if depth != 0:  # never closed — skip past the prefix and keep looking
            i = start + len(PREFIX)
            continue

        inner = text[start + len(PREFIX) : j]
        colon = inner.find(":")
        if colon == -1:
            i = j + 1
            continue

        blocks.append(
            Block(start=start, end=j + 1, count_slot=inner[:colon], forms_raw=inner[colon + 1 :])
        )
        i = j + 1
    return blocks


def normalize_base_lang(locale: str) -> str:
    """`pt-BR` → `pt`, `uk_UA` → `uk`, `RU` → `ru`.

    Script and region subtags carry no plural grammar, so `sr-Latn` and `sr_RS` both
    reduce to `sr`. Three-letter tags are deliberately not mapped: `srp` stays `srp`
    and falls to the two-form default.
    """
    return _TAG_SPLIT_RE.split(locale.lower(), 1)[0]


def arity(base_lang: str) -> int:
    """How many forms a locale expects: 3 for the Slavic family, 2 for everything else.

    Everything else includes `pl`, `cs`, `sk`, `sl` and `bg`, whose real grammars are
    not implemented — they are bucketed by the English rule rather than rejected.
    """
    return 3 if base_lang in _THREE_FORM else 2
