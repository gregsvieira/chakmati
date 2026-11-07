const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createCloudSetup } = require('../../../src/features/engine/cloud-setup');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');
const KEY = 'sk-test-abcdefghijklmnop';
const store = (over = {}) => { const saved = []; return { saved, available: () => true, save: (k) => saved.push(k), ...over }; };

test('the shared setup stores a key only after the provider accepted it, and says why when it did not', async () => {
  const s = store();
  assert.deepEqual(await createCloudSetup({ keyStore: s, check: async () => ({ ok: true }) }).connect('openai', KEY, 'gpt-5'), { ok: true });
  assert.deepEqual(s.saved, [KEY]);
  const refused = store();
  assert.match((await createCloudSetup({ keyStore: refused, check: async () => ({ error: 'O provedor recusou a chave.' }) }).connect('openai', KEY, 'gpt-5')).error, /recusou/);
  assert.deepEqual(refused.saved, []);
});

test('bad input never reaches the provider or the store', async () => {
  let calls = 0;
  const setup = createCloudSetup({ keyStore: store(), check: async () => { calls += 1; return { ok: true }; } });
  assert.match((await setup.connect('nope', KEY, 'm')).error, /provedor/);
  assert.match((await setup.connect('openai', KEY, 'a b')).error, /modelo/);
  assert.match((await setup.connect('openai', 'short', 'm')).error, /chave/);
  assert.match((await createCloudSetup({ keyStore: store({ available: () => false }), check: async () => { calls += 1; return { ok: true }; } }).connect('openai', KEY, 'm')).error, /cofre/);
  assert.equal(calls, 0);
});

test('Ajustes: the section, the modal and every element the page looks up exist, and the key is cleared on send', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const js = read('features', 'cloud', 'renderer', 'cloud.js');
  const wanted = [...new Set([...js.matchAll(/\$\('([\w-]+)'\)/g)].map((m) => m[1]))];
  assert.deepEqual(wanted.filter((id) => !html.includes(`id="${id}"`)), []);
  assert.match(js, /\$\('cloud-key'\)\.value = '';   \/\/ gone from the page the moment it is sent/);
  assert.match(html, /<script src="\.\.\/\.\.\/cloud\/renderer\/cloud\.js"><\/script>/);
  assert.match(read('features', 'settings', 'renderer', 'settings.js'), /P\.renderCloud\(\)/);
});

test('the main side: validates, keeps the key when it is left blank for the same provider, removes the key and the choice, and restarts the engine it owns', () => {
  const ipc = read('features', 'cloud', 'ipc.js');
  assert.match(ipc, /validProvider\(provider\)/);
  assert.match(ipc, /validModel\(model\)/);
  assert.match(ipc, /ctx\.settings\.cloudProvider !== provider \|\| !store\(\)\.load\(\)/);
  assert.match(ipc, /store\(\)\.clear\(\);\s*Object\.assign\(ctx\.settings, \{ cloudProvider: '', cloudModel: '', localModel: true \}\)/);
  assert.match(ipc, /if \(ctx\.engineProcess\) \{ await engine\.restartEngine\(\)/);
  assert.equal(/return \{[^}]*key[^}]*\}/.test(ipc.replace(/keepKey|key\.trim|, key,|\(key\)/g, '')), false, 'the key is never returned to the page');
  assert.match(read('app', 'ipc.js'), /cloudIpc\.register\(\)/);
  const preload = read('preload.js');
  for (const c of ['panel:cloud-providers', 'panel:cloud-save', 'panel:cloud-remove']) assert.ok(preload.includes(`'${c}'`), c);
});

test('the panel state carries the choice (never the key)', () => {
  const w = read('features', 'panel', 'window.js');
  assert.match(w, /cloudProvider: ctx\.settings\.cloudProvider, cloudModel: ctx\.settings\.cloudModel, localModel: ctx\.settings\.localModel/);
  assert.equal(/cloudKey|api[_-]?key/i.test(w), false);
});
