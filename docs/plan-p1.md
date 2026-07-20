# P1 — parser, validator, extract

Status: **complete**, with one step moved rather than done. `validate()` and `extract()` are
wired and every case in `validate.json` and `extract.json` passes. Governing contract:
[`spec-python-port.md`](spec-python-port.md). Next: P2 (parser + renderer).

P0 left the corpus running against an empty engine: **7 passed, 168 xfailed, 0 skipped**. P1's
progress metric is that number moving — every step below turns a named set of xfails into passes,
and no step is "done" until its cases pass for the reason intended.

## What P1 must close

`validate.json` — 40 cases (15 valid, 25 invalid) across **17 distinct diagnostic codes** — plus
`extract.json` (2 cases). That is 42 of the 168.

Two scope corrections against the spec's milestone list, both found by reading the fixtures rather
than the plan:

- **Plural *arity* belongs to P1, not P2.** 14 validate cases carry a `locale` and 5 assert
  `plural.arity`, so `normalize_base_lang` and the arity table are P1 work. Rendering plurals
  stays P2; deciding whether a template *could* render is P1.
- **`extract` is pulled forward from P3.** Once the parser exists, the names are already collected
  for the diagnostics — `refs`, `sets`, `defs`, `includes` fall out of work P1 has to do anyway.
  Leaving it in P3 would mean building the same index twice.

## Steps

Ordered so that each one moves the counter, and the hardest lands last against a suite that is
already mostly green.

### 1. Parser → `Ast` — **moved to P2, not done**

Reading the reference before writing any of it showed the premise was wrong: `validate` and
`extract` are raw-text scanners *by design*, because the AST is lenient — an unbalanced bracket
is not represented in it at all, and a `[…]` body stays a raw string. Neither needs a tree, so
building one first would have been a week with no case moving. It is P2's opening, where the
renderer actually requires it. `parse()` still raises.

What did survive from this step is the position work, and it moved into `_source.py`: comment
stripping keeps a map back to the original offsets, so a diagnostic points at the place the
author is looking at rather than at a place that existed before the comments were removed.

### 2. Structural diagnostics — 8 codes

`bracket.unclosed`, `bracket.mismatched`, `bracket.unexpected-closing`, `set.malformed`,
`def.malformed`, `permutation.minsize-not-integer`, `permutation.maxsize-not-integer`,
`permutation.unknown-key`.

Mechanical, and the first visible movement in the corpus.

### 3. Variable graph — 3 codes

`variable.self-reference`, `variable.circular-reference`, `variable.undefined` (a **warning**, and
the only one that must not flip a verdict to invalid).

`known_variables` suppression is implemented here and **is not gated by the corpus** — the fixture
schema has no such field. It needs local tests or it can break silently.

### 4. Plural diagnostics — 2 codes, 14 cases touched

`normalize_base_lang` (`sr-Latn` → `sr`, `pt-BR` → `pt`; three-letter tags are *not* mapped) plus
the arity table: 3 forms for `ru`/`uk`/`be`/`sr`/`hr`/`bs`, 2 for everything else — including
`pl`/`cs`/`sk`/`sl`/`bg`, which are wrong-but-accepted by design.

Then `plural.arity`. Note an empty or absent locale **skips** the arity check entirely.

`plural.nested-brackets` lands here too, and needs no locale: a form slot must be plain text, so
`{plural 1: {a|b}|c}` is rejected structurally. Keep it distinct from step 6 — this one is about
brackets *inside a form*, that one about a count that only becomes bracketed after expansion.

### 5. Definitions and includes — 3 codes

`definition.duplicate-name`, `def.include-in-value`, and `include.unknown-target`.

The include check is the only diagnostic that depends on caller-supplied data: it fires only when
`known_includes` is non-empty, so with no list every target is assumed to exist. Two fixtures
cover it, and one of them is a *valid* verdict — a circular include is a runtime outcome, not a
static error.

Read spec §5.3 before writing this: duplicate detection requires keeping directive **occurrences**
until after the diagnostic runs. Folding directives into a `dict[str, str]` first destroys the
evidence — the second assignment overwrites the first and there is nothing left to report. The PHP
pass lost duplicates exactly this way.

### 6. `plural.count-macro` — 1 code, 5 cases, and the real work

A taint analysis, not a node check. A count slot is poisoned when it resolves — possibly through a
chain of `#set` aliases — to a value that still holds unresolved spintax at the moment plurals run.

```
#set %m% = {1|4|9}            # chained alias: taint must reach %n%
#set %n% = %m%
{plural %n%: item|items}      # error

#set %n% = {?flag?{1|4}|2}    # a conditional is exempt (resolves before plurals)…
{plural %n%: item|items}      # …but the enumeration inside it is not — still an error
```

The rule is **stage order**, not bracket-spotting: conditionals resolve before the plural pass, so
they are the single exemption; a nested `{plural …}` is not. Propagate to a fixed point — a
one-pass walk gets `plural-count-macro` right and `plural-count-macro-chained` wrong.

There is a paired case where a conditional count **is valid**. If both pass, the rule is a rule; if
only the error cases pass, it is over-eager and the valid one will say so.

### 7. `extract`

`refs` / `sets` / `defs` / `includes` from the index step 3 already built. `sets` and `defs` are
separate buckets — the whole point of the fixture we added upstream.

## What the corpus will not catch

Local tests are mandatory for these; a green corpus says nothing about any of them:

| surface | why it is invisible |
| --- | --- |
| `line` / `column` | **zero** fixtures assert positions |
| `known_variables` | no such field in the fixture schema |
| `max_depth` | only the circular-include outcome is pinned |
| `parse` itself | no fixtures; only observable through other ops |

## Why `validate()` is not wired yet

The corpus reports by **op**: while `validate` raises `NotImplementedError` every one of its 40
cases is an xfail, which reads as "not built". Wire a half-finished validator and those cases run
for real — the ones whose codes exist pass, the rest **fail** — and the suite goes red for work
that was never claimed to be done. Red would stop meaning "something broke".

So the checks are proved by their own tests first, and the public entry point flips exactly once,
when all seventeen codes exist. That is the same reason the reference suite lights up by op
rather than by code.

## Definition of done

- `validate.json` and `extract.json` fully green — 42 cases moved from xfail to pass.
- The corpus's 42 P1 cases move from xfail to passed, and no case is ever skipped. The absolute
  totals are deliberately not written down here: they change with every local test added, and a
  number in a document is a number that goes stale.
- Local tests covering the ungated surfaces above, each verified by breaking the implementation
  and watching the test fail — not by observing that it passes. `max_depth` is excluded: it is a
  render budget, so it belongs to P2 with the code that enforces it.
- `mypy --strict` and `ruff` clean.
