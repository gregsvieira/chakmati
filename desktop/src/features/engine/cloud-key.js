'use strict';
// Where the API key of the paid AI lives: encrypted with the operating system's own store (Electron's safeStorage: the Keychain on macOS,
// DPAPI on Windows, the keyring on Linux), in a file of the app's data folder. Never in settings.json, never in a log, never sent to the page.
// The only thing that ever reads it back is the main process, to put it in the environment of the engine it starts, and to check it with the provider.
const fs = require('node:fs');
const path = require('node:path');

const PROVIDERS = Object.freeze({
  anthropic: Object.freeze({ id: 'anthropic', label: 'Anthropic (Claude)', defaultModel: 'claude-sonnet-5-5', checkUrl: 'https://api.anthropic.com/v1/models', keyHelp: 'console.anthropic.com' }),
  openai: Object.freeze({ id: 'openai', label: 'OpenAI', defaultModel: 'gpt-5', checkUrl: 'https://api.openai.com/v1/models', keyHelp: 'platform.openai.com' }),
});
const MODEL_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$/;
const KEY_RE = /^[A-Za-z0-9_\-.]{16,400}$/;   // no spaces, quotes or line breaks: a pasted key with those is a mistake

const validProvider = (id) => typeof id === 'string' && Object.hasOwn(PROVIDERS, id);
const validModel = (m) => typeof m === 'string' && MODEL_RE.test(m);
const validKey = (k) => typeof k === 'string' && KEY_RE.test(k);

function headers(provider, key) {
  return provider === 'anthropic' ? { 'x-api-key': key, 'anthropic-version': '2023-06-01' } : { authorization: `Bearer ${key}` };
}

function createKeyStore({ file, safeStorage }) {
  return {
    available: () => { try { return !!safeStorage.isEncryptionAvailable(); } catch { return false; } },
    save(key) {
      if (!validKey(key)) throw new Error('A chave tem um formato inválido.');
      if (!this.available()) throw new Error('Este computador não tem um cofre do sistema para guardar a chave com segurança.');
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, safeStorage.encryptString(key), { mode: 0o600 });
    },
    load() {
      try { return safeStorage.decryptString(fs.readFileSync(file)); } catch { return ''; }
    },
    clear() { try { fs.rmSync(file, { force: true }); } catch { /* nothing to clear */ } },
  };
}

// Asks the provider's own models list with the key: 200 = accepted. Nothing is sent anywhere else. -> { ok } | { error }
async function checkKey(provider, key, fetchImpl = globalThis.fetch) {
  if (!validProvider(provider) || !validKey(key)) return { error: 'Provedor ou chave inválidos.' };
  try {
    const res = await fetchImpl(PROVIDERS[provider].checkUrl, { headers: headers(provider, key), signal: AbortSignal.timeout(15000) });
    if (res.ok) return { ok: true };
    if (res.status === 401 || res.status === 403) return { error: 'O provedor recusou a chave. Confira se copiou inteira e se ela é uma chave de API.' };
    return { error: `O provedor respondeu com o erro ${res.status}. Tente de novo.` };
  } catch { return { error: 'Não consegui falar com o provedor. Confira a internet e tente de novo.' }; }
}

module.exports = { PROVIDERS, validProvider, validModel, validKey, createKeyStore, checkKey };
