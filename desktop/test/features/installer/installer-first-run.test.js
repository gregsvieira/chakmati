const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { needsSetup, writeSetupDone } = require('../../../src/features/installer/first-run');
const { venvPython } = require('../../../src/features/engine/launch');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'chakmati-fr-'));
const makeVenv = (dir) => { const py = venvPython({ dataDir: dir }); fs.mkdirSync(path.dirname(py), { recursive: true }); fs.writeFileSync(py, ''); };

test('a development run never opens the wizard on its own', () => {
  assert.equal(needsSetup({ packaged: false, dataDir: tmp() }), false);
});

test('an installed app with no marker needs the setup', () => {
  assert.equal(needsSetup({ packaged: true, dataDir: tmp() }), true);
});

test('the marker alone is not enough: the Python environment must exist too', () => {
  const dir = tmp();
  writeSetupDone({ dataDir: dir, extras: [] });
  assert.equal(needsSetup({ packaged: true, dataDir: dir }), true);
  makeVenv(dir);
  assert.equal(needsSetup({ packaged: true, dataDir: dir }), false);
});

test('a corrupt or unfinished marker means setup again', () => {
  const dir = tmp();
  makeVenv(dir);
  fs.writeFileSync(path.join(dir, 'setup.json'), '{not json');
  assert.equal(needsSetup({ packaged: true, dataDir: dir }), true);
  fs.writeFileSync(path.join(dir, 'setup.json'), JSON.stringify({ done: false }));
  assert.equal(needsSetup({ packaged: true, dataDir: dir }), true);
});

test('the marker is written whole, records the extras and leaves no temporary file', () => {
  const dir = path.join(tmp(), 'nested', 'data');
  writeSetupDone({ dataDir: dir, extras: ['voice'] });
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, 'setup.json'), 'utf8')), { done: true, extras: ['voice'] });
  assert.deepEqual(fs.readdirSync(dir), ['setup.json']);
});
