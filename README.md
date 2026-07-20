# spintax-core (Python)

A framework-agnostic **[Spintax](https://spintax.net) engine** for Python — parse, render,
validate, extract, analyze, and neutralize spintax templates. MIT, zero runtime dependencies,
Python 3.10+.

This is the third engine in the Spintax family, and an **independent implementation** — not a
transcription of the others. It is held to the same behavior contract by a **shared golden corpus**
of language-neutral fixtures, which already gates the TypeScript engine and the PHP one. All 168
of them pass here, none skipped, none expected to fail.

## Install

```bash
pip install spintax-core
```

## Use

```python
from spintax_core import render, validate, parse

render("{Hello|Hi} there!")                        # "Hello there!" or "Hi there!"
render("{Hello|Hi} there!", seed=42)               # same seed, same output, every time
render("Hi %name%!", context={"name": "Sam"})      # "Hi Sam!"

# Reuse a template: parse once, render many.
ast = parse('[<sep=", ">fast|cheap|good]')
[render(ast) for _ in range(3)]
# ['Cheap, fast, good', 'Good, cheap, fast', 'Cheap, good, fast']

# Check a template before you ship it.
[d.code for d in validate("{a|b")]                 # -> ['bracket.unclosed']
```

Rendering is **lenient**: malformed markup degrades rather than raising, so a template a
non-programmer wrote cannot take a page down.

Syntax — enumerations `{a|b}`, permutations `[a|b]`, variables `%name%`, conditionals
`{?VAR?yes|no}`, plural agreement `{plural 3: one|few|many}`, `#set` / `#def` / `#include` — is
documented at **[spintax.net/docs](https://spintax.net/docs/)**.

- **Spec:** [`docs/spec-python-port.md`](docs/spec-python-port.md) — the parity contract, the API
  surface, and the decisions behind the port (including where Python's regex dialect is wider than
  JavaScript's and how each divergence was measured and pinned).
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
