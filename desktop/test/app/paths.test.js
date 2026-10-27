const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', '..', 'src');
const sources = [];
(function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p); else if (p.endsWith('.js')) sources.push(p);
  }
})(SRC);

test('every file the main process builds from __dirname exists (pages, preload, the project folder)', () => {
  let checked = 0;
  for (const file of sources) {
    const text = fs.readFileSync(file, 'utf8');
    for (const m of text.matchAll(/path\.(?:join|resolve)\(\s*__dirname((?:\s*,\s*'[^']*')+)\s*\)/g)) {
      const parts = [...m[1].matchAll(/'([^']*)'/g)].map((x) => x[1]);
      const target = path.resolve(path.dirname(file), ...parts);
      assert.ok(fs.existsSync(target), `${path.relative(SRC, file)} builds ${parts.join('/')}, which does not exist (${target})`);
      checked += 1;
    }
  }
  assert.ok(checked >= 5, `only ${checked} paths were checked`);
});

test('the project folder the app finds is the one with pyproject.toml', () => {
  const service = fs.readFileSync(path.join(SRC, 'features', 'engine', 'service.js'), 'utf8');
  const parts = [...service.match(/path\.resolve\(__dirname((?:\s*,\s*'[^']*')+)\)/)[1].matchAll(/'([^']*)'/g)].map((x) => x[1]);
  assert.ok(fs.existsSync(path.join(path.resolve(SRC, 'features', 'engine', ...parts), 'pyproject.toml')));
});
