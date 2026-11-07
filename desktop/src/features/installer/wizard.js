'use strict';
// The wizard window and its IPC. Every handler recomputes from the real hardware; the page only sends the ids ticked.
const path = require('node:path');
const { BrowserWindow, dialog, shell, app, safeStorage } = require('electron');
const { readHardware } = require('./hardware');
const { verdict: judge, suggestions, reasoningFor } = require('./tiers');
const { ENGINE, MODELS, optionsFor } = require('./catalog');
const { buildPlan } = require('./plan');
const { runPlan } = require('./run-plan');
const { makeRunners } = require('./runners');
const { makeSync } = require('./engine-sync');
const { writeSetupDone } = require('./first-run');
const { extrasFromSettings } = require('../engine').launch;
const { formatSize, levelText } = require('./format');
const { quip } = require('./quips');
const settingsLib = require('../settings').settings;
const ctx = require('../../shared/context');
const cloudKey = require('../engine').cloudKey;

const PROFILE = { personalities: settingsLib.PERSONALITIES.map((id) => ({ id, name: settingsLib.PERSONALITY_NAMES[id] })), pronouns: settingsLib.PRONOUNS.map((id) => ({ id, name: settingsLib.PRONOUN_NAMES[id] })) };

const OLLAMA_DOWNLOAD = 'https://ollama.com/download';

const ids = (value) => (Array.isArray(value) ? value.filter((v) => typeof v === 'string') : []);

function openSetup({ ipcMain, webPreferences, settingsFile, engine = null, onClosed, onFinish }) {
  const win = new BrowserWindow({ width: 760, height: 720, minWidth: 560, title: 'Instalar o Chakmati', webPreferences: webPreferences() });
  win.removeMenu?.();
  win.loadFile(path.join(__dirname, 'renderer', 'installer.html'));
  win.on('closed', onClosed);
  const send = (channel, payload) => { if (!win.isDestroyed()) win.webContents.send(channel, payload); };

  const runners = makeRunners({
    saveSettings: async (patch) => settingsLib.save(settingsFile, { ...settingsLib.load(settingsFile), ...patch }),
    sync: engine ? makeSync({ resourcesPath: engine.resourcesPath, dataDir: engine.dataDir }) : undefined,
  });

  async function scan() {
    const hw = readHardware();
    const v = judge(hw);
    const model = MODELS.find((m) => m.id === v.model) || null;
    let ollamaUp = false;
    try { await runners.checkOllama(); ollamaUp = true; } catch { /* the page explains how to get it */ }
    return {
      hw, verdict: v, levelText: levelText(v.level), suggested: suggestions(hw, v.level), ollamaUp, quip: quip(hw, v),
      hwText: {
        system: `${hw.platform} ${hw.arch} (${hw.osRelease})`, ram: `${hw.ramGb} GB`, cores: String(hw.cores),
        disk: hw.freeDiskGb === null ? 'não consegui medir' : `${hw.freeDiskGb} GB livres`,
      },
      profile: PROFILE,
      providers: Object.values(cloudKey.PROVIDERS).map((p) => ({ id: p.id, label: p.label, defaultModel: p.defaultModel, keyHelp: p.keyHelp })),
      engineText: engine ? formatSize(ENGINE.baseMb) : null, // the engine is only prepared by the installed app
      model: model && { id: model.id, label: model.label, sizeText: formatSize(model.diskMb) },
      options: optionsFor(hw.platform, { packaged: !!engine }).filter((o) => o.id !== 'reasoning' || reasoningFor(hw)).map((o) => ({
        id: o.id, advice: o.advice || null, label: o.id === 'reasoning' ? `${o.label}: ${reasoningFor(hw).id}` : o.label, description: o.description,
        costText: o.id === 'reasoning' ? `cerca de ${formatSize(reasoningFor(hw).diskMb)} em disco e ${formatSize(reasoningFor(hw).ramMb)} de memória (não ao mesmo tempo que o modelo de conversa)`
          : o.diskMb || o.ramMb ? `cerca de ${formatSize(o.diskMb)} em disco e ${formatSize(o.ramMb)} de memória` : 'não ocupa espaço nem memória extra',
      })),
    };
  }

  // The paid AI: its key was checked with the provider and stored (encrypted) by `installer:cloud-check`; here only the provider and the model are known.
  const keyStore = cloudKey.createKeyStore({ file: path.join(app.getPath('userData'), 'cloud-key.bin'), safeStorage });
  let cloud = null;   // { provider, model } once a key was accepted

  function planFor(selected, profile, opts) {
    const hw = readHardware();
    const wantsCloud = !!(opts && opts.cloud);
    const wantsLocal = !(opts && opts.local === false);
    try {
      if (!wantsLocal && !wantsCloud) throw new Error('Escolha o modelo local, a sua assinatura de IA paga, ou os dois.');
      if (wantsCloud && !cloud) throw new Error('Falta conectar a sua IA paga: volte e informe a chave.');
      return buildPlan({
        hw, verdict: judge(hw), selected: ids(selected), engine: engine ? { packaged: true } : null, profile: profile && typeof profile === 'object' ? profile : null,
        cloud: wantsCloud ? { ...cloud, local: wantsLocal } : null,
      });
    } catch (e) {
      return { ok: false, blocked: [e.message], steps: [], baseline: {}, totals: null, warnings: [], after: [] };
    }
  }

  // The engine and the chat model are mandatory: the Chakmati does not work without them, so there is no "Pular" for them, only a way out (and the default button
  // is still the one that downloads nothing).
  const approve = async (step) => {
    const { response } = await dialog.showMessageBox(win, {
      type: 'question', buttons: step.required ? ['Aprovar', 'Cancelar a instalação'] : ['Aprovar', 'Pular'], defaultId: 1, cancelId: 1, title: 'Aprovar download', message: step.label,
      detail: `Origem: ${step.approval.source}\nTamanho: ${formatSize(step.approval.sizeMb)}\n\n`
        + (step.required ? 'Obrigatório: sem isso o Chakmati não funciona. Se você não aprovar, a instalação é cancelada e nada é salvo.\n\n' : '')
        + 'Nada é baixado sem a sua aprovação.',
    });
    return response === 0;
  };

  ipcMain.handle('installer:scan', () => scan());
  ipcMain.handle('installer:cloud-check', async (_e, provider, key, model) => {
    if (!cloudKey.validProvider(provider)) return { error: 'Escolha o provedor.' };
    if (!cloudKey.validModel(model)) return { error: 'O nome do modelo tem caracteres inválidos.' };
    if (!cloudKey.validKey(key)) return { error: 'A chave tem um formato inválido (sem espaços nem quebras de linha).' };
    if (!keyStore.available()) return { error: 'Este computador não tem um cofre do sistema para guardar a chave com segurança, então não vou guardá-la.' };
    const checked = await cloudKey.checkKey(provider, key);
    if (checked.error) return checked;
    try { keyStore.save(key); } catch (e) { return { error: e.message }; }
    cloud = { provider, model };
    return { ok: true };
  });
  ipcMain.handle('installer:cloud-clear', () => { keyStore.clear(); cloud = null; return { ok: true }; });
  ipcMain.handle('installer:plan', (_e, selected, profile, opts) => {
    const plan = planFor(selected, profile, opts);
    const totalsText = plan.totals
      ? `Espaço em disco: cerca de ${formatSize(plan.totals.diskMb)}. Memória em uso: cerca de ${formatSize(plan.totals.ramMb)} (estimativas).`
      : '';
    return { ...plan, totalsText };
  });
  ipcMain.handle('installer:run', async (_e, selected, profile, opts) => {
    const plan = planFor(selected, profile, opts);
    const result = await runPlan(plan, { approve, runners, onProgress: (p) => send('installer:progress', p) });
    if (engine && result.status === 'done') writeSetupDone({ dataDir: engine.dataDir, extras: extrasFromSettings(result.settings) });
    return { ...result, after: plan.after };
  });
  ipcMain.handle('installer:ollama-page', async () => {
    const { response } = await dialog.showMessageBox(win, {
      type: 'question', buttons: ['Abrir', 'Cancelar'], defaultId: 1, cancelId: 1, title: 'Abrir página do Ollama',
      message: 'Abrir a página oficial do Ollama no navegador?', detail: OLLAMA_DOWNLOAD,
    });
    if (response === 0) await shell.openExternal(OLLAMA_DOWNLOAD);
  });
  // The smart-house step needs the engine: start it here (with the settings the wizard just saved) and wait until it answers. The page never chooses what runs.
  ipcMain.handle('installer:home-prepare', async () => {
    try {
      const { EngineClient } = require('../engine').client;
      ctx.settingsFile = settingsFile;
      ctx.settings = settingsLib.load(settingsFile);
      ctx.engine = ctx.engine || new EngineClient({ baseUrl: ctx.settings.engineUrl });
      if (!(await ctx.engine.health())) {
        if (!(await require('../engine').service.startEngine())) return { error: 'Não consegui iniciar o motor do Chakmati agora.' };
        for (let i = 0; i < 60 && !(await ctx.engine.health()); i += 1) await new Promise((r) => setTimeout(r, 1000));
      }
      if (!(await ctx.engine.health())) return { error: 'O motor do Chakmati demorou demais para responder.' };
      ctx.state.engineUp = true;
      return { ok: true };
    } catch (e) { return { error: 'Não consegui iniciar o motor do Chakmati agora.' }; }
  });
  ipcMain.on('installer:finish', async () => {
    // The engine started for the house step is stopped, so the app that opens next starts it with the final settings.
    const child = ctx.engineProcess;
    if (child) await new Promise((resolve) => { child.once('exit', resolve); child.kill(); setTimeout(resolve, 4000); });
    onFinish();
  });
  return win;
}

module.exports = { openSetup };
