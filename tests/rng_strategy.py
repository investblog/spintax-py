"""Build the injected RNG for a fixture's `rng` strategy.

Mirrors the TS harness (`packages/core/test/corpus-harness.ts`), which in turn
mirrors the plugin's make_first / make_last / make_sequence: a raw value clamped
to [min, max], with the last value reused once the sequence is exhausted.

Why this matters more than it looks: the number of draws a template takes is the
*only* observable difference between `#set` (a macro — re-rolled at every
reference) and `#def` (rolled once and held). Under a fixed `first` strategy both
render identically. A template like `{a|a|a}` is worthless for the same reason.
So the sequence strategy is not a convenience here, it is the discriminator.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Rng = Callable[[int, int], int]


def rng_from_strategy(strategy: Any) -> Rng:
    """`"first"` | `"last"` | `{"sequence": [...]}` → an `(min, max) -> int`."""
    if strategy == "first":
        return lambda lo, _hi: lo
    if strategy == "last":
        return lambda _lo, hi: hi

    seq: list[int] = list(strategy["sequence"])
    state = {"i": 0}

    def _seq(lo: int, hi: int) -> int:
        raw = seq[min(state["i"], len(seq) - 1)] if seq else lo
        state["i"] += 1
        return max(lo, min(hi, raw))

    return _seq
