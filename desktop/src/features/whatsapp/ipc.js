'use strict';
// IPC of WhatsApp: conversations, messages and audio (refused in discreet mode) and the link setup.
const { ipcMain } = require('electron');
const { EngineError } = require('../engine/client');
const ctx = require('../../app/context');
const { friendlyError } = require('../../app/util');
const openwa = require('./openwa');

function register() {
    // Reading a conversation. Names and texts are hidden in discreet mode, so these refuse to run then.
    const guard = () => (ctx.settings.masked ? 'Modo discreto ligado: desligue em Ajustes para ver as conversas.' : ctx.state.engineUp ? null : 'O motor não está rodando.');

  ipcMain.handle('panel:chats', async () => {
      const blocked = guard();
      if (blocked) return { error: blocked };
      try { return { chats: await ctx.engine.chats(80) }; } catch (e) { return { error: friendlyError(e) }; }
    });

  ipcMain.handle('panel:messages', async (_e, chatId) => {
      const blocked = guard();
      if (blocked || typeof chatId !== 'string') return { error: blocked || 'Conversa inválida.' };
      try { return { messages: await ctx.engine.messages(chatId, 40) }; } catch (e) { return { error: friendlyError(e) }; }
    });

  ipcMain.handle('panel:audio', async (_e, chatId, messageId) => {
      const blocked = guard();
      if (blocked || typeof chatId !== 'string' || typeof messageId !== 'string') return { error: blocked || 'Áudio inválido.' };
      try {
        const a = await ctx.engine.audio(chatId, messageId);
        return { dataUrl: `data:${a.mime};base64,${a.base64}` };
      } catch (e) { return { error: e instanceof EngineError && e.status === 404 ? 'Este áudio não pode ser reproduzido.' : friendlyError(e) }; }
    });

  ipcMain.handle('panel:openwa', () => openwa.openWaSetup());
}

Object.assign(module.exports, { register });
