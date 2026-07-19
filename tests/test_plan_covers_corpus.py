"""The P1 plan must name every diagnostic code the corpus expects.

This exists because the plan silently under-covered the corpus: it claimed 17
codes and its steps enumerated 15, having dropped `plural.nested-brackets` and
`include.unknown-target`. Following it to the letter would have produced a
finished-looking P1 that could not reach its own definition of done — and the
error was in prose, so nothing would have failed.

Counting by hand is what broke; this counts from the fixtures. It also fails when
upstream *adds* a code, which is the more valuable direction: a new cross-engine
diagnostic should reach the plan before it reaches the implementation.

Retire this once P1 is done — from then on the corpus itself is the gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import corpus_dir, load_cases

PLAN = Path(__file__).resolve().parents[1] / "docs" / "plan-p1.md"


def _expected_codes() -> set[str]:
    return {
        d["code"]
        for c in load_cases()
        if c.get("op") == "validate"
        for d in c.get("expect", {}).get("diagnostics", [])
    }


def _counted_steps(plan: str) -> list[str]:
    """The `### … — N codes` sections. A code owned by no such step is unscheduled."""
    return [s for s in re.split(r"^### ", plan, flags=re.M)[1:] if re.search(r"—\s*\d+\s*codes?", s)]


def test_every_diagnostic_code_is_owned_by_a_counted_step() -> None:
    """Not merely *mentioned* somewhere in the plan — owned by a step that schedules it.

    The first version of this test searched the whole document, which is weaker than
    the promise it makes: a new code named in a TODO or in passing prose would satisfy
    it while no step had agreed to implement it, and the definition of done would still
    be unreachable.
    """
    if corpus_dir() is None:
        pytest.skip("corpus absent; test_corpus_is_present reports it")
    plan = PLAN.read_text(encoding="utf-8")
    owned = {code for step in _counted_steps(plan) for code in _expected_codes() if f"`{code}`" in step}
    missing = sorted(_expected_codes() - owned)
    assert not missing, (
        f"no counted step in {PLAN.name} owns: {', '.join(missing)}. "
        "Mentioning a code is not scheduling it."
    )


def test_plan_step_counts_match_the_codes_they_list() -> None:
    """A step heading says "— N codes"; N must equal the backticked codes under it.

    The heading and the list drifted apart once already ("7 codes" over eight of
    them). Prose that counts itself is worth checking mechanically.
    """
    if corpus_dir() is None:
        pytest.skip("corpus absent; test_corpus_is_present reports it")
    plan = PLAN.read_text(encoding="utf-8")
    known = _expected_codes()

    sections = re.split(r"^### ", plan, flags=re.M)[1:]
    checked = 0
    for section in sections:
        heading, _, _body = section.partition("\n")
        m = re.search(r"—\s*(\d+)\s*codes?", heading)
        if not m:
            continue
        claimed = int(m.group(1))
        # The whole step, heading included: a one-code step names it in the title
        # and never repeats it below, which is fine prose and would read as zero.
        found = {c for c in known if f"`{c}`" in section}
        assert claimed == len(found), (
            f"step {heading.strip()!r} claims {claimed} codes "
            f"but lists {len(found)}: {sorted(found)}"
        )
        checked += 1
    assert checked >= 4, f"only {checked} counted steps found — did the plan's shape change?"
