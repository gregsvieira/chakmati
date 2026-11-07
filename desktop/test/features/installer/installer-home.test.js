const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');
const ids = (html) => [...new Set([...html.matchAll(/id="(hm-[\w-]+)"/g)].map((m) => m[1]))].sort();

test('the wizard has the same smart-house markup as the modal in Ajustes, so the one flow drives both', () => {
  const panel = read('features', 'panel', 'renderer', 'panel.html');
  const modal = panel.slice(panel.indexOf('<div id="home-modal"'), panel.indexOf('<div id="notice-modal"'));
  const wizard = read('features', 'installer', 'renderer', 'installer.html');
  const section = wizard.slice(wizard.indexOf('<section id="s-home"'), wizard.indexOf('</section>', wizard.indexOf('<section id="s-home"')));
  assert.deepEqual(ids(section), ids(modal));
  assert.match(wizard, /<script src="\.\.\/\.\.\/home\/modal-logic\.js"><\/script>\s*<script src="\.\.\/\.\.\/home\/renderer\/flow\.js"><\/script>\s*<script src="installer\.js"><\/script>/);
});

test('the step is offered only after a finished install, is optional, and every call it makes is exposed to the wizard', () => {
  const js = read('features', 'installer', 'renderer', 'installer.js');
  assert.match(js, /if \(result\.status === 'done'\) return showDone\(true\)/);
  assert.match(js, /onClose: \(\) => showDone\(false\)/);
  assert.match(js, /rootId: 's-home'/);
  const preload = read('preload.js');
  const installer = preload.slice(preload.indexOf('installer: {'), preload.indexOf('}', preload.indexOf('homeOpenHa')));
  for (const call of ['homePrepare', 'homeDiscover', 'homeConnect', 'homeStatus', 'homeInstallInfo', 'homeInstallStart', 'homeAccount', 'homeAlexaStart', 'homeAlexaStatus', 'homeAlexaCancel', 'homeOpenHa']) assert.ok(installer.includes(`${call}:`), call);
});

test('the main process starts the engine for the step, checks it answers, and stops it before the app relaunches', () => {
  const wiz = read('features', 'installer', 'wizard.js');
  assert.match(wiz, /ipcMain\.handle\('installer:home-prepare'/);
  assert.match(wiz, /startEngine\(\)/);
  assert.match(wiz, /child\.kill\(\)/);
  assert.ok(wiz.indexOf('child.kill()') < wiz.indexOf('onFinish();'), 'the engine stops before the relaunch');
});

test('the shared flow takes its root, its labels and its way out from the screen that hosts it', () => {
  const flow = read('features', 'home', 'renderer', 'flow.js');
  assert.match(flow, /rootId = 'home-modal'/);
  assert.match(flow, /onClose = \(\) => \{\}/);
  assert.match(flow, /root\.HomeFlow = \{ create \}/);
});
