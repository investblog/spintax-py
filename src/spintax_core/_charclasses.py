"""Character classes, written out so they match what the engine being ported matches.

Every constant here exists because the obvious Python escape silently accepts a different
set than the pattern it is translating. Left alone, this port would quietly accept syntax
the other engines reject, which is the worst kind of parity bug: nothing fails, the
engines just disagree about what a template means.

**Three dialects, and every pattern belongs to exactly one.** The plugin is the origin, so
the question a ported pattern asks is *does the PHP source carry `/u`?*

- **`/u` — PCRE2_UCP.** `\\s`, `\\d`, `\\w` and `\\b` are Unicode there: `\\s` takes NBSP and
  the rest of `\\p{Z}`, `\\b` counts a letter of any script. Take the class from `UCP_SPACE`
  / `UCP_WORD` below.
- **no `/u` — byte mode.** The same shorthands are ASCII. Take `ASCII_SPACE`,
  `ASCII_DIGIT`, `ASCII_WORD`.
- **JavaScript**, where a pattern was written for `@spintax/core` rather than translated
  from PHP — a third set again: its `\\s` takes U+FEFF and misses U+0085 and U+180E, and
  its `\\w`, `\\d` and `\\b` stay ASCII even under `u`. Take `JS_SPACE`, `JS_WORD_BOUNDARY`.

Python is none of the three. Its `\\w`, `\\d` and `\\b` are Unicode, its `\\s` is Unicode
plus the ASCII separators, and `re.IGNORECASE` folds more than either engine does — so a
class that is not spelled out here is a class that means something else.

The post-process was once written on the belief that PHP's `/u` was NOT UCP. That is how
`и т.д.` rendered `и т. Д.` and `пример.рф` rendered `пример. Рф` in every tree-walk
engine while both PHP engines left them intact (spintax-js#81).

**Which Unicode version these speak, and why it is the runtime's.** A class written as
`[^\\W\\d_]` or `\\d` resolves against the tables the RUNNING interpreter carries: Python 3.10
ships Unicode 13, 3.11 ships 14, 3.12 ships 15.0 and 3.13 ships 15.1. So `go.𮯰a` (U+2EBF0,
assigned in 15.1) is not a domain on 3.12 and is one on 3.13 — measured, not reasoned.

That is deliberate, and it is what the reference does. `@spintax/core` writes `\\p{L}` and
`\\p{N}`, which V8 resolves against the ICU bundled with the Node that is running, and it
supports `node >= 18` — Unicode 14 through 16. An engine's alphabet following its runtime
is the model; pinning one here would not buy parity with the reference, it would only pick
a different version to be wrong about, and freeze it.

The BAKED tables below are the exception, and only because Python's `re` cannot name the
property at all. They are therefore the one place where a version skew is a real risk, and
they are guarded rather than trusted: `tests/test_charclass_tables.py` composes each class
the way this module composes it and asserts it against the running `unicodedata`. A table
missing a character this interpreter knows is a failure whichever direction it bites —
subtraction inverts the polarity, so `_LU_LT` missing a new `Lu` would read that letter as
a lower-case TLD, and the test sees it as assigned surplus in the composed class.

Held here rather than in whichever module needed it first: `_directives`, `_validator`,
`_parser` and `_postprocess` all want them now, and a constant copied into four files is a
constant that will drift in three of them.
"""

from __future__ import annotations

#: JavaScript's `\w` — and therefore its `\b`, which is defined in terms of it.
ASCII_WORD = "[A-Za-z0-9_]"

#: PHP's `\s` in BYTE mode — a pattern written WITHOUT `/u`. A fragment for inside `[…]`.
#:
#: The permutation-config patterns are the ones that want it: the plugin writes all of them
#: without `/u`, so `[<minsize<NBSP>=<NBSP>1>a|b|c]` is a single literal separator there and
#: not a size. Python's `\s` and JavaScript's are both Unicode here and both wrong.
ASCII_SPACE = " \\t\\n\\x0b\\f\\r"

#: A lookbehind standing in for JavaScript's `\b` at the START of a token. Python's `\b`
#: would treat a preceding Unicode letter as a word character and find no boundary there.
NOT_AFTER_WORD = "(?<![A-Za-z0-9_])"

#: The dotted and dotless Turkish `i`. **Python's `re.IGNORECASE` folds both into ASCII
#: `i`; JavaScript's `/iu` never does.**
#:
#: Python applies the Turkic-only (status `T`) case foldings of U+0130 and U+0131.
#: JavaScript uses simple folding, which excludes them by design. Measured over every ASCII
#: letter against both engines, the entire divergence set is these two characters — no
#: more, and nothing in the other direction. `ſ` (U+017F) and `K` (U+212A) fold in BOTH,
#: which is why the fix cannot simply be "drop IGNORECASE and spell out `[a-zA-Z]`": that
#: would lose two characters the reference accepts while removing two it rejects.
TURKIC_I = "İı"

#: The same pair as a class that IGNORECASE cannot touch. Without the scoped `(?-i:…)`
#: the exclusion is self-defeating: `[İı]` under IGNORECASE also matches plain `i`, so a
#: lookahead built from it rejects the very letter it was meant to protect.
NOT_TURKIC = f"(?!(?-i:[{TURKIC_I}]))"
_IS_TURKIC = f"(?=(?-i:[{TURKIC_I}]))"
_AFTER_TURKIC = f"(?<=(?-i:[{TURKIC_I}]))"
_NOT_AFTER_TURKIC = f"(?<!(?-i:[{TURKIC_I}]))"


def js_ci_unicode(literal: str) -> str:
    """A literal matched case-insensitively as JavaScript's `/iu` does it.

    Use with `re.IGNORECASE`. Only `i` needs guarding: `ſ` and `K` fold into `s` and `k`
    under `/iu`, and Python agrees, so they must be left alone.

    Getting this wrong is not cosmetic. `[<mınsize=2>a|b|c]` — a dotless `ı` in a
    permutation config key — rendered `"b c"` here and `"bmınsize=2cmınsize=2a"` in the
    reference, because Python accepted the key and JavaScript read the whole `<…>` as a
    separator instead. That is a template meaning differently in two engines.
    """
    return "".join(f"{NOT_TURKIC}{ch}" if ch in "iI" else ch for ch in literal)


def js_ci_ascii(literal: str) -> str:
    """A literal matched case-insensitively as JavaScript's `/i` **without** `u` does it.

    Use WITHOUT `re.IGNORECASE` — the classes carry the case themselves, so no flag can
    widen them. That is the point: the `u` flag is what makes JavaScript fold `ſ` into
    `s`, and a regex declared `/i` alone does not. Python's `re.IGNORECASE` has no such
    distinction and always folds, so the only faithful translation of a non-`u` pattern is
    to stop using the flag.

    The reference's five permutation-config patterns are all `/i` with no `u`, which is
    why `[<ſep="x">a|b|c]` is a config here and a literal separator there. Eight of 3437
    differential cases, all from that one flag.
    """
    return "".join(
        f"[{ch.lower()}{ch.upper()}]" if ch.isascii() and ch.isalpha() else ch
        for ch in literal
    )


#: JavaScript's `\b`, which is NOT the same thing as `NOT_AFTER_WORD`.
#:
#: A boundary needs a TRANSITION: exactly one side must be a word character, with
#: out-of-string counting as non-word. Checking only the preceding character finds a
#: boundary that is not there whenever the following character is also non-word — and
#: since JavaScript's word set is ASCII, every Cyrillic or accented letter is non-word.
#:
#: Measured cost of getting that wrong: `приме.com` and `ß.a.com` were shielded as domains
#: here and left alone by the reference, so the spacing and capitalization passes skipped
#: text the reference rewrites. 64 of 1922 differential cases, all from one line.
#:
#: The Turkic guards matter because `re.IGNORECASE` applies to the WHOLE pattern, so a
#: case-insensitive caller silently widened this ASCII-only set. JavaScript's `\b` does
#: gain `ſ` and `K` under `/iu` — both fold into ASCII word characters — and this keeps
#: them; it is only U+0130 and U+0131 that must stay non-word.
_WORD = "[A-Za-z0-9_]"
_WORD_AHEAD = f"(?={NOT_TURKIC}{_WORD})"
_WORD_BEHIND = f"(?<={_WORD}){_NOT_AFTER_TURKIC}"
_NOT_WORD_AHEAD = f"(?:(?!{_WORD})|{_IS_TURKIC})"
_NOT_WORD_BEHIND = f"(?:(?<!{_WORD})|{_AFTER_TURKIC})"
JS_WORD_BOUNDARY = (
    f"(?:{_NOT_WORD_BEHIND}{_WORD_AHEAD}|{_WORD_BEHIND}{_NOT_WORD_AHEAD})"
)

#: JavaScript's `\d`. Python's also matches every Unicode decimal digit, so an Arabic-Indic
#: numeral would parse as a permutation size the reference would refuse.
ASCII_DIGIT = "[0-9]"

#: JavaScript's `\s`. Not Python's: Python adds `\x1c`–`\x1f` (the ASCII file/group/record/
#: unit separators) and omits `﻿`, so the two disagree on six characters in both
#: directions.
JS_SPACE = (
    "[\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a"
    "\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]"
)

#: JavaScript's `\S`. Built by negating the class above rather than written out, because
#: two hand-kept lists of the same characters drift. Conditional truthiness is decided
#: with this — a variable holding only U+FEFF is falsy to the reference and would be
#: truthy under Python's `\S`, flipping which branch renders.
JS_NOT_SPACE = "[^" + JS_SPACE[1:]

#: PCRE2 UCP `\s` — what `\s` means in a PHP pattern that carries `/u`. `\p{Z}` plus `\h`
#: and `\v`: U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+180E, U+2000–U+200A, U+2028,
#: U+2029, U+202F, U+205F, U+3000. A fragment for inside `[…]`.
#:
#: Neither `JS_SPACE` nor Python's `\s`: it has U+0085 and U+180E, which JavaScript's lacks,
#: and not U+FEFF, which JavaScript's has. The whole post-process runs on this set, and so
#: does conditional truthiness — a value of U+FEFF alone is TRUTHY, one of U+0085 alone is
#: blank, and reading those the other way round flips which branch renders.
UCP_SPACE = (
    "\\t\\n\\x0b\\f\\r \\x85\\xa0\\u1680\\u180e\\u2000-\\u200a"
    "\\u2028\\u2029\\u202f\\u205f\\u3000"
)

#: PCRE2 UCP `\S`. Negated from the class above rather than written out, because two
#: hand-kept lists of the same characters drift.
UCP_NOT_SPACE = f"[^{UCP_SPACE}]"

#: The same set as `UCP_SPACE`, as characters — for a scanner that reads a string one
#: character at a time instead of running a regex. `tests/test_charclass_tables.py` asserts
#: the two agree, which is the only thing keeping a second hand-kept list honest.
UCP_SPACE_CHARS = frozenset(
    "\t\n\x0b\f\r \x85\xa0 ᠎    　"
) | frozenset(chr(cp) for cp in range(0x2000, 0x200B))

#: What JavaScript calls a LineTerminator. Python's `re` knows only `\n`, which is why a
#: line-anchored pattern needs the three constants below rather than `^`, `$` and `.`.
JS_LINE_TERMINATORS = "\\n\\r\\u2028\\u2029"

#: JavaScript's `^` under `/m`: start of input, or just after a terminator.
JS_LINE_START = f"(?:\\A|(?<=[{JS_LINE_TERMINATORS}]))"

#: JavaScript's `$` under `/m`: end of input, or just before a terminator. A LOOKAHEAD, so
#: the terminator is not consumed — which is the whole point. Normalising terminators to
#: `\n` on a scratch copy is fine for anchoring alone, and silently wrong as soon as the
#: pattern also carries an explicit terminator class beside the anchor: the class then
#: matches a rewritten U+2028 the reference's own class could never match, and eats a
#: separator the reference leaves in place.
JS_LINE_END = f"(?=\\Z|[{JS_LINE_TERMINATORS}])"

#: JavaScript's `.` — anything that is not a LineTerminator. Python's `.` matches `\r`,
#: U+2028 and U+2029 happily, so a value group written as `(.*?)` swallows past the end of
#: its line.
JS_DOT = f"[^{JS_LINE_TERMINATORS}]"

#: Categories `Nl` and `No`, as a ranged class. GENERATED — see
#: `tests/test_charclass_tables.py`, which rebuilds this from the running `unicodedata`
#: and fails if it has drifted.
#:
#: Baked rather than computed at import because building it means walking all 1.1M code
#: points, which is 0.23 s a library has no business spending on `import`. The cost of
#: baking is that it is frozen to one Unicode version, and the four-interpreter CI matrix
#: is what turns that from a silent risk into a named test failure.
_NL_NO = (
    "\\U000000b2-\\U000000b3\\U000000b9\\U000000bc-\\U000000be\\U000009f4-\\U000009f9"
    "\\U00000b72-\\U00000b77\\U00000bf0-\\U00000bf2\\U00000c78-\\U00000c7e"
    "\\U00000d58-\\U00000d5e\\U00000d70-\\U00000d78\\U00000f2a-\\U00000f33"
    "\\U00001369-\\U0000137c\\U000016ee-\\U000016f0\\U000017f0-\\U000017f9\\U000019da"
    "\\U00002070\\U00002074-\\U00002079\\U00002080-\\U00002089\\U00002150-\\U00002182"
    "\\U00002185-\\U00002189\\U00002460-\\U0000249b\\U000024ea-\\U000024ff"
    "\\U00002776-\\U00002793\\U00002cfd\\U00003007\\U00003021-\\U00003029"
    "\\U00003038-\\U0000303a\\U00003192-\\U00003195\\U00003220-\\U00003229"
    "\\U00003248-\\U0000324f\\U00003251-\\U0000325f\\U00003280-\\U00003289"
    "\\U000032b1-\\U000032bf\\U0000a6e6-\\U0000a6ef\\U0000a830-\\U0000a835"
    "\\U00010107-\\U00010133\\U00010140-\\U00010178\\U0001018a-\\U0001018b"
    "\\U000102e1-\\U000102fb\\U00010320-\\U00010323\\U00010341\\U0001034a"
    "\\U000103d1-\\U000103d5\\U00010858-\\U0001085f\\U00010879-\\U0001087f"
    "\\U000108a7-\\U000108af\\U000108fb-\\U000108ff\\U00010916-\\U0001091b"
    "\\U000109bc-\\U000109bd\\U000109c0-\\U000109cf\\U000109d2-\\U000109ff"
    "\\U00010a40-\\U00010a48\\U00010a7d-\\U00010a7e\\U00010a9d-\\U00010a9f"
    "\\U00010aeb-\\U00010aef\\U00010b58-\\U00010b5f\\U00010b78-\\U00010b7f"
    "\\U00010ba9-\\U00010baf\\U00010cfa-\\U00010cff\\U00010e60-\\U00010e7e"
    "\\U00010f1d-\\U00010f26\\U00010f51-\\U00010f54\\U00010fc5-\\U00010fcb"
    "\\U00011052-\\U00011065\\U000111e1-\\U000111f4\\U0001173a-\\U0001173b"
    "\\U000118ea-\\U000118f2\\U00011c5a-\\U00011c6c\\U00011fc0-\\U00011fd4"
    "\\U00012400-\\U0001246e\\U00016b5b-\\U00016b61\\U00016e80-\\U00016e96"
    "\\U0001d2c0-\\U0001d2d3\\U0001d2e0-\\U0001d2f3\\U0001d360-\\U0001d378"
    "\\U0001e8c7-\\U0001e8cf\\U0001ec71-\\U0001ecab\\U0001ecad-\\U0001ecaf"
    "\\U0001ecb1-\\U0001ecb4\\U0001ed01-\\U0001ed2d\\U0001ed2f-\\U0001ed3d"
    "\\U0001f100-\\U0001f10c"
)

#: JavaScript's `\p{L}`. Python's `\w` decomposes exactly as `L u N u _`, so `[^\W\d_]`
#: lands on `L u Nl u No` — subtract those two and what is left is `L` on the nose.
#: Verified across the whole Unicode range: zero disagreements.
#:
#: The tempting `[^\W\d_]` on its own is NOT `\p{L}`. It disagrees on 1151 code points
#: and would read `2` and `1/2` as letters.
JS_LETTER = rf"(?![{_NL_NO}])[^\W\d_]"

#: JavaScript's `[\p{L}\p{N}]`, which needs no subtraction at all.
JS_LETTER_OR_NUMBER = r"[^\W_]"

#: Category `Ll`, as a ranged class. GENERATED, same as `_NL_NO` above.
#:
#: Baked because the alternative does not work. Matching any letter and filtering for `Ll`
#: inside the replacement callback looks equivalent and is not: a broadened match CONSUMES
#: its region, so a capital letter that the narrow pattern would have skipped instead
#: swallows a following lowercase one that should have been capitalised. Caught by
#: differential fuzzing: on a fragment where a broadened match reaches an uppercase letter
#: through an HTML tag, the reference capitalises a lowercase letter inside the tag and the
#: broadened version leaves it alone.
_LL = (
    "\\U00000061-\\U0000007a\\U000000b5\\U000000df-\\U000000f6\\U000000f8-\\U000000ff"
    "\\U00000101\\U00000103\\U00000105\\U00000107\\U00000109\\U0000010b\\U0000010d\\U0000010f"
    "\\U00000111\\U00000113\\U00000115\\U00000117\\U00000119\\U0000011b\\U0000011d\\U0000011f"
    "\\U00000121\\U00000123\\U00000125\\U00000127\\U00000129\\U0000012b\\U0000012d\\U0000012f"
    "\\U00000131\\U00000133\\U00000135\\U00000137-\\U00000138\\U0000013a\\U0000013c"
    "\\U0000013e\\U00000140\\U00000142\\U00000144\\U00000146\\U00000148-\\U00000149"
    "\\U0000014b\\U0000014d\\U0000014f\\U00000151\\U00000153\\U00000155\\U00000157\\U00000159"
    "\\U0000015b\\U0000015d\\U0000015f\\U00000161\\U00000163\\U00000165\\U00000167\\U00000169"
    "\\U0000016b\\U0000016d\\U0000016f\\U00000171\\U00000173\\U00000175\\U00000177\\U0000017a"
    "\\U0000017c\\U0000017e-\\U00000180\\U00000183\\U00000185\\U00000188"
    "\\U0000018c-\\U0000018d\\U00000192\\U00000195\\U00000199-\\U0000019b\\U0000019e"
    "\\U000001a1\\U000001a3\\U000001a5\\U000001a8\\U000001aa-\\U000001ab\\U000001ad"
    "\\U000001b0\\U000001b4\\U000001b6\\U000001b9-\\U000001ba\\U000001bd-\\U000001bf"
    "\\U000001c6\\U000001c9\\U000001cc\\U000001ce\\U000001d0\\U000001d2\\U000001d4\\U000001d6"
    "\\U000001d8\\U000001da\\U000001dc-\\U000001dd\\U000001df\\U000001e1\\U000001e3"
    "\\U000001e5\\U000001e7\\U000001e9\\U000001eb\\U000001ed\\U000001ef-\\U000001f0"
    "\\U000001f3\\U000001f5\\U000001f9\\U000001fb\\U000001fd\\U000001ff\\U00000201\\U00000203"
    "\\U00000205\\U00000207\\U00000209\\U0000020b\\U0000020d\\U0000020f\\U00000211\\U00000213"
    "\\U00000215\\U00000217\\U00000219\\U0000021b\\U0000021d\\U0000021f\\U00000221\\U00000223"
    "\\U00000225\\U00000227\\U00000229\\U0000022b\\U0000022d\\U0000022f\\U00000231"
    "\\U00000233-\\U00000239\\U0000023c\\U0000023f-\\U00000240\\U00000242\\U00000247"
    "\\U00000249\\U0000024b\\U0000024d\\U0000024f-\\U00000293\\U00000295-\\U000002af"
    "\\U00000371\\U00000373\\U00000377\\U0000037b-\\U0000037d\\U00000390"
    "\\U000003ac-\\U000003ce\\U000003d0-\\U000003d1\\U000003d5-\\U000003d7\\U000003d9"
    "\\U000003db\\U000003dd\\U000003df\\U000003e1\\U000003e3\\U000003e5\\U000003e7\\U000003e9"
    "\\U000003eb\\U000003ed\\U000003ef-\\U000003f3\\U000003f5\\U000003f8"
    "\\U000003fb-\\U000003fc\\U00000430-\\U0000045f\\U00000461\\U00000463\\U00000465"
    "\\U00000467\\U00000469\\U0000046b\\U0000046d\\U0000046f\\U00000471\\U00000473\\U00000475"
    "\\U00000477\\U00000479\\U0000047b\\U0000047d\\U0000047f\\U00000481\\U0000048b\\U0000048d"
    "\\U0000048f\\U00000491\\U00000493\\U00000495\\U00000497\\U00000499\\U0000049b\\U0000049d"
    "\\U0000049f\\U000004a1\\U000004a3\\U000004a5\\U000004a7\\U000004a9\\U000004ab\\U000004ad"
    "\\U000004af\\U000004b1\\U000004b3\\U000004b5\\U000004b7\\U000004b9\\U000004bb\\U000004bd"
    "\\U000004bf\\U000004c2\\U000004c4\\U000004c6\\U000004c8\\U000004ca\\U000004cc"
    "\\U000004ce-\\U000004cf\\U000004d1\\U000004d3\\U000004d5\\U000004d7\\U000004d9"
    "\\U000004db\\U000004dd\\U000004df\\U000004e1\\U000004e3\\U000004e5\\U000004e7\\U000004e9"
    "\\U000004eb\\U000004ed\\U000004ef\\U000004f1\\U000004f3\\U000004f5\\U000004f7\\U000004f9"
    "\\U000004fb\\U000004fd\\U000004ff\\U00000501\\U00000503\\U00000505\\U00000507\\U00000509"
    "\\U0000050b\\U0000050d\\U0000050f\\U00000511\\U00000513\\U00000515\\U00000517\\U00000519"
    "\\U0000051b\\U0000051d\\U0000051f\\U00000521\\U00000523\\U00000525\\U00000527\\U00000529"
    "\\U0000052b\\U0000052d\\U0000052f\\U00000560-\\U00000588\\U000010d0-\\U000010fa"
    "\\U000010fd-\\U000010ff\\U000013f8-\\U000013fd\\U00001c80-\\U00001c88"
    "\\U00001d00-\\U00001d2b\\U00001d6b-\\U00001d77\\U00001d79-\\U00001d9a\\U00001e01"
    "\\U00001e03\\U00001e05\\U00001e07\\U00001e09\\U00001e0b\\U00001e0d\\U00001e0f\\U00001e11"
    "\\U00001e13\\U00001e15\\U00001e17\\U00001e19\\U00001e1b\\U00001e1d\\U00001e1f\\U00001e21"
    "\\U00001e23\\U00001e25\\U00001e27\\U00001e29\\U00001e2b\\U00001e2d\\U00001e2f\\U00001e31"
    "\\U00001e33\\U00001e35\\U00001e37\\U00001e39\\U00001e3b\\U00001e3d\\U00001e3f\\U00001e41"
    "\\U00001e43\\U00001e45\\U00001e47\\U00001e49\\U00001e4b\\U00001e4d\\U00001e4f\\U00001e51"
    "\\U00001e53\\U00001e55\\U00001e57\\U00001e59\\U00001e5b\\U00001e5d\\U00001e5f\\U00001e61"
    "\\U00001e63\\U00001e65\\U00001e67\\U00001e69\\U00001e6b\\U00001e6d\\U00001e6f\\U00001e71"
    "\\U00001e73\\U00001e75\\U00001e77\\U00001e79\\U00001e7b\\U00001e7d\\U00001e7f\\U00001e81"
    "\\U00001e83\\U00001e85\\U00001e87\\U00001e89\\U00001e8b\\U00001e8d\\U00001e8f\\U00001e91"
    "\\U00001e93\\U00001e95-\\U00001e9d\\U00001e9f\\U00001ea1\\U00001ea3\\U00001ea5"
    "\\U00001ea7\\U00001ea9\\U00001eab\\U00001ead\\U00001eaf\\U00001eb1\\U00001eb3\\U00001eb5"
    "\\U00001eb7\\U00001eb9\\U00001ebb\\U00001ebd\\U00001ebf\\U00001ec1\\U00001ec3\\U00001ec5"
    "\\U00001ec7\\U00001ec9\\U00001ecb\\U00001ecd\\U00001ecf\\U00001ed1\\U00001ed3\\U00001ed5"
    "\\U00001ed7\\U00001ed9\\U00001edb\\U00001edd\\U00001edf\\U00001ee1\\U00001ee3\\U00001ee5"
    "\\U00001ee7\\U00001ee9\\U00001eeb\\U00001eed\\U00001eef\\U00001ef1\\U00001ef3\\U00001ef5"
    "\\U00001ef7\\U00001ef9\\U00001efb\\U00001efd\\U00001eff-\\U00001f07"
    "\\U00001f10-\\U00001f15\\U00001f20-\\U00001f27\\U00001f30-\\U00001f37"
    "\\U00001f40-\\U00001f45\\U00001f50-\\U00001f57\\U00001f60-\\U00001f67"
    "\\U00001f70-\\U00001f7d\\U00001f80-\\U00001f87\\U00001f90-\\U00001f97"
    "\\U00001fa0-\\U00001fa7\\U00001fb0-\\U00001fb4\\U00001fb6-\\U00001fb7\\U00001fbe"
    "\\U00001fc2-\\U00001fc4\\U00001fc6-\\U00001fc7\\U00001fd0-\\U00001fd3"
    "\\U00001fd6-\\U00001fd7\\U00001fe0-\\U00001fe7\\U00001ff2-\\U00001ff4"
    "\\U00001ff6-\\U00001ff7\\U0000210a\\U0000210e-\\U0000210f\\U00002113\\U0000212f"
    "\\U00002134\\U00002139\\U0000213c-\\U0000213d\\U00002146-\\U00002149\\U0000214e"
    "\\U00002184\\U00002c30-\\U00002c5f\\U00002c61\\U00002c65-\\U00002c66\\U00002c68"
    "\\U00002c6a\\U00002c6c\\U00002c71\\U00002c73-\\U00002c74\\U00002c76-\\U00002c7b"
    "\\U00002c81\\U00002c83\\U00002c85\\U00002c87\\U00002c89\\U00002c8b\\U00002c8d\\U00002c8f"
    "\\U00002c91\\U00002c93\\U00002c95\\U00002c97\\U00002c99\\U00002c9b\\U00002c9d\\U00002c9f"
    "\\U00002ca1\\U00002ca3\\U00002ca5\\U00002ca7\\U00002ca9\\U00002cab\\U00002cad\\U00002caf"
    "\\U00002cb1\\U00002cb3\\U00002cb5\\U00002cb7\\U00002cb9\\U00002cbb\\U00002cbd\\U00002cbf"
    "\\U00002cc1\\U00002cc3\\U00002cc5\\U00002cc7\\U00002cc9\\U00002ccb\\U00002ccd\\U00002ccf"
    "\\U00002cd1\\U00002cd3\\U00002cd5\\U00002cd7\\U00002cd9\\U00002cdb\\U00002cdd\\U00002cdf"
    "\\U00002ce1\\U00002ce3-\\U00002ce4\\U00002cec\\U00002cee\\U00002cf3"
    "\\U00002d00-\\U00002d25\\U00002d27\\U00002d2d\\U0000a641\\U0000a643\\U0000a645"
    "\\U0000a647\\U0000a649\\U0000a64b\\U0000a64d\\U0000a64f\\U0000a651\\U0000a653\\U0000a655"
    "\\U0000a657\\U0000a659\\U0000a65b\\U0000a65d\\U0000a65f\\U0000a661\\U0000a663\\U0000a665"
    "\\U0000a667\\U0000a669\\U0000a66b\\U0000a66d\\U0000a681\\U0000a683\\U0000a685\\U0000a687"
    "\\U0000a689\\U0000a68b\\U0000a68d\\U0000a68f\\U0000a691\\U0000a693\\U0000a695\\U0000a697"
    "\\U0000a699\\U0000a69b\\U0000a723\\U0000a725\\U0000a727\\U0000a729\\U0000a72b\\U0000a72d"
    "\\U0000a72f-\\U0000a731\\U0000a733\\U0000a735\\U0000a737\\U0000a739\\U0000a73b"
    "\\U0000a73d\\U0000a73f\\U0000a741\\U0000a743\\U0000a745\\U0000a747\\U0000a749\\U0000a74b"
    "\\U0000a74d\\U0000a74f\\U0000a751\\U0000a753\\U0000a755\\U0000a757\\U0000a759\\U0000a75b"
    "\\U0000a75d\\U0000a75f\\U0000a761\\U0000a763\\U0000a765\\U0000a767\\U0000a769\\U0000a76b"
    "\\U0000a76d\\U0000a76f\\U0000a771-\\U0000a778\\U0000a77a\\U0000a77c\\U0000a77f"
    "\\U0000a781\\U0000a783\\U0000a785\\U0000a787\\U0000a78c\\U0000a78e\\U0000a791"
    "\\U0000a793-\\U0000a795\\U0000a797\\U0000a799\\U0000a79b\\U0000a79d\\U0000a79f"
    "\\U0000a7a1\\U0000a7a3\\U0000a7a5\\U0000a7a7\\U0000a7a9\\U0000a7af\\U0000a7b5\\U0000a7b7"
    "\\U0000a7b9\\U0000a7bb\\U0000a7bd\\U0000a7bf\\U0000a7c1\\U0000a7c3\\U0000a7c8\\U0000a7ca"
    "\\U0000a7d1\\U0000a7d3\\U0000a7d5\\U0000a7d7\\U0000a7d9\\U0000a7f6\\U0000a7fa"
    "\\U0000ab30-\\U0000ab5a\\U0000ab60-\\U0000ab68\\U0000ab70-\\U0000abbf"
    "\\U0000fb00-\\U0000fb06\\U0000fb13-\\U0000fb17\\U0000ff41-\\U0000ff5a"
    "\\U00010428-\\U0001044f\\U000104d8-\\U000104fb\\U00010597-\\U000105a1"
    "\\U000105a3-\\U000105b1\\U000105b3-\\U000105b9\\U000105bb-\\U000105bc"
    "\\U00010cc0-\\U00010cf2\\U000118c0-\\U000118df\\U00016e60-\\U00016e7f"
    "\\U0001d41a-\\U0001d433\\U0001d44e-\\U0001d454\\U0001d456-\\U0001d467"
    "\\U0001d482-\\U0001d49b\\U0001d4b6-\\U0001d4b9\\U0001d4bb\\U0001d4bd-\\U0001d4c3"
    "\\U0001d4c5-\\U0001d4cf\\U0001d4ea-\\U0001d503\\U0001d51e-\\U0001d537"
    "\\U0001d552-\\U0001d56b\\U0001d586-\\U0001d59f\\U0001d5ba-\\U0001d5d3"
    "\\U0001d5ee-\\U0001d607\\U0001d622-\\U0001d63b\\U0001d656-\\U0001d66f"
    "\\U0001d68a-\\U0001d6a5\\U0001d6c2-\\U0001d6da\\U0001d6dc-\\U0001d6e1"
    "\\U0001d6fc-\\U0001d714\\U0001d716-\\U0001d71b\\U0001d736-\\U0001d74e"
    "\\U0001d750-\\U0001d755\\U0001d770-\\U0001d788\\U0001d78a-\\U0001d78f"
    "\\U0001d7aa-\\U0001d7c2\\U0001d7c4-\\U0001d7c9\\U0001d7cb\\U0001df00-\\U0001df09"
    "\\U0001df0b-\\U0001df1e\\U0001df25-\\U0001df2a\\U0001e922-\\U0001e943"
)

#: JavaScript's `\p{Ll}`. No table-free predicate exists: `str.islower()` is true for 311
#: code points outside `Ll`, and every repair built on `upper() != c` fails on U+0138 `ĸ`,
#: a lowercase letter with no uppercase pair.
JS_LOWERCASE_LETTER = f"[{_LL}]"

#: The Unicode version every baked table below was generated from.
#:
#: Recorded because the tables track the REFERENCE's Unicode, not Python's, so on an older
#: interpreter they are deliberately ahead — and "ahead" is not only about characters that
#: did not exist yet. A category can also SHRINK: U+1734 HANUNOO SIGN PAMUDPOD is `Mn` in
#: Unicode 13 (Python 3.10) and `Mc` from 14 on, so it belongs to PCRE2's UCP `\w` there and
#: not here. `tests/test_charclass_tables.py` compares this against the running
#: `unicodedata` to tell a reclassification apart from a table that is genuinely missing a
#: character — the second is always a bug, the first is the intended state.
TABLES_UNICODE_VERSION = "15.0.0"

#: Categories `Mn` and `Pc`, as a ranged class. GENERATED — see
#: `tests/test_charclass_tables.py`, which rebuilds this from the running `unicodedata`
#: and fails if it has drifted.
_MN_PC = (
    "\\U0000005f\\U00000300-\\U0000036f\\U00000483-\\U00000487\\U00000591-\\U000005bd\\U000005bf"
    "\\U000005c1-\\U000005c2\\U000005c4-\\U000005c5\\U000005c7\\U00000610-\\U0000061a"
    "\\U0000064b-\\U0000065f\\U00000670\\U000006d6-\\U000006dc\\U000006df-\\U000006e4"
    "\\U000006e7-\\U000006e8\\U000006ea-\\U000006ed\\U00000711\\U00000730-\\U0000074a"
    "\\U000007a6-\\U000007b0\\U000007eb-\\U000007f3\\U000007fd\\U00000816-\\U00000819"
    "\\U0000081b-\\U00000823\\U00000825-\\U00000827\\U00000829-\\U0000082d\\U00000859-\\U0000085b"
    "\\U00000898-\\U0000089f\\U000008ca-\\U000008e1\\U000008e3-\\U00000902\\U0000093a\\U0000093c"
    "\\U00000941-\\U00000948\\U0000094d\\U00000951-\\U00000957\\U00000962-\\U00000963\\U00000981"
    "\\U000009bc\\U000009c1-\\U000009c4\\U000009cd\\U000009e2-\\U000009e3\\U000009fe"
    "\\U00000a01-\\U00000a02\\U00000a3c\\U00000a41-\\U00000a42\\U00000a47-\\U00000a48"
    "\\U00000a4b-\\U00000a4d\\U00000a51\\U00000a70-\\U00000a71\\U00000a75\\U00000a81-\\U00000a82"
    "\\U00000abc\\U00000ac1-\\U00000ac5\\U00000ac7-\\U00000ac8\\U00000acd\\U00000ae2-\\U00000ae3"
    "\\U00000afa-\\U00000aff\\U00000b01\\U00000b3c\\U00000b3f\\U00000b41-\\U00000b44\\U00000b4d"
    "\\U00000b55-\\U00000b56\\U00000b62-\\U00000b63\\U00000b82\\U00000bc0\\U00000bcd\\U00000c00"
    "\\U00000c04\\U00000c3c\\U00000c3e-\\U00000c40\\U00000c46-\\U00000c48\\U00000c4a-\\U00000c4d"
    "\\U00000c55-\\U00000c56\\U00000c62-\\U00000c63\\U00000c81\\U00000cbc\\U00000cbf\\U00000cc6"
    "\\U00000ccc-\\U00000ccd\\U00000ce2-\\U00000ce3\\U00000d00-\\U00000d01\\U00000d3b-\\U00000d3c"
    "\\U00000d41-\\U00000d44\\U00000d4d\\U00000d62-\\U00000d63\\U00000d81\\U00000dca"
    "\\U00000dd2-\\U00000dd4\\U00000dd6\\U00000e31\\U00000e34-\\U00000e3a\\U00000e47-\\U00000e4e"
    "\\U00000eb1\\U00000eb4-\\U00000ebc\\U00000ec8-\\U00000ece\\U00000f18-\\U00000f19\\U00000f35"
    "\\U00000f37\\U00000f39\\U00000f71-\\U00000f7e\\U00000f80-\\U00000f84\\U00000f86-\\U00000f87"
    "\\U00000f8d-\\U00000f97\\U00000f99-\\U00000fbc\\U00000fc6\\U0000102d-\\U00001030"
    "\\U00001032-\\U00001037\\U00001039-\\U0000103a\\U0000103d-\\U0000103e\\U00001058-\\U00001059"
    "\\U0000105e-\\U00001060\\U00001071-\\U00001074\\U00001082\\U00001085-\\U00001086\\U0000108d"
    "\\U0000109d\\U0000135d-\\U0000135f\\U00001712-\\U00001714\\U00001732-\\U00001733"
    "\\U00001752-\\U00001753\\U00001772-\\U00001773\\U000017b4-\\U000017b5\\U000017b7-\\U000017bd"
    "\\U000017c6\\U000017c9-\\U000017d3\\U000017dd\\U0000180b-\\U0000180d\\U0000180f"
    "\\U00001885-\\U00001886\\U000018a9\\U00001920-\\U00001922\\U00001927-\\U00001928\\U00001932"
    "\\U00001939-\\U0000193b\\U00001a17-\\U00001a18\\U00001a1b\\U00001a56\\U00001a58-\\U00001a5e"
    "\\U00001a60\\U00001a62\\U00001a65-\\U00001a6c\\U00001a73-\\U00001a7c\\U00001a7f"
    "\\U00001ab0-\\U00001abd\\U00001abf-\\U00001ace\\U00001b00-\\U00001b03\\U00001b34"
    "\\U00001b36-\\U00001b3a\\U00001b3c\\U00001b42\\U00001b6b-\\U00001b73\\U00001b80-\\U00001b81"
    "\\U00001ba2-\\U00001ba5\\U00001ba8-\\U00001ba9\\U00001bab-\\U00001bad\\U00001be6"
    "\\U00001be8-\\U00001be9\\U00001bed\\U00001bef-\\U00001bf1\\U00001c2c-\\U00001c33"
    "\\U00001c36-\\U00001c37\\U00001cd0-\\U00001cd2\\U00001cd4-\\U00001ce0\\U00001ce2-\\U00001ce8"
    "\\U00001ced\\U00001cf4\\U00001cf8-\\U00001cf9\\U00001dc0-\\U00001dff\\U0000203f-\\U00002040"
    "\\U00002054\\U000020d0-\\U000020dc\\U000020e1\\U000020e5-\\U000020f0\\U00002cef-\\U00002cf1"
    "\\U00002d7f\\U00002de0-\\U00002dff\\U0000302a-\\U0000302d\\U00003099-\\U0000309a\\U0000a66f"
    "\\U0000a674-\\U0000a67d\\U0000a69e-\\U0000a69f\\U0000a6f0-\\U0000a6f1\\U0000a802\\U0000a806"
    "\\U0000a80b\\U0000a825-\\U0000a826\\U0000a82c\\U0000a8c4-\\U0000a8c5\\U0000a8e0-\\U0000a8f1"
    "\\U0000a8ff\\U0000a926-\\U0000a92d\\U0000a947-\\U0000a951\\U0000a980-\\U0000a982\\U0000a9b3"
    "\\U0000a9b6-\\U0000a9b9\\U0000a9bc-\\U0000a9bd\\U0000a9e5\\U0000aa29-\\U0000aa2e"
    "\\U0000aa31-\\U0000aa32\\U0000aa35-\\U0000aa36\\U0000aa43\\U0000aa4c\\U0000aa7c\\U0000aab0"
    "\\U0000aab2-\\U0000aab4\\U0000aab7-\\U0000aab8\\U0000aabe-\\U0000aabf\\U0000aac1"
    "\\U0000aaec-\\U0000aaed\\U0000aaf6\\U0000abe5\\U0000abe8\\U0000abed\\U0000fb1e"
    "\\U0000fe00-\\U0000fe0f\\U0000fe20-\\U0000fe2f\\U0000fe33-\\U0000fe34\\U0000fe4d-\\U0000fe4f"
    "\\U0000ff3f\\U000101fd\\U000102e0\\U00010376-\\U0001037a\\U00010a01-\\U00010a03"
    "\\U00010a05-\\U00010a06\\U00010a0c-\\U00010a0f\\U00010a38-\\U00010a3a\\U00010a3f"
    "\\U00010ae5-\\U00010ae6\\U00010d24-\\U00010d27\\U00010eab-\\U00010eac\\U00010efd-\\U00010eff"
    "\\U00010f46-\\U00010f50\\U00010f82-\\U00010f85\\U00011001\\U00011038-\\U00011046\\U00011070"
    "\\U00011073-\\U00011074\\U0001107f-\\U00011081\\U000110b3-\\U000110b6\\U000110b9-\\U000110ba"
    "\\U000110c2\\U00011100-\\U00011102\\U00011127-\\U0001112b\\U0001112d-\\U00011134\\U00011173"
    "\\U00011180-\\U00011181\\U000111b6-\\U000111be\\U000111c9-\\U000111cc\\U000111cf"
    "\\U0001122f-\\U00011231\\U00011234\\U00011236-\\U00011237\\U0001123e\\U00011241\\U000112df"
    "\\U000112e3-\\U000112ea\\U00011300-\\U00011301\\U0001133b-\\U0001133c\\U00011340"
    "\\U00011366-\\U0001136c\\U00011370-\\U00011374\\U00011438-\\U0001143f\\U00011442-\\U00011444"
    "\\U00011446\\U0001145e\\U000114b3-\\U000114b8\\U000114ba\\U000114bf-\\U000114c0"
    "\\U000114c2-\\U000114c3\\U000115b2-\\U000115b5\\U000115bc-\\U000115bd\\U000115bf-\\U000115c0"
    "\\U000115dc-\\U000115dd\\U00011633-\\U0001163a\\U0001163d\\U0001163f-\\U00011640\\U000116ab"
    "\\U000116ad\\U000116b0-\\U000116b5\\U000116b7\\U0001171d-\\U0001171f\\U00011722-\\U00011725"
    "\\U00011727-\\U0001172b\\U0001182f-\\U00011837\\U00011839-\\U0001183a\\U0001193b-\\U0001193c"
    "\\U0001193e\\U00011943\\U000119d4-\\U000119d7\\U000119da-\\U000119db\\U000119e0"
    "\\U00011a01-\\U00011a0a\\U00011a33-\\U00011a38\\U00011a3b-\\U00011a3e\\U00011a47"
    "\\U00011a51-\\U00011a56\\U00011a59-\\U00011a5b\\U00011a8a-\\U00011a96\\U00011a98-\\U00011a99"
    "\\U00011c30-\\U00011c36\\U00011c38-\\U00011c3d\\U00011c3f\\U00011c92-\\U00011ca7"
    "\\U00011caa-\\U00011cb0\\U00011cb2-\\U00011cb3\\U00011cb5-\\U00011cb6\\U00011d31-\\U00011d36"
    "\\U00011d3a\\U00011d3c-\\U00011d3d\\U00011d3f-\\U00011d45\\U00011d47\\U00011d90-\\U00011d91"
    "\\U00011d95\\U00011d97\\U00011ef3-\\U00011ef4\\U00011f00-\\U00011f01\\U00011f36-\\U00011f3a"
    "\\U00011f40\\U00011f42\\U00013440\\U00013447-\\U00013455\\U00016af0-\\U00016af4"
    "\\U00016b30-\\U00016b36\\U00016f4f\\U00016f8f-\\U00016f92\\U00016fe4\\U0001bc9d-\\U0001bc9e"
    "\\U0001cf00-\\U0001cf2d\\U0001cf30-\\U0001cf46\\U0001d167-\\U0001d169\\U0001d17b-\\U0001d182"
    "\\U0001d185-\\U0001d18b\\U0001d1aa-\\U0001d1ad\\U0001d242-\\U0001d244\\U0001da00-\\U0001da36"
    "\\U0001da3b-\\U0001da6c\\U0001da75\\U0001da84\\U0001da9b-\\U0001da9f\\U0001daa1-\\U0001daaf"
    "\\U0001e000-\\U0001e006\\U0001e008-\\U0001e018\\U0001e01b-\\U0001e021\\U0001e023-\\U0001e024"
    "\\U0001e026-\\U0001e02a\\U0001e08f\\U0001e130-\\U0001e136\\U0001e2ae\\U0001e2ec-\\U0001e2ef"
    "\\U0001e4ec-\\U0001e4ef\\U0001e8d0-\\U0001e8d6\\U0001e944-\\U0001e94a\\U000e0100-\\U000e01ef"
)

#: PCRE2 UCP `\w` — what `\w`, and therefore `\b`, mean in a PHP pattern that carries
#: `/u`: letters, numbers, non-spacing marks and connector punctuation. A fragment for
#: inside `[…]`.
#:
#: Python's own `\w` is `L u N u _` — right for the first two categories and nothing else —
#: so the marks and the remaining connectors are added from the baked table. (`_` is in
#: `Pc`, so the table carries it twice over; a duplicate inside `[…]` costs nothing.)
#:
#: PCRE2 before 10.43 leaves out the marks and every connector but `_`, so a PHP host on an
#: older library differs next to one of those; the corpus measures PHP 8.4 (10.44), and this
#: follows it.
UCP_WORD = f"\\w{_MN_PC}"

#: Categories `Lu` and `Lt` — the letters that count as UPPER case. GENERATED, same as
#: `_MN_PC` above and `_LL` below.
_LU_LT = (
    "\\U00000041-\\U0000005a\\U000000c0-\\U000000d6\\U000000d8-\\U000000de\\U00000100\\U00000102"
    "\\U00000104\\U00000106\\U00000108\\U0000010a\\U0000010c\\U0000010e\\U00000110\\U00000112"
    "\\U00000114\\U00000116\\U00000118\\U0000011a\\U0000011c\\U0000011e\\U00000120\\U00000122"
    "\\U00000124\\U00000126\\U00000128\\U0000012a\\U0000012c\\U0000012e\\U00000130\\U00000132"
    "\\U00000134\\U00000136\\U00000139\\U0000013b\\U0000013d\\U0000013f\\U00000141\\U00000143"
    "\\U00000145\\U00000147\\U0000014a\\U0000014c\\U0000014e\\U00000150\\U00000152\\U00000154"
    "\\U00000156\\U00000158\\U0000015a\\U0000015c\\U0000015e\\U00000160\\U00000162\\U00000164"
    "\\U00000166\\U00000168\\U0000016a\\U0000016c\\U0000016e\\U00000170\\U00000172\\U00000174"
    "\\U00000176\\U00000178-\\U00000179\\U0000017b\\U0000017d\\U00000181-\\U00000182\\U00000184"
    "\\U00000186-\\U00000187\\U00000189-\\U0000018b\\U0000018e-\\U00000191\\U00000193-\\U00000194"
    "\\U00000196-\\U00000198\\U0000019c-\\U0000019d\\U0000019f-\\U000001a0\\U000001a2\\U000001a4"
    "\\U000001a6-\\U000001a7\\U000001a9\\U000001ac\\U000001ae-\\U000001af\\U000001b1-\\U000001b3"
    "\\U000001b5\\U000001b7-\\U000001b8\\U000001bc\\U000001c4-\\U000001c5\\U000001c7-\\U000001c8"
    "\\U000001ca-\\U000001cb\\U000001cd\\U000001cf\\U000001d1\\U000001d3\\U000001d5\\U000001d7"
    "\\U000001d9\\U000001db\\U000001de\\U000001e0\\U000001e2\\U000001e4\\U000001e6\\U000001e8"
    "\\U000001ea\\U000001ec\\U000001ee\\U000001f1-\\U000001f2\\U000001f4\\U000001f6-\\U000001f8"
    "\\U000001fa\\U000001fc\\U000001fe\\U00000200\\U00000202\\U00000204\\U00000206\\U00000208"
    "\\U0000020a\\U0000020c\\U0000020e\\U00000210\\U00000212\\U00000214\\U00000216\\U00000218"
    "\\U0000021a\\U0000021c\\U0000021e\\U00000220\\U00000222\\U00000224\\U00000226\\U00000228"
    "\\U0000022a\\U0000022c\\U0000022e\\U00000230\\U00000232\\U0000023a-\\U0000023b"
    "\\U0000023d-\\U0000023e\\U00000241\\U00000243-\\U00000246\\U00000248\\U0000024a\\U0000024c"
    "\\U0000024e\\U00000370\\U00000372\\U00000376\\U0000037f\\U00000386\\U00000388-\\U0000038a"
    "\\U0000038c\\U0000038e-\\U0000038f\\U00000391-\\U000003a1\\U000003a3-\\U000003ab\\U000003cf"
    "\\U000003d2-\\U000003d4\\U000003d8\\U000003da\\U000003dc\\U000003de\\U000003e0\\U000003e2"
    "\\U000003e4\\U000003e6\\U000003e8\\U000003ea\\U000003ec\\U000003ee\\U000003f4\\U000003f7"
    "\\U000003f9-\\U000003fa\\U000003fd-\\U0000042f\\U00000460\\U00000462\\U00000464\\U00000466"
    "\\U00000468\\U0000046a\\U0000046c\\U0000046e\\U00000470\\U00000472\\U00000474\\U00000476"
    "\\U00000478\\U0000047a\\U0000047c\\U0000047e\\U00000480\\U0000048a\\U0000048c\\U0000048e"
    "\\U00000490\\U00000492\\U00000494\\U00000496\\U00000498\\U0000049a\\U0000049c\\U0000049e"
    "\\U000004a0\\U000004a2\\U000004a4\\U000004a6\\U000004a8\\U000004aa\\U000004ac\\U000004ae"
    "\\U000004b0\\U000004b2\\U000004b4\\U000004b6\\U000004b8\\U000004ba\\U000004bc\\U000004be"
    "\\U000004c0-\\U000004c1\\U000004c3\\U000004c5\\U000004c7\\U000004c9\\U000004cb\\U000004cd"
    "\\U000004d0\\U000004d2\\U000004d4\\U000004d6\\U000004d8\\U000004da\\U000004dc\\U000004de"
    "\\U000004e0\\U000004e2\\U000004e4\\U000004e6\\U000004e8\\U000004ea\\U000004ec\\U000004ee"
    "\\U000004f0\\U000004f2\\U000004f4\\U000004f6\\U000004f8\\U000004fa\\U000004fc\\U000004fe"
    "\\U00000500\\U00000502\\U00000504\\U00000506\\U00000508\\U0000050a\\U0000050c\\U0000050e"
    "\\U00000510\\U00000512\\U00000514\\U00000516\\U00000518\\U0000051a\\U0000051c\\U0000051e"
    "\\U00000520\\U00000522\\U00000524\\U00000526\\U00000528\\U0000052a\\U0000052c\\U0000052e"
    "\\U00000531-\\U00000556\\U000010a0-\\U000010c5\\U000010c7\\U000010cd\\U000013a0-\\U000013f5"
    "\\U00001c90-\\U00001cba\\U00001cbd-\\U00001cbf\\U00001e00\\U00001e02\\U00001e04\\U00001e06"
    "\\U00001e08\\U00001e0a\\U00001e0c\\U00001e0e\\U00001e10\\U00001e12\\U00001e14\\U00001e16"
    "\\U00001e18\\U00001e1a\\U00001e1c\\U00001e1e\\U00001e20\\U00001e22\\U00001e24\\U00001e26"
    "\\U00001e28\\U00001e2a\\U00001e2c\\U00001e2e\\U00001e30\\U00001e32\\U00001e34\\U00001e36"
    "\\U00001e38\\U00001e3a\\U00001e3c\\U00001e3e\\U00001e40\\U00001e42\\U00001e44\\U00001e46"
    "\\U00001e48\\U00001e4a\\U00001e4c\\U00001e4e\\U00001e50\\U00001e52\\U00001e54\\U00001e56"
    "\\U00001e58\\U00001e5a\\U00001e5c\\U00001e5e\\U00001e60\\U00001e62\\U00001e64\\U00001e66"
    "\\U00001e68\\U00001e6a\\U00001e6c\\U00001e6e\\U00001e70\\U00001e72\\U00001e74\\U00001e76"
    "\\U00001e78\\U00001e7a\\U00001e7c\\U00001e7e\\U00001e80\\U00001e82\\U00001e84\\U00001e86"
    "\\U00001e88\\U00001e8a\\U00001e8c\\U00001e8e\\U00001e90\\U00001e92\\U00001e94\\U00001e9e"
    "\\U00001ea0\\U00001ea2\\U00001ea4\\U00001ea6\\U00001ea8\\U00001eaa\\U00001eac\\U00001eae"
    "\\U00001eb0\\U00001eb2\\U00001eb4\\U00001eb6\\U00001eb8\\U00001eba\\U00001ebc\\U00001ebe"
    "\\U00001ec0\\U00001ec2\\U00001ec4\\U00001ec6\\U00001ec8\\U00001eca\\U00001ecc\\U00001ece"
    "\\U00001ed0\\U00001ed2\\U00001ed4\\U00001ed6\\U00001ed8\\U00001eda\\U00001edc\\U00001ede"
    "\\U00001ee0\\U00001ee2\\U00001ee4\\U00001ee6\\U00001ee8\\U00001eea\\U00001eec\\U00001eee"
    "\\U00001ef0\\U00001ef2\\U00001ef4\\U00001ef6\\U00001ef8\\U00001efa\\U00001efc\\U00001efe"
    "\\U00001f08-\\U00001f0f\\U00001f18-\\U00001f1d\\U00001f28-\\U00001f2f\\U00001f38-\\U00001f3f"
    "\\U00001f48-\\U00001f4d\\U00001f59\\U00001f5b\\U00001f5d\\U00001f5f\\U00001f68-\\U00001f6f"
    "\\U00001f88-\\U00001f8f\\U00001f98-\\U00001f9f\\U00001fa8-\\U00001faf\\U00001fb8-\\U00001fbc"
    "\\U00001fc8-\\U00001fcc\\U00001fd8-\\U00001fdb\\U00001fe8-\\U00001fec\\U00001ff8-\\U00001ffc"
    "\\U00002102\\U00002107\\U0000210b-\\U0000210d\\U00002110-\\U00002112\\U00002115"
    "\\U00002119-\\U0000211d\\U00002124\\U00002126\\U00002128\\U0000212a-\\U0000212d"
    "\\U00002130-\\U00002133\\U0000213e-\\U0000213f\\U00002145\\U00002183\\U00002c00-\\U00002c2f"
    "\\U00002c60\\U00002c62-\\U00002c64\\U00002c67\\U00002c69\\U00002c6b\\U00002c6d-\\U00002c70"
    "\\U00002c72\\U00002c75\\U00002c7e-\\U00002c80\\U00002c82\\U00002c84\\U00002c86\\U00002c88"
    "\\U00002c8a\\U00002c8c\\U00002c8e\\U00002c90\\U00002c92\\U00002c94\\U00002c96\\U00002c98"
    "\\U00002c9a\\U00002c9c\\U00002c9e\\U00002ca0\\U00002ca2\\U00002ca4\\U00002ca6\\U00002ca8"
    "\\U00002caa\\U00002cac\\U00002cae\\U00002cb0\\U00002cb2\\U00002cb4\\U00002cb6\\U00002cb8"
    "\\U00002cba\\U00002cbc\\U00002cbe\\U00002cc0\\U00002cc2\\U00002cc4\\U00002cc6\\U00002cc8"
    "\\U00002cca\\U00002ccc\\U00002cce\\U00002cd0\\U00002cd2\\U00002cd4\\U00002cd6\\U00002cd8"
    "\\U00002cda\\U00002cdc\\U00002cde\\U00002ce0\\U00002ce2\\U00002ceb\\U00002ced\\U00002cf2"
    "\\U0000a640\\U0000a642\\U0000a644\\U0000a646\\U0000a648\\U0000a64a\\U0000a64c\\U0000a64e"
    "\\U0000a650\\U0000a652\\U0000a654\\U0000a656\\U0000a658\\U0000a65a\\U0000a65c\\U0000a65e"
    "\\U0000a660\\U0000a662\\U0000a664\\U0000a666\\U0000a668\\U0000a66a\\U0000a66c\\U0000a680"
    "\\U0000a682\\U0000a684\\U0000a686\\U0000a688\\U0000a68a\\U0000a68c\\U0000a68e\\U0000a690"
    "\\U0000a692\\U0000a694\\U0000a696\\U0000a698\\U0000a69a\\U0000a722\\U0000a724\\U0000a726"
    "\\U0000a728\\U0000a72a\\U0000a72c\\U0000a72e\\U0000a732\\U0000a734\\U0000a736\\U0000a738"
    "\\U0000a73a\\U0000a73c\\U0000a73e\\U0000a740\\U0000a742\\U0000a744\\U0000a746\\U0000a748"
    "\\U0000a74a\\U0000a74c\\U0000a74e\\U0000a750\\U0000a752\\U0000a754\\U0000a756\\U0000a758"
    "\\U0000a75a\\U0000a75c\\U0000a75e\\U0000a760\\U0000a762\\U0000a764\\U0000a766\\U0000a768"
    "\\U0000a76a\\U0000a76c\\U0000a76e\\U0000a779\\U0000a77b\\U0000a77d-\\U0000a77e\\U0000a780"
    "\\U0000a782\\U0000a784\\U0000a786\\U0000a78b\\U0000a78d\\U0000a790\\U0000a792\\U0000a796"
    "\\U0000a798\\U0000a79a\\U0000a79c\\U0000a79e\\U0000a7a0\\U0000a7a2\\U0000a7a4\\U0000a7a6"
    "\\U0000a7a8\\U0000a7aa-\\U0000a7ae\\U0000a7b0-\\U0000a7b4\\U0000a7b6\\U0000a7b8\\U0000a7ba"
    "\\U0000a7bc\\U0000a7be\\U0000a7c0\\U0000a7c2\\U0000a7c4-\\U0000a7c7\\U0000a7c9\\U0000a7d0"
    "\\U0000a7d6\\U0000a7d8\\U0000a7f5\\U0000ff21-\\U0000ff3a\\U00010400-\\U00010427"
    "\\U000104b0-\\U000104d3\\U00010570-\\U0001057a\\U0001057c-\\U0001058a\\U0001058c-\\U00010592"
    "\\U00010594-\\U00010595\\U00010c80-\\U00010cb2\\U000118a0-\\U000118bf\\U00016e40-\\U00016e5f"
    "\\U0001d400-\\U0001d419\\U0001d434-\\U0001d44d\\U0001d468-\\U0001d481\\U0001d49c"
    "\\U0001d49e-\\U0001d49f\\U0001d4a2\\U0001d4a5-\\U0001d4a6\\U0001d4a9-\\U0001d4ac"
    "\\U0001d4ae-\\U0001d4b5\\U0001d4d0-\\U0001d4e9\\U0001d504-\\U0001d505\\U0001d507-\\U0001d50a"
    "\\U0001d50d-\\U0001d514\\U0001d516-\\U0001d51c\\U0001d538-\\U0001d539\\U0001d53b-\\U0001d53e"
    "\\U0001d540-\\U0001d544\\U0001d546\\U0001d54a-\\U0001d550\\U0001d56c-\\U0001d585"
    "\\U0001d5a0-\\U0001d5b9\\U0001d5d4-\\U0001d5ed\\U0001d608-\\U0001d621\\U0001d63c-\\U0001d655"
    "\\U0001d670-\\U0001d689\\U0001d6a8-\\U0001d6c0\\U0001d6e2-\\U0001d6fa\\U0001d71c-\\U0001d734"
    "\\U0001d756-\\U0001d76e\\U0001d790-\\U0001d7a8\\U0001d7ca\\U0001e900-\\U0001e921"
)

#: Guards that SUBTRACT a case category from a wider letter class.
#:
#: A domain's TLD is a label in one case (spintax-js#79), which wants `\p{Ll}\p{Lm}\p{Lo}`
#: and `\p{Lu}\p{Lt}\p{Lm}\p{Lo}` — unions of categories Python cannot write inside
#: `[…]`. Since the five letter categories partition `\p{L}`, each union is the whole of
#: `\p{L}` minus the other case: put one of these in front of `JS_LETTER` (or of
#: `JS_LETTER_OR_NUMBER`, to keep the numbers) and the result is exact.
#:
#: The obvious shortcut — `re.IGNORECASE` off and a `\p{Ll}` class — is what the reference
#: could not use either: under a case-insensitive flag JavaScript folds a Unicode property
#: and matches capitals with `\p{Ll}`, while PCRE2 leaves the property alone. Python folds
#: like JavaScript, so `<p>ǅivot</p>` capitalized to `Ǆ` where PHP keeps the titlecase letter.
NOT_UPPERCASE_LETTER = f"(?![{_LU_LT}])"
NOT_LOWERCASE_LETTER = f"(?![{_LL}])"


#: PHP's `trim` charlist. Narrower than both Python's `str.strip()` (Unicode whitespace)
#: and JavaScript's — it is exactly these five characters, including NUL and vertical tab.
#: The plugin trims permutation config, element text, separators and plural forms, so
#: using anything wider here changes which templates round-trip identically.
PHP_TRIM_CHARS = " \t\n\r\0\x0b"
