'use strict';
// IPC of the home feature: connect to Home Assistant (find it, open its login, wait for the approval) and disconnect.
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
  ipcMain.handle('panel:home-connect', (_e, url) => service.connect(typeof url === 'string' ? url.slice(0, 200) : ''));
  ipcMain.handle('panel:home-disconnect', () => service.disconnect());
}

Object.assign(module.exports, { register });
