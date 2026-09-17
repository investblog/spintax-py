/**
 * Where the reference engine's checkout is.
 *
 * Both generators here hard-coded `W:/Projects/spintax-js` until the drive letter went
 * away and neither script could run — the fixtures they produce are the port's only
 * measured record of the reference, so a generator that cannot start is a generator whose
 * output silently ages. The path is resolved rather than written down now:
 *
 *   1. `$SPINTAX_JS`, for a checkout that is somewhere else entirely;
 *   2. otherwise the sibling `../spintax-js` of this repository, which is how the family's
 *      repos are laid out.
 *
 * It fails loudly with both candidates named, because the alternative is a generator that
 * writes a stub fixture and a suite that goes green against nothing.
 */
const fs = require('fs');
const path = require('path');

module.exports = function referenceRepo() {
  const repoRoot = path.resolve(__dirname, '..', '..');
  const candidates = [];
  if (process.env.SPINTAX_JS) candidates.push(path.resolve(process.env.SPINTAX_JS));
  candidates.push(path.resolve(repoRoot, '..', 'spintax-js'));

  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, 'packages/core/package.json'))) return dir;
  }
  throw new Error(
    'no @spintax/core checkout found. Looked in:\n  ' +
      candidates.join('\n  ') +
      '\nSet SPINTAX_JS to the spintax-js checkout and run again.',
  );
};
