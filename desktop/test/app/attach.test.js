const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const L = require('../../src/features/files/attach-logic');
const { EngineClient } = require('../../src/features/engine/client');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', 'src', ...p), 'utf8');

test('the + accepts text, PDF, Word, Excel and PowerPoint, with a sentence for everything else', () => {
  for (const name of ['a.txt', 'A.PDF', 'b.docx', 'c.xlsx', 'd.pptx', 'notas.md']) assert.equal(L.check({ name, size: 10 }, 0), null, name);
  assert.match(L.check({ name: 'foto.png', size: 10 }, 0), /ainda não é lido/);
  assert.match(L.check({ name: 'a.txt', size: 0 }, 0), /vazio/);
  assert.match(L.check({ name: 'a.txt', size: L.MAX_BYTES + 1 }, 0), /20 MB/);
  assert.match(L.check({ name: 'a.txt', size: 10 }, L.MAX_FILES), /até 5 arquivos/);
});

test('a long file name is shortened in the middle and keeps its extension', () => {
  assert.equal(L.shortName('curto.pdf'), 'curto.pdf');
  const s = L.shortName('relatorio-anual-de-vendas-da-empresa-2026.pdf');
  assert.ok(s.length <= 26 && s.endsWith('.pdf') && s.includes('…'), s);
});

function client(handler) {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return handler(url, init); };
  return { calls, engine: new EngineClient({ fetchImpl }) };
}
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json' } });

test('attach sends the bytes with the name and the ui header; detach validates the id', async () => {
  const { calls, engine } = client(() => json({ id: 'a'.repeat(32), name: 'x.pdf', chars: 5 }));
  const out = await engine.attach('relatório 1.pdf', new Uint8Array([1, 2, 3]));
  assert.equal(out.chars, 5);
  assert.equal(calls[0].url, 'http://127.0.0.1:8765/attachments');
  assert.equal(calls[0].init.headers['x-filename'], encodeURIComponent('relatório 1.pdf'));
  assert.equal(calls[0].init.headers['X-LiteAgent-UI'], '1');
  await assert.rejects(() => engine.attach('x.pdf', new Uint8Array()), /empty file/);
  await assert.rejects(() => engine.detach('../etc'), /invalid attachment/);
});

test('the messages carry only well-formed attachment ids, at most five', async () => {
  const { calls, engine } = client(() => new Response('data: {"type":"done","result":"ok"}\n\n', { status: 200 }));
  const ids = Array.from({ length: 7 }, (_, i) => String(i).repeat(32));
  for await (const e of engine.streamMessage('resuma', undefined, [...ids, 'not-an-id'])) void e;
  assert.deepEqual(JSON.parse(calls[0].init.body).attachments, ids.slice(0, 5));
});

test('the conversation has the + button, the chips row and the scripts that drive them', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  for (const id of ['attach', 'attach-input', 'attached', 'attached-note']) assert.match(html, new RegExp(`id="${id}"`));
  assert.match(html, /files\/attach-logic\.js/);
  assert.match(html, /files\/renderer\/attach\.js/);
  assert.match(read('features', 'panel', 'renderer', 'thread.js'), /api\.send\(clean, P\.attachedIds/);
  assert.match(read('preload.js'), /attach: \(name, bytes\)/);
});
