# Releasing `spintax-core`

Tag-driven, and deliberately not automatic on push: a release is a decision, not a side
effect of merging. Pushing a `vX.Y.Z` tag runs `.github/workflows/release.yml`, which
**re-verifies** the tagged commit (pytest + ruff + mypy against the golden corpus checked
out from `investblog/spintax-js`), **publishes** to PyPI, and **announces** a GitHub
release. The workflow re-runs the gate on purpose: a tag can be placed on any commit,
including one CI never saw green, and the artifact that reaches PyPI must be one that
passed — not one that probably did.

There is no CHANGELOG file in this repo. **The tag annotation IS the release note**:
its subject becomes the GitHub release title, its body the release notes (an empty body
falls back to generated notes — fine for a one-line patch). Write it at the moment the
release is decided; the `announce` job publishes it verbatim.

## Preconditions

1. `main` is green in CI. Note that ruff is installed **unpinned** (by design — the
   four-interpreter matrix exists to turn tool drift into a named failure): a fresh ruff
   release can red the verify job on code the previous ruff accepted. Fix the findings,
   don't pin (the 0.16 precedent: nine findings, all mechanical).
2. If the release covers a cross-engine fix, its corpus fixtures are already on
   `spintax-js@main` — the verify job pulls fixtures from there, so a fixture landing
   *after* the tag never gated the tagged artifact.
3. `pyproject.toml` `version` is bumped: the publish job **fails the release if the
   built wheel's version does not match the tag** — that gate is why the bump commit
   must land before (or be) the tagged commit.

## Versioning

While 0.x / Beta: a behaviour fix toward the family contract is a **patch** (the `0.1.2`
precedent — parse/render sentinel consistency); anything that widens or changes the
public API is a minor.

## Cutting a release

```sh
# 1. Bump the version
#    pyproject.toml: version = "X.Y.Z"

# 2. Release commit (convention: "Release X.Y.Z")
git add pyproject.toml && git commit -m "Release X.Y.Z"
git push origin main

# 3. Wait for CI on that exact commit, then tag it — annotated; the annotation is the
#    release note (subject line + blank line + body).
git tag -a vX.Y.Z -m "spintax-core X.Y.Z — one-line headline

A few sentences: what changed, what it was measured against, corpus numbers."

# 4. Push the tag — this triggers Release (verify → publish → announce).
git push origin vX.Y.Z
```

## What the workflow enforces (so you don't have to)

- Full gate re-run on the tagged commit (pytest vs corpus, ruff, mypy).
- `twine check` on both artifacts.
- **Wheel version == tag** — a mismatched bump stops before upload.
- `py.typed` present in both the wheel and the sdist.
- Upload uses the `PYPI_API_TOKEN` repository secret in the `pypi` environment
  (token-based; if PyPI Trusted Publishing is ever configured for this repo+workflow,
  the token and the two `TWINE_*` lines are what it replaces).
- The GitHub release is created only after PyPI accepted the upload, so a release never
  announces an artifact that wasn't published.

## After the tag

```sh
gh run watch --repo investblog/spintax-py        # or check the Actions tab
curl -s https://pypi.org/pypi/spintax-core/json | python -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
gh release view vX.Y.Z --repo investblog/spintax-py
```

## Un-shipping a mistake

PyPI forbids re-uploading a version, ever — deleting a release frees the *name* of the
page but the version number is burned. Ship `X.Y.(Z+1)`; use `yank` only to stop new
installs of a broken version (existing pins keep resolving).
