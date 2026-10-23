'use strict';
// HTTP client for the local lite-agent engine. Used only by the main process: the renderer windows have no network access
// at all (their CSP forbids it), so every call to the engine goes through here, and here it can only reach loopback.

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]']);
const ACTION_ID = /^[0-9a-f]{32}$/;
const MAX_TEXT = 8000;
const CHAT_ID = /^[0-9A-Za-z._-]+@(?:c\.us|lid|g\.us)$/;
const MESSAGE_ID = /^[0-9A-Za-z_.@:-]{1,160}$/;
const UI = { 'X-LiteAgent-UI': '1' };

class EngineError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'EngineError';
    this.status = status;
  }
}

function assertLoopback(url) {
  let u;
  try { u = new URL(url); } catch { throw new Error('invalid engine URL'); }
  if (u.protocol !== 'http:' || !LOOPBACK_HOSTS.has(u.hostname)) throw new Error('engine URL must be a loopback http address');
  return u;
}

// Server-Sent Events -> JSON objects. Tolerates events split across chunks (including inside a multi-byte character),
// comment lines and malformed data lines.
async function* parseSse(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  const emit = (block) => {
    const data = block.split(/\r?\n/).filter((l) => l.startsWith('data:')).map((l) => l.slice(5).replace(/^ /, '')).join('\n');
    if (!data) return null;
    try { return JSON.parse(data); } catch { return null; }
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let m;
      while ((m = /\r?\n\r?\n/.exec(buffer))) {
        const block = buffer.slice(0, m.index);
        buffer = buffer.slice(m.index + m[0].length);
        const event = emit(block);
        if (event !== null) yield event;
      }
    }
    buffer += decoder.decode();
    const tail = emit(buffer);
    if (tail !== null) yield tail;
  } finally {
    reader.releaseLock?.();
  }
}

class EngineClient {
  constructor({ baseUrl = 'http://127.0.0.1:8765', fetchImpl = globalThis.fetch } = {}) {
    assertLoopback(baseUrl);
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.fetch = fetchImpl;
  }

  async _request(path, init = {}) {
    const res = await this.fetch(this.baseUrl + path, init);
    if (!res.ok) {
      let detail = res.statusText || `HTTP ${res.status}`;
      try { const body = await res.json(); detail = body.detail || body.error || detail; } catch { /* keep the status text */ }
      throw new EngineError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return res;
  }

  async health() {
    try {
      const res = await this.fetch(this.baseUrl + '/health', { signal: AbortSignal.timeout(3000) });
      return res.ok;
    } catch {
      return false;
    }
  }

  async overview() { return (await this._request('/overview')).json(); }

  async notices(after, wait, signal) {
    return (await this._request(`/notices?after=${Number(after) || 0}&wait=${Number(wait) || 0}`, { signal })).json();
  }

  async chats(limit = 60) {
    return (await this._request(`/whatsapp/chats?limit=${Math.max(1, Math.min(Number(limit) || 60, 200))}`)).json();
  }

  async messages(chatId, last = 40) {
    if (!CHAT_ID.test(chatId)) throw new Error('invalid chat id');
    const n = Math.max(1, Math.min(Number(last) || 40, 200));
    return (await this._request(`/whatsapp/chats/${encodeURIComponent(chatId)}/messages?last=${n}`, { headers: UI })).json();
  }

  // The decrypted voice note as { mime, base64 }. The engine does the downloading and decrypting.
  async audio(chatId, messageId) {
    if (!CHAT_ID.test(chatId)) throw new Error('invalid chat id');
    if (!MESSAGE_ID.test(messageId)) throw new Error('invalid message id');
    const res = await this._request(`/whatsapp/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/audio`, { headers: UI });
    const mime = (res.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    if (!mime.startsWith('audio/')) throw new Error('not audio');
    return { mime, base64: Buffer.from(await res.arrayBuffer()).toString('base64') };
  }

  // Speech to text: the recording goes to the local engine (faster-whisper); nothing leaves the computer.
  async transcribe(bytes, mime) {
    const type = String(mime || '').split(';')[0].trim().toLowerCase();
    if (!type.startsWith('audio/')) throw new Error('not audio');
    if (!bytes || !bytes.length) throw new Error('empty recording');
    if (bytes.length > 20 * 1024 * 1024) throw new Error('recording too large');
    const res = await this._request('/transcribe', { method: 'POST', headers: { ...UI, 'content-type': type }, body: bytes });
    return res.json();
  }

  async _decide(id, verb) {
    if (!ACTION_ID.test(id)) throw new Error('invalid action id');
    return (await this._request(`/actions/${id}/${verb}`, { method: 'POST', headers: { 'X-LiteAgent-UI': '1' } })).json();
  }

  approve(id) { return this._decide(id, 'approve'); }
  reject(id) { return this._decide(id, 'reject'); }

  async* streamMessage(text, signal) {
    const clean = String(text ?? '').trim();
    if (!clean) throw new Error('empty message');
    if (clean.length > MAX_TEXT) throw new Error('message too long');
    const res = await this._request('/message/stream', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: clean }), signal,
    });
    yield* parseSse(res.body);
  }
}

module.exports = { EngineClient, EngineError, assertLoopback, parseSse };
