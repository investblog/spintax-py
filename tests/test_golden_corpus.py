"""The golden corpus — the cross-engine contract, run against this engine.

This suite *is* the corpus, not a replica of it: the same JSON files the TypeScript
and PHP engines are tested against. If a case goes red here, the engines have
diverged, and that is the point.

Reading it while the engine is empty: every case reports **xfail**, because the
API raises NotImplementedError. That is the P0 goal — a visible count of what is
not built yet. As milestones land, cases flip to real passes with no change to
this file. Nothing is ever silently skipped: a missing corpus fails loudly, and
cases excluded by `engines` are reported as skips with a reason.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import corpus_dir, corpus_help, load_cases
from rng_strategy import rng_from_strategy

import spintax_core as engine

_CASES = load_cases()


def _ids(cases: list[dict[str, Any]]) -> list[str]:
    return [c.get("id", f"{c.get('_file')}#{i}") for i, c in enumerate(cases)]


def test_corpus_is_present() -> None:
    """A missing corpus must fail the run, never quietly empty it.

    Without this the suite would report "0 tests, all good" on a machine where the
    fixtures are absent — the most expensive kind of green.
    """
    assert corpus_dir() is not None, f"golden corpus not found.\n{corpus_help()}"
    assert _CASES, f"corpus directory found but no cases loaded.\n{corpus_help()}"


def test_corpus_size_is_sane() -> None:
    """Guard against the corpus silently shrinking to a handful of cases.

    Deliberately a floor, not an equality: upstream adds fixtures often, and a
    suite that breaks on every addition trains people to edit the number.
    """
    if corpus_dir() is None:
        pytest.skip("corpus absent; test_corpus_is_present reports it")
    assert len(_CASES) >= 150, f"only {len(_CASES)} cases loaded — corpus looks truncated"


# ── the engine's own opinion of each case ──────────────────────────────────


def _render_opts(case: dict[str, Any]) -> dict[str, Any]:
    """The pipeline options a fixture carries. Deliberately NOT seed — a deterministic
    case is fixed by its `rng` strategy, not by seeding a real PRNG."""
    context = dict(case.get("context") or {})
    for key in case.get("neutralizeContext") or []:
        if key in context:
            context[key] = engine.neutralize(context[key])
    opts: dict[str, Any] = {}
    if context:
        opts["context"] = context
    if case.get("locale") is not None:
        opts["locale"] = case["locale"]
    if case.get("postProcess") is not None:
        opts["post_process"] = case["postProcess"]
    return opts


def _render(case: dict[str, Any]) -> str:
    """Render through the engine's own pipeline with the fixture's choice source.

    An omitted `rng` defaults to `"first"`, matching the reference harness. That is
    only sound because such fixtures do not select — single option, or a
    non-selecting plural/conditional/variable. A real PRNG here would make every
    deterministic fixture a coin flip.
    """
    if case.get("kind") == "rng":
        rng = engine.make_rng(case.get("seed"))
    else:
        rng = rng_from_strategy(case.get("rng") or "first")
    return engine.render_with(case["template"], rng, **_render_opts(case))


def _run(case: dict[str, Any]) -> Any:
    """Dispatch one case to the engine. Raises NotImplementedError while empty."""
    op = case["op"]
    if op == "validate":
        return engine.validate(
            case["template"],
            locale=case.get("locale"),
            known_includes=case.get("knownIncludes"),
        )
    if op == "extract":
        return engine.extract(case["template"])
    if op == "neutralize":
        return engine.neutralize(case["template"])
    if op == "render":
        return _render(case)
    raise AssertionError(f"unknown op {op!r} in case {case['id']!r}")


def _assert_validate(case: dict[str, Any], actual: list[engine.Diagnostic]) -> None:
    expect = case["expect"]
    errors = [d for d in actual if d.severity == "error"]
    verdict = "invalid" if errors else "valid"
    assert verdict == expect["verdict"], f"verdict {verdict!r}, diagnostics={actual!r}"

    # Expected diagnostics are a subset check on the asserted fields only: `code` is
    # parity-gated, wording is not, and position is asserted only when the fixture
    # bothers to state it.
    for want in expect.get("diagnostics", []):
        matched = any(
            d.code == want["code"]
            and ("severity" not in want or d.severity == want["severity"])
            and ("line" not in want or d.line == want["line"])
            and ("column" not in want or d.column == want["column"])
            for d in actual
        )
        assert matched, f"no diagnostic matching {want!r}; got {[d.code for d in actual]}"


def _assert_extract(case: dict[str, Any], actual: engine.Extraction) -> None:
    # Order-normalized, and only the keys the fixture states are compared — the
    # corpus predates `defs`, so a strict whole-object equality would be wrong.
    for key in ("refs", "sets", "includes"):
        if key in case["expect"]:
            assert sorted(getattr(actual, key)) == sorted(case["expect"][key]), key


def _assert_rng(case: dict[str, Any], actual: str) -> None:
    expect = case["expect"]

    # `reproducible` is the only promise here, and it is within-engine: a fresh RNG
    # from the same seed must reproduce the output. Never an exact cross-engine gate.
    assert actual == _render(case), "same seed produced different output"

    if "oneOf" in expect:
        assert actual in expect["oneOf"], f"{actual!r} not in {expect['oneOf']!r}"
    if "subsetOf" in expect or "sizeRange" in expect:
        sep = expect.get("separator", " ")
        tokens = [] if actual == "" else actual.split(sep)
        if "subsetOf" in expect:
            assert set(tokens) <= set(expect["subsetOf"]), f"{tokens!r} not drawn from set"
            # A permutation draws WITHOUT replacement, so tokens are distinct. Together
            # with subsetOf + an exhaustive sizeRange this is what rejects a broken
            # shuffle that repeats or drops an element ("a a a" passes subsetOf alone).
            assert len(set(tokens)) == len(tokens), f"repeated element in {tokens!r}"
        if "sizeRange" in expect:
            lo, hi = expect["sizeRange"]
            assert lo <= len(tokens) <= hi, f"{len(tokens)} elements, expected {lo}..{hi}"


@pytest.mark.parametrize("case", _CASES, ids=_ids(_CASES))
def test_corpus_case(case: dict[str, Any]) -> None:
    # `engines` names the engines that assert a case; absent means all of them.
    # The schema's enum is ["ts", "php"] — there is no "py" yet — so any explicit
    # list excludes this engine. Reported as a skip with a reason, never dropped.
    engines = case.get("engines")
    if engines is not None:
        pytest.skip(f"case is asserted by {engines} only")

    try:
        actual = _run(case)
    except NotImplementedError as exc:
        pytest.xfail(str(exc))

    op, expect = case["op"], case["expect"]
    if op == "validate":
        _assert_validate(case, actual)
    elif op == "extract":
        _assert_extract(case, actual)
    elif case.get("kind") == "rng":
        _assert_rng(case, actual)
    else:
        assert actual == expect["output"]
