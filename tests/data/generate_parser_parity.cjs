/**
 * Regenerate tests/data/parser_parity.json from the REFERENCE engine.
 *
 * The golden corpus gates observable behaviour — what a template renders to. It says
 * nothing about the shape of the tree in between, and a parser can agree on every
 * rendered string while building a tree that differs in ways the renderer has not
 * exercised yet. This file closes that gap by freezing the reference's own `parse()`
 * output, which is the internal ParsedAst, for a set of templates chosen to sit on the
 * seams between the two dialects.
 *
 * Frozen rather than compared live because the reference's dist/ is gitignored, so a CI
 * checkout would have to npm-install and build it on every Python run. The cost of
 * freezing is that this can go stale; `reference_version` is recorded so a mismatch is
 * visible, and refreshing is one command.
 *
 * HOW TO REGENERATE, after bumping @spintax/core — both commands from THIS repo's root
 * (the second resolves the checkout itself; see reference_repo.cjs):
 *   npm --prefix ../spintax-js run build
 *   node tests/data/generate_parser_parity.cjs
 * Then read the diff. A change here is a change in the reference's tree shape and
 * deserves an explanation in the commit message, not a silent refresh.
 */
const fs = require('fs');
const path = require('path');

const JS_REPO = require('./reference_repo.cjs')();
const CORE = path.join(JS_REPO, 'packages/core');
const core = require(`${CORE}/dist/index.cjs`);
const version = require(`${CORE}/package.json`).version;

const TEMPLATES = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'parser_parity_templates.json'), 'utf8'),
);

const cases = TEMPLATES.map((template) => ({ template, ast: core.parse(template) }));

const payload = {
  reference_version: version,
  note: 'Generated — do not hand-edit. See generate_parser_parity.cjs.',
  cases,
};

const out = path.join(__dirname, 'parser_parity.json');
fs.writeFileSync(out, `${JSON.stringify(payload, null, 1)}\n`, 'utf8');
console.log(`${cases.length} cases from @spintax/core ${version} -> ${out}`);
