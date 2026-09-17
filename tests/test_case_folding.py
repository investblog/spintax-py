"""Case-insensitive matching means three different things across these two engines.

Python's `re.IGNORECASE` has one behaviour. JavaScript has two, chosen by the `u` flag,
and the reference uses both — `postprocess.ts` compiles everything `/giu`, while
`parser.ts`'s five permutation-config patterns are `/i` with no `u` at all. Nothing warns
you; the flags just sit there looking equivalent.

Measured, per character:

| char | JS `/i` | JS `/iu` | Python `re.I` |
|---|---|---|---|
| `ſ` U+017F vs `s` | no | **yes** | yes |
| `K` U+212A vs `k` | yes | yes | yes |
| `İ` U+0130 vs `i` | no | no | **yes** |
| `ı` U+0131 vs `i` | no | no | **yes** |

So Python is too permissive in two different ways, and the fix differs by call site:
`js_ci_unicode` keeps `IGNORECASE` and excludes only the Turkic pair, while `js_ci_ascii`
drops the flag entirely and spells the case out.

Both were real. `[<mınsize=2>a|b|c]` rendered `"b c"` here and
`"bmınsize=2cmınsize=2a"` in the reference — a template MEANING differently, not a
cosmetic difference — and `[<ſep="x">a|b|c]` did the same for the other rule. Confirmed
gone by 3437 differential cases across both post-process modes, on a corpus built
specifically around this alphabet after a 1922-case run missed it entirely for having no
such characters in its bag.
"""

from __future__ import annotations

import pytest

from spintax_core import render, render_with

DOTTED = chr(0x130)  # İ  LATIN CAPITAL LETTER I WITH DOT ABOVE
DOTLESS = chr(0x131)  # ı  LATIN SMALL LETTER DOTLESS I
LONG_S = chr(0x17F)  # ſ  LATIN SMALL LETTER LONG S
KELVIN = chr(0x212A)  # K  KELVIN SIGN


def first(lo: int, _hi: int) -> int:
    return lo


# ── permutation config: `/i` without `u`, so NOTHING folds beyond ASCII ──


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        # Recognised: plain ASCII, either case.
        ("[<minsize=2>a|b|c]", "b c"),
        ("[<MINSIZE=2>a|b|c]", "b c"),
        ("[<MinSize=2>a|b|c]", "b c"),
        # NOT recognised: the whole `<…>` becomes a literal separator instead.
        (f"[<m{DOTLESS}nsize=2>a|b|c]", f"bm{DOTLESS}nsize=2cm{DOTLESS}nsize=2a"),
        (f"[<m{DOTTED}nsize=2>a|b|c]", f"bm{DOTTED}nsize=2cm{DOTTED}nsize=2a"),
        # `ſ` folds to `s` under `/iu` — but these patterns have no `u`, so it does not.
        (f"[<{LONG_S}ep=2>a|b|c]", f"b{LONG_S}ep=2c{LONG_S}ep=2a"),
    ],
)
def test_config_keys_fold_only_across_ascii(template: str, expected: str) -> None:
    assert render_with(template, first, post_process=False) == expected


# ── post-process: `/giu`, so `ſ` and `K` fold and the Turkic pair does not ──


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        # `Inc.` is a known abbreviation: shielded, so no sentence-space is inserted.
        ("Inc. hello", "Inc. hello"),
        ("INC. hello", "INC. hello"),
        # `ınc.` is NOT `Inc.` to the reference, so it is an ordinary sentence end — the
        # `ı` is capitalised (to `I`) and a space goes in after the stop.
        (f"{DOTLESS}nc. hello", "Inc. Hello"),
        # `ſ` DOES fold, so `ſt.` is the abbreviation `St.` and stays shielded.
        (f"{LONG_S}t. hello", f"{LONG_S}t. hello"),
    ],
)
def test_abbreviations_fold_the_unicode_way(template: str, expected: str) -> None:
    assert render(template, post_process=True) == expected


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("zzz<div>hello", "Zzz<div>Hello"),
        ("zzz<DIV>hello", "Zzz<DIV>Hello"),
        # A dotless `ı` makes it not a `div`, so the capitalize-after-block rule is silent.
        (f"zzz<d{DOTLESS}v>hello", f"Zzz<d{DOTLESS}v>hello"),
    ],
)
def test_block_tags_fold_the_unicode_way(template: str, expected: str) -> None:
    assert render(template, post_process=True) == expected


def test_an_email_local_part_rejects_the_turkic_pair() -> None:
    """`[a-z]` under `re.IGNORECASE` accepts `ı`; PCRE2's and JavaScript's `[a-z]/iu` do
    not — they take A–Z plus U+017F and U+212A, and nothing else.

    Which is why the local-part class is spelled out character by character and matched
    with no flag at all. A recognised address is shielded whole, so the capitalizer meets a
    placeholder rather than a letter and the line is left alone. Put a `ı` in the local
    part and the address stops being one, so the first letter gets capitalised after all.
    """
    assert render("bob@example.com sent", post_process=True) == "bob@example.com sent"
    got = render(f"bob{DOTLESS}@example.com sent", post_process=True)
    assert got == f"Bob{DOTLESS}@example.com sent"


def test_a_uri_scheme_folds_the_unicode_way() -> None:
    """`mailto:` is matched `/iu`, so the Turkic pair must not fold into its `i`.

    A recognised URI is shielded whole and keeps its colon; an unrecognised one is prose,
    and the "space after a colon" rule splits it. That is the visible difference, and it is
    the same defect that once printed a bare `mailto:` (spintax-js#41).

    This test replaced one that probed the same guard through the DOMAIN shield. That probe
    retired with spintax-js#79: the domain and email patterns now carry no `re.IGNORECASE`
    at all — under a case-insensitive flag Python folds a Unicode property just as
    JavaScript does, and PCRE2 does not — so the Turkic guard has no case-insensitive
    caller left there. `js_ci_unicode` is still load-bearing here, in the block-tag names
    below, and in the abbreviations above.
    """
    assert render("mailto:a@b.io x", post_process=True) == "mailto:a@b.io x"
    assert render("MAILTO:a@b.io x", post_process=True) == "MAILTO:a@b.io x"
    assert (
        render(f"ma{DOTLESS}lto:a@b.io x", post_process=True)
        == f"Ma{DOTLESS}lto: a@b.io x"
    )
    assert (
        render(f"ma{DOTTED}lto:a@b.io x", post_process=True)
        == f"Ma{DOTTED}lto: a@b.io x"
    )
