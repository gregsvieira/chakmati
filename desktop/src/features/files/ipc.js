'use strict';
// IPC of the files attached to the conversation: hand the bytes to the engine (which keeps only the text) and take a file away again.
const { ipcMain } = require('electron');
const ctx = require('../../shared/context');
const { friendlyError } = require('../engine').errors;
const { EngineError } = require('../engine').client;
const { MAX_BYTES, check } = require('./attach-logic');

const ID = /^[0-9a-f]{32}$/;

function register() {
  ipcMain.handle('panel:attach', async (_e, name, bytes) => {
    if (typeof name !== 'string' || !(bytes instanceof Uint8Array)) return { error: 'Arquivo inválido.' };
    const problem = check({ name, size: bytes.length }, 0);
    if (problem) return { error: problem };
    if (!ctx.state.engineUp) return { error: 'O motor não está rodando. Inicie o Chakmati.' };
    try {
      return await ctx.engine.attach(name, bytes);
    } catch (e) {
      if (e instanceof EngineError && (e.status === 422 || e.status === 413) && e.message) return { error: e.message };
      return { error: friendlyError(e) };
    }
  });
  ipcMain.handle('panel:detach', async (_e, id) => {
    if (typeof id !== 'string' || !ID.test(id) || !ctx.state.engineUp) return { ok: false };
    try { return await ctx.engine.detach(id); } catch { return { ok: false }; }
  });
}

module.exports = { register, MAX_BYTES };
