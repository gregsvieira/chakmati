'use strict';
// The two things the installer asks Ollama for, over its local HTTP API (no shell, no command line built from text).
const { assertLoopback } = require('../engine').client;
const { MODELS, REASONING } = require('./catalog');

const OLLAMA_URL = 'http://127.0.0.1:11434';
const NOT_FOUND = 'Não encontrei o Ollama rodando neste computador. Instale e abra o Ollama (ollama.com/download) e tente de novo.';

function makeRunners({ fetchFn = fetch, baseUrl = OLLAMA_URL, saveSettings, sync, shortcut }) {
  assertLoopback(baseUrl);
  return {
    async checkOllama() {
      let res;
      try { res = await fetchFn(`${baseUrl}/api/version`, { signal: AbortSignal.timeout(3000) }); } catch { throw new Error(NOT_FOUND); }
      if (!res.ok) throw new Error(NOT_FOUND);
    },

    async pullModel(model, onProgress) {
      if (![...MODELS, ...REASONING].some((m) => m.id === model)) throw new Error('Esse modelo não está na lista do instalador.');
      const res = await fetchFn(`${baseUrl}/api/pull`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ model, stream: true }),
      });
      if (!res.ok || !res.body) throw new Error(`O Ollama respondeu ${res.status}.`);

      let finished = false;
      const handle = (line) => {
        const data = JSON.parse(line);
        if (data.error) throw new Error(data.error);
        onProgress({ status: data.status, completed: data.completed || 0, total: data.total || 0 });
        if (data.status === 'success') finished = true;
      };
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (line) handle(line);
        }
      }
      if (buffer.trim()) handle(buffer.trim());
      if (!finished) throw new Error('O download do modelo não terminou.');
    },

    async syncEngine(extras, onProgress) {
      if (!sync) throw new Error('O motor só é preparado no aplicativo instalado.');
      return sync(extras, onProgress);
    },

    async createDesktopShortcut() {
      if (!shortcut) throw new Error('O atalho só é criado no aplicativo instalado.');
      return shortcut();
    },

    saveSettings: (patch) => saveSettings(patch),
  };
}

module.exports = { makeRunners, OLLAMA_URL };
