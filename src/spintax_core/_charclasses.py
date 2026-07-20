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

#: PHP's `trim` charlist. Narrower than both Python's `str.strip()` (Unicode whitespace)
#: and JavaScript's — it is exactly these five characters, including NUL and vertical tab.
#: The plugin trims permutation config, element text, separators and plural forms, so
#: using anything wider here changes which templates round-trip identically.
PHP_TRIM_CHARS = " \t\n\r\0\x0b"
