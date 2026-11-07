const test = require('node:test');
const assert = require('node:assert/strict');
const { CORE, MODELS, OPTIONS, optionsFor } = require('../../../src/features/installer/catalog');
const { formatSize, levelText } = require('../../../src/features/installer/format');
const { MODEL_BY_LEVEL } = require('../../../src/features/installer/tiers');
const { DEFAULTS, normalize } = require('../../../src/features/settings/settings');

test('every model of the ladder is in the catalog, and the catalog has nothing else', () => {
  assert.deepEqual(MODELS.map((m) => m.id).sort(), Object.values(MODEL_BY_LEVEL).sort());
});

test('ids are unique and every entry has what the wizard shows', () => {
  const ids = [...MODELS, ...OPTIONS].map((x) => x.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const x of [...MODELS, ...OPTIONS]) {
    assert.ok(x.label && Number.isFinite(x.diskMb) && Number.isFinite(x.ramMb), x.id);
  }
  assert.ok(Number.isFinite(CORE.diskMb) && Number.isFinite(CORE.ramMb));
});

test('options only touch settings that exist, with values the app accepts', () => {
  for (const o of OPTIONS) {
    for (const group of [o.settings, o.offSettings]) {
      for (const [key, value] of Object.entries(group)) {
        assert.ok(key in DEFAULTS, `${o.id}: unknown setting ${key}`);
        assert.equal(normalize({ [key]: value })[key], value, `${o.id}: ${key}=${value} is not accepted by normalize`);
      }
    }
  }
});

test('an option that downloads something says where from and how much', () => {
  for (const o of OPTIONS.filter((x) => x.approval && !x.dynamic)) { // (the reasoning model's size depends on the computer: the plan fills it in)
    assert.ok(o.approval.source && o.approval.sizeMb > 0, o.id);
  }
  assert.ok(OPTIONS.find((o) => o.id === 'voice').approval);
  assert.ok(OPTIONS.find((o) => o.id === 'talk').approval);
});

test('nothing is on by default: an option left out is written as off', () => {
  assert.equal(OPTIONS.find((o) => o.id === 'voice').settings.enhancedVoice, true);
  assert.equal(OPTIONS.find((o) => o.id === 'voice').offSettings.enhancedVoice, false);
  assert.equal(OPTIONS.find((o) => o.id === 'animations').offSettings.still, true);
  assert.equal(OPTIONS.find((o) => o.id === 'hideShare').offSettings.protect, false);
});

test('WhatsApp is not offered on Windows (the OpenWA setup is a shell script)', () => {
  assert.equal(optionsFor('win32').some((o) => o.id === 'whatsapp'), false);
  assert.equal(optionsFor('darwin').some((o) => o.id === 'whatsapp'), true);
  assert.equal(optionsFor('linux').some((o) => o.id === 'whatsapp'), true);
  assert.ok(OPTIONS.find((o) => o.id === 'whatsapp').after, 'WhatsApp says what to do after the installation');
});

test('sizes and levels read naturally in Portuguese', () => {
  assert.equal(formatSize(63), '63 MB');
  assert.equal(formatSize(1200), '1,2 GB');
  assert.equal(formatSize(6600), '6,6 GB');
  assert.equal(levelText('unsupported'), 'Este computador não atende o mínimo');
  assert.match(levelText('light'), /mínimo/);
  assert.match(levelText('compact'), /compacto/);
  assert.match(levelText('full'), /folga/);
});

test('two ways into the smart house: connect the one you have (free), or have one installed here (it costs disk and memory, said up front)', () => {
  const have = OPTIONS.find((o) => o.id === 'home');
  const install = OPTIONS.find((o) => o.id === 'homeInstall');
  assert.deepEqual(have.settings, { home: true });
  assert.deepEqual(have.offSettings, { home: false });
  assert.equal(have.diskMb + have.ramMb, 0);
  assert.deepEqual(install.settings, { home: true });
  assert.deepEqual(install.offSettings, {});               // leaving it out must not undo "I already have one"
  assert.ok(install.diskMb >= 1000 && install.ramMb >= 2000, 'the wizard says what it costs');
  assert.match(install.description, /Docker/);
  assert.match(install.after, /Ajustes > Integrações/);
});

test('choosing to install turns the house on even though the other item is left out', () => {
  const { buildPlan } = require('../../../src/features/installer/plan');
  const { verdict } = require('../../../src/features/installer/tiers');
  const hw = { platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 15.6, freeDiskGb: 50, cores: 8 };
  const p = buildPlan({ hw, verdict: verdict(hw), selected: ['homeInstall'] });
  assert.equal(p.baseline.home, false);                                   // written off because "I already have one" was left out...
  assert.deepEqual(p.steps.find((s) => s.id === 'homeInstall').settings, { home: true });   // ...and then turned on by the step, which is applied after
  assert.deepEqual(p.after.filter((a) => /Home Assistant/.test(a)).length, 1);
  assert.equal(p.totals.diskMb, 1500 + 6600 + 1000);
});
