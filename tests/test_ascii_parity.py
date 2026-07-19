"""Character classes must be ASCII, because JavaScript's are.

Python's `\\w`, `\\d` and `\\b` are Unicode-aware by default; JavaScript's are ASCII-only
even under the `u` flag. Left alone, that silently widens the accepted syntax — and
"accepted syntax surface" is the first item the spec marks parity-REQUIRED.

Every expectation here was measured against `@spintax/core`, not reasoned about:

    #set %имя% = X    -> ["set.malformed"]     (not a directive)
    [<ключ=1>a|b]     -> []                    (not read as a config at all)
    #def %x% = #includeя -> ["def.include-in-value"]
    [<minsize=٣>a|b]  -> ["permutation.minsize-not-integer"]

The corpus cannot catch any of this: it contains no non-ASCII identifier anywhere,
so this whole surface is ungated across all three engines (spec §5.2).

Known and separate: the PHP engine's patterns carry PCRE's `/u`, which enables UCP
and therefore makes ITS `\\w` Unicode-aware. TS and PHP already disagree here. This
port follows TS — the stricter of the two, so the choice can be widened later
without breaking a template that already works.
"""

from __future__ import annotations

from spintax_core import _directives, _validator


def codes(src: str) -> list[str]:
    _source, findings = _validator.run(src)
    return [f.code for f in findings]


def test_a_cyrillic_directive_name_is_malformed() -> None:
    assert codes("#set %имя% = X\n%имя%") == ["set.malformed"]


def test_a_cyrillic_name_defines_nothing() -> None:
    """The malformed report and the extraction must agree: neither accepts it."""
    assert _directives.extract("#set %имя% = X").set_defs == {}


def test_an_ascii_name_with_digits_and_underscore_is_fine() -> None:
    assert codes("#set %x_1% = a\n%x_1%") == []
    assert _directives.extract("#set %x_1% = a").set_defs == {"x_1": "a"}


def test_a_cyrillic_config_key_is_not_a_config() -> None:
    """`[<ключ=1>…]` is content or a separator, never a config block — so there is no
    unknown key to report. Reading it as config invents a diagnostic."""
    assert codes("[<ключ=1>a|b]") == []


def test_an_ascii_unknown_key_is_still_reported() -> None:
    assert codes("[<nope=1>a|b]") == ["permutation.unknown-key"]


def test_include_boundary_ends_at_a_non_ascii_letter() -> None:
    assert codes("#def %x% = #includeя") == ["def.include-in-value"]


def test_include_boundary_does_not_end_at_an_underscore() -> None:
    """`#include_more` is one word in both engines, so it is not an include."""
    assert codes("#def %x% = #include_more") == []


def test_non_ascii_digits_are_not_integers() -> None:
    assert codes("[<minsize=٣>a|b]") == ["permutation.minsize-not-integer"]
    assert codes("[<maxsize=３>a|b]") == ["permutation.maxsize-not-integer"]


def test_ascii_digits_still_pass() -> None:
    assert codes("[<minsize=2;maxsize=3>a|b]") == []
