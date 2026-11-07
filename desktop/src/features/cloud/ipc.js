'use strict';
// IPC of the paid-AI section of Ajustes. The key comes in from the page once, is checked with the provider and stored encrypted by the main process; nothing
// here ever sends it back. Saving or removing restarts the engine (when the app started it), because the engine reads the key and the choice at start.
const path = require('node:path');
const { ipcMain, app, safeStorage } = require('electron');
const ctx = require('../../shared/context');
const cloudKey = require('../engine').cloudKey;
const { createCloudSetup } = require('../engine').cloudSetup;
const { validProvider, validModel } = cloudKey;

function register() {
  const store = () => cloudKey.createKeyStore({ file: path.join(app.getPath('userData'), 'cloud-key.bin'), safeStorage });
  const persist = () => require('../settings').service.persistSettings();

  // The engine reads the choice and the key at start: restart it when this app owns it, and say so when it does not.
  async function apply() {
    const engine = require('../engine').service;
    let restarted = false;
    if (ctx.engineProcess) { await engine.restartEngine(); restarted = true; }
    await engine.refreshOverview();
    require('../panel').window.sendPanelState();
    return restarted;
  }

  ipcMain.handle('panel:cloud-providers', () => Object.values(cloudKey.PROVIDERS).map((p) => ({ id: p.id, label: p.label, defaultModel: p.defaultModel, keyHelp: p.keyHelp })));

  ipcMain.handle('panel:cloud-save', async (_e, provider, key, model, local) => {
    if (!validProvider(provider)) return { error: 'Escolha o provedor.' };
    if (!validModel(model)) return { error: 'O nome do modelo tem caracteres inválidos.' };
    const keepKey = typeof key !== 'string' || key.trim() === '';
    if (keepKey) {
      // no new key: only the model and the local fallback change, for the same provider that is already connected
      if (ctx.settings.cloudProvider !== provider || !store().load()) return { error: 'Cole a chave de API para conectar.' };
    } else {
      const res = await createCloudSetup({ keyStore: store() }).connect(provider, key.trim(), model);
      if (res.error) return res;
    }
    Object.assign(ctx.settings, { cloudProvider: provider, cloudModel: model, localModel: local !== false });
    persist();
    return { ok: true, restarted: await apply() };
  });

  ipcMain.handle('panel:cloud-remove', async () => {
    store().clear();
    Object.assign(ctx.settings, { cloudProvider: '', cloudModel: '', localModel: true });
    persist();
    return { ok: true, restarted: await apply() };
  });
}

Object.assign(module.exports, { register });
