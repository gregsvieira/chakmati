const test = require('node:test');
const assert = require('node:assert/strict');
const { buildPlan } = require('../src/installer/plan');
const { verdict } = require('../src/installer/tiers');

const pc = (over = {}) => ({ platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 15.6, freeDiskGb: 50, cores: 8, ...over });
const plan = (hw, selected = [], v = verdict(hw)) => buildPlan({ hw, verdict: v, selected });

test('nothing selected: only check Ollama and fetch the model for this computer', () => {
  const p = plan(pc());
  assert.equal(p.ok, true);
  assert.deepEqual(p.steps.map((s) => s.id), ['ollama', 'model']);
  const model = p.steps[1];
  assert.equal(model.kind, 'pull-model');
  assert.equal(model.model, 'qwen3.5:latest');
  assert.equal(model.required, true);
  assert.deepEqual(model.approval.sizeMb, 6600);
  assert.deepEqual(model.settings, { chatModel: 'qwen3.5:latest' });
  assert.deepEqual(p.totals, { diskMb: 1500 + 6600, ramMb: 400 + 7100 });
});

test('what was not chosen is written off, so nothing optional ends up on', () => {
  const p = plan(pc());
  assert.deepEqual(p.baseline, { enhancedVoice: false, talk: false, still: true, protect: false });
});

test('chosen items become steps after the model, and leave the baseline', () => {
  const p = plan(pc(), ['animations', 'voice']);
  assert.deepEqual(p.steps.map((s) => s.id), ['ollama', 'model', 'voice', 'animations']); // catalog order, not click order
  const voice = p.steps.find((s) => s.id === 'voice');
  assert.deepEqual(voice.settings, { enhancedVoice: true });
  assert.equal(voice.required, false);
  assert.ok(voice.approval.sizeMb > 0);
  assert.equal(p.steps.find((s) => s.id === 'animations').approval, undefined);
  assert.equal('enhancedVoice' in p.baseline, false);
  assert.equal('still' in p.baseline, false);
  assert.equal(p.baseline.protect, false);
  assert.equal(p.totals.diskMb, 1500 + 6600 + 63);
});

test('the light level carries its warning along', () => {
  const p = plan(pc({ ramGb: 3.7 }));
  assert.equal(p.steps[1].model, 'qwen3.5:0.8b');
  assert.ok(p.warnings.some((w) => /pedidos no computador/.test(w)));
});

test('an unsupported computer gets no plan, only the reasons', () => {
  const p = plan(pc({ ramGb: 2 }));
  assert.equal(p.ok, false);
  assert.ok(p.blocked.length > 0);
  assert.deepEqual(p.steps, []);
  assert.equal(p.totals, null);
});

test('it refuses a selection that does not fit the free disk', () => {
  const hw = pc({ freeDiskGb: 6 });
  const p = plan(hw, [], { level: 'full', model: 'qwen3.5:latest', reasons: [], notes: [] }); // forced, to test the sum itself
  assert.equal(p.ok, false);
  assert.ok(p.blocked.some((b) => /espaço/i.test(b)));
});

test('it warns, without blocking, when memory will be tight', () => {
  const hw = pc({ ramGb: 8 });
  const p = plan(hw, [], { level: 'full', model: 'qwen3.5:latest', reasons: [], notes: [] });
  assert.equal(p.ok, true);
  assert.ok(p.warnings.some((w) => /memória/i.test(w)));
});

test('WhatsApp changes no setting here; it tells what to do afterwards', () => {
  const p = plan(pc(), ['whatsapp']);
  assert.deepEqual(p.steps.find((s) => s.id === 'whatsapp').settings, {});
  assert.equal(p.after.length, 1);
  assert.match(p.after[0], /Ajustes > Integrações/);
});

test('unknown ids and items not offered on this system are rejected', () => {
  assert.throws(() => plan(pc(), ['rm-rf']), /desconhecido/);
  assert.throws(() => plan(pc({ platform: 'win32' }), ['whatsapp']), /indisponível/);
});

test('the same id twice counts once', () => {
  assert.deepEqual(plan(pc(), ['voice', 'voice']).steps.map((s) => s.id), ['ollama', 'model', 'voice']);
});
