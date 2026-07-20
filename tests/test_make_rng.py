"""`make_rng` promises determinism within this engine, and an inclusive range.

The range half is the one with teeth. `rng(min, max)` is inclusive at both ends, and the
engine turns its result straight into an option index — so an off-by-one that makes `max`
unreachable does not crash anything. It silently stops the last option of every
enumeration from ever being chosen, and every fixture using a `first` strategy still
passes. Only a test that reaches for the boundary finds it.

The determinism half is narrower than it looks: same seed, same output, *within this
engine*. Cross-engine sequence parity is a deliberate non-goal (spec §3), so nothing
here compares against TypeScript.
"""

from __future__ import annotations

import random

import pytest

from spintax_core import make_rng


def _draws(seed: int | str | None, count: int = 40) -> list[int]:
    rng = make_rng(seed)
    return [rng(0, 9) for _ in range(count)]


def test_the_same_seed_gives_the_same_sequence() -> None:
    assert _draws(1234) == _draws(1234)


def test_a_string_seed_is_accepted_and_stable() -> None:
    """Stable because `random.Random` hashes a string with SHA-512. The built-in `hash()`
    would not do: `PYTHONHASHSEED` randomises it per process, so a seeded render would
    differ between runs of the same program."""
    assert _draws("spintax") == _draws("spintax")


def test_different_seeds_diverge() -> None:
    """Not a statistical claim — just that the seed reaches the generator at all. A
    `make_rng` that ignored its argument would pass every test above this one."""
    assert _draws(1) != _draws(2)


def test_an_unseeded_rng_is_not_frozen() -> None:
    """`None` means unseeded. Two draws of forty from a real source colliding is about
    one in 10^40; a constant return would collide every time."""
    assert _draws(None) != _draws(None)


@pytest.mark.parametrize("bounds", [(0, 1), (0, 9), (3, 4), (-2, 2)])
def test_both_bounds_are_reachable(bounds: tuple[int, int]) -> None:
    """The off-by-one guard. `max` unreachable is invisible in output — it just quietly
    removes the last option of every enumeration from the running."""
    low, high = bounds
    rng = make_rng(7)
    seen = {rng(low, high) for _ in range(2000)}
    assert low in seen, f"never drew the lower bound {low}"
    assert high in seen, f"never drew the upper bound {high}"


def test_nothing_falls_outside_the_bounds() -> None:
    rng = make_rng(7)
    assert all(2 <= rng(2, 5) <= 5 for _ in range(2000))


def test_an_inverted_range_rounds_the_way_javascript_does() -> None:
    """`min > max` is misuse, and `Rng` is a public seam that a host can call directly.

    `int()` truncates toward zero; `Math.floor` rounds down. They agree everywhere the
    renderer can reach — the product is non-negative whenever `min <= max` — and diverge
    exactly here: `rng(5, 1)` draws from {2,3,4} in JavaScript and from {3,4,5} under
    `int()`. Cheap to match, so matched.
    """
    rng = make_rng(11)
    assert {rng(5, 1) for _ in range(500)} <= {2, 3, 4}
    assert {rng(2, 0) for _ in range(200)} == {1}


def test_each_handle_owns_its_stream() -> None:
    """Two handles from the same seed must agree, which they cannot if they share one.

    Without this, a `make_rng` built on the module-level `random` passes every other test
    in this file. It would also make two concurrent renders draw from one sequence, so
    each would see the other's draws — non-determinism that appears only under load and
    only in a host, never here.
    """
    first, second = make_rng(7), make_rng(7)
    assert [first(0, 999) for _ in range(10)] == [second(0, 999) for _ in range(10)]


def test_the_host_s_global_random_is_left_alone() -> None:
    """The other half of the same mistake: seeding the module-level generator would
    silently re-seed the host's own `random`, changing results in code that has nothing
    to do with this library."""
    random.seed(99)
    expected = random.random()

    random.seed(99)
    make_rng("anything")(0, 10)
    assert random.random() == expected


def test_a_single_point_range_returns_that_point() -> None:
    """The engine short-circuits `min == max` before calling the rng, so this is belt and
    braces — but a formula that returned `min + 1` here would corrupt the draw *count*,
    and draw count is the only thing distinguishing `#set` from `#def`."""
    rng = make_rng(7)
    assert all(rng(4, 4) == 4 for _ in range(50))
