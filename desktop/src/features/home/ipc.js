'use strict';
// IPC of the home feature: connect to Home Assistant (find it, open its login, wait for the approval) and disconnect.
const { ipcMain, shell, dialog } = require('electron');
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
    async confirm({ message, detail }) {
      const { response } = await dialog.showMessageBox(ctx.panelWin && !ctx.panelWin.isDestroyed() ? ctx.panelWin : null, {
        type: 'question', buttons: ['Instalar', 'Agora não'], defaultId: 1, cancelId: 1, title: 'Instalar o Home Assistant', message, detail,
      });
      return response === 0;
    },
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
  ipcMain.handle('panel:home-install', (_e, name, password) => service.install({ name: typeof name === 'string' ? name.slice(0, 60) : '', password: typeof password === 'string' ? password.slice(0, 128) : '' }));
  ipcMain.handle('panel:home-install-info', async () => { try { return await ctx.engine.homeInstallStatus(); } catch (e) { return { error: friendlyError(e) }; } });
  ipcMain.handle('panel:home-docker-page', () => shell.openExternal('https://www.docker.com/products/docker-desktop/'));   // a fixed address: the page never chooses it
  ipcMain.handle('panel:home-disconnect', () => service.disconnect());
}

Object.assign(module.exports, { register });
