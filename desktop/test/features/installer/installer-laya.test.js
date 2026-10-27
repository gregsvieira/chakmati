const test = require('node:test');
const assert = require('node:assert/strict');
const { OPTIONS, extrasSizeMb } = require('../../../src/features/installer/catalog');
const { buildPlan } = require('../../../src/features/installer/plan');
const { verdict } = require('../../../src/features/installer/tiers');

const hw = { platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 24, freeDiskGb: 80, cores: 12 };

test('Laya is offered with the advice not to use it, and is never recommended or on by default', () => {
  const laya = OPTIONS.find((o) => o.id === 'laya');
  assert.match(laya.advice, /^Não recomendado\. Possui baixa eficácia neste projeto até o momento\.$/);
  assert.equal(laya.offSettings.laya, false);
  assert.ok(!(require('../../../src/features/installer/tiers').suggestions(hw, 'full')).laya);
});

test('ticking Laya installs its package in the installed app and switches the setting on', () => {
  const p = buildPlan({ hw, verdict: verdict(hw), selected: ['laya'], engine: { packaged: true } });
  const extras = p.steps.find((s) => s.id === 'extras');
  assert.deepEqual(extras.extras, ['laya']);
  assert.match(extras.label, /Laya/);
  assert.equal(p.steps.find((s) => s.id === 'laya').settings.laya, true);
  assert.equal(extrasSizeMb(['voice', 'laya']) > extrasSizeMb(['laya']), true);
});

test('not ticked, it is written off', () => {
  assert.equal(buildPlan({ hw, verdict: verdict(hw), selected: [] }).baseline.laya, false);
});
