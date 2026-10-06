// Regenerates the Script tables of src/spintax_core/_charclasses.py: UNSPACED_SCRIPT,
// ARABIC_LETTER, HEBREW_LETTER (spintax-js#87, #90). Python has neither `\p{Script=…}` nor a
// Script property in `unicodedata`, so the suite cannot rebuild these; this script is how they
// were built and how to check them. It brute-forces the reference's own regexes over every code
// point and prints the Python literals, headed by the Node and Unicode versions.
//
// Usage: node tools/gen_script_tables.mjs
// To verify: run it on the Node named in _charclasses.py and diff against the constants there.
// A newer Node may add code points (a script only grows); anything it REMOVES is real drift.
const tables = {
  UNSPACED_SCRIPT: /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}ーｰ\p{Script=Thai}\p{Script=Lao}\p{Script=Khmer}\p{Script=Myanmar}]$/u,
  ARABIC_LETTER: /^(?=\p{L})\p{Script=Arabic}$/u,
  HEBREW_LETTER: /^(?=\p{L})\p{Script=Hebrew}$/u,
};
const hex = (cp) => '\\\\U' + cp.toString(16).padStart(8, '0');
console.log(`# ${process.version} (Unicode ${process.versions.unicode})`);
for (const [name, re] of Object.entries(tables)) {
  const ranges = [];
  let start = -1;
  for (let cp = 0; cp <= 0x110000; cp++) {
    const ok = cp < 0x110000 && !(cp >= 0xd800 && cp <= 0xdfff) && re.test(String.fromCodePoint(cp));
    if (ok && start < 0) start = cp;
    if (!ok && start >= 0) { ranges.push([start, cp - 1]); start = -1; }
  }
  const items = ranges.map(([a, b]) => (a === b ? hex(a) : `${hex(a)}-${hex(b)}`));
  const lines = [];
  let line = '';
  for (const it of items) {
    if (line.length + it.length > 84) { lines.push(line); line = ''; }
    line += it;
  }
  if (line) lines.push(line);
  const count = ranges.reduce((s, [a, b]) => s + b - a + 1, 0);
  console.log(`# ${name}: ${ranges.length} ranges, ${count} code points`);
  console.log(`${name} = (\n${lines.map((l) => `    "${l}"`).join('\n')}\n)`);
}
