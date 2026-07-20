"""Variables, plurals and includes — with the emphasis on what the corpus cannot see.

The 40 corpus cases already pin the verdicts and codes. These add the surfaces no
fixture reaches: `known_variables` (the schema has no such field), diagnostic
positions (no fixture asserts one), and the *reason* the taint analysis is a fixed
point rather than a single pass — the corpus proves the outcome, not the mechanism,
so a one-pass implementation that happened to pass would look correct here too.
"""

from __future__ import annotations

import spintax_core as engine


def codes(src: str, **kw: object) -> list[str]:
    return [d.code for d in engine.validate(src, **kw)]  # type: ignore[arg-type]


# ── known_variables: implemented, ungated by the corpus ────────────────


def test_undefined_variable_is_a_warning_not_an_error() -> None:
    """It may well be supplied at render time, so it must not flip the verdict."""
    diags = engine.validate("Hello %runtime_name%!")
    assert [d.code for d in diags] == ["variable.undefined"]
    assert diags[0].severity == "warning"


def test_known_variables_suppresses_the_warning() -> None:
    assert codes("Hello %brand%!", known_variables=["brand"]) == []


def test_known_variables_is_case_insensitive() -> None:
    assert codes("Hello %Brand%!", known_variables=["brand"]) == []
    assert codes("Hello %brand%!", known_variables=["BRAND"]) == []


def test_known_variables_does_not_suppress_a_different_name() -> None:
    assert codes("%brand% %other%", known_variables=["brand"]) == ["variable.undefined"]


def test_a_name_is_warned_about_once_however_often_it_appears() -> None:
    """Forty uses of one undefined name are one problem, not forty."""
    assert codes("%a% %a% %a% %a%") == ["variable.undefined"]


def test_a_conditional_name_counts_as_a_reference() -> None:
    assert codes("{?promo?yes|no}") == ["variable.undefined"]
    assert codes("{?promo?yes|no}", known_variables=["promo"]) == []


def test_a_definition_target_is_not_a_reference_to_itself() -> None:
    """Miss this and every `#set` reports its own name as undefined."""
    assert codes("#set %x% = a\n%x%") == []


# ── self-reference and cycles ──────────────────────────────────────────


def test_self_reference() -> None:
    assert codes("#set %x% = %x%\n%x%") == ["variable.self-reference"]


def test_two_step_cycle() -> None:
    assert "variable.circular-reference" in codes("#set %a% = %b%\n#set %b% = %a%\n%a%")


def test_three_step_cycle() -> None:
    assert "variable.circular-reference" in codes(
        "#set %a% = %b%\n#set %b% = %c%\n#set %c% = %a%\n%a%"
    )


def test_a_shared_dependency_is_not_a_cycle() -> None:
    """Two names pointing at the same third one is a diamond, not a loop."""
    assert codes("#set %a% = %c%\n#set %b% = %c%\n#set %c% = x\n%a%%b%") == []


# ── plurals ────────────────────────────────────────────────────────────


def test_arity_is_skipped_without_a_locale() -> None:
    """No locale means no opinion — 2 or 3 forms could both be right."""
    assert codes("{plural 1: a|b|c}") == []


def test_arity_for_a_three_form_locale() -> None:
    assert codes("{plural 1: a|b}", locale="ru") == ["plural.arity"]
    assert codes("{plural 1: a|b|c}", locale="ru") == []


def test_bcs_shares_the_three_form_rule() -> None:
    for locale in ("sr", "hr", "bs", "sr-Latn", "sr_RS"):
        assert codes("{plural 1: a|b}", locale=locale) == ["plural.arity"], locale


def test_locales_with_their_own_grammar_are_bucketed_as_two_form() -> None:
    """pl/cs/sk/sl/bg are not implemented and not rejected — a known compromise."""
    for locale in ("pl", "cs", "sk", "sl", "bg"):
        assert codes("{plural 1: a|b}", locale=locale) == [], locale


def test_a_locale_that_normalizes_to_nothing_skips_the_check() -> None:
    assert codes("{plural 1: a|b|c}", locale="_en") == []


def test_nested_brackets_in_a_form() -> None:
    assert codes("{plural 1: {a|b}|c}") == ["plural.nested-brackets"]


def test_nested_brackets_suppress_the_arity_report() -> None:
    """Splitting on `|` would count the nested construct's pipes and invent a second
    problem out of the first one."""
    assert codes("{plural 1: {a|b}|c}", locale="ru") == ["plural.nested-brackets"]


def test_a_block_without_a_colon_is_not_a_plural() -> None:
    assert codes("{plural 1 a|b}", locale="ru") == []


# ── the taint analysis ─────────────────────────────────────────────────


def test_a_macro_count_is_an_error() -> None:
    assert codes("#set %n% = {1|4}\n{plural %n%: a|b}") == ["plural.count-macro"]


def test_taint_follows_a_chain_of_aliases() -> None:
    """The reference the count depends on is invisible in the count's own text.

    A single pass over the definitions catches the direct case and misses this one —
    which is why the analysis iterates to a fixed point.
    """
    assert codes("#set %m% = {1|4}\n#set %n% = %m%\n{plural %n%: a|b}") == ["plural.count-macro"]


def test_taint_follows_a_longer_chain_regardless_of_declaration_order() -> None:
    """Declaration order reversed on purpose: a forward-only walk would miss it."""
    assert codes(
        "{plural %c%: a|b}\n#set %c% = %b%\n#set %b% = %a%\n#set %a% = [1|2]"
    ) == ["plural.count-macro"]


def test_a_conditional_count_is_valid() -> None:
    """Conditionals resolve *before* plurals, so the count is already a literal.

    This is the case that catches an over-eager rule: a check that simply looked for
    brackets would reject a template that renders perfectly well.
    """
    assert codes("#set %flag% = 1\n#set %n% = {?flag?1|2}\n{plural %n%: a|b}") == []


def test_an_enumeration_inside_a_conditional_is_still_tainted() -> None:
    """The conditional is exempt; what it contains is not."""
    assert codes("#set %flag% = 1\n#set %n% = {?flag?{1|4}|2}\n{plural %n%: a|b}") == [
        "plural.count-macro"
    ]


def test_a_def_count_is_never_tainted() -> None:
    """A `#def` is frozen to literal text before the body is walked — the fix itself."""
    assert codes("#def %n% = {1|4}\n{plural %n%: a|b}") == []


def test_a_literal_count_is_fine() -> None:
    assert codes("#set %n% = 4\n{plural %n%: a|b}") == []


# ── includes ───────────────────────────────────────────────────────────


def test_unknown_include_target() -> None:
    assert codes('#include "nope"', known_includes=["real"]) == ["include.unknown-target"]


def test_known_include_target_is_clean() -> None:
    assert codes('#include "real"', known_includes=["real"]) == []


def test_without_a_slug_list_every_target_is_assumed_to_exist() -> None:
    """The engine does not resolve includes, so it cannot tell an unknown slug from
    one the host is about to provide."""
    assert codes('#include "anything"') == []


# ── positions, which no fixture asserts ────────────────────────────────


def test_diagnostics_carry_useful_positions() -> None:
    src = "line one\n#set %x = broken\nline three"
    (diag,) = engine.validate(src)
    assert (diag.line, diag.column) == (2, 1)


def test_positions_survive_a_comment_above_them() -> None:
    src = "/# a long comment #/\n#set %x = broken"
    (diag,) = engine.validate(src)
    assert (diag.line, diag.column) == (2, 1)


def test_diagnostics_come_back_in_source_order() -> None:
    src = "a}\n{plural 1: {x|y}|z}\n#set %q = broken"
    lines = [d.line for d in engine.validate(src)]
    assert lines == sorted(lines)
