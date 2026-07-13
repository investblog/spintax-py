# Spintax Python engine — `spintax-core` (spec draft)

Status: **DRAFT / pre-code.** Idea captured 2026-07-13; nothing is scheduled.
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
- `#set` collapse-once semantics
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
    locale: str | None = None,              # plural buckets, e.g. "ru" (3-form)
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

def extract(input: str | Ast) -> Extraction: ...        # refs / sets / includes
def analyze(input: str | Ast, **opts) -> Analysis: ...  # extract + validate + constructs census
def neutralize(value: str) -> str: ...                  # text-safe shielding of untrusted values
```

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

- **P0 — fixture access + corpus runner.** Decide §6 Q4, stand up a pytest runner over the shared
  fixtures, green on an empty engine. **Before any engine code.**
- **P1 — parser + validator.** Full syntax surface; `validate.json` green (verdicts are the
  strictest gate).
- **P2 — renderer + post-process.** Seeded render; deterministic render + post-process fixtures
  green; RNG fixtures pass structural invariants only.
- **P3 — extract + neutralize + analyze + docs.** API surface complete.
- **P4 — publish `0.1.0` to PyPI.** Claim `spintax-core` early (see Q1) but publish only here.

## 6. Open questions — decide these BEFORE writing code

### Q1 — package name and import name
Dist name **`spintax-core`** is free on PyPI (checked 2026-07-13), consistent with `@spintax/core`.
Import name: **`spintax_core`** is the safe pick — `import spintax` would collide with the
abandoned GPLv3 `spintax` package if both are installed. *Recommendation: `spintax-core` /
`spintax_core`. Claim the name on PyPI before someone else does.*

### Q2 — minimum Python version
`3.10+` buys `X | Y` unions and `match`, with **zero** dependencies. `3.9` widens reach but needs
`typing_extensions` (a dependency) or uglier typing. *Recommendation: 3.10+, revisit only if a
real consumer is stuck on 3.9.*

### Q3 — RNG
Seeds are `int | str` and must be **reproducible within this engine**. Two paths:

- **`random.Random(seed)`** (stdlib Mersenne Twister). Cheap, but ties reproducibility to CPython's
  guarantee, and `str` seeds hash differently from the TS engine anyway.
- **Port the TS PRNG shape** (mulberry32 + FNV-1a for `str` seeds). Full control, tiny, and the
  seed → sequence mapping is ours, not the runtime's.

Cross-engine sequence parity is a non-goal either way, so this is purely a robustness call.
*Recommendation: implement the small PRNG — the engine's RNG should not be a hostage to a stdlib
implementation detail.*

> **Note on seed UX** (already learned in the TS engine, do not re-learn it): distinct seeds are
> *independent draws, not distinct results*. A low-cardinality template will repeat across seeds.
> N-unique-variants is a **host** job (dedupe + cap retries), not an engine promise.

### Q4 — how does this repo get the golden corpus? ⚠ blocking for P0
The fixtures live in `spintax-js` (`packages/conformance/fixtures/*.json`) and are currently read
**by local path**. A third engine is the forcing function for spec **Q3** in the TS repo. Options:

1. **Env var + local path**, mirroring the existing PHP runner (`SPINTAX_PLUGIN_SRC` precedent) —
   fastest, works today, but is dev-machine-bound.
2. **Publish `@spintax/conformance`** (npm) and vendor a synced copy here — awkward for a Python
   repo to consume npm.
3. **Publish a `spintax-conformance` package on PyPI** carrying the same fixtures — cleanest for
   Python, but forks the distribution of the corpus.

*Recommendation: start with (1) to unblock P0, and treat (2)/(3) as the real fix before publishing
`0.1.0` — a published engine whose acceptance suite only runs on one laptop is not a parity gate.*

### Q5 — Unicode in post-process ⚠ real trap, already verified
The TS post-process leans on `\p{L}` / `\p{N}` with the `u` flag. **Python's stdlib `re` does NOT
support Unicode property escapes** — `re.compile(r"\p{L}")` raises `bad escape \p` (verified on
CPython 3.13). The obvious fix, the third-party `regex` module, would **break the zero-dependency
rule.**

Stdlib workaround, verified: `[^\W\d_]` (with the default Unicode semantics of `str` patterns)
matches Unicode letters, including Cyrillic —
`re.findall(r"[^\W\d_]+", "Привет мир 42 test-case")` → `['Привет', 'мир', 'test', 'case']`.

So the domain/URL/email shielding patterns must be **rewritten**, not transliterated from the TS
source. This is the single most likely place for a silent parity break, and the post-process
fixtures (including the Cyrillic ones) are what will catch it. *Do the post-process pass with the
corpus already wired, never blind.*

### Q6 — `#include` resolution
Stays **synchronous and host-injected** (`Callable[[str], str | None]`), same as TS. Async sources
use the two-phase pattern: `extract().includes` → host prefetches → sync map resolver. The circular
guard and scope isolation (a child inherits global+runtime vars, **not** the parent's `#set` locals)
live in the engine; the fetch does not. *No `async def render`. Not now, probably not ever.*

## 7. Conventions

- Zero runtime dependencies. Dev deps (pytest, ruff, mypy) are fine.
- Type-annotated, `mypy --strict` clean.
- Every behavior change is argued against the golden corpus, not vibes.
