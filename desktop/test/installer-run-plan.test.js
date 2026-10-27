const test = require('node:test');
const assert = require('node:assert/strict');
const { runPlan } = require('../src/installer/run-plan');
const { buildPlan } = require('../src/installer/plan');
const { verdict } = require('../src/installer/tiers');

const hw = { platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 15.6, freeDiskGb: 50, cores: 8 };
const planFor = (selected = []) => buildPlan({ hw, verdict: verdict(hw), selected });

function harness({ approveWith = () => true, pullFails = false } = {}) {
  const log = [];
  const runners = {
    checkOllama: async () => { log.push('check'); },
    pullModel: async (model, onProgress) => {
      log.push(`pull:${model}`);
      onProgress({ status: 'pulling', completed: 1, total: 2 });
      if (pullFails) throw new Error('sem rede');
    },
    saveSettings: async (patch) => { log.push(`save:${JSON.stringify(patch)}`); },
  };
  const approve = async (step) => { log.push(`approve:${step.id}`); return approveWith(step); };
  const progress = [];
  return { log, runners, approve, progress, onProgress: (p) => progress.push(p) };
}

test('the person is asked before the model is downloaded, never after', async () => {
  const h = harness();
  const out = await runPlan(planFor(), h);
  assert.equal(out.status, 'done');
  assert.deepEqual(h.log.slice(0, 3), ['check', 'approve:model', 'pull:qwen3.5:latest']);
});

test('declining the model downloads nothing and saves nothing', async () => {
  const h = harness({ approveWith: () => false });
  const out = await runPlan(planFor(), h);
  assert.equal(out.status, 'aborted');
  assert.equal(h.log.some((l) => l.startsWith('pull:')), false);
  assert.equal(h.log.some((l) => l.startsWith('save:')), false);
  assert.equal(out.settings, null);
  assert.deepEqual(out.results.map((r) => r.status), ['done', 'declined']);
});

test('only an explicit true counts as approval', async () => {
  for (const answer of [undefined, null, 1, 'yes', {}]) {
    const h = harness({ approveWith: () => answer });
    const out = await runPlan(planFor(), h);
    assert.equal(out.status, 'aborted', String(answer));
    assert.equal(h.log.some((l) => l.startsWith('pull:')), false);
  }
});

test('an approval that throws is a refusal', async () => {
  const h = harness();
  h.approve = async () => { throw new Error('dialog closed'); };
  const out = await runPlan(planFor(), h);
  assert.equal(out.status, 'aborted');
  assert.equal(h.log.includes('pull:qwen3.5:latest'), false);
});

test('settings are saved once, at the end: chosen items on, the rest off', async () => {
  const h = harness();
  const out = await runPlan(planFor(['voice', 'animations']), h);
  assert.equal(out.status, 'done');
  const saves = h.log.filter((l) => l.startsWith('save:'));
  assert.equal(saves.length, 1);
  assert.deepEqual(out.settings, { talk: false, laya: false, protect: false, chatModel: 'qwen3.5:latest', enhancedVoice: true, still: false });
});

test('declining an optional item skips it and keeps going', async () => {
  const h = harness({ approveWith: (s) => s.id !== 'voice' });
  const out = await runPlan(planFor(['voice', 'animations']), h);
  assert.equal(out.status, 'done');
  assert.equal(out.results.find((r) => r.id === 'voice').status, 'declined');
  assert.equal('enhancedVoice' in out.settings, false);
  assert.equal(out.settings.still, false);
});

test('a failed download stops the install and saves nothing', async () => {
  const h = harness({ pullFails: true });
  const out = await runPlan(planFor(['animations']), h);
  assert.equal(out.status, 'failed');
  assert.equal(out.results.find((r) => r.id === 'model').error, 'sem rede');
  assert.equal(h.log.some((l) => l.startsWith('save:')), false);
  assert.equal(out.results.some((r) => r.id === 'animations'), false);
});

test('progress is passed on with the step id', async () => {
  const h = harness();
  await runPlan(planFor(), h);
  assert.deepEqual(h.progress, [{ id: 'model', status: 'pulling', completed: 1, total: 2 }]);
});

test('a blocked plan runs nothing at all', async () => {
  const h = harness();
  const out = await runPlan({ ok: false, blocked: ['x'], steps: [], baseline: {} }, h);
  assert.equal(out.status, 'blocked');
  assert.deepEqual(h.log, []);
});
