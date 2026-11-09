'use strict';
// HTTP client for the local Chakmati engine. Used only by the main process: the renderer windows have no network access
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
  // the person's own message, typed in the reply box of a conversation: sent to WhatsApp as it is, not through the assistant
  async sendDirect(chatId, text) {
    if (!CHAT_ID.test(chatId)) throw new Error('invalid chat id');
    if (typeof text !== 'string' || !text.trim() || text.length > 4000) throw new Error('invalid text');
    return (await this._request(`/whatsapp/chats/${encodeURIComponent(chatId)}/send`, { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ text }) })).json();
  }

  async audio(chatId, messageId) {
    if (!CHAT_ID.test(chatId)) throw new Error('invalid chat id');
    if (!MESSAGE_ID.test(messageId)) throw new Error('invalid message id');
    const res = await this._request(`/whatsapp/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/audio`, { headers: UI });
    const mime = (res.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    if (!mime.startsWith('audio/')) throw new Error('not audio');
    return { mime, base64: Buffer.from(await res.arrayBuffer()).toString('base64') };
  }

  // The optional enhanced voice (a small neural voice that is downloaded the first time it is turned on).
  async voiceStatus() { return (await this._request('/voice/status')).json(); }
  async voiceDownload() { return (await this._request('/voice/download', { method: 'POST', headers: UI })).json(); }
  async voiceRemove() { return (await this._request('/voice', { method: 'DELETE', headers: UI })).json(); }

  async speak(text, speed = 'normal') {
    const clean = String(text ?? '').trim();
    if (!clean) throw new Error('empty text');
    if (clean.length > 600) throw new Error('text too long');
    if (speed !== 'normal' && speed !== 'fast') throw new Error('invalid speed');
    const res = await this._request('/speak', { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ text: clean, speed }) });
    if (!(res.headers.get('content-type') || '').startsWith('audio/')) throw new Error('not audio');
    return { mime: 'audio/wav', base64: Buffer.from(await res.arrayBuffer()).toString('base64') };
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

  // The regional way of speaking, changed in the running engine.
  async setPersonality(id) {
    if (typeof id !== 'string' || !/^[a-z]{3,20}$/.test(id)) throw new Error('invalid personality');
    return (await this._request('/personality', { method: 'PUT', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ id }) })).json();
  }

  // Connecting to Home Assistant (the way to the Alexa): find it, start the sign-in, say what is connected, disconnect.
  async homeDiscover() { return (await this._request('/home/discover')).json(); }
  async homeStatus() { return (await this._request('/home/status')).json(); }
  async homeConnect(url) {
    if (typeof url !== 'string' || !url.trim() || url.length > 200) throw new Error('invalid address');
    return (await this._request('/home/connect', { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ url: url.trim() }) })).json();
  }
  // Installing a Home Assistant on this computer through Docker (for someone who has none): what is there, and start it.
  async homeInstallStatus() { return (await this._request('/home/install')).json(); }
  async homeInstallStart() {
    return (await this._request('/home/install', { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ confirm: true }) })).json();
  }
  async homeAccount(name, password) {
    if (typeof password !== 'string' || password.length < 8 || password.length > 128) throw new Error('invalid password');
    const body = { name: typeof name === 'string' ? name.slice(0, 60) : '', password };
    return (await this._request('/home/install/account', { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify(body) })).json();
  }
  // Linking the Alexa through Home Assistant's own setup: status (and the countries), start with the credentials (they go no further than the engine), cancel.
  async homeAlexaStatus() { return (await this._request('/home/alexa')).json(); }
  async homeAlexaStart(email, password, code) {
    if (typeof email !== 'string' || email.length < 3 || email.length > 254) throw new Error('invalid email');
    if (typeof password !== 'string' || !password || password.length > 256) throw new Error('invalid password');
    if (typeof code !== 'string' || !/^[\d\s]{6,12}$/.test(code)) throw new Error('invalid code');
    return (await this._request('/home/alexa', { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ email, password, code }) })).json();
  }
  async homePlayers() { return (await this._request('/home/players')).json(); }
  async homePlayerControl(id, action, text = '') {
    if (typeof id !== 'string' || !/^media_player\.[a-z0-9_]{1,100}$/.test(id)) throw new Error('invalid player');
    if (!['pause', 'play', 'next', 'previous', 'volume_up', 'volume_down', 'search'].includes(action)) throw new Error('invalid action');
    if (typeof text !== 'string' || text.length > 200) throw new Error('invalid text');
    return (await this._request('/home/players/control', { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ id, action, text }) })).json();
  }
  async homeAlexaCancel() { return (await this._request('/home/alexa', { method: 'DELETE', headers: UI })).json(); }
  async homeDisconnect() { return (await this._request('/home', { method: 'DELETE', headers: UI })).json(); }

  // How the person is addressed (ele/dele, ela/dela, elu/delu, or none), changed in the running engine.
  async setPronouns(id) {
    if (typeof id !== 'string' || !/^[a-z]{3,20}$/.test(id)) throw new Error('invalid pronouns');
    return (await this._request('/pronouns', { method: 'PUT', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ id }) })).json();
  }

  async _decide(id, verb) {
    if (!ACTION_ID.test(id)) throw new Error('invalid action id');
    return (await this._request(`/actions/${id}/${verb}`, { method: 'POST', headers: { 'X-LiteAgent-UI': '1' } })).json();
  }

  async setAutomation(id, op) {
    if (!ACTION_ID.test(id)) throw new Error('invalid automation id');
    if (op === 'delete') return (await this._request(`/automations/${id}`, { method: 'DELETE', headers: UI })).json();
    if (op !== 'enable' && op !== 'disable') throw new Error('invalid operation');
    return (await this._request(`/automations/${id}/${op}`, { method: 'POST', headers: UI })).json();
  }

  // The recording of a voice automation waiting for confirmation, so the person can listen before saying yes.
  async preview(id) {
    if (!ACTION_ID.test(id)) throw new Error('invalid action id');
    const res = await this._request(`/actions/${id}/preview`, { headers: UI });
    return { mime: 'audio/ogg', base64: Buffer.from(await res.arrayBuffer()).toString('base64') };
  }

  // The person's own recorded reply (a 16 kHz WAV of at most ~10 s) becomes a proposal that still has to be confirmed.
  async proposeRecorded(bytes, hours = null) {
    if (!bytes || !bytes.length) throw new Error('empty recording');
    if (bytes.length > 1.5 * 1024 * 1024) throw new Error('recording too large');
    if (hours && !(/^([01]\d|2[0-3]):[0-5]\d$/.test(hours.from) && /^([01]\d|2[0-3]):[0-5]\d$/.test(hours.to))) throw new Error('invalid hours');
    const query = hours ? `?hours_from=${encodeURIComponent(hours.from)}&hours_to=${encodeURIComponent(hours.to)}` : '';
    return (await this._request(`/automations/recorded${query}`, { method: 'POST', headers: { ...UI, 'content-type': 'audio/wav' }, body: bytes })).json();
  }

  // "Manter aprovado" for safe computer commands: the engine itself enforces that only safe ones skip the question.
  async setStanding(on) {
    return (await this._request('/computer/standing', { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ on: on === true }) })).json();
  }

  approve(id) { return this._decide(id, 'approve'); }
  reject(id) { return this._decide(id, 'reject'); }

  // The person's answer to something the browser asked ("qual é o seu usuário?", a password). Not stored here and not logged.
  async sendInput(jobId, requestId, value) {
    if (!ACTION_ID.test(String(jobId)) || !ACTION_ID.test(String(requestId))) throw new Error('invalid request');
    const text = String(value ?? '');
    if (!text || text.length > 500) throw new Error('invalid answer');
    await this._request(`/jobs/${jobId}/input`, { method: 'POST', headers: { ...UI, 'content-type': 'application/json' }, body: JSON.stringify({ request_id: requestId, value: text }) });
    return { ok: true };
  }

  // Parar: stops a job in the engine (the browser closes, nothing more is done).
  async cancelJob(jobId) {
    if (!ACTION_ID.test(String(jobId))) throw new Error('invalid request');
    await this._request(`/jobs/${jobId}/cancel`, { method: 'POST', headers: UI });
    return { ok: true };
  }

  // Files attached to the conversation: the engine keeps only their text (swept after a week). `bytes` is a Uint8Array.
  async attach(name, bytes) {
    const clean = String(name ?? '').trim();
    if (!clean || !bytes || !bytes.length) throw new Error('empty file');
    if (bytes.length > 20 * 1024 * 1024) throw new Error('file too large');
    const res = await this._request('/attachments', { method: 'POST', headers: { ...UI, 'content-type': 'application/octet-stream', 'x-filename': encodeURIComponent(clean) }, body: bytes });
    return res.json();
  }

  async detach(id) {
    if (!ACTION_ID.test(String(id))) throw new Error('invalid attachment');
    return (await this._request(`/attachments/${id}`, { method: 'DELETE', headers: UI })).json();
  }

  async* streamMessage(text, signal, attachments = []) {
    const clean = String(text ?? '').trim();
    if (!clean) throw new Error('empty message');
    if (clean.length > MAX_TEXT) throw new Error('message too long');
    const res = await this._request('/message/stream', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: clean, attachments: attachments.filter((id) => ACTION_ID.test(String(id))).slice(0, 5) }), signal,
    });
    for await (const event of parseSse(res.body)) yield event.type === 'screenshot' ? await this._withImage(event, signal) : event;
  }

  // A browser step: the renderer has no network, so the screenshot is fetched here and handed over as a data URL.
  async _withImage(event, signal) {
    if (!ACTION_ID.test(String(event.job_id)) || !Number.isInteger(event.step) || event.step < 1) return event;
    try {
      const res = await this._request(`/jobs/${event.job_id}/frames/${event.step}`, { signal });
      return { ...event, image: `data:image/jpeg;base64,${Buffer.from(await res.arrayBuffer()).toString('base64')}` };
    } catch { return event; } // a missing picture must not end the conversation: the note still shows what happened
  }
}

module.exports = { EngineClient, EngineError, assertLoopback, parseSse };
