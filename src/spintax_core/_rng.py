"""The choice source, and the seam that makes `#set` distinguishable from `#def`.

Signature is `(min, max) -> int`, inclusive — a bounded integer, **not** a choice index,
mirroring the injectable `$random_fn` the plugin exposes. Keeping it a parameter of
`render_with` is what lets the corpus fix a draw *sequence* and observe how many draws a
template takes: with a constant strategy, a macro re-rolled at every reference and a
value rolled once produce identical output, and the distinction is untestable.

**The engine short-circuits `min == max` before it ever gets here** — see `randomInt` in
the reference's `render.ts`, and note that its `makeRng` does not short-circuit either.
That belongs in this docstring because the renderer is where it bites: a default-config
permutation clamps its size pick to `min == max`, so the reference spends ZERO draws on
it. A Python renderer that calls `rng(2, 2)` anyway consumes a draw and shifts every
later one, which breaks `def/rolled-once-covers-permutations` and
`set/macro-re-shuffles-a-permutation` — the only pair in the corpus that tells `#set`
from `#def` for permutations — and collapses them to the same output. The failure reads
as a shuffle-order bug and is a draw-count bug.

**Cross-engine sequence parity is a deliberate non-goal (spec §3).** The reference uses
mulberry32 over an FNV-1a hash of the seed, which would port in about fifteen lines of
masked 32-bit arithmetic and would make a seeded render byte-identical to TypeScript
today. It is not ported on purpose: because the shared spec does not promise it, the
reference is free to change its PRNG in a patch release, and matching it here would
manufacture a promise nobody upstream has made. Users would come to depend on identical
output and an upstream change we neither control nor hear about would break them.

What IS promised: determinism *within this engine* — the same seed yields the same output,
stably across Python versions. That rests on `random.Random.random()`, whose sequence
Python guarantees not to change; the bounded draw is computed here rather than delegated
to `randint`, so the guarantee covers the whole path.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

#: An injected source of choice: `(min, max) -> int`, inclusive at both ends.
Rng = Callable[[int, int], int]


def make_rng(seed: int | str | None) -> Rng:
    """Build a choice source. `None` means unseeded — a fresh sequence per call.

    A string seed is accepted directly: `random.Random` hashes it with SHA-512, which is
    stable across runs and interpreters, unlike the built-in `hash()` that
    `PYTHONHASHSEED` randomizes. `version=2` is passed explicitly rather than left to the
    default — the default is what a future Python is free to change, and the promise made
    above is that a seed keeps meaning the same thing.

    Each call returns its OWN generator. Reaching for the module-level `random` would
    work in every test and then corrupt a host that renders two templates concurrently,
    because both would be drawing from one shared stream.
    """
    source = random.Random()
    if seed is not None:
        source.seed(seed, version=2)

    def rng(minimum: int, maximum: int) -> int:
        # `math.floor`, not `int`: they agree for every range the engine produces, and
        # disagree when `minimum > maximum` because `int` truncates toward zero while
        # JavaScript's `Math.floor` rounds down. `Rng` is a public injectable seam, so a
        # caller can reach that case even though the renderer's own clamping cannot.
        return minimum + math.floor(source.random() * (maximum - minimum + 1))

    return rng
