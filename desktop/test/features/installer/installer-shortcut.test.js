'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { createDesktopShortcut, appBundle } = require('../../../src/features/installer/shortcut');
const { optionsFor, OPTIONS } = require('../../../src/features/installer/catalog');
const { buildPlan } = require('../../../src/features/installer/plan');
const { runPlan } = require('../../../src/features/installer/run-plan');

const fakeFs = () => {
  const calls = [];
  return { calls, mkdirSync: (...a) => calls.push(['mkdir', ...a]), unlinkSync: (...a) => calls.push(['unlink', ...a]), symlinkSync: (...a) => calls.push(['symlink', ...a]),
    writeFileSync: (...a) => calls.push(['write', ...a]), chmodSync: (...a) => calls.push(['chmod', ...a]) };
};

test('the app bundle is found from the executable inside it', () => {
  assert.equal(appBundle('/Applications/Chakmati.app/Contents/MacOS/Chakmati'), '/Applications/Chakmati.app');
  assert.equal(appBundle('/usr/bin/node'), null);
});

test('Mac: the shortcut is a link on the desktop to the app in Applications', () => {
  const fs = fakeFs();
  const r = createDesktopShortcut({ platform: 'darwin', execPath: '/Applications/Chakmati.app/Contents/MacOS/Chakmati', desktopDir: '/Users/a/Desktop', fs });
  assert.equal(r.path, path.join('/Users/a/Desktop', 'Chakmati'));
  assert.deepEqual(fs.calls.find((c) => c[0] === 'symlink'), ['symlink', '/Applications/Chakmati.app', path.join('/Users/a/Desktop', 'Chakmati')]);
});

test('Mac: it refuses to run from outside an installed app', () => {
  assert.throws(() => createDesktopShortcut({ platform: 'darwin', execPath: '/usr/local/bin/electron', desktopDir: '/d', fs: fakeFs() }), /instalado/);
});

test('Windows: a .lnk is written pointing at the installed executable', () => {
  let args;
  const r = createDesktopShortcut({ platform: 'win32', execPath: 'C:\\Apps\\Chakmati\\Chakmati.exe', desktopDir: 'C:\\Users\\a\\Desktop', fs: fakeFs(), writeShortcutLink: (...a) => { args = a; return true; } });
  assert.match(r.path, /Chakmati\.lnk$/);
  assert.equal(args[1], 'create');
  assert.equal(args[2].target, 'C:\\Apps\\Chakmati\\Chakmati.exe');
});

test('Windows: a failure of the system is reported', () => {
  assert.throws(() => createDesktopShortcut({ platform: 'win32', execPath: 'x.exe', desktopDir: 'd', fs: fakeFs(), writeShortcutLink: () => false }), /atalho/);
});

test('Ubuntu: an executable .desktop launcher is written', () => {
  const fs = fakeFs();
  createDesktopShortcut({ platform: 'linux', execPath: '/opt/Chakmati/chakmati', desktopDir: '/home/a/Desktop', fs });
  const write = fs.calls.find((c) => c[0] === 'write');
  assert.match(write[1], /chakmati\.desktop$/);
  assert.match(write[2], /Exec="\/opt\/Chakmati\/chakmati"/);
  assert.match(write[2], /Name=Chakmati/);
  assert.equal(fs.calls.find((c) => c[0] === 'chmod')[2], 0o755);
});

test('the option exists only in the installed app, on every system', () => {
  for (const p of ['darwin', 'win32', 'linux']) {
    assert.ok(optionsFor(p, { packaged: true }).some((o) => o.id === 'desktopShortcut'));
    assert.ok(!optionsFor(p, { packaged: false }).some((o) => o.id === 'desktopShortcut'));
  }
  assert.equal(OPTIONS.find((o) => o.id === 'desktopShortcut').label, 'Atalho na área de trabalho');
});

test('ticking it adds a shortcut step with nothing to download; running it calls the runner', async () => {
  const hw = { platform: 'darwin', arch: 'arm64', ramGb: 16, freeDiskGb: 200, cores: 8 };
  const plan = buildPlan({ hw, verdict: { level: 'ok', model: 'qwen3.5:4b', reasons: [], notes: [] }, selected: ['desktopShortcut'], engine: { packaged: true } });
  const step = plan.steps.find((s) => s.id === 'desktopShortcut');
  assert.equal(step.kind, 'shortcut');
  assert.equal(step.approval, undefined);
  let made = 0;
  const runners = { checkOllama: async () => {}, pullModel: async () => {}, syncEngine: async () => {}, saveSettings: async () => {}, createDesktopShortcut: async () => { made += 1; } };
  const res = await runPlan(plan, { approve: async () => true, runners });
  assert.equal(res.status, 'done');
  assert.equal(made, 1);
});

test('without ticking it, no shortcut is made', async () => {
  const hw = { platform: 'darwin', arch: 'arm64', ramGb: 16, freeDiskGb: 200, cores: 8 };
  const plan = buildPlan({ hw, verdict: { level: 'ok', model: 'qwen3.5:4b', reasons: [], notes: [] }, selected: [], engine: { packaged: true } });
  assert.ok(!plan.steps.some((s) => s.id === 'desktopShortcut'));
});
