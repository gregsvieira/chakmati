const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PRONOUNS, PRONOUN_NAMES, PERSONALITIES, PERSONALITY_NAMES, DEFAULTS, normalize, load, save, engineEnv } = require('../../../src/features/settings/settings');

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'chakmati-'));
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

test('animations and the glass are off by default (they cost memory) and each can be switched on', () => {
  assert.equal(DEFAULTS.still, true);   // still = no animations
  assert.equal(DEFAULTS.glass, false);
  assert.equal(normalize({ still: false }).still, false);
  assert.equal(normalize({ glass: true }).glass, true);
  assert.equal(normalize({ still: 'no' }).still, true);     // not a boolean: the default stays
  assert.equal(normalize({ glass: 'yes' }).glass, false);
  assert.equal(normalize({}).still, true);
});

test('integrations map to the engine environment: web search on by default, the rest off', () => {
  assert.deepEqual(engineEnv(DEFAULTS), { CHAKMATI_CHAT_MODEL: 'qwen3.5:latest', CHAKMATI_PERSONALITY: 'padrao', CHAKMATI_PRONOUNS: 'none', CHAKMATI_RESEARCH_BACKEND: 'ddg', CHAKMATI_WHATSAPP_BACKEND: 'off', CHAKMATI_CALENDAR_BACKEND: 'off', CHAKMATI_HOME_BACKEND: 'off', CHAKMATI_RESEARCH_SCORER: 'keepall' });
  assert.equal(engineEnv(DEFAULTS, { searxng: true }).CHAKMATI_RESEARCH_BACKEND, 'searxng');
  assert.equal(engineEnv({ ...DEFAULTS, research: false }).CHAKMATI_RESEARCH_BACKEND, 'off');
  assert.deepEqual(engineEnv({ ...DEFAULTS, whatsapp: true, calendar: true }), { CHAKMATI_CHAT_MODEL: 'qwen3.5:latest', CHAKMATI_PERSONALITY: 'padrao', CHAKMATI_PRONOUNS: 'none', CHAKMATI_RESEARCH_BACKEND: 'ddg', CHAKMATI_WHATSAPP_BACKEND: 'openwa', CHAKMATI_CALENDAR_BACKEND: 'auto', CHAKMATI_HOME_BACKEND: 'off', CHAKMATI_RESEARCH_SCORER: 'keepall' });
  assert.equal(engineEnv({ ...DEFAULTS, laya: true }).CHAKMATI_RESEARCH_SCORER, 'laya');
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

test('the system voice is the default; the enhanced voice is an explicit choice, normal pace', () => {
  assert.equal(DEFAULTS.enhancedVoice, false);
  assert.equal(DEFAULTS.voiceSpeed, 'normal');
  assert.equal(normalize({ enhancedVoice: true }).enhancedVoice, true);
  assert.equal(normalize({ enhancedVoice: 'sim' }).enhancedVoice, false);
  assert.equal(normalize({ voiceSpeed: 'fast' }).voiceSpeed, 'fast');
  assert.equal(normalize({ voiceSpeed: 'warp' }).voiceSpeed, 'normal');
});

test('the chat model is a plain Ollama name and reaches the engine', () => {
  assert.equal(DEFAULTS.chatModel, 'qwen3.5:latest');
  assert.equal(normalize({ chatModel: 'qwen3.5:0.8b' }).chatModel, 'qwen3.5:0.8b');
  assert.equal(engineEnv({ ...DEFAULTS, chatModel: 'qwen3.5:4b' }).CHAKMATI_CHAT_MODEL, 'qwen3.5:4b');
  for (const bad of ['', 'a b', '../x', 'x;rm', 'm'.repeat(80), 5, null]) assert.equal(normalize({ chatModel: bad }).chatModel, DEFAULTS.chatModel);
});

test('the personality is padrao unless one of the known regional ones is chosen, and it reaches the engine at start', () => {
  assert.equal(DEFAULTS.personality, 'padrao');
  for (const p of ['carioca', 'paulista', 'gaucho', 'nordestino', 'mineiro']) assert.equal(normalize({ personality: p }).personality, p);
  for (const bad of ['klingon', '', null, 42, 'GAUCHO']) assert.equal(normalize({ personality: bad }).personality, 'padrao');
  assert.equal(engineEnv({ ...DEFAULTS, personality: 'gaucho' }).CHAKMATI_PERSONALITY, 'gaucho');
});

test('pronouns are "none" unless one of the known ones is chosen, and they reach the engine at start', () => {
  assert.equal(DEFAULTS.pronouns, 'none');
  for (const p of ['none', 'ele', 'ela', 'elu']) assert.equal(normalize({ pronouns: p }).pronouns, p);
  for (const bad of ['eles', '', null, 42, 'ELA']) assert.equal(normalize({ pronouns: bad }).pronouns, 'none');
  assert.equal(engineEnv({ ...DEFAULTS, pronouns: 'ela' }).CHAKMATI_PRONOUNS, 'ela');
  assert.deepEqual(Object.keys(PRONOUN_NAMES), PRONOUNS);
  assert.deepEqual(Object.keys(PERSONALITY_NAMES), PERSONALITIES);
});

test('the installed personalities: everything for someone who never chose, and Padrão plus the active one are never removable', () => {
  assert.deepEqual(normalize({}).personalities, PERSONALITIES);                                   // an upgrade keeps what was there
  assert.deepEqual(normalize({ personalities: ['gaucho'] }).personalities, ['padrao', 'gaucho']);  // Padrão is always installed
  assert.deepEqual(normalize({ personality: 'mineiro', personalities: ['gaucho'] }).personalities, ['padrao', 'gaucho', 'mineiro']); // so is the active one
  assert.deepEqual(normalize({ personalities: ['klingon', 'gaucho', 'gaucho'] }).personalities, ['padrao', 'gaucho']);              // unknown and repeated ones drop out
  assert.deepEqual(normalize({ personalities: 'gaucho' }).personalities, PERSONALITIES);          // not a list: ignored
  assert.deepEqual(normalize({ personalities: [], personality: 'padrao' }).personalities, ['padrao']);
});

test('the smart house is off by default; switching it on starts the engine with the Home Assistant backend', () => {
  assert.equal(DEFAULTS.home, false);
  assert.equal(normalize({ home: true }).home, true);
  assert.equal(normalize({ home: 'yes' }).home, false);
  assert.equal(engineEnv({ ...DEFAULTS, home: true }).CHAKMATI_HOME_BACKEND, 'homeassistant');
  assert.equal(engineEnv(DEFAULTS).CHAKMATI_HOME_BACKEND, 'off');
});
