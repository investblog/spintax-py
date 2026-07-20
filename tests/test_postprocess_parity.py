"""Post-process must produce byte-identical output to the reference.

The shared corpus samples this pass with 39 cases. It is a dozen interacting rules whose
ORDER matters — shield, collapse, space, capitalize, restore — and 39 samples of that is
not coverage, it is a spot check. Differential fuzzing against the reference found two
real divergences the fixtures did not:

- A mistranslated `\\b`. JavaScript's word boundary needs a TRANSITION, and translating it
  as "no word character before" finds boundaries that are not there whenever the next
  character is also non-word — which, since JavaScript's word set is ASCII, means every
  Cyrillic or accented letter. `приме.com` was shielded as a domain here and left alone by
  the reference, so the spacing and capitalization passes skipped text it rewrites. 64 of
  1922 cases.
- A broadened `\\p{Ll}`. Matching any letter and filtering for lowercase in the callback
  reads as equivalent and is not: the broadened match still CONSUMES its region, so
  reaching an uppercase letter through an HTML tag swallows a lowercase one further in
  that the narrow pattern would have capitalised. 1 of 1922 — and it was found only after
  that reasoning had been written down in a docstring as safe.

Neither would have been caught by a test written from reading this port. So the
reference's own answers are frozen instead. Regenerating is a deliberate act — see
`tests/data/generate_postprocess_parity.cjs`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from spintax_core import render_with

_FIXTURE = Path(__file__).resolve().parent / "data" / "postprocess_parity.json"
_DATA = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_CASES = _DATA["cases"]


def first(lo: int, _hi: int) -> int:
    return lo


@pytest.mark.parametrize("case", _CASES, ids=[f"{i:03d}" for i in range(len(_CASES))])
def test_post_process_matches_the_reference(case: dict[str, Any]) -> None:
    template = case["template"]
    assert render_with(template, first, post_process=True) == case["text"], (
        f"post-process differs from @spintax/core {_DATA['reference_version']} "
        f"for {template!r}"
    )


def test_the_fixture_records_which_engine_built_it() -> None:
    """A parity failure after a dependency bump should read as 'regenerate me', not as
    'the port broke'."""
    assert _DATA["reference_version"]
    assert len(_CASES) > 400, "corpus shrank — was the fixture regenerated from a stub?"
