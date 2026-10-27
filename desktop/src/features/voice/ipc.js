'use strict';
// IPC of speech: recognition, the enhanced voice and removing it.
const { ipcMain } = require('electron');
const { EngineError } = require('../engine').client;
const ctx = require('../../shared/context');
const { friendlyError } = require('../engine').errors;
const voiceService = require('./service');
const settingsService = require('../settings').service;
const panelWindow = require('../panel').window;

function register() {
  ipcMain.handle('panel:transcribe', async (_e, bytes, mime) => {
      if (!ctx.settings.talk) return { error: 'Ative "Falar com o Chakmati" em Ajustes.' };
      if (!ctx.state.engineUp) return { error: 'O motor não está rodando.' };
      if (!(bytes instanceof Uint8Array) || typeof mime !== 'string') return { error: 'Gravação inválida.' };
      try {
        const timeout = new Promise((_resolve, reject) => setTimeout(() => reject(new Error('timeout')), 90000));
        return await Promise.race([ctx.engine.transcribe(bytes, mime), timeout]);
      } catch (e) {
        if (e && e.message === 'timeout') return { error: 'O reconhecimento de voz demorou demais.' };
        return { error: e instanceof EngineError && e.status === 503 ? 'O reconhecimento de voz está desligado no motor.' : friendlyError(e) };
      }
    });

    // Speaking with the enhanced voice: the engine synthesizes the text on this computer and sends the audio back.
    ipcMain.handle('voice:synthesize', async (_e, text, speed) => {
      if (!voiceService.enhancedReady() || typeof text !== 'string' || !text.trim() || text.length > 600) return { error: 'unavailable' };
      try {
        const a = await ctx.engine.speak(text, speed === 'fast' ? 'fast' : 'normal');
        return { dataUrl: `data:${a.mime};base64,${a.base64}` };
      } catch (e) { return { error: friendlyError(e) }; } // the renderer falls back to the system voice
    });

  ipcMain.handle('panel:voice-remove', async () => {
      try {
        ctx.state.voice = await ctx.engine.voiceRemove();
        ctx.settings.enhancedVoice = false;
        settingsService.persistSettings();
        voiceService.sendVoice();
        panelWindow.sendPanelState();
        return { ok: true };
      } catch (e) { return { ok: false, error: friendlyError(e) }; }
    });
}

Object.assign(module.exports, { register });
