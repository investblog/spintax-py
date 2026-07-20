"""The choice source, and the seam that makes `#set` distinguishable from `#def`.

Signature is `(min, max) -> int`, inclusive — a bounded integer, **not** a choice index,
mirroring the injectable `$random_fn` the plugin exposes. Keeping it a parameter of
`render_with` is what lets the corpus fix a draw *sequence* and observe how many draws a
template takes: with a constant strategy, a macro re-rolled at every reference and a
value rolled once produce identical output, and the distinction is untestable.

**Cross-engine sequence parity is a deliberate non-goal (spec §3.2).** The reference uses
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

import random
from collections.abc import Callable

#: An injected source of choice: `(min, max) -> int`, inclusive at both ends.
Rng = Callable[[int, int], int]


def make_rng(seed: int | str | None) -> Rng:
    """Build a choice source. `None` means unseeded — a fresh sequence per call.

    A string seed is accepted directly: `random.Random` hashes it with SHA-512, which is
    stable across runs and interpreters, unlike the built-in `hash()` that
    `PYTHONHASHSEED` randomizes.
    """
    source = random.Random(seed) if seed is not None else random.Random()

    def rng(minimum: int, maximum: int) -> int:
        return minimum + int(source.random() * (maximum - minimum + 1))

    return rng
