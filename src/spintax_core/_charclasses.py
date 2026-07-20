"""Character classes where Python's regex dialect is WIDER than JavaScript's.

Every constant here exists because the obvious Python escape silently accepts more than
the reference does. `\\w`, `\\d` and `\\b` are ASCII in JavaScript — always, `u` flag
included — and Unicode in Python; `\\s` differs in both directions. Left alone, this port
would quietly accept syntax the other engines reject, which is the worst kind of parity
bug: nothing fails, the engines just disagree about what a template means.

PHP is a third dialect again — `/u` turns on PCRE_UCP, so PHP's `\\w` is Unicode and
already diverges from TypeScript. That is upstream's problem; this file only guarantees
Python matches the reference it is porting.

Held here rather than in whichever module needed it first: `_directives`, `_validator` and
`_parser` all want them now, and a constant copied into three files is a constant that
will drift in two of them.
"""

from __future__ import annotations

#: JavaScript's `\w` — and therefore its `\b`, which is defined in terms of it.
ASCII_WORD = "[A-Za-z0-9_]"

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

#: PHP's `trim` charlist. Narrower than both Python's `str.strip()` (Unicode whitespace)
#: and JavaScript's — it is exactly these five characters, including NUL and vertical tab.
#: The plugin trims permutation config, element text, separators and plural forms, so
#: using anything wider here changes which templates round-trip identically.
PHP_TRIM_CHARS = " \t\n\r\0\x0b"
