const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { DEFAULTS, normalize, load, save, engineEnv } = require('../src/lib/settings');

test('defaults protect the window and show names', () => {
  assert.deepEqual(normalize(undefined), DEFAULTS);
  assert.equal(DEFAULTS.protect, true);
  assert.equal(DEFAULTS.masked, false);
  assert.equal(DEFAULTS.bubbleSide, 'auto');
});

test('valid values are kept and invalid ones fall back to the default, one by one', () => {
  const s = normalize({ protect: false, masked: true, bubbleSide: 'left', icon: { x: 10.4, y: 20 }, engineUrl: 'http://localhost:9000' });
  assert.deepEqual(s, { ...DEFAULTS, protect: false, masked: true, bubbleSide: 'left', icon: { x: 10, y: 20 }, engineUrl: 'http://localhost:9000' });
  const bad = normalize({ protect: 'yes', masked: 1, bubbleSide: 'diagonal', icon: { x: NaN, y: 3 }, engineUrl: 'http://evil.test', extra: 1 });
  assert.deepEqual(bad, DEFAULTS);
  assert.equal('extra' in bad, false);
});

test('the engine address can never be moved off the local machine through the settings file', () => {
  assert.equal(normalize({ engineUrl: 'https://example.com' }).engineUrl, DEFAULTS.engineUrl);
});

test('save then load round-trips, and a missing or corrupt file gives the defaults', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'liteagent-'));
  const file = path.join(dir, 'settings.json');
  assert.deepEqual(load(file), DEFAULTS);
  save(file, { ...DEFAULTS, masked: true, icon: { x: 5, y: 6 } });
  assert.deepEqual(load(file), { ...DEFAULTS, masked: true, icon: { x: 5, y: 6 } });
  fs.writeFileSync(file, '{ not json');
  assert.deepEqual(load(file), DEFAULTS);
  assert.equal(fs.readdirSync(dir).filter((f) => f.endsWith('.tmp')).length, 0);
});

test('integrations are off by default and map to the engine environment', () => {
  assert.deepEqual(engineEnv(DEFAULTS), { LITEAGENT_WHATSAPP_BACKEND: 'off', LITEAGENT_CALENDAR_BACKEND: 'off' });
  assert.deepEqual(engineEnv({ ...DEFAULTS, whatsapp: true, calendar: true }), { LITEAGENT_WHATSAPP_BACKEND: 'openwa', LITEAGENT_CALENDAR_BACKEND: 'auto' });
  assert.equal(normalize({ whatsapp: 'yes' }).whatsapp, false);
});
