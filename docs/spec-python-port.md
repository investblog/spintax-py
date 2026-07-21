# Spintax Python engine — `spintax-core` (spec draft)

Status: **SHIPPED — P0 through P4 complete** ([`plan-p1.md`](plan-p1.md),
[`plan-p2.md`](plan-p2.md), [`plan-p3.md`](plan-p3.md)). **`spintax-core` is published on
[PyPI](https://pypi.org/project/spintax-core/)** (first release 0.1.0, 2026-07-20; see the git tags
for the current version). All 168 corpus fixtures pass, 0 xfailed, 0 skipped. Every entry point —
`parse`, `render`, `validate`, `extract`, `analyze`, `neutralize` — is built and takes a `str` or a
parsed `Ast`. Idea captured 2026-07-13; revised 2026-07-19 for engine 3.0.0 (`#def`, `#set` reverted
to macro, BCS plurals). All questions below are answered or recorded as deliberate; this file is now
a record of the decisions, not a plan of open ones.
Owner: 301st
Canonical location: this file, `W:\projects\spintax-py\docs\spec-python-port.md`.

> **Cross-repo paths.** This is the third engine in the Spintax family. Unless a path is
> absolute, it is local to this repo. The other repos:
>
> | repo | what | license |
> | --- | --- | --- |
> | `W:\projects\spintax` | WordPress plugin — the **origin** PHP engine | GPL |
> | `W:\projects\spintax-js` | `@spintax/core` (TS/npm) + **the golden corpus** | MIT |
> | `W:\spintax-java` | Java origin | — |
> | this repo | `spintax-core` (Python/PyPI) | MIT |

## 1. Why

The PyPI incumbent, `spintax`, is **GPLv3** and its last release was **2018-11-11** (checked
2026-07-13). GPL is a hard blocker for commercial/SaaS adoption, so a maintained MIT engine is
a positioning story, not just another parser — it is the same wedge that already worked on npm
(the WP plugin stays GPL; `@spintax/core` ships MIT).

Python is also where the LLM pipelines live, and the project's pitch — *the model drafts the
template once, the engine spins it locally, offline, free, with no per-generation API call* —
lands hardest in that stack.

Tracking issue: [spintax-js#43](https://github.com/investblog/spintax-js/issues/43).

## 2. Scope

An **independent** Python implementation of the Spintax engine: `parse` / `render` / `validate` /
`extract` / `analyze` / `neutralize`. Framework-agnostic, zero runtime dependencies, MIT.

**Not in scope** (host concerns — same split as the TS engine, spec §9.3): batching /
`render_batch`, "N variants", exact variant cardinality, async `#include` fetching, a large typed
error hierarchy.

## 3. The parity contract (inherited — this is the whole point)

Parity is enforced by the **shared golden corpus**: language-neutral JSON fixtures
`(template, context, locale, seed) → expected`, already consumed by the TS suite and by a
WP-free PHPUnit runner against the real plugin engine.

**Parity REQUIRED** (machine-checked, exact output):

- accepted syntax surface
- validation verdicts (valid ⇔ no `severity: "error"`; unresolved `%var%` is a **warning**)
- plural grammar buckets (locale-sensitive)
- `{?…}` truthiness
- **directive semantics**: `#set` is a **macro** — re-substituted, and any spintax inside it
  re-rolled, at every reference; `#def` resolves **once per render** and holds that result
  everywhere. (Engine 3.0.0 reverted `#set` to macro expansion and moved roll-once to `#def`.
  The pre-3.0.0 draft of this spec listed "`#set` collapse-once" here — that behaviour no longer
  exists under that name, and porting it would have reproduced a retracted contract.)
- **`#def` constraints**: `#include` inside a `#def` value is a validation error; a name belongs to
  a single `#set` or `#def`; a `{plural}` count that resolves through a `#set` macro still holding
  spintax is an error, not a silent empty render
- the **post-process pipeline** (shielding / spacing / capitalization)

**Allowed to diverge:** RNG selection results, internal architecture, diagnostic message strings,
performance. Seeded rendering must be reproducible **within** this engine; cross-engine
RNG-sequence parity is a **non-goal**.

### 3.1 What may be used as a reference — and what may not

- **The PHP plugin engine is GPL. Do NOT transcribe it.** Reimplement from the behavior contract
  and the corpus, exactly as the TS port did — transcribing would pull GPL into an MIT package.
- **`@spintax/core` (TS) is our own MIT code, so it *is* a legitimate reference.** Reading it, and
  even mirroring its structure, is legally fine. But *idiomatic* Python is still the goal: mirror
  the **behavior**, not the TypeScript. Where the TS shape fights Python (see §6), the corpus wins
  and the TS loses.

## 4. Public API (mirrors the TS §9.2, snake_cased)

All functions accept a `str` **or** a parsed `Ast`, so a host parses once and reuses.

```python
def parse(src: str) -> Ast: ...

def render(
    input: str | Ast,
    *,
    context: Mapping[str, str] | None = None,
    seed: int | str | None = None,          # omit ⇒ nondeterministic
    locale: str | None = None,              # plural buckets; 3-form: ru/uk/be + sr/hr/bs
    include_resolver: Callable[[str], str | None] | None = None,   # host-injected, SYNC
    post_process: bool = True,              # default ON, like the TS engine
    max_depth: int = 20,
) -> str: ...

def validate(
    input: str | Ast,
    *,
    locale: str | None = None,
    known_includes: Sequence[str] | None = None,
    known_variables: Sequence[str] | None = None,
) -> list[Diagnostic]: ...

def extract(input: str | Ast) -> Extraction: ...        # refs / sets / defs / includes
def analyze(input: str | Ast, **opts) -> Analysis: ...  # extract + validate + constructs census
def neutralize(value: str) -> str: ...                  # text-safe shielding of untrusted values
```

### 4.1 The RNG seam — required, not an implementation detail

```python
Rng = Callable[[int, int], int]          # (min, max) -> int; a bounded value, NOT an index

def make_rng(seed: int | str | None) -> Rng: ...
def render_with(input: str | Ast, rng: Rng, **opts: object) -> str: ...
```

**`render_with` is the only renderer**; `render` must be a thin wrapper that builds an `Rng` and
delegates to it. This is a contract, not a convenience:

- The corpus injects a choice source — 19 fixtures carry an explicit `rng` (`first` / `last` / a
  sequence) and the reference harness defaults the rest to `first`. Without the seam those cases
  cannot run at all, and the remaining ones become coin flips.
- The seam is what makes `#set` vs `#def` observable. The semantics differ only in **how many
  draws** a template takes, so under a fixed strategy both render identically. A sequence RNG is
  the discriminator; `{a|a|a}` proves nothing under either.
- One renderer, not two. A harness-only path beside the real one is how stage order ends up
  written in five places (see §5.1).

Invariants carried over from the TS engine:

- **`render` is lenient** — it never raises on malformed markup; a bad block is emitted verbatim
  with fullwidth braces `｛…｝`. Too-deep / circular `#include` resolves to `""`, it does not raise.
- **`Ast` is opaque and versioned** — an in-memory perf handle, not a serialization format. Do not
  persist it across engine versions.
- **`neutralize`'s safety restore is mandatory** — it survives `post_process=False` (that flag
  skips cosmetics only).
- `Diagnostic` carries `severity`, `code`, `message`, `line`, `column`, and optional `end_line`,
  `end_column`, `data`, so a consumer builds UI without parsing the (non-parity-gated) `message`.

## 5. Milestones (corpus-first, mirroring what worked for TS)

- **P0 — fixture access + corpus runner.** Q4 is decided (env var + CI checkout); stand up a pytest
  runner over the shared fixtures, green on an empty engine — every fixture reported as *expected
  failure*, none silently skipped. **Before any engine code.**
- **P1 — validator + `extract`.** ✅ Done. `validate.json` green (verdicts are the strictest
  gate), plus `extract.json`. Three boundaries moved by reading the fixtures rather than the plan
  — see [`plan-p1.md`](plan-p1.md): plural **arity** validation is P1 (14 cases carry a locale);
  `extract` came forward from P3; and the **parser went the other way, to P2**, because neither
  `validate` nor `extract` needs a tree — both are raw-text scanners, by design.
- **P2 — parser + renderer + post-process + neutralize.** The `Ast` lands here, with the renderer
  that is the first thing to need it. Seeded render; deterministic render + post-process fixtures
  green; RNG fixtures pass structural invariants only. **`neutralize` moved here from P3** — see
  [`plan-p2.md`](plan-p2.md): its `strip_sentinels` / `safety_restore` halves are the pipeline's
  first and last stages, and 7 of the 8 `neutralize.json` cases are `op: render` round-trips that
  cannot pass without the renderer anyway. P2 therefore closes all 126 remaining fixtures.
- **P3 — analyze + docs.** API surface complete (`extract` landed in P1, `neutralize` in P2).
  `analyze` is small — it composes `extract`, `validate` and a construct census over the tree,
  all of which exist. **But there is no `analyze.json`**, so like `#include` it is entirely
  ungated by the corpus and needs local tests measured against the reference. Note also that
  the reference's census counts `setDefs` and not `defDefs`, which looks like an oversight left
  from when `#def` was added; decide deliberately rather than copying it by reflex.
- **P4 — publish `0.1.0` to PyPI.** Claim `spintax-core` early (see Q1) but publish only here.

### 5.1 What the other three ports paid for

Four lessons the TS, PHP and OpenCart ports learned the expensive way. They are here because
each one is invisible until it has already cost something.

**Corpus-first works, and it is why the family has not drifted.** The TS engine was built against
the shared corpus from M0. That ordering is not ceremony — it is the reason three engines still
agree. P0 exists for this reason and must stay ahead of P1.

**But a green corpus does not certify a renderer.** The PHP `GoldenCorpusTest` reproduces the
pipeline by hand, so what it attests to is the primitives *and that replica* — not the shipped
orchestration. Stage order is already written down in four places (the plugin, the package, that
replica, the OpenCart orchestrator); a fifth would rot like the others. **So this port must not
hand-compose stages in its test harness.** The runner calls `render_with` — the engine's own and
only pipeline, which `render` also delegates to. If a stage order ever needs asserting, assert it
through the public entry point, never by re-implementing it beside the engine.

**A seeded RNG is the only thing that distinguishes `#set` from `#def`.** The semantics differ
solely in *how many draws* a template takes: a macro re-rolls per reference, a definition rolls
once. Under a fixed `first` strategy both render identically, and `{a|a|a}` proves nothing under
either. This is why `render_with` takes an injected `Rng` at all, and why the sequence strategy is
load-bearing rather than a convenience — see `tests/test_rng_strategy.py`, which pins it while the
engine is still empty.

**A verification narrower than its claim is worse than none** — it converts an unknown into a
wrong answer. In the session that produced this milestone the same mistake happened three times:
a SQL check scoped to a library while the admin controller sat outside it (shipped), a lint whose
own docblock recommended the pattern it was meant to ban, and this runner's RNG wiring, which was
wrong while the suite reported an unchanged, reassuring 160 xfails. The habit that catches it:
before believing a green, break the thing on purpose and watch the check go red.

### 5.2 Surfaces the corpus does NOT gate (know these before trusting a green)

The corpus is the acceptance gate, and it is not total. Three surfaces have no fixture behind
them today, so an implementation can be wrong about them with the suite fully green:

- **`known_variables`.** `validate()` accepts it to suppress `variable.undefined` for names the
  host supplies at render time, but the fixture schema has no `knownVariables` field, so no case
  exercises it. Break the suppression and nothing goes red. Cover it with local tests until the
  schema grows the field (which is the real fix — the same gap exists for TS and PHP).
- **`max_depth` and `include_resolver` behaviour beyond the circular case.** The corpus asserts
  that a too-deep or circular include resolves to `""`; it does not pin the budget itself.
- **Non-ASCII identifiers, anywhere.** No fixture contains one, so nothing pins whether
  `#set %имя% = X` is a directive or a malformed line. It is not a hypothetical gap: JavaScript's
  `\w` is ASCII-only even under the `u` flag, while PCRE's `/u` enables UCP and makes PHP's `\w`
  Unicode-aware — so **TS and PHP already disagree**, on the very first item this spec marks
  parity-REQUIRED. This port follows TS, the stricter of the two, because a narrower accepted
  syntax can be widened later without breaking a template that already works. Covered locally in
  `tests/test_ascii_parity.py`. **Decided 2026-07-20: this port stays ASCII and does not chase
  the difference.** Widening it would mean either diverging from the reference on purpose or
  reopening the question for three engines and a published package, to support identifiers
  nobody has asked for. If a real template ever needs them, the narrower rule can be widened
  without breaking anything that already works — which is the whole reason for choosing it.
- **Comments.** Not one of the 168 fixtures contains a `/#` at all, so comment stripping — and
  therefore every position that passes through it — is held up by local tests alone.
- **Diagnostic ORDER.** `validate()` returns findings sorted by position; the reference returns
  them in check order. The corpus matches diagnostics by `any()`, so it cannot see the difference,
  and §3's allowed-to-diverge list does not mention ordering either way. Treated as a deliberate
  divergence: a consumer reading a template top to bottom is better served by source order than
  by the order the checks happen to run in. Recorded here so it is a decision rather than a
  discovery.
- **`line` / `column` on every diagnostic.** **Zero** fixtures assert a position, so the corpus is
  green whatever the numbers say — while the public `Diagnostic` type promises them and editor
  integrations depend on them. Track positions in the parser from the start (retrofitting means
  touching every construct twice) and cover them locally.

Recorded rather than silently trusted: a gate you believe is total, and is not, is worse than one
you know the edges of.

### 5.2a Line terminators: a break for the rules, a character for the output

Python's `^`/`$` end a line at `\n` alone. JavaScript's also end one at a bare `\r`, U+2028 and
U+2029 — so without help a CR-terminated file has its whole remainder swallowed into one `#set`
value and the directive after it is never seen.

The engine therefore matches against a copy whose terminators are normalised, and **cuts the body
from the text as authored**. Both halves matter, and the reference shows why in one line:

```
render("#set %x% = A\r%x%", {postProcess: false})  ->  "\rA"
```

The CR ended the directive — otherwise `%x%` would never resolve — *and* it reached the output
unchanged. A renderer that emits from the normalised copy would print `"\nA"` and silently rewrite
the author's bytes.

Two rules follow, and both are pinned by `tests/test_terminators_and_body.py`:

- **`Source.text` is a scanning view.** `validate` and `extract` never return template text, which
  is why normalising it is safe for them. Nothing that renders may emit from it.
- **`_directives.extract` normalises for itself.** It does not assume a caller has done it, so a
  parser reaching for the module directly cannot reintroduce the swallowing bug.

The one exception, and it belongs to the grammar rather than to this: `DIRECTIVE_RE` ends
`[ \t]*\r?$`, so the CR of a **CRLF** line ending is part of the directive's own line and leaves
with it. `"#set %x% = A\r\n%x%"` renders `"\nA"`, matching the reference.

### 5.3 Implementation notes that are contract, not style

- **`definition.duplicate-name` requires preserving directive *occurrences* before any map is
  built.** The obvious implementation — fold directives into a `dict[str, str]` and validate the
  dict — has already lost duplicates once in the PHP pass, because the second assignment silently
  overwrites the first and there is nothing left to report. Collect occurrences first, diagnose,
  then collapse.

## 6. Design questions — all decided (kept as a record of why)

### Q1 — package name and import name ✅ ANSWERED
Published as dist **`spintax-core`**, import **`spintax_core`**. `spintax_core` avoids the collision
`import spintax` would have with the abandoned GPLv3 `spintax` package, and the dist name lines up
with `@spintax/core`.

### Q2 — minimum Python version ✅ ANSWERED
**3.10+** (`requires-python >=3.10`). It buys `X | Y` unions and `match` with zero dependencies;
`3.9` would have needed `typing_extensions`. Revisit only if a real consumer is stuck on 3.9.

### Q3 — RNG
Seeds are `int | str` and must be **reproducible within this engine**. Two paths:

- **`random.Random(seed)`** (stdlib Mersenne Twister). Cheap, but ties reproducibility to CPython's
  guarantee, and `str` seeds hash differently from the TS engine anyway.
- **Port the TS PRNG shape** (mulberry32 + FNV-1a for `str` seeds). Full control, tiny, and the
  seed → sequence mapping is ours, not the runtime's.

Cross-engine sequence parity is a non-goal either way, so this is purely a robustness call.

✅ **ANSWERED (P2 step 0): `random.Random`, one instance per `make_rng` call.** The
recommendation above was to port the small PRNG, and it was not followed. Porting mulberry32 would
have made a seeded render byte-identical to TypeScript *today* — and that is the argument against
it, not for it. Parity is a non-goal in this very section, so the reference may change its PRNG in
a patch release; matching it would manufacture a promise upstream has not made, and Python users
who came to rely on it would be broken by a change nobody here controls or is told about.

The "hostage to a stdlib implementation detail" worry is real but narrower than it reads. Python
guarantees the sequence of `Random.random()` for a given seed, so the bounded draw is computed from
`random()` rather than delegated to `randint()`, and `seed(…, version=2)` is passed explicitly so a
future change of default cannot silently re-map string seeds. What is promised is therefore exactly
what is guaranteed, and no more.

> **Note on seed UX** (already learned in the TS engine, do not re-learn it): distinct seeds are
> *independent draws, not distinct results*. A low-cardinality template will repeat across seeds.
> N-unique-variants is a **host** job (dedupe + cap retries), not an engine promise.

### Q4 — how does this repo get the golden corpus? ✅ ANSWERED 2026-07-19
**Decided: env var locally, `actions/checkout` of the corpus repo in CI. Never vendor it.**

This was marked blocking, and it was — until `spintax-php` solved it in production. Its CI checks
out `investblog/spintax-js` into `.corpus` and points `SPINTAX_FIXTURES` at
`.corpus/packages/conformance/fixtures`; the runner reads that env var and skips with an
actionable message when it is unset. So the pattern is not a proposal here, it is a second
non-JS engine already living on it, and copying a proven recipe beats inventing a third.

The publish-a-fixtures-package options are dropped rather than deferred. Both fork the
distribution of the corpus, and the objection that killed them is written into the PHP runner:
*a copy would drift, and a drifting contract is not a contract.* A checkout is always the file
the other engines are tested against; a package is a snapshot of it that ages silently.

Concretely for this repo:

```yaml
- uses: actions/checkout@v4
  with:
    repository: investblog/spintax-js
    path: .corpus
# then, on the test step:
#   SPINTAX_FIXTURES: ${{ github.workspace }}/.corpus/packages/conformance/fixtures
```

Locally: `SPINTAX_FIXTURES=/path/to/spintax-js/packages/conformance/fixtures pytest`.

The one residual weakness, inherited knowingly: the corpus is pinned to whatever the default
branch of `spintax-js` holds at run time, so an upstream fixture change turns this suite red
without a commit here. That is the intended failure mode — it is how a contract announces that
the engines have diverged.

### Q5 — Unicode in post-process ✅ ANSWERED (P2), and the first-draft answer was WRONG
Python's stdlib `re` has no Unicode property escapes — `re.compile(r"\p{L}")` raises `bad escape
\p`. The third-party `regex` module would break the zero-dependency rule. All of this is centralised
in `src/spintax_core/_charclasses.py`, each constant carrying its measured divergence set. Read that
file before touching any post-process or parser regex; the summary here is a map, not the territory.

**`[^\W\d_]` is NOT `\p{L}` — this was the draft answer and it is a trap.** It disagrees on 1151
code points, because Python's `\w` includes categories `Nl` and `No`, so under it `²` and `½` parse
as letters. The identities that actually hold, measured across the whole Unicode range:

- `[\p{L}\p{N}]` **is** `[^\W_]` exactly (Python's `\w` = `L ∪ N ∪ _`).
- `\p{L}` is `[^\W\d_]` **minus** `Nl ∪ No` — an 81-range baked constant (`_NL_NO`).
- `\p{Ll}` has **no** table-free form (`U+0138 ĸ` defeats every `upper()`-based predicate); it is a
  658-range baked constant. Both tables are generated and frozen; `tests/test_charclass_tables.py`
  rebuilds them from the running `unicodedata` and asserts COVERAGE (not equality — they track the
  reference's Unicode version, not Python's).

Two more traps in the same territory, both found only by differential fuzzing after being reasoned
about wrongly first:

- **`\b` is ASCII in JS and Unicode in Python, and needs a TRANSITION, not a one-sided lookaround.**
  Translating it as "no word char before" invents boundaries wherever the next char is also
  non-word — which, JS's word set being ASCII, is every accented or Cyrillic letter. `приме.com`
  was shielded as a domain here and left alone there. See `JS_WORD_BOUNDARY`.
- **`re.IGNORECASE` means three different things.** Python always folds Turkish `İ`/`ı`→`i`; JS
  `/iu` never does; JS `/i` **without** `u` also won't fold `ſ`→`s`. The reference uses `/giu` in
  post-process and `/i` (no `u`) in the parser's config keys — so `[<ſep="x">…]` and `[<mınsize=2>…]`
  meant different things in the two engines. Hence `js_ci_unicode` (keep the flag, exclude the
  Turkic pair via scoped `(?-i:…)`) and `js_ci_ascii` (drop the flag, spell the case out).

The post-process and config patterns are **rewritten**, never transliterated from the TS source,
and the shared fixtures plus `tests/test_case_folding.py` are what keep them honest. This is the
single most likely place for a silent parity break; do it with the corpus wired and fuzz against the
reference, never blind.

### Q6 — `#include` resolution ✅ ANSWERED
Stays **synchronous and host-injected** (`Callable[[str], str | None]`), same as TS. Async sources
use the two-phase pattern: `extract().includes` → host prefetches → sync map resolver. The circular
guard and scope isolation (a child inherits global+runtime vars, **not** the parent's local
`#set` **or** `#def` definitions — both are template-local, and naming only one invites the
leak that already had to be fixed once in the plugin)
live in the engine; the fetch does not. *No `async def render`. Not now, probably not ever.*

## 7. Conventions

- Zero runtime dependencies. Dev deps (pytest, ruff, mypy) are fine.
- Type-annotated, `mypy --strict` clean.
- Every behavior change is argued against the golden corpus, not vibes.
