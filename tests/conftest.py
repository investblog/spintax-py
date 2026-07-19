"""Locate the shared golden corpus.

The fixtures live in `spintax-js` and are **never vendored here** — a copy would
drift, and a drifting contract is not a contract (spec §6 Q4). They are read from
a checkout: `SPINTAX_FIXTURES` locally, `actions/checkout` in CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FIXTURES_ENV = "SPINTAX_FIXTURES"

# Tried in order when the env var is unset. Both are conveniences for a dev box;
# CI always sets the env var explicitly.
_FALLBACKS = (
    Path(__file__).resolve().parents[2] / "spintax-js" / "packages" / "conformance" / "fixtures",
    Path(__file__).resolve().parents[1] / ".corpus" / "packages" / "conformance" / "fixtures",
)

_HOWTO = (
    f"Point {FIXTURES_ENV} at a checkout of the corpus, e.g.\n"
    f"  {FIXTURES_ENV}=/path/to/spintax-js/packages/conformance/fixtures pytest\n"
    "or clone it next to this repo:\n"
    "  git clone https://github.com/investblog/spintax-js ../spintax-js"
)


def corpus_dir() -> Path | None:
    """The fixtures directory, or None when it cannot be found."""
    env = os.environ.get(FIXTURES_ENV)
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    for p in _FALLBACKS:
        if p.is_dir():
            return p
    return None


def corpus_help() -> str:
    return _HOWTO


def load_cases() -> list[dict[str, Any]]:
    """Every case in the corpus, in file then declaration order."""
    d = corpus_dir()
    if d is None:
        return []
    cases: list[dict[str, Any]] = []
    for f in sorted(d.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for case in data:
            case["_file"] = f.name
            cases.append(case)
    return cases
