'use strict';
// The wizard window and its IPC. Every handler recomputes from the real hardware; the page only sends the ids ticked.
const path = require('node:path');
const { BrowserWindow, dialog, shell } = require('electron');
const { readHardware } = require('./hardware');
const { verdict: judge, suggestions } = require('./tiers');
const { MODELS, optionsFor } = require('./catalog');
const { buildPlan } = require('./plan');
const { runPlan } = require('./run-plan');
const { makeRunners } = require('./runners');
const { formatSize, levelText } = require('./format');
const settingsLib = require('../lib/settings');

const OLLAMA_DOWNLOAD = 'https://ollama.com/download';

const ids = (value) => (Array.isArray(value) ? value.filter((v) => typeof v === 'string') : []);

function openSetup({ ipcMain, webPreferences, settingsFile, onClosed, onFinish }) {
  const win = new BrowserWindow({ width: 760, height: 720, minWidth: 560, title: 'Instalar o Chakmati', webPreferences: webPreferences() });
  win.removeMenu?.();
  win.loadFile(path.join(__dirname, '..', 'renderer', 'installer.html'));
  win.on('closed', onClosed);
  const send = (channel, payload) => { if (!win.isDestroyed()) win.webContents.send(channel, payload); };

  const runners = makeRunners({
    saveSettings: async (patch) => settingsLib.save(settingsFile, { ...settingsLib.load(settingsFile), ...patch }),
  });

  async function scan() {
    const hw = readHardware();
    const v = judge(hw);
    const model = MODELS.find((m) => m.id === v.model) || null;
    let ollamaUp = false;
    try { await runners.checkOllama(); ollamaUp = true; } catch { /* the page explains how to get it */ }
    return {
      hw, verdict: v, levelText: levelText(v.level), suggested: suggestions(hw, v.level), ollamaUp,
      hwText: {
        system: `${hw.platform} ${hw.arch} (${hw.osRelease})`, ram: `${hw.ramGb} GB`, cores: String(hw.cores),
        disk: hw.freeDiskGb === null ? 'não consegui medir' : `${hw.freeDiskGb} GB livres`,
      },
      model: model && { id: model.id, label: model.label, sizeText: formatSize(model.diskMb) },
      options: optionsFor(hw.platform).map((o) => ({
        id: o.id, label: o.label, description: o.description,
        costText: o.diskMb || o.ramMb ? `cerca de ${formatSize(o.diskMb)} em disco e ${formatSize(o.ramMb)} de memória` : 'não ocupa espaço nem memória extra',
      })),
    };
  }

  function planFor(selected) {
    const hw = readHardware();
    try { return buildPlan({ hw, verdict: judge(hw), selected: ids(selected) }); } catch (e) {
      return { ok: false, blocked: [e.message], steps: [], baseline: {}, totals: null, warnings: [], after: [] };
    }
  }

  const approve = async (step) => {
    const { response } = await dialog.showMessageBox(win, {
      type: 'question', buttons: ['Aprovar', 'Pular'], defaultId: 1, cancelId: 1, title: 'Aprovar download', message: step.label,
      detail: `Origem: ${step.approval.source}\nTamanho: ${formatSize(step.approval.sizeMb)}\n\nNada é baixado sem a sua aprovação.`,
    });
    return response === 0;
  };

  ipcMain.handle('installer:scan', () => scan());
  ipcMain.handle('installer:plan', (_e, selected) => {
    const plan = planFor(selected);
    const totalsText = plan.totals
      ? `Espaço em disco: cerca de ${formatSize(plan.totals.diskMb)}. Memória em uso: cerca de ${formatSize(plan.totals.ramMb)} (estimativas).`
      : '';
    return { ...plan, totalsText };
  });
  ipcMain.handle('installer:run', async (_e, selected) => {
    const plan = planFor(selected);
    const result = await runPlan(plan, { approve, runners, onProgress: (p) => send('installer:progress', p) });
    return { ...result, after: plan.after };
  });
  ipcMain.handle('installer:ollama-page', async () => {
    const { response } = await dialog.showMessageBox(win, {
      type: 'question', buttons: ['Abrir', 'Cancelar'], defaultId: 1, cancelId: 1, title: 'Abrir página do Ollama',
      message: 'Abrir a página oficial do Ollama no navegador?', detail: OLLAMA_DOWNLOAD,
    });
    if (response === 0) await shell.openExternal(OLLAMA_DOWNLOAD);
  });
  ipcMain.on('installer:finish', () => onFinish());
  return win;
}

module.exports = { openSetup };
