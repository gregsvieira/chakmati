'use strict';
// IPC of the home feature: the modal of the smart-house assistant (find a Home Assistant or install one, connect, disconnect).
const { ipcMain, shell } = require('electron');
const ctx = require('../../shared/context');
const { friendlyError } = require('../engine').errors;
const { createHomeService, summary } = require('./service');

function register() {
  const note = (text) => { ctx.state.homeNote = text || ''; require('../panel').window.sendPanelState(); };
  const service = createHomeService({
    engine: () => ctx.engine,
    isEngineUp: () => ctx.state.engineUp,
    openExternal: (url) => shell.openExternal(url),
    note,
    friendlyError,
    async afterConnected(status) {
      note(summary(status));
      if (!ctx.settings.home) {   // connecting means wanting it: the house is switched on (the engine restarts to start serving it)
        ctx.settings.home = true;
        require('../settings').service.persistSettings();
        if (ctx.engineProcess) await require('../engine').service.restartEngine();
      }
      await require('../engine').service.refreshOverview();
    },
    async afterDisconnected() { await require('../engine').service.refreshOverview(); },
  });
  const text = (v, max) => (typeof v === 'string' ? v.slice(0, max) : '');
  ipcMain.handle('panel:home-discover', () => service.discover());
  ipcMain.handle('panel:home-connect', (_e, url) => service.connect(text(url, 200)));
  ipcMain.handle('panel:home-status', async () => { try { return await ctx.engine.homeStatus(); } catch (e) { return { error: friendlyError(e) }; } });
  ipcMain.handle('panel:home-install-info', async () => { try { return await ctx.engine.homeInstallStatus(); } catch (e) { return { error: friendlyError(e) }; } });
  ipcMain.handle('panel:home-install-start', () => service.startInstall());
  ipcMain.handle('panel:home-account', (_e, name, password) => service.account({ name: text(name, 60), password: text(password, 128) }));
  ipcMain.handle('panel:home-alexa-start', (_e, email, password, code) => service.alexaStart({ email: text(email, 254), password: text(password, 256), code: text(code, 12) }));
  ipcMain.handle('panel:home-alexa-status', async () => { try { return await ctx.engine.homeAlexaStatus(); } catch (e) { return { state: 'error', message: friendlyError(e) }; } });
  ipcMain.handle('panel:home-players', async () => { try { return await ctx.engine.homePlayers(); } catch (e) { return { players: [], error: friendlyError(e) }; } });
  ipcMain.handle('panel:home-player-control', async (_e, id, action, query) => {
    try { return await ctx.engine.homePlayerControl(text(id, 120), text(action, 20), text(query, 200)); } catch (e) { return { error: friendlyError(e) }; }
  });
  ipcMain.handle('panel:home-alexa-cancel', () => service.alexaCancel());
  ipcMain.handle('panel:home-open-ha', () => shell.openExternal('http://localhost:8123'));   // a fixed address: the page never chooses it
  ipcMain.handle('panel:home-disconnect', () => service.disconnect());
}

Object.assign(module.exports, { register });
