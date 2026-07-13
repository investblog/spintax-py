# spintax-core (Python)

> **Status: DRAFT / pre-code.** Scaffolding and a spec only — no engine code yet, nothing published.

A framework-agnostic **[Spintax](https://spintax.net) engine** for Python — parse, render,
validate, extract, analyze, and neutralize spintax templates. MIT, zero runtime dependencies.

This is the third engine in the Spintax family, and an **independent implementation** — not a
transcription of the others. It is held to the same behavior contract by a **shared golden corpus**
of language-neutral fixtures, which already gates the TypeScript engine and the PHP one.

- **Spec:** [`docs/spec-python-port.md`](docs/spec-python-port.md) — read it before writing any
  code. It records the parity contract, the API surface, and six open questions that must be
  answered first (two of them, corpus access and Unicode handling in post-process, are blocking).
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
