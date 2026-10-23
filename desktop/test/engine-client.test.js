const test = require('node:test');
const assert = require('node:assert/strict');
const { EngineClient, EngineError, assertLoopback, parseSse } = require('../src/lib/engine-client');

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
function recorder(handler) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => { calls.push({ url: String(url), init }); return handler(String(url), init, calls.length); };
  return { fetchImpl, calls };
}

test('only loopback http addresses are accepted as the engine', () => {
  for (const ok of ['http://127.0.0.1:8765', 'http://localhost:8765', 'http://[::1]:8765']) assert.doesNotThrow(() => assertLoopback(ok));
  for (const bad of ['http://example.com:8765', 'https://127.0.0.1:8765', 'http://192.168.0.5:8765', 'file:///etc/passwd', 'nope'])
    assert.throws(() => assertLoopback(bad), /loopback|invalid/i);
  assert.throws(() => new EngineClient({ baseUrl: 'http://evil.test' }), /loopback/i);
});

test('health is true only for a 200 answer and never throws', async () => {
  assert.equal(await new EngineClient({ fetchImpl: async () => json({ status: 'ok' }) }).health(), true);
  assert.equal(await new EngineClient({ fetchImpl: async () => json({}, 500) }).health(), false);
  assert.equal(await new EngineClient({ fetchImpl: async () => { throw new Error('refused'); } }).health(), false);
});

test('overview and notices use the documented routes and parameters', async () => {
  const { fetchImpl, calls } = recorder(() => json({ ok: true }));
  const c = new EngineClient({ fetchImpl });
  await c.overview();
  await c.notices(7, 25);
  assert.equal(calls[0].url, 'http://127.0.0.1:8765/overview');
  assert.equal(calls[1].url, 'http://127.0.0.1:8765/notices?after=7&wait=25');
});

test('approve and reject send the UI header and POST to the right action', async () => {
  const { fetchImpl, calls } = recorder(() => json({ status: 'executed' }));
  const c = new EngineClient({ fetchImpl });
  await c.approve('a'.repeat(32));
  await c.reject('b'.repeat(32));
  assert.equal(calls[0].url, `http://127.0.0.1:8765/actions/${'a'.repeat(32)}/approve`);
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers['X-LiteAgent-UI'], '1');
  assert.equal(calls[1].url, `http://127.0.0.1:8765/actions/${'b'.repeat(32)}/reject`);
});

test('action ids that are not plain hex are refused before any request is made', async () => {
  const { fetchImpl, calls } = recorder(() => json({}));
  const c = new EngineClient({ fetchImpl });
  for (const bad of ['../x', 'a/b', '', 'zz', 'a'.repeat(33)]) await assert.rejects(() => c.approve(bad), /invalid action id/i);
  assert.equal(calls.length, 0);
});

test('HTTP errors become EngineError carrying the status and the server detail', async () => {
  const c = new EngineClient({ fetchImpl: async () => json({ detail: 'the proposal expired' }, 410) });
  await assert.rejects(() => c.approve('a'.repeat(32)), (e) => e instanceof EngineError && e.status === 410 && /expired/.test(e.message));
});

function sseResponse(chunks) {
  const enc = new TextEncoder();
  return new Response(new ReadableStream({ start(ctrl) { chunks.forEach((s) => ctrl.enqueue(enc.encode(s))); ctrl.close(); } }),
    { status: 200, headers: { 'content-type': 'text/event-stream' } });
}
async function collect(iter) { const out = []; for await (const x of iter) out.push(x); return out; }

test('parseSse yields JSON events, ignores comments and broken lines, and handles events split across chunks', async () => {
  const res = sseResponse(['data: {"type":"route","route":"chat"}\n\n: ping\n\ndata: {"type":"del', 'ta","text":"Olá"}\n\ndata: not json\n\ndata: {"type":"done","result":"Olá"}\n\n']);
  assert.deepEqual(await collect(parseSse(res.body)), [
    { type: 'route', route: 'chat' }, { type: 'delta', text: 'Olá' }, { type: 'done', result: 'Olá' },
  ]);
});

test('parseSse keeps multi-byte characters intact when a chunk boundary falls inside them', async () => {
  const bytes = new TextEncoder().encode('data: {"type":"delta","text":"ação 🚗"}\n\n');
  const cut = 28; // inside the emoji or the accented letters
  const body = new ReadableStream({ start(c) { c.enqueue(bytes.slice(0, cut)); c.enqueue(bytes.slice(cut)); c.close(); } });
  assert.deepEqual(await collect(parseSse(body)), [{ type: 'delta', text: 'ação 🚗' }]);
});

test('streamMessage posts the text and yields the engine events', async () => {
  const { fetchImpl, calls } = recorder(() => sseResponse(['data: {"type":"done","result":"ok"}\n\n']));
  const c = new EngineClient({ fetchImpl });
  const events = await collect(c.streamMessage('tenho mensagens novas?'));
  assert.deepEqual(events, [{ type: 'done', result: 'ok' }]);
  assert.equal(calls[0].url, 'http://127.0.0.1:8765/message/stream');
  assert.deepEqual(JSON.parse(calls[0].init.body), { text: 'tenho mensagens novas?' });
});

test('streamMessage refuses empty or oversized text', async () => {
  const c = new EngineClient({ fetchImpl: async () => sseResponse([]) });
  await assert.rejects(() => collect(c.streamMessage('   ')), /empty/i);
  await assert.rejects(() => collect(c.streamMessage('x'.repeat(8001))), /too long/i);
});

test('messages and audio use the UI header and url-encode the ids', async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, headers: init && init.headers });
    if (url.endsWith('/audio')) return new Response(Buffer.from('OggS-bytes'), { status: 200, headers: { 'content-type': 'audio/ogg' } });
    return new Response(JSON.stringify([{ id: 'm1' }]), { status: 200 });
  };
  const c = new EngineClient({ fetchImpl });
  assert.deepEqual(await c.messages('162457@lid', 500), [{ id: 'm1' }]);
  assert.equal(calls[0].url, 'http://127.0.0.1:8765/whatsapp/chats/162457%40lid/messages?last=200');
  assert.equal(calls[0].headers['X-LiteAgent-UI'], '1');
  const a = await c.audio('162457@lid', 'false_162457@lid_AB12');
  assert.equal(a.mime, 'audio/ogg');
  assert.equal(Buffer.from(a.base64, 'base64').toString(), 'OggS-bytes');
  assert.equal(calls[1].url, 'http://127.0.0.1:8765/whatsapp/chats/162457%40lid/messages/false_162457%40lid_AB12/audio');
});

test('bad chat or message ids never reach the network', async () => {
  const c = new EngineClient({ fetchImpl: async () => { throw new Error('should not be called'); } });
  await assert.rejects(() => c.messages('../../etc'), /invalid chat id/);
  await assert.rejects(() => c.audio('1@lid', 'a b/c'), /invalid message id/);
  await assert.rejects(() => c.audio('x', 'ok'), /invalid chat id/);
});

test('audio refuses a response that is not audio', async () => {
  const c = new EngineClient({ fetchImpl: async () => new Response('<html>', { status: 200, headers: { 'content-type': 'text/html' } }) });
  await assert.rejects(() => c.audio('1@lid', 'm1'), /not audio/);
});

test('transcribe posts the recording as audio with the UI header', async () => {
  let seen;
  const c = new EngineClient({ fetchImpl: async (url, init) => { seen = { url, init }; return new Response(JSON.stringify({ text: 'oi', language: 'pt' }), { status: 200 }); } });
  const out = await c.transcribe(new Uint8Array([1, 2, 3]), 'audio/webm;codecs=opus');
  assert.deepEqual(out, { text: 'oi', language: 'pt' });
  assert.equal(seen.url, 'http://127.0.0.1:8765/transcribe');
  assert.equal(seen.init.method, 'POST');
  assert.equal(seen.init.headers['content-type'], 'audio/webm');
  assert.equal(seen.init.headers['X-LiteAgent-UI'], '1');
});

test('transcribe refuses empty, non-audio and oversized recordings without calling the network', async () => {
  const c = new EngineClient({ fetchImpl: async () => { throw new Error('should not be called'); } });
  await assert.rejects(() => c.transcribe(new Uint8Array(), 'audio/webm'), /empty/);
  await assert.rejects(() => c.transcribe(new Uint8Array([1]), 'text/plain'), /not audio/);
  await assert.rejects(() => c.transcribe(new Uint8Array(21 * 1024 * 1024), 'audio/webm'), /too large/);
});
