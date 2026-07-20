# P2 — parser, renderer, post-process

Status: **COMPLETE** — all 168 corpus fixtures pass, 0 xfailed, 0 skipped. Governing contract: [`spec-python-port.md`](spec-python-port.md).
Previous: [`plan-p1.md`](plan-p1.md) — `validate()` and `extract()` are done and green.

P1 left the suite at **180 passed, 126 xfailed, 0 skipped**. That xfail count is P2's progress
metric, and unlike P1 it does not move step by step from the start — see *Why the counter stays
still at first*.

## What P2 must close

Everything that is left. All 126 remaining xfails, across six fixture files:

| File | Cases | What it demands |
|---|---:|---|
| `render-semantics.json` | 59 | the node types, variable scope, `#include`, leniency |
| `render-postprocess.json` | 39 | the cosmetic pass |
| `render-rng-selection.json` | 10 | which option a given draw sequence selects |
| `render-deterministic.json` | 6 | exact output under a fixed strategy |
| `render-rng.json` | 4 | seeded `make_rng`, structural invariants only |
| `neutralize.json` | 8 | shielding round-trips |
| **Total** | **126** | |

`analyze()` is the only public entry point P2 does not fill; it is the whole of P3 along with docs.

### Scope correction: `neutralize` is P2, not P3

The third boundary this port has moved by reading the reference rather than the milestone list.
The spec files `neutralize` under P3. It belongs here, for three reasons that compound:

1. **The pipeline cannot run without it.** `renderWith` opens with `stripSentinels` on string input
   and closes with `safetyRestore` — always, even when `postProcess` is off. They are the first and
   last stages, not an optional extra.
2. **Seven of the eight fixtures are `op=render`.** Only `neutralize/identity-plain` calls the
   function directly; the rest neutralize a context value, render, and assert the structural
   characters came back as literal glyphs having never been read as markup. They need the renderer.
   Seven cases also carry a `neutralizeContext` key, which exists solely for this.
3. **The function itself is three lines** over a map the other two stages already need.

So the module lands whole. Leaving `neutralize()` unimplemented while shipping its two halves would
be bookkeeping that costs more than the work.

## Why the counter stays still at first

P1 could order its steps so each one turned a named set of xfails green. P2 cannot, and pretending
otherwise would hide the risk. **No render fixture passes until the parser, the renderer and the
pipeline all exist** — there is no partial credit for a tree nobody walks.

The answer is a walking skeleton: get the narrowest end-to-end path working early (literal text and
enumerations, wired through `render_with`), then add one node type at a time. From step 2 onward
every step moves the counter; steps 0–1 are enabling work with local tests only, and are the one
stretch where the corpus is silent about progress.

## Steps

### 0. Foundations — `_rng`, `_neutralize`, `_ast`

Three small modules, none of which move a fixture on their own.

`_rng.py` is **not** a port of the reference's mulberry32 + FNV-1a — see *Decision: no
cross-engine sequence parity*. It wraps a per-call `random.Random`, and its docstring carries the
one fact the renderer author has to know: the engine short-circuits `min == max` before calling the
rng at all, so a default-config permutation spends zero draws on its size pick. `_neutralize.py` is the sentinel map:
`{ } [ ] % #` to U+E000–U+E005, with `neutralize` / `safety_restore` / `strip_sentinels`.
`_ast.py` is the node model — six node types, `AST_VERSION = 2`, `ParsedAst` carrying
`source` + `set_defs` + `def_defs` + `nodes`, and a depth-first `walk`.

### 1. Parser → the tree

The step P1 deferred, and the largest single piece (426 reference lines). Literal, variable,
enumeration, permutation, conditional, plural. Two ordering constraints the reference comments call
out explicitly, both of which are the kind that look arbitrary until they break something:

- The permutation `<config>` prefix is extracted **before** splitting on `|`, so a `|` inside a
  quoted separator (`sep="|"`) is not a false split.
- A malformed `{?…}` is **not** a conditional — the parser falls back to reading the braces as an
  enumeration, matching the plugin, where a bad conditional survives its pass untouched and is then
  eaten by the enumeration pass.

Directives are not tree nodes. `_directives.py` already extracts them line-anchored, and that is
where they stay.

> **What actually happened at step 2: steps 2–6 landed together.** The skeleton was planned
> narrow — literal, variable, enumeration — on the assumption that each further node type
> would be its own increment. Reading `render.ts` showed the increments were not separable:
> the node types share one `_Walk`, one draw-ordering contract and one variable map, and a
> renderer that handled three of six would have had to be rewritten rather than extended for
> the other three. So permutations, conditionals, plurals and `#include` shipped in the same
> commit, and the counter moved from 125 xfails to 43 in one step instead of five.
>
> The prediction that held exactly was the *split*: 82 fixtures carry `postProcess: false`
> and all 82 went green; the remaining 43 are precisely the ones that need step 7.

### 2. Walking skeleton — literal + variable + enumeration, wired end to end

`render_with` assembled in one place, in the reference's order: strip sentinels → parse → walk →
post-process (if on) → safety-restore (always). Deliberately assembled **once**, in the pipeline
module, and never re-composed by the test harness — spec §5.1's second lesson is that the PHP port
hand-composed stages in its corpus test and therefore certified a replica instead of the shipped
orchestration. This port's harness calls `render_with`.

Expected to move `render-deterministic` and a first slice of `render-semantics`.

### 3. Permutation

`<config>` parsing (`minsize`/`maxsize`/`sep`/`lastsep`), per-element separators, selection and
join. `null` size means the default rules at render time, §4.2.

### 4. Conditionals

`{?VAR?then|else}` and the inverted `{?!VAR?then}`, over the truthiness table P1 already validates.

### 5. Plurals

The renderer half only — `_plurals.py` exists with `normalize_base_lang`, the arity table and
`find_blocks`, because P1 needed arity to validate. Both slots are kept raw and variables are
expanded in them first; the lenient path re-emits with fullwidth braces.

### 6. `#include`

Resolved by the renderer as a post-tree string pass (the plugin resolves includes after enum/perm),
so includes stay literal in the tree. Carries the depth and cycle guard: too deep or circular
resolves to an empty string, never an exception.

### 7. Post-process — 39 cases ✅

Done, and the fixtures were the smaller half of the verification. 39 cases is a spot check
of a dozen interacting rules whose order matters, so the pass was differentially fuzzed
against the reference on 1922 inputs. That found two divergences the corpus is blind to:

- **A mistranslated `` — 64 of 1922.** JavaScript's word boundary needs a TRANSITION;
  rendering it as "no word character before" invents boundaries wherever the next
  character is also non-word, which — JavaScript's word set being ASCII — is every
  Cyrillic or accented letter. `приме.com` was shielded as a domain here and left alone
  there, so the spacing and capitalization passes skipped text the reference rewrites.
- **A broadened `\p{Ll}` — 1 of 1922.** Matching any letter and filtering for lowercase in
  the callback reads as equivalent and is not: the broadened match still CONSUMES its
  region, so reaching an uppercase letter through an HTML tag swallows a lowercase one
  further in. Found *after* that reasoning had been written into a docstring as safe.

Both fixed; 1922/1922 now identical. A curated 614-case slice is frozen as
`tests/data/postprocess_parity.json`.

## Decision: no cross-engine sequence parity

`mulberry32` and the FNV-1a string hash would port in about fifteen lines of masked 32-bit
arithmetic, and doing so would make a seeded render byte-identical to TypeScript today.

Declining, because spec §3 makes sequence parity an explicit **non-goal**, which means the
reference is free to change its PRNG in a patch release. Matching it here would manufacture a
promise the engine we are matching has not made: Python users would come to rely on identical
output, and an upstream change we neither control nor get notified about would break them. A
property that holds by luck is worse than one that was never claimed.

What is promised instead: deterministic **within this engine** — same seed, same output, stable
across Python versions. The four `render-rng.json` cases assert structural invariants only, so they
do not care either way; this is a choice about what to promise, not about passing the corpus.

## Decision made: the error classes mirror the reference

`SpintaxError`, `AstVersionError` and `IncludeResolverError` ship in `_errors.py` and are
exported. `NotImplementedError` is the one the reference defines that this port does not — Python
has it built in, and shadowing a builtin to gain nothing is a poor trade.

Nothing in the corpus forced this, so the deciding argument was the one below: the ecosystem's
value is a single mental model across three engines, and a second vocabulary for the same two
failures taxes exactly the person moving between them. Both are about the CALLER — a stale handle,
a resolver that threw — never about a template, which stays lenient.

## Original framing of that decision

The reference exports `SpintaxError`, `IncludeResolverError`, `AstVersionError` and
`NotImplementedError`. Our `__all__` has none of them, and `render_with` needs at least the version
guard — handing a foreign or stale `Ast` to the renderer has to fail loudly rather than silently
drop every `#def`, which is exactly why `AST_VERSION` went to 2 upstream.

**No fixture forces this.** All 126 remaining cases are `op: render` or `op: neutralize`, and not
one asserts a thrown error, so this is a local API decision rather than a parity obligation.
Leaning toward mirroring the reference's names: the ecosystem's value is one mental model across
engines, and gratuitously different exception names tax exactly the person moving between them.

## The `\p{L}` problem — Q5, and it is bigger than a footnote

Python's `re` has no Unicode property escapes. The reference uses them in eight places, seven of
them in `postprocess.ts`, so this lands squarely on the 39-case fixture block. Zero runtime
dependencies is a hard rule (§7), so the `regex` module that would solve this in one import is not
available.

The mapping below was **measured across the whole Unicode range** against `unicodedata.category`,
not reasoned about. That matters: the first three answers this plan carried were all wrong, and the
obvious one was wrong in the most expensive way — `[^\W\d_]` looks like `\p{L}` and disagrees on
1151 code points, because Python's `\w` includes `Nl` and `No`. Under it, `²` and `½` are letters.

| Reference | Python `re` | Verified |
|---|---|---|
| `[\p{L}\p{N}]` | `[^\W_]` | **exact**, and free |
| `\p{Nd}` | `\d` | **exact**, and free |
| `\p{L}` | `(?![«Nl∪No»])[^\W\d_]` | **exact**, needs one constant |
| `\p{N}` | `\d` widened by the same constant | **exact**, same constant |
| `\p{Ll}` | — | **no table-free form exists** |

The identity underneath the first four is that Python's `\w` decomposes exactly as `L ∪ N ∪ _`,
which is why `[^\W_]` lands on `L ∪ N` on the nose and `[^\W\d_]` lands on `L ∪ Nl ∪ No`.
Subtracting `Nl ∪ No` from the latter therefore gives `\p{L}` exactly — and that set is only **81
ranges, 1624 characters** of class text, small enough to be a constant rather than a table.

`\p{Ll}` has no such escape. Every table-free predicate tried fails, and they fail on real letters
rather than exotica: `str.islower()` is off by 311 (it accepts `Lo`/`Lm` code points such as `ª`),
and adding `upper() != c` to fix that breaks 825 more — U+0138 `ĸ` is `Ll` and simply has no
uppercase pair. So the four capitalization rules get either a generated 658-range class or a
callback testing `unicodedata.category(c) == "Ll"`, which is exact wherever a callback can reach.
One reference use needs no regex at all: `/^\p{L}+$/u` on a trimmed string is `str.isalpha()`,
which measured **exactly** equal to categories `L*` with zero disagreements.

**These constants are interpreter-derived, and that is a maintenance edge.** Python 3.10 and 3.13
ship different Unicode versions, so a baked literal is frozen to whichever built it. Building at
import instead costs a 0.23 s sweep of 1.1 M code points on every import, which is not acceptable
for a library. So: bake the constant, and carry a test that rebuilds it from the running
`unicodedata` and asserts equality. The four-interpreter CI matrix then answers the question we
cannot answer locally — if a supported Python disagrees, a test says so by name instead of a
superscript quietly becoming a letter.

## Two places this port is deliberately MORE correct than the reference

Found by differential fuzzing, both harmless, both recorded so a future "parity failure"
report does not chase them:

- **Plural counts above 2^53.** `{plural 10000000000000001: one|few|many}` in `ru` gives
  `many` here and `one` there, because JavaScript's `Number.parseInt` rounds the count to
  `1e16` while Python's `int` is exact. Matching the reference would mean deliberately
  losing precision.
- **`%constructor%` and `%__proto__%`.** The reference looks variables up in an object
  literal, so `constructor` resolves to `Object` and throws, and `__proto__` renders
  empty. A Python `dict` has no prototype, so both stay verbatim — which is also what a
  reader of the template would expect.

Neither is on §3's allowed-to-diverge list, and neither is worth adding to it as a
promise; they are noted here as facts.

## What the corpus will not catch

Carried forward from P1, because it stays true and P2 has more surface for it:

- **Leniency is undertested by construction.** The fixtures assert what a malformed template
  renders to, not that nothing raised on the way. A stage that throws where the contract says it
  must degrade will be caught only where a fixture happens to cover that shape.
- **`max_depth` and include cycles.** One fixture family, many ways to get the guard subtly wrong
  (off-by-one on depth, a stack that is not popped, a cycle detected only at the top level).
- **The RNG seam.** Draw *count* is the only thing separating `#set` from `#def`, and only a
  sequence strategy makes it observable. A renderer that rolls at the wrong moment can still pass
  every fixed-strategy case.

Local tests carry these, in the pattern P1 established: a test whose docstring says what breaks if
the assertion is deleted.

## Definition of done

1. All 126 remaining fixtures pass — 306 passed, 0 xfailed, 0 skipped.
2. `render_with` is the only renderer, and the harness calls it. No stage order is written down a
   second time anywhere in this repository.
3. Every step's local tests are verified to gate — each one demonstrated failing against a
   deliberate break, not merely observed passing.
4. `ruff`, `mypy` and the packaging job green on every supported interpreter, checked before the
   claim is made rather than after CI contradicts it.
5. The two decisions above are resolved in the spec, not just here.
