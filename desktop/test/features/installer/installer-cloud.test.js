const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { buildPlan } = require('../../../src/features/installer/plan');
const { verdict } = require('../../../src/features/installer/tiers');
const { PROVIDERS, validKey, validModel, validProvider, createKeyStore, checkKey } = require('../../../src/features/engine/cloud-key');
const { normalize, engineEnv, DEFAULTS } = require('../../../src/features/settings/settings');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');
const hw = { platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 15.6, freeDiskGb: 80, cores: 8 };
const plan = (cloud, selected = []) => buildPlan({ hw, verdict: verdict(hw), selected, cloud });

test('with a paid AI and the local model: both, the paid one is only a setting (no download), the local model is still installed', () => {
  const p = plan({ provider: 'anthropic', model: 'claude-sonnet-5-5', local: true });
  assert.ok(p.steps.some((s) => s.id === 'model'));
  const cloud = p.steps.find((s) => s.id === 'cloud');
  assert.equal(cloud.approval, undefined);
  assert.deepEqual(cloud.settings, { cloudProvider: 'anthropic', cloudModel: 'claude-sonnet-5-5', localModel: true });
  assert.equal(p.baseline.cloudProvider, undefined);
});

test('only the paid AI: no local model, no Ollama check, nothing of the model in the totals, and a warning about the limit', () => {
  const only = plan({ provider: 'openai', model: 'gpt-5', local: false });
  const both = plan({ provider: 'openai', model: 'gpt-5', local: true });
  assert.equal(only.steps.some((s) => s.id === 'model' || s.id === 'ollama'), false);
  assert.ok(only.totals.diskMb < both.totals.diskMb);
  assert.ok(only.warnings.some((w) => /limite da sua assinatura/.test(w)));
  assert.equal(only.steps.find((s) => s.id === 'cloud').settings.localModel, false);
});

test('only the paid AI, with the reasoning model: Ollama is still checked (that model needs it)', () => {
  assert.ok(plan({ provider: 'openai', model: 'gpt-5', local: false }, ['reasoning']).steps.some((s) => s.id === 'ollama'));
});

test('no paid AI: written off, and a half-done or unknown one is refused', () => {
  assert.deepEqual([plan(null).baseline.cloudProvider, plan(null).baseline.cloudModel, plan(null).baseline.localModel], ['', '', true]);
  assert.throws(() => plan({ provider: 'nope', model: 'x', local: true }), /incompleta/);
  assert.throws(() => plan({ provider: 'openai', model: 'bad model!', local: true }), /incompleta/);
});

test('the settings keep a provider only with its model, and the engine hears about it (never the key)', () => {
  assert.equal(normalize({ cloudProvider: 'openai' }).cloudProvider, '');
  const s = normalize({ cloudProvider: 'anthropic', cloudModel: 'claude-sonnet-5-5', localModel: false });
  assert.deepEqual([s.cloudProvider, s.cloudModel, s.localModel], ['anthropic', 'claude-sonnet-5-5', false]);
  assert.equal(normalize({ cloudProvider: 'x', cloudModel: 'm', localModel: false }).localModel, true);
  const env = engineEnv(s);
  assert.deepEqual([env.CHAKMATI_CLOUD_PROVIDER, env.CHAKMATI_CLOUD_MODEL, env.CHAKMATI_LOCAL_MODEL], ['anthropic', 'claude-sonnet-5-5', '0']);
  assert.equal('CHAKMATI_CLOUD_API_KEY' in engineEnv(DEFAULTS), false);
  assert.equal(JSON.stringify(s).includes('sk-'), false);
});

test('inputs are validated before anything is stored or sent', () => {
  assert.ok(validProvider('openai') && !validProvider('constructor') && !validProvider(''));
  assert.ok(validModel('claude-sonnet-5-5') && !validModel('a b') && !validModel('../x'));
  assert.ok(validKey('sk-ant-api03-abcdefghijklmnop') && !validKey('short') && !validKey('has space in it 12345678') && !validKey('line\nbreak0123456789ab'));
});

test('the key store encrypts with the system store, refuses without one, and clears', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ck-'));
  const file = path.join(dir, 'cloud-key.bin');
  const safe = { isEncryptionAvailable: () => true, encryptString: (s) => Buffer.from(`enc:${Buffer.from(s).toString('base64')}`), decryptString: (b) => Buffer.from(b.toString().slice(4), 'base64').toString() };
  const store = createKeyStore({ file, safeStorage: safe });
  store.save('sk-test-abcdefghijklmnop');
  assert.equal(fs.readFileSync(file, 'utf8').includes('sk-test'), false, 'the file never holds the key in clear');
  assert.equal(store.load(), 'sk-test-abcdefghijklmnop');
  store.clear();
  assert.equal(store.load(), '');
  const none = createKeyStore({ file, safeStorage: { ...safe, isEncryptionAvailable: () => false } });
  assert.throws(() => none.save('sk-test-abcdefghijklmnop'), /cofre/);
  assert.equal(fs.existsSync(file), false);
});

test('the key is checked against the provider\'s own address, and the answers become sentences', async () => {
  const calls = [];
  const fake = (status) => async (url, init) => { calls.push({ url, headers: init.headers }); return { ok: status === 200, status }; };
  assert.deepEqual(await checkKey('anthropic', 'sk-ant-abcdefghijklmnop', fake(200)), { ok: true });
  assert.equal(calls[0].url, PROVIDERS.anthropic.checkUrl);
  assert.equal(calls[0].headers['x-api-key'], 'sk-ant-abcdefghijklmnop');
  await checkKey('openai', 'sk-abcdefghijklmnopqr', fake(200));
  assert.equal(calls[1].headers.authorization, 'Bearer sk-abcdefghijklmnopqr');
  assert.match((await checkKey('openai', 'sk-abcdefghijklmnopqr', fake(401))).error, /recusou a chave/);
  assert.match((await checkKey('openai', 'sk-abcdefghijklmnopqr', fake(500))).error, /erro 500/);
  assert.match((await checkKey('openai', 'sk-abcdefghijklmnopqr', async () => { throw new Error('offline'); })).error, /Não consegui falar/);
  assert.match((await checkKey('nope', 'sk-abcdefghijklmnopqr', fake(200))).error, /inválidos/);
  assert.equal(calls.length, 4);   // the invalid provider never reached the network
  assert.ok(calls.every((c) => /^https:\/\/api\.(anthropic|openai)\.com\//.test(c.url)));
});

test('the page never keeps the key, the main process stores it, and the engine only gets it at start from the store', () => {
  const js = read('features', 'installer', 'renderer', 'installer.js');
  assert.match(js, /\$\('cloud-key'\)\.value = '';   \/\/ gone from the page the moment it is sent/);
  assert.equal(/(local|session)Storage\.setItem\([^)]*key/i.test(js), false);
  const wiz = read('features', 'installer', 'wizard.js');
  assert.match(wiz, /ipcMain\.handle\('installer:cloud-check'/);
  assert.match(wiz, /createCloudSetup\(\{ keyStore \}\)\.connect\(provider, key, model\)/);
  const setup = read('features', 'engine', 'cloud-setup.js');
  assert.ok(setup.indexOf('await check(provider, key)') < setup.indexOf('keyStore.save(key)'), 'only a key the provider accepted is stored');
  assert.match(read('features', 'engine', 'service.js'), /CHAKMATI_CLOUD_API_KEY = cloudKeyStore\(\)\.load\(\)/);
  assert.match(read('preload.js'), /cloudCheck: \(provider, key, model\)/);
});

test('the screens: boxes to flag, grouped, and the paid AI behind its own box', () => {
  const html = read('features', 'installer', 'renderer', 'installer.html');
  for (const id of ['s-options', 's-cloud', 'cloud-provider', 'cloud-key', 'cloud-model', 'cloud-save', 'opt-yes']) assert.ok(html.includes(`id="${id}"`), id);
  const js = read('features', 'installer', 'renderer', 'installer.js');
  assert.match(js, /Quero rodar com a minha assinatura de IA paga/);
  assert.match(js, /type: 'checkbox'/);
  for (const g of ['Voz', 'Modelos extras', 'Integrações', 'Aparência e privacidade']) assert.ok(js.includes(`'${g}'`), g);
});
