# spintax-core (Python)

> **Status: P1 in progress — the validator is being built.** The shared golden corpus runs from
> commit one and reports what is not built yet as *expected failures*, so the remaining work is a
> number on every test run. Nothing is published yet.

A framework-agnostic **[Spintax](https://spintax.net) engine** for Python — parse, render,
validate, extract, analyze, and neutralize spintax templates. MIT, zero runtime dependencies.

This is the third engine in the Spintax family, and an **independent implementation** — not a
transcription of the others. It is held to the same behavior contract by a **shared golden corpus**
of language-neutral fixtures, which already gates the TypeScript engine and the PHP one.

- **Spec:** [`docs/spec-python-port.md`](docs/spec-python-port.md) — read it before writing any
  code. It records the parity contract, the API surface, and the open questions. Corpus access
  (Q4) is decided; Unicode in post-process (Q5) is a known trap with a verified stdlib answer,
  and lands with P2.
- **Sibling engines:** [`@spintax/core`](https://www.npmjs.com/package/@spintax/core) (TypeScript,
  MIT, published) · [Spintax for WordPress](https://wordpress.org/plugins/spintax/) (PHP, GPL, the
  origin).
- **Tracking issue:** [investblog/spintax-js#43](https://github.com/investblog/spintax-js/issues/43).

## Why

The existing PyPI `spintax` package is **GPLv3** and has not shipped since **2018**. GPL blocks
commercial adoption; this one is MIT and maintained.

## License

[MIT](LICENSE). The WordPress plugin remains GPL; MIT/Expat is GPL-compatible.

---

Part of the [301.st](https://301.st) toolset. Product home: [spintax.net](https://spintax.net).

## Development

The test suite **is** the shared golden corpus — the same JSON fixtures the TypeScript and PHP
engines are tested against, read from a checkout rather than vendored here. A copy would drift,
and a drifting contract is not a contract.

```sh
git clone https://github.com/investblog/spintax-js ../spintax-js   # once
python -m venv .venv && .venv/bin/pip install -e . pytest
SPINTAX_FIXTURES=../spintax-js/packages/conformance/fixtures pytest
```

Without the fixtures the suite **fails** rather than passing an empty run — a green suite that
tested nothing is the most expensive kind of green. The shape of the output is:

```
N passed, M xfailed, 0 skipped
```

The two numbers are the milestone tracker: `passed` grows as the engine does, `xfailed` is what
the corpus still expects and the engine cannot yet do. A **skip** should never appear — it would
mean a case is being neither asserted nor counted.

The xfails are the whole cross-engine contract, waiting on P1–P3. As milestones land, cases turn
into real passes with no change to the runner.

> **If you mutate a source file to check that a test catches it, delete `__pycache__` first.**
> Python invalidates bytecode on (mtime, size). A mutation that preserves both — swapping `.*?`
> for `.+?`, say — leaves the stale `.pyc` in place, so the *next* run still imports the mutated
> module after you have restored the file. That produced a failure pointing at correct code, and
> the obvious response to it would have been to break the code for real.
