"""T2 shielding — make data-derived text unable to act as markup (spec §6).

A host that interpolates untrusted data into a template has a problem the template
author cannot solve: a value containing `{a|b}` would be *rendered*, not printed. So
values pass through `neutralize`, which maps the six structural characters to
Private-Use-Area sentinels no pass in this engine treats as syntax, and the pipeline's
mandatory final stage maps them back to their literal glyphs.

Text-safe, **not** HTML-safe. `< > &` are untouched, so this is not XSS mitigation — an
HTML-entity variant is a host concern (§6). The name says what it defends against:
re-interpretation as spintax, nothing more.

PUA rather than the `\\x00…` scheme post-process uses, so the two shielding mechanisms
cannot collide with each other.

**U+E000–U+E005 are reserved.** Author markup is stripped of them on the way in, so only
`neutralize` can introduce one — otherwise `safety_restore` would rewrite a sentinel the
author typed. A raw (non-neutralized) context value carrying these code points is
therefore altered; hosts should neutralize or strip such data.
"""

from __future__ import annotations

import re

#: The characters that mean something to this engine: enumeration and permutation
#: brackets, the variable delimiter, and the directive marker.
STRUCTURAL = ("{", "}", "[", "]", "%", "#")
SENTINEL_BASE = 0xE000

_SHIELD = {ch: chr(SENTINEL_BASE + i) for i, ch in enumerate(STRUCTURAL)}
_RESTORE = {sentinel: ch for ch, sentinel in _SHIELD.items()}

_SHIELD_RE = re.compile(r"[{}\[\]%#]")
_RESTORE_RE = re.compile(f"[{chr(SENTINEL_BASE)}-{chr(SENTINEL_BASE + len(STRUCTURAL) - 1)}]")


def neutralize(value: str) -> str:
    """Shield data-derived (T2) input so it cannot be re-interpreted as spintax markup."""
    return _SHIELD_RE.sub(lambda m: _SHIELD[m.group()], value)


def safety_restore(text: str) -> str:
    """Mandatory final stage: put the shielded structural characters back as glyphs.

    Runs on **every** render, including `post_process=False` — it is a correctness step,
    not a cosmetic one. Skipping it would emit private-use code points to the caller.
    """
    return _RESTORE_RE.sub(lambda m: _RESTORE[m.group()], text)


def strip_sentinels(text: str) -> str:
    """Remove stray sentinels from author markup (template source and `#include` results).

    Without this, an author who pastes a U+E000 gets it silently turned into `{` by
    `safety_restore` — the engine would be rewriting text it never shielded.
    """
    return _RESTORE_RE.sub("", text)
