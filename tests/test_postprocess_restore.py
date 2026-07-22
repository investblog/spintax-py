"""The restore in step 12 is two restores, and both halves need pinning here.

`postprocess_parity.json` freezes the reference's answers for these cases too, but it
freezes them as indexed rows of generated JSON: it proves the port agrees with
`@spintax/core`, and says nothing about WHAT the agreement is. These tests name it.

The shared corpus cannot: no fixture carries a `\\x00`, and none carries text that spells
a placeholder key. That is why the corruption below survived three engines.
"""

from __future__ import annotations

import time

import pytest

from spintax_core import render
from spintax_core._postprocess import post_process

#: One prose unit carrying every shieldable construct — URL, mailto/tel URI, email,
#: domain, decimal, multi-dot and single-token abbreviation. Repeated to size, the
#: placeholder count grows with the text, which is what makes the per-key restore
#: quadratic.
_SHIELD_HEAVY = (
    "Visit https://example.com/a?b=1 or mailto:a.b@example.com or tel:+1-555-0100. "
    "See www.example.org and 3.14 and 2.71, e.g. Mr. Smith, Dr. Jones, etc. "
)


@pytest.mark.parametrize(
    "text",
    [
        #: The family's canonical case — spintax-py#2, spintax-js#54.
        "https://a.io e.g. URL_0mailto:x@y.io",
        "ABBR_1т.д.URL_0ftp://f.org/z",
    ],
)
def test_text_that_spells_a_placeholder_key_survives_intact(text: str) -> None:
    """The whole reason the fast path is not just an optimisation.

    A restore that replaces each key across the whole text does not only replace the tokens
    it minted. In the first case `e.g.` is shielded as `ABBR_2` and `mailto:x@y.io` as
    `URI_1`, which leaves `ABBR_2`'s closing `\\x00` and `URI_1`'s opening `\\x00`
    sandwiching the author's literal `URL_0` — a third occurrence of the key
    `\\x00URL_0\\x00`, which the shield really did mint for `https://a.io`. Delimiters are
    not owned by the token that placed them. Replacing `URL_0` first substitutes both
    occurrences and destroys two real tokens, returning raw NULs to the caller:

        'https://a.io e.g. URL_0mailto:x@y.io'
            -> 'https://a.io \\x00ABBR_2https://a.ioURI_1\\x00'

    No `\\x00` in the input is needed. `URL_0` and `ABBR_1` are just words — any document
    about this engine contains them. Nothing is shielded across a boundary here, so the
    right answer is the input, unchanged.

    This is where the port had a choice, and took the reference's: an earlier draft declined
    the fast path here to reproduce the loop exactly, which made this engine the only one in
    the family returning the wreckage. `spintax-php` took the same decision (spintax-php#1).
    """
    assert render(text) == text


def test_a_literal_nul_in_the_input_keeps_the_per_key_restore() -> None:
    """The corner the fast path declines.

    When the caller writes their own `\\x00`, the delimiters no longer pair up as the
    shield placed them, and a key the caller spelt out in full is indistinguishable from
    one the shield minted. The per-key restore substitutes it — so this input comes back
    with the caller's `\\x00URL_0\\x00` replaced by the URL that was shielded as `URL_0`.

    The parity fixture runs this branch too — eight of its rows carry a `\\x00` — but this
    is where it is named. A single-pass restore would leave the caller's token alone.
    """
    assert (
        render("\x00URL_0\x00 see https://example.com/a")
        == "https://example.com/a see https://example.com/a"
    )
    #: A key shape the shield never minted is left alone by both restores.
    assert (
        render("\x00URL_9\x00 see https://example.com/a")
        == "\x00URL_9\x00 see https://example.com/a"
    )


#: The "portable cases" table from spintax-js#52, as corrected by #53 — the reference
#: author's own answers, stated as exact and engine-independent so a port can check them
#: without regenerating anything. Kept verbatim, in table order.
#:
#: Row 4 is the correction: #52 first pinned `mailto:http://x.io/p` as emitting a raw
#: `\x00URL_0\x00`, recorded as observed-not-desirable. #53 established that was a defect
#: rather than shared behaviour and fixed it, so the URI is now one token.
_PORTABLE_CASES = [
    (
        "</p>\x00NUM_9\x00http://x.io/p?q=1\x00URI_1\x00. \x00tel:+1-555-0100",
        "</p>\x00NUM_9\x00http://x.io/p?q=1tel:+1-555-0100. \x00tel:+1-555-0100",
    ),
    #: An unpaired `\x00` forging `\x00DOM_2\x00` out of the NEXT placeholder's opening
    #: delimiter — an unguarded single pass consumes the forgery and loses the real `URL_0`.
    ("hello world\x00DOM_2http://x.io/p?q=1", "Hello world\x00DOM_2http://x.io/p?q=1"),
    #: The caller's own key, substituted.
    (
        "see \x00URL_0\x00 and https://example.com now",
        "See https://example.com and https://example.com now",
    ),
    #: Needs no guard — it is what a port shipping only the fast path still has to match.
    ("mailto:http://x.io/p", "mailto:http://x.io/p"),
]


@pytest.mark.parametrize(("source", "expected"), _PORTABLE_CASES)
def test_the_portable_cases_from_the_reference_issue(source: str, expected: str) -> None:
    """Rows 1–3 need the guard; row 4 needs the merged URI pass."""
    assert render(source) == expected


def test_the_restore_does_not_scale_with_the_placeholder_count() -> None:
    """A guard against the quadratic returning, not a benchmark.

    Quadrupling shield-heavy text quadruples the placeholder count too, so a per-key
    restore pays 4× the scans over 4× the text. Measured on this unit: the per-key loop
    takes 0.199 s at 58 KB and 2.412 s at 233 KB — a ratio of 12 — while one pass takes
    0.058 s and 0.245 s, a ratio of 4.2. The bound sits between them with room for a slow
    or loaded runner in either direction.

    The first call is discarded: it pays for the four capitalization patterns, which are
    compiled lazily on first use and cost 27 ms. Charged to the small size, that alone
    moved the observed ratio between 1.9 and 4.5 — noise wide enough to make the bound
    look tighter than it is. If this ever flakes anyway, the answer is to move it to a
    bench script, not to widen the bound.
    """

    def elapsed(text: str) -> float:
        best = float("inf")
        for _ in range(2):
            start = time.perf_counter()
            post_process(text)
            best = min(best, time.perf_counter() - start)
        return best

    elapsed(_SHIELD_HEAVY)  # warm-up: compile the lazy capitalization rules.
    small = elapsed(_SHIELD_HEAVY * 400)
    large = elapsed(_SHIELD_HEAVY * 1600)
    assert large < small * 8, (
        f"4x the text cost {large / small:.1f}x the time — the restore is scaling with "
        f"the placeholder count again ({small:.3f}s -> {large:.3f}s)"
    )
