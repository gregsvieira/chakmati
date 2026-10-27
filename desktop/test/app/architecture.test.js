// The shape of the desktop app, enforced (main process; the pages in renderer/ are scripts, not modules):
//   app/       composes the app (start, IPC registration, hardening, snapshots); may use anything, but features only through their index.js
//   shared/    the kernel (context, constants, util, window preferences, UI assets); depends on nothing above it
//   features/  one folder per capability; a feature uses `shared`, itself, and another feature ONLY through that feature's index.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', '..', 'src');

function modules() {
  const out = [];
  (function walk(dir) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== 'renderer') walk(p); } else if (p.endsWith('.js')) out.push(p);
    }
  })(SRC);
  return out;
}

const layerOf = (file) => {
  const parts = path.relative(SRC, file).split(path.sep);
  if (parts[0] === 'features') return { layer: 'features', feature: parts[1], isIndex: parts.length === 3 && parts[2] === 'index.js' };
  return { layer: parts.length > 1 ? parts[0] : 'root', feature: '', isIndex: false };
};

function requires(file) {
  const found = [];
  for (const m of fs.readFileSync(file, 'utf8').matchAll(/require\(\s*'(\.[^']*)'\s*\)/g)) {
    const base = path.resolve(path.dirname(file), m[1]);
    const target = [base, base + '.js', path.join(base, 'index.js')].find((c) => fs.existsSync(c) && fs.statSync(c).isFile());
    if (target) found.push({ spec: m[1], target });
  }
  return found;
}

test('shared depends on nothing above it', () => {
  const bad = [];
  for (const file of modules().filter((f) => layerOf(f).layer === 'shared')) {
    for (const r of requires(file)) if (layerOf(r.target).layer !== 'shared') bad.push(`${path.relative(SRC, file)} -> ${r.spec}`);
  }
  assert.deepEqual(bad, []);
});

test('a feature reaches another feature only through its index.js', () => {
  const bad = [];
  for (const file of modules().filter((f) => ['features', 'app'].includes(layerOf(f).layer))) {
    const mine = layerOf(file);
    for (const r of requires(file)) {
      const theirs = layerOf(r.target);
      if (theirs.layer === 'features' && (mine.layer !== 'features' || theirs.feature !== mine.feature) && !theirs.isIndex) bad.push(`${path.relative(SRC, file)} -> ${r.spec}`);
    }
  }
  assert.deepEqual(bad, [], 'go through features/<name>/index.js (add a getter there)');
});

test('a feature never depends on app/', () => {
  const bad = [];
  for (const file of modules().filter((f) => layerOf(f).layer === 'features')) {
    for (const r of requires(file)) if (layerOf(r.target).layer === 'app') bad.push(`${path.relative(SRC, file)} -> ${r.spec}`);
  }
  assert.deepEqual(bad, []);
});

test('the entry points only start the app', () => {
  for (const entry of ['main.js']) {
    const targets = requires(path.join(SRC, entry)).map((r) => path.relative(SRC, r.target));
    assert.deepEqual(targets, [path.join('app', 'start.js')]);
  }
});

test('every feature index exposes only files that exist', () => {
  for (const file of modules().filter((f) => layerOf(f).isIndex)) {
    const text = fs.readFileSync(file, 'utf8');
    for (const m of text.matchAll(/require\('\.\/([^']+)'\)/g)) {
      assert.ok(fs.existsSync(path.join(path.dirname(file), m[1] + '.js')), `${path.relative(SRC, file)} exposes ${m[1]}, which is not there`);
    }
  }
});
