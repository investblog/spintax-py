# P3 — `analyze`, and the `Ast` input path

Status: **active**. Governing contract: [`spec-python-port.md`](spec-python-port.md).
Previous: [`plan-p2.md`](plan-p2.md) — all 168 corpus fixtures pass, 0 xfailed, 0 skipped.

## What P3 must close

The corpus is already green, so **the counter cannot move at all this milestone**. That is not a
reason to relax: it means every line of P3 is ungated by the shared fixtures, which is precisely
the shape that shipped five surviving mutations when `#include` landed.

Three `NotImplementedError`s remain, and they are not one item but two:

| Entry point | State |
|---|---|
| `analyze()` | not built |
| `validate(Ast)` | raises — "pass the source string for now" |
| `extract(Ast)` | raises — same |

### The `Ast` path is the bigger half

Spec §4 opens with: *"All functions accept a `str` **or** a parsed `Ast`, so a host parses once and
reuses."* That sentence is the entire reason `Ast` is part of the public API — and three of the five
entry points currently refuse it. A host that follows the documented pattern gets an exception.

The fix is small because `ParsedAst` already carries `source`: the raw-text checks that `validate`
and `extract` are built from read it directly, exactly as the reference's `resolveAst` does. What
needs care is the **failure** path, which is the same one `render_with` already has: a foreign or
stale handle must raise `AstVersionError`, and a bare `Ast()` must not reach a `.source` that is
not there.

### `analyze` itself is thirty lines

It composes what exists: `extract` + `validate` + a census over the tree. The census counts node
types via `walk`, plus two directive counts. Nothing new is computed.

## The census counts `set` and not `def` — decide, do not copy

Measured on the reference:

```
analyze('#set %a% = {x|y}\n#def %b% = 1\n…')
  → constructs: { enumeration: 1, permutation: 1, variable: 1, conditional: 1,
                  plural: 1, set: 1, include: 1 }
```

`defs: ["b"]` appears in the extraction, and `def` appears nowhere in the census. That reads like an
oversight left over from `#def` arriving in AST version 2, not a decision.

**Decision: match the reference — no `def` key — and raise it upstream instead.** `constructs` is a
mapping a host iterates, so adding a key the TypeScript engine does not emit breaks the "one mental
model across three engines" argument that settled the error classes one milestone ago. If the census
should count definitions, it should count them in all three engines, and that starts with an issue
on `spintax-js`, not a silent divergence here. Recorded in `REGISTRY`-style terms: the port is
deliberately reproducing a suspected upstream bug, and saying so.

## `Analysis` stays nested, unlike the reference's flat object

The reference spreads the extraction across the top level (`{refs, sets, defs, includes,
diagnostics, constructs}`). This port declared `Analysis(extraction, diagnostics, constructs)` back
at P0 and keeps it: a typed dataclass with a nested `Extraction` is what a Python consumer expects,
`Extraction` is already public and already returned by `extract()`, and flattening would mean two
shapes for one thing. §3 lists internal architecture as allowed to diverge; this is that.

## Steps

1. **`Ast` input for `validate` and `extract`.** Resolve `str | Ast` in one place, shared with the
   pipeline's existing resolver so the version guard is written once.
2. **`analyze`.** Census helper in `_analyze.py`, wiring in `__init__.py`.
3. **Tests, measured against the reference.** No fixture covers any of this. Every expectation is a
   measurement from `@spintax/core` 0.3.0 — the first draft of the last ungated test file had 18
   wrong expectations and 0 wrong implementation because it was written by reading the port.
4. **Docs.** README status, the module docstring's "still raises" list, and the spec's §4.

## What the corpus will not catch

Everything in this milestone. Named specifically, so the local tests have targets:

- That `parse()` then `validate(ast)` gives the same diagnostics as `validate(src)` — the whole
  point of the handle.
- That a foreign or bare `Ast` raises rather than returning a plausible empty answer.
- That the census counts NESTED nodes, not just top-level ones.
- That `include` counts occurrences and `set` counts distinct names — two different things, and the
  reference computes them from two different sources.

## Definition of done

1. No `NotImplementedError` left in the public API.
2. The corpus stays at 168 passed, 0 xfailed, 0 skipped.
3. Every new test verified to gate against a deliberate break.
4. `ruff`, `mypy` and the packaging job green on 3.10–3.13, checked before the claim is made.
5. The upstream census question is filed, not just written down here.
