const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const src = fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', 'features', 'whatsapp', 'openwa.js'), 'utf8');

test('the link button runs one attempt at a time: the source shape', () => {
  assert.match(src, /let setupRunning = null;\s*function openWaSetup\(\) \{\s*if \(!setupRunning\) setupRunning = openWaSetupOnce\(\)\.finally\(\(\) => \{ setupRunning = null; \}\);\s*return setupRunning;\s*\}/);
  assert.match(src, /async function openWaSetupOnce\(\) \{/);
  assert.match(src, /Object\.assign\(module\.exports, \{ openWaSetup \}\)/);
});

test('behaviour: three clicks while the first is starting share one attempt, and a later click starts a new one', async () => {
  // only the guard is run: the function around it is cut out of the file, with a fake attempt that takes a moment
  const start = src.indexOf('let setupRunning = null;');
  const end = src.indexOf('async function openWaSetupOnce()');
  let calls = 0;
  let release;
  const context = { openWaSetupOnce: () => { calls += 1; return new Promise((r) => { release = () => r({ ok: true }); }); }, result: null };
  vm.createContext(context);
  vm.runInContext(`${src.slice(start, end)}\nresult = { openWaSetup };`, context);
  const { openWaSetup } = context.result;
  const a = openWaSetup();
  const b = openWaSetup();
  const c = openWaSetup();
  assert.equal(calls, 1);
  assert.equal(a, b);
  assert.equal(b, c);
  release();
  assert.deepEqual(await a, { ok: true });
  await new Promise((r) => setImmediate(r));
  openWaSetup();
  assert.equal(calls, 2);
  release();
});
