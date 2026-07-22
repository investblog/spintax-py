/**
 * Regenerate tests/data/postprocess_parity.json from the REFERENCE engine.
 *
 * Post-process is a dozen interacting rules whose ORDER matters, and the shared corpus
 * samples it with 39 cases. Differential fuzzing against the reference found two real
 * divergences the fixtures missed — a mistranslated `\b` (64 failures) and a broadened
 * `\p{Ll}` that consumed the region a narrower match needed (1 failure). Neither would
 * have been caught by the corpus, and neither would be caught again by a test written
 * from reading the code.
 *
 * So the reference's own answers are frozen. The cases are curated rather than the full
 * fuzz run: the hand-written seams, the combinatorial sentence-boundary grid, and a
 * seeded sample of the junk that found the bugs.
 *
 * Driven through the INTERNAL renderWith so the same fixed draw source is injectable —
 * the public render() seeds its own RNG and could not be compared exactly.
 *
 * HOW TO REGENERATE, after bumping @spintax/core:
 *   cd W:/Projects/spintax-js && npm install && npm run build
 *   node W:/Projects/spintax-py/tests/data/generate_postprocess_parity.cjs
 * Read the diff. A change here is a change in the reference's cosmetics and deserves an
 * explanation in the commit message, not a silent refresh.
 */
const fs = require('fs');
const path = require('path');
const esbuild = require('W:/Projects/spintax-js/node_modules/esbuild');

const CORE = 'W:/Projects/spintax-js/packages/core';
const bundled = path.join(__dirname, '.ref-pipeline.cjs');
esbuild.buildSync({
  entryPoints: [`${CORE}/src/internal/pipeline.ts`],
  bundle: true, platform: 'node', format: 'cjs', outfile: bundled,
});
const { renderWith } = require(bundled);

// The bundle is built from the spintax-js WORKING TREE, not from the published tarball, so
// package.json's version is only half the provenance: a fixture generated on top of an
// unreleased commit would otherwise claim to be the release below it, and the recipe above
// run against that release would produce different rows and a red suite with nothing to
// explain it. Record the commit too, and mark it when the tree is dirty.
const version = require(`${CORE}/package.json`).version;
const git = (args) =>
  require('child_process')
    .execFileSync('git', ['-C', 'W:/Projects/spintax-js', ...args], { encoding: 'utf8' })
    .trim();
const head = git(['rev-parse', '--short', 'HEAD']);
const dirty = git(['status', '--porcelain', 'packages/core/src']) ? '-dirty' : '';
const reference = `${version}+${head}${dirty}`;

const templates = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'postprocess_parity_cases.json'), 'utf8'),
);

const first = (lo) => lo;
const cases = templates.map((template) => ({
  template,
  text: renderWith(template, first, { postProcess: true }),
}));

fs.writeFileSync(
  path.join(__dirname, 'postprocess_parity.json'),
  `${JSON.stringify({ reference_version: reference, note: 'Generated — do not hand-edit.', cases }, null, 1)}\n`,
  'utf8',
);
fs.unlinkSync(bundled);
console.log(`${cases.length} cases from @spintax/core ${reference}`);
