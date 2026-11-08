const test = require('node:test');
const assert = require('node:assert/strict');
const { wanted, createKeepAwake } = require('../../../src/features/engine/keep-awake');

const on = { automations: [{ id: 'a', enabled: false }, { id: 'b', enabled: true }] };
const fakePower = () => {
  const live = new Set();
  let next = 1;
  return { live, start: (kind) => { assert.equal(kind, 'prevent-app-suspension'); live.add(next); return next++; }, stop: (id) => live.delete(id), isStarted: (id) => live.has(id) };
};

test('wanted: only with the option on and an enabled automation', () => {
  assert.equal(wanted({ keepAwake: true }, on), true);
  assert.equal(wanted({ keepAwake: false }, on), false);
  assert.equal(wanted({ keepAwake: true }, { automations: [{ enabled: false }] }), false);
  assert.equal(wanted({ keepAwake: true }, { automations: [] }), false);
  assert.equal(wanted({ keepAwake: true }, null), false);
  assert.equal(wanted({ keepAwake: true }, {}), false);
});

test('holds one blocker, no duplicates, and lets go when nothing needs it', () => {
  const power = fakePower();
  const k = createKeepAwake(power);
  assert.equal(k.sync({ keepAwake: true }, on), true);
  assert.equal(k.sync({ keepAwake: true }, on), true);
  assert.equal(power.live.size, 1);
  assert.equal(k.sync({ keepAwake: true }, { automations: [] }), false);
  assert.equal(power.live.size, 0);
  assert.equal(k.sync({ keepAwake: true }, on), true);
  assert.equal(k.sync({ keepAwake: false }, on), false);
  assert.equal(power.live.size, 0);
});

test('release drops the blocker; a blocker the system dropped is taken again', () => {
  const power = fakePower();
  const k = createKeepAwake(power);
  k.sync({ keepAwake: true }, on);
  power.live.clear();
  assert.equal(k.active, false);
  assert.equal(k.sync({ keepAwake: true }, on), true);
  k.release();
  assert.equal(power.live.size, 0);
});

test('the panel state carries keepAwake, or the switch always shows off', () => {
  const src = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', '..', '..', 'src', 'features', 'panel', 'window.js'), 'utf8');
  assert.match(src, /keepAwake: ctx\.settings\.keepAwake/);
});
