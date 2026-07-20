"""Shielding must be a round trip, and the reserved range must stay the engine's.

The corpus covers this through the renderer, which means these two properties are only
observed there in combination with everything else. Pinned here so a break points at the
shield rather than at whatever render stage happened to notice.

Sentinels are built with `chr()` rather than written literally. A Private-Use-Area code
point in source is invisible in a diff, easy for an editor to eat, and — found the hard
way while writing this file — silently rewritten by tooling that normalises escapes.
"""

from __future__ import annotations

import pytest

from spintax_core import _neutralize

STRUCTURAL = "{}[]%#"
FIRST_SENTINEL = chr(0xE000)  # the shield for "{"


@pytest.mark.parametrize("ch", list(STRUCTURAL))
def test_every_structural_character_survives_the_round_trip(ch: str) -> None:
    """Shield then restore is identity. A missing pair in either map loses a character
    or, worse, restores it as the wrong one."""
    assert _neutralize.safety_restore(_neutralize.neutralize(ch)) == ch


def test_shielded_text_holds_no_structural_characters() -> None:
    """The whole point: after shielding there is nothing left for a later pass to read
    as markup. If one character escaped the map, a hostile value could still spin."""
    shielded = _neutralize.neutralize("{a|b} [c] %v% #set")
    assert not any(c in shielded for c in STRUCTURAL)


def test_plain_text_is_untouched() -> None:
    assert _neutralize.neutralize("nothing structural here") == "nothing structural here"


def test_an_author_typed_sentinel_is_stripped() -> None:
    """The reserved range belongs to the engine.

    The second assertion states the stakes: left in place, a sentinel the author pasted
    becomes a brace they never wrote, and a later pass is free to read it as markup.
    Stripping is what makes `neutralize` the only door into the stream.
    """
    pasted = f"a{FIRST_SENTINEL}b"
    assert _neutralize.strip_sentinels(pasted) == "ab"
    assert _neutralize.safety_restore(pasted) == "a{b"


def test_the_two_shielding_schemes_do_not_share_a_range() -> None:
    """Post-process shields with `\\x00…`; this uses the Private Use Area. Were they to
    overlap, one pass would restore the other's markers."""
    shielded = _neutralize.neutralize(STRUCTURAL)
    assert all(0xE000 <= ord(c) <= 0xE005 for c in shielded)
