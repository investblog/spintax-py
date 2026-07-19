"""The corpus RNG seam — the one part of the harness that is testable today.

The corpus suite cannot vouch for this while the engine is empty: every case
xfails before the RNG is ever consumed, so the run reports the same 160 whether
the seam is right or gibberish. These assertions are what actually hold it, and
they mirror the reference harness case for case
(`spintax-js/packages/core/test/smoke.test.ts`).

It earns the attention because the sequence strategy is the discriminator between
`#set` and `#def`: the semantics differ only in how many draws a template takes.
Get the exhaustion or clamping rule wrong and those fixtures start agreeing with
both semantics — passing, while testing nothing.
"""

from __future__ import annotations

from rng_strategy import rng_from_strategy


def test_first_returns_min_and_last_returns_max() -> None:
    assert rng_from_strategy("first")(0, 5) == 0
    assert rng_from_strategy("last")(0, 5) == 5


def test_sequence_clamps_and_reuses_the_last_value() -> None:
    rng = rng_from_strategy({"sequence": [1, 9]})
    assert rng(0, 2) == 1  # in range, returned as-is
    assert rng(0, 2) == 2  # 9 clamped to max
    assert rng(0, 2) == 2  # exhausted ⇒ last value reused, still clamped


def test_sequence_clamps_up_to_min() -> None:
    rng = rng_from_strategy({"sequence": [-4]})
    assert rng(2, 7) == 2


def test_each_strategy_call_yields_an_independent_cursor() -> None:
    """Two fixtures must not share sequence position.

    A module-level cursor would make case order significant — the kind of coupling
    that shows up as one fixture failing only when another runs first.
    """
    a = rng_from_strategy({"sequence": [0, 1]})
    b = rng_from_strategy({"sequence": [0, 1]})
    assert a(0, 1) == 0
    assert a(0, 1) == 1
    assert b(0, 1) == 0, "second strategy started mid-sequence"


def test_draw_count_is_what_separates_set_from_def() -> None:
    """Pin the property the corpus relies on, in isolation from the engine.

    `#set %x% = {a|b}` with `%x%` twice takes TWO draws (a macro re-rolls), while
    `#def` takes ONE and reuses the result. Under sequence [0, 1] that is exactly
    "a-b" versus "a-a" — so the fixtures discriminate only because draw two
    returns something different from draw one.
    """
    rng = rng_from_strategy({"sequence": [0, 1]})
    assert [rng(0, 1), rng(0, 1)] == [0, 1], "the two draws must differ, or the fixture proves nothing"
