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

test('the mood is auto unless one of the known moods is pinned', () => {
  assert.equal(DEFAULTS.mood, 'auto');
  assert.equal(normalize({ mood: 'happy' }).mood, 'happy');
  assert.equal(normalize({ mood: 'offline' }).mood, 'auto'); // offline is a fact, not a choice
  assert.equal(normalize({ mood: 'angry' }).mood, 'auto');
});

test('animations are on by default and can be switched off', () => {
  assert.equal(DEFAULTS.still, false);
  assert.equal(normalize({ still: true }).still, true);
  assert.equal(normalize({ still: 'yes' }).still, false);
});

test('integrations map to the engine environment: web search on by default, the rest off', () => {
  assert.deepEqual(engineEnv(DEFAULTS), { LITEAGENT_RESEARCH_BACKEND: 'ddg', LITEAGENT_WHATSAPP_BACKEND: 'off', LITEAGENT_CALENDAR_BACKEND: 'off' });
  assert.equal(engineEnv(DEFAULTS, { searxng: true }).LITEAGENT_RESEARCH_BACKEND, 'searxng');
  assert.equal(engineEnv({ ...DEFAULTS, research: false }).LITEAGENT_RESEARCH_BACKEND, 'off');
  assert.deepEqual(engineEnv({ ...DEFAULTS, whatsapp: true, calendar: true }), { LITEAGENT_RESEARCH_BACKEND: 'ddg', LITEAGENT_WHATSAPP_BACKEND: 'openwa', LITEAGENT_CALENDAR_BACKEND: 'auto' });
  assert.equal(normalize({ whatsapp: 'yes' }).whatsapp, false);
});

test('hearing Chakmati and talking to it are two separate switches, both off by default', () => {
  assert.equal(DEFAULTS.hear, false);
  assert.equal(DEFAULTS.talk, false);
  assert.deepEqual([normalize({ hear: true }).hear, normalize({ hear: true }).talk], [true, false]);
  assert.deepEqual([normalize({ talk: true }).hear, normalize({ talk: true }).talk], [false, true]);
  assert.equal(normalize({ hear: 'sim', talk: 1 }).hear, false);
  assert.equal(normalize({ voice: true }).hear, false); // the old single switch is not carried over silently
});

test('automatic approval of WhatsApp sends is off by default and only a boolean turns it on', () => {
  assert.equal(DEFAULTS.autoSend, false);
  assert.equal(normalize({ autoSend: true }).autoSend, true);
  assert.equal(normalize({ autoSend: 'sim' }).autoSend, false);
});

test('emojis are not described by default, and the microphone defaults to the computer\'s own', () => {
  assert.equal(DEFAULTS.speakEmojis, false);
  assert.equal(normalize({ speakEmojis: true }).speakEmojis, true);
  assert.equal(normalize({ speakEmojis: 'sim' }).speakEmojis, false);
  assert.equal(DEFAULTS.micSource, 'computer');
  assert.equal(normalize({ micSource: 'system' }).micSource, 'system');
  assert.equal(normalize({ micSource: 'usb' }).micSource, 'computer');
});
