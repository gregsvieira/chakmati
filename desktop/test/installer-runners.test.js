const test = require('node:test');
const assert = require('node:assert/strict');
const { makeRunners } = require('../src/installer/runners');

const ndjson = (...objs) => new Response(objs.map((o) => JSON.stringify(o)).join('\n') + '\n');
const noSave = async () => {};

test('checkOllama passes when the local Ollama answers', async () => {
  const calls = [];
  const r = makeRunners({ fetchFn: async (url) => { calls.push(url); return new Response('{"version":"0.1"}'); }, saveSettings: noSave });
  await r.checkOllama();
  assert.deepEqual(calls, ['http://127.0.0.1:11434/api/version']);
});

test('checkOllama explains when Ollama is not running', async () => {
  const r = makeRunners({ fetchFn: async () => { throw new Error('ECONNREFUSED'); }, saveSettings: noSave });
  await assert.rejects(r.checkOllama(), /Ollama/);
  const r2 = makeRunners({ fetchFn: async () => new Response('x', { status: 500 }), saveSettings: noSave });
  await assert.rejects(r2.checkOllama(), /Ollama/);
});

test('pullModel streams progress and succeeds on "success"', async () => {
  let sent;
  const r = makeRunners({
    fetchFn: async (url, init) => {
      sent = { url, body: JSON.parse(init.body), method: init.method };
      return ndjson({ status: 'pulling manifest' }, { status: 'pulling abc', completed: 5, total: 10 }, { status: 'success' });
    },
    saveSettings: noSave,
  });
  const seen = [];
  await r.pullModel('qwen3.5:4b', (p) => seen.push(p));
  assert.deepEqual(sent, { url: 'http://127.0.0.1:11434/api/pull', body: { model: 'qwen3.5:4b', stream: true }, method: 'POST' });
  assert.deepEqual(seen[1], { status: 'pulling abc', completed: 5, total: 10 });
  assert.equal(seen.at(-1).status, 'success');
});

test('pullModel refuses a model that is not in the catalog, without any request', async () => {
  let called = false;
  const r = makeRunners({ fetchFn: async () => { called = true; return ndjson({ status: 'success' }); }, saveSettings: noSave });
  await assert.rejects(r.pullModel('evil/model:latest', () => {}), /lista do instalador/);
  await assert.rejects(r.pullModel('qwen3.5:2b', () => {}), /lista do instalador/);
  assert.equal(called, false);
});

test('pullModel fails on an error line or when it never says success', async () => {
  const bad = makeRunners({ fetchFn: async () => ndjson({ status: 'pulling' }, { error: 'disco cheio' }), saveSettings: noSave });
  await assert.rejects(bad.pullModel('qwen3.5:4b', () => {}), /disco cheio/);
  const cut = makeRunners({ fetchFn: async () => ndjson({ status: 'pulling', completed: 1, total: 9 }), saveSettings: noSave });
  await assert.rejects(cut.pullModel('qwen3.5:4b', () => {}), /não terminou/);
  const http = makeRunners({ fetchFn: async () => new Response('no', { status: 500 }), saveSettings: noSave });
  await assert.rejects(http.pullModel('qwen3.5:4b', () => {}), /500/);
});

test('the Ollama address can only be this computer', () => {
  assert.throws(() => makeRunners({ baseUrl: 'https://example.com', saveSettings: noSave }));
  assert.doesNotThrow(() => makeRunners({ baseUrl: 'http://localhost:11434', saveSettings: noSave }));
});

test('saveSettings is handed through untouched', async () => {
  let got;
  const r = makeRunners({ saveSettings: async (p) => { got = p; } });
  await r.saveSettings({ still: true });
  assert.deepEqual(got, { still: true });
});
