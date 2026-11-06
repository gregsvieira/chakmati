const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { ENGINE, OPTIONS, extrasSizeMb, optionsFor } = require('../../../src/features/installer/catalog');
const { buildPlan } = require('../../../src/features/installer/plan');
const { runPlan } = require('../../../src/features/installer/run-plan');
const { makeRunners } = require('../../../src/features/installer/runners');
const { makeSync } = require('../../../src/features/installer/engine-sync');
const { verdict } = require('../../../src/features/installer/tiers');

const hw = { platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 15.6, freeDiskGb: 80, cores: 8 };
const planFor = (selected = [], engine = { packaged: true }) => buildPlan({ hw, verdict: verdict(hw), selected, engine });

test('extras sizes are the measured ones, and the two together share packages', () => {
  assert.equal(extrasSizeMb([]), 0);
  assert.equal(extrasSizeMb(['voice']), 198);
  assert.equal(extrasSizeMb(['listen']), 183);
  assert.equal(extrasSizeMb(['voice', 'listen']), 228);
  assert.equal(ENGINE.baseMb, 189);
});

test('WhatsApp is not offered by an installed app (its setup script is not in the package)', () => {
  assert.equal(optionsFor('darwin').some((o) => o.id === 'whatsapp'), true);
  assert.equal(optionsFor('darwin', { packaged: true }).some((o) => o.id === 'whatsapp'), false);
  assert.equal(optionsFor('darwin', { packaged: true }).some((o) => o.id === 'voice'), true);
});

test('the main process refuses a hidden item even if the page sends it (installed app only)', () => {
  assert.throws(() => planFor(['whatsapp']), /indisponível/);
  assert.doesNotThrow(() => buildPlan({ hw, verdict: verdict(hw), selected: ['whatsapp'] })); // development still has it
});

test('only voice, microphone and Laya need Python packages', () => {
  assert.deepEqual(OPTIONS.filter((o) => o.extra).map((o) => [o.id, o.extra]), [['voice', 'voice'], ['talk', 'listen'], ['laya', 'laya']]);
});

test('a development plan has no engine or extras step', () => {
  const p = buildPlan({ hw, verdict: verdict(hw), selected: ['voice'] });
  assert.deepEqual(p.steps.map((s) => s.id), ['ollama', 'model', 'voice']);
  assert.equal(p.steps.find((s) => s.id === 'voice').requires, undefined);
});

test('an installed plan prepares the engine right after Ollama, with approval and its size', () => {
  const p = planFor();
  assert.deepEqual(p.steps.map((s) => s.id), ['ollama', 'engine', 'model']);
  const engine = p.steps[1];
  assert.equal(engine.kind, 'sync-engine');
  assert.equal(engine.required, true);
  assert.equal(engine.approval.sizeMb, 189);
  assert.match(engine.approval.source, /pypi\.org/);
});

test('choosing voice or microphone adds one extras step with the shared size, and ties the items to it', () => {
  const p = planFor(['voice', 'talk']);
  assert.deepEqual(p.steps.map((s) => s.id), ['ollama', 'engine', 'model', 'extras', 'voice', 'talk']);
  const extras = p.steps.find((s) => s.id === 'extras');
  assert.deepEqual(extras.extras, ['voice', 'listen']);
  assert.equal(extras.kind, 'sync-extras');
  assert.equal(extras.required, false);
  assert.equal(extras.approval.sizeMb, 228);
  assert.equal(p.steps.find((s) => s.id === 'voice').requires, 'extras');
  assert.equal(p.steps.find((s) => s.id === 'talk').requires, 'extras');
  assert.equal(p.totals.diskMb, 1500 + 6600 + 228 + 63 + 140);
});

test('items that need no package are not tied to the extras step', () => {
  const p = planFor(['animations']);
  assert.deepEqual(p.steps.map((s) => s.id), ['ollama', 'engine', 'model', 'animations']);
  assert.equal(p.steps.find((s) => s.id === 'animations').requires, undefined);
});

function runners(log, { failSync = false } = {}) {
  return {
    checkOllama: async () => { log.push('check'); },
    pullModel: async () => { log.push('pull'); },
    syncEngine: async (extras) => { log.push(`sync:${extras.join('+')}`); if (failSync) throw new Error('sem rede'); },
    saveSettings: async (p) => { log.push(`save:${JSON.stringify(p)}`); },
  };
}

test('the engine and the extras are prepared after the person approves each one', async () => {
  const log = [];
  const approve = async (s) => { log.push(`approve:${s.id}`); return true; };
  const out = await runPlan(planFor(['voice']), { approve, runners: runners(log) });
  assert.equal(out.status, 'done');
  assert.deepEqual(log.slice(0, 8), ['check', 'approve:engine', 'sync:', 'approve:model', 'pull', 'approve:extras', 'sync:voice', 'approve:voice']);
  assert.equal(out.settings.enhancedVoice, true);
});

test('declining the engine stops the install before anything is saved', async () => {
  const log = [];
  const out = await runPlan(planFor(), { approve: async (s) => s.id !== 'engine', runners: runners(log) });
  assert.equal(out.status, 'aborted');
  assert.equal(log.some((l) => l.startsWith('sync')), false);
  assert.equal(log.some((l) => l.startsWith('save')), false);
});

test('without the packages, the items that need them are skipped and their settings are not applied', async () => {
  const log = [];
  const out = await runPlan(planFor(['voice', 'animations']), { approve: async (s) => s.id !== 'extras', runners: runners(log) });
  assert.equal(out.status, 'done');
  const byId = Object.fromEntries(out.results.map((r) => [r.id, r.status]));
  assert.equal(byId.extras, 'declined');
  assert.equal(byId.voice, 'skipped');
  assert.equal(byId.animations, 'done');
  assert.equal('enhancedVoice' in out.settings, false);
  assert.equal(out.settings.still, false);
});

test('a failed extras install also skips the items that need them, and the install still ends well', async () => {
  const log = [];
  const r = runners(log);
  r.syncEngine = async (extras) => { if (extras.length) throw new Error('sem rede'); };
  const out = await runPlan(planFor(['talk']), { approve: async () => true, runners: r });
  assert.equal(out.status, 'done');
  const byId = Object.fromEntries(out.results.map((x) => [x.id, x.status]));
  assert.equal(byId.extras, 'failed');
  assert.equal(byId.talk, 'skipped');
});

test('a failed engine preparation fails the whole install', async () => {
  const log = [];
  const out = await runPlan(planFor(), { approve: async () => true, runners: runners(log, { failSync: true }) });
  assert.equal(out.status, 'failed');
  assert.equal(out.settings, null);
});

test('syncEngine is wired through makeRunners, and absent outside an installed app', async () => {
  const calls = [];
  const r = makeRunners({ saveSettings: async () => {}, sync: async (extras) => { calls.push(extras); } });
  await r.syncEngine(['voice'], () => {});
  assert.deepEqual(calls, [['voice']]);
  await assert.rejects(makeRunners({ saveSettings: async () => {} }).syncEngine([], () => {}), /instalado/);
});

// ---- the process that runs uv
function fakeSpawn({ code = 0, out = '', err = '' } = {}) {
  const seen = {};
  const spawnFn = (command, args, options) => {
    Object.assign(seen, { command, args, options });
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    setImmediate(() => { if (out) child.stdout.emit('data', Buffer.from(out)); if (err) child.stderr.emit('data', Buffer.from(err)); child.emit('close', code); });
    return child;
  };
  return { spawnFn, seen };
}

test('uv is started with a fixed argument list, no shell, in the data folder', async () => {
  const { spawnFn, seen } = fakeSpawn({ err: 'Resolved 44 packages\nInstalled 44 packages\n' });
  const progress = [];
  await makeSync({ spawnFn, resourcesPath: '/app/resources', dataDir: '/data', platform: 'darwin', env: { PATH: '/x' } })(['voice'], (p) => progress.push(p));
  assert.equal(seen.command, '/app/resources/bin/uv');
  assert.deepEqual(seen.args.slice(0, 2), ['sync', '--frozen']);
  assert.equal(seen.args.includes('--extra'), true);
  assert.notEqual(seen.options.shell, true);
  assert.equal(seen.options.env.UV_PROJECT_ENVIRONMENT, '/data/engine-venv');
  assert.equal(seen.options.env.PATH, '/x');
  assert.equal(progress.at(-1).status, 'Installed 44 packages');
});

test('a uv failure carries the last lines of its output', async () => {
  const { spawnFn } = fakeSpawn({ code: 2, err: 'linha 1\nerro de rede\n' });
  await assert.rejects(makeSync({ spawnFn, resourcesPath: '/r', dataDir: '/d', platform: 'linux', env: {} })([], () => {}), /erro de rede/);
});

test('a missing uv is reported, and an unknown extra never starts a process', async () => {
  const spawnFn = () => { const c = new EventEmitter(); c.stdout = new EventEmitter(); c.stderr = new EventEmitter(); setImmediate(() => c.emit('error', new Error('ENOENT'))); return c; };
  await assert.rejects(makeSync({ spawnFn, resourcesPath: '/r', dataDir: '/d', platform: 'linux', env: {} })([], () => {}), /uv/);
  let started = false;
  await assert.rejects(makeSync({ spawnFn: () => { started = true; }, resourcesPath: '/r', dataDir: '/d', platform: 'linux', env: {} })(['evil'], () => {}), /extra/i);
  assert.equal(started, false);
});

test('the engine and the chat model are mandatory: always in the plan, whatever is ticked, each with its approval and nothing that can skip it', () => {
  for (const selected of [[], ['voice'], ['animations', 'hideShare', 'talk', 'voice', 'laya']]) {
    const p = planFor(selected);
    for (const id of ['engine', 'model']) {
      const step = p.steps.find((x) => x.id === id);
      assert.ok(step, id);
      assert.equal(step.required, true, id);
      assert.ok(step.approval && step.approval.sizeMb > 0, id);
      assert.equal(step.requires, undefined, id);
    }
  }
});

test('declining or failing the engine stops the install before the model, and saves nothing', async () => {
  for (const how of ['declined', 'failed']) {
    const calls = [];
    const runners = {
      checkOllama: async () => { calls.push('check'); },
      syncEngine: async () => { calls.push('engine'); if (how === 'failed') throw new Error('uv falhou'); },
      pullModel: async () => { calls.push('model'); },
      saveSettings: async () => { calls.push('save'); },
    };
    const approve = async (step) => (how === 'declined' ? step.id !== 'engine' : true);
    const out = await runPlan(planFor(), { approve, runners });
    assert.equal(out.status, how === 'declined' ? 'aborted' : 'failed', how);
    assert.equal(calls.includes('model'), false, how);
    assert.equal(calls.includes('save'), false, how);
    assert.equal(out.settings, null, how);
  }
});
