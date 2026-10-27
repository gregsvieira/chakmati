'use strict';
// Talking to the engine: its state, notices, health, starting and restarting it.
const { pickGreeting } = require('../notices').greetings;
const { app } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { engineLaunch, toolPath: engineToolPath } = require('./launch');
const { spawn } = require('node:child_process');
const settingsLib = require('../settings').settings;
const ctx = require('../../shared/context');
const { sleep } = require('../../shared/util');
const { friendlyError } = require('./errors');
const widgetMood = require('../widget').mood;
const panelWindow = require('../panel').window;
const voiceService = require('../voice').service;

const autoTried = new Set();
let greeted = false;

async function autoApproveNew() {
  if (!ctx.settings || !ctx.settings.autoSend || !ctx.state.overview) return;
  for (const item of ctx.state.overview.pending || []) {
    if (item.kind !== 'whatsapp.send' || autoTried.has(item.id)) continue;
    autoTried.add(item.id);
    try {
      await ctx.engine.approve(item.id);
      widgetMood.localNotice('Mensagem enviada.');
    } catch (e) {
      widgetMood.localNotice(`Não consegui enviar a mensagem: ${friendlyError(e)}`);
    }
    refreshOverview();
  }
}

// The engine forgets "manter aprovado" when it restarts, so it is told again whenever it disagrees with the setting.
async function syncStanding() {
  if (!ctx.state.overview || ctx.state.overview.computer_standing === undefined) return;
  const want = ctx.settings.autoRunSafe === true;
  if (ctx.state.overview.computer_standing === want) return;
  try { await ctx.engine.setStanding(want); ctx.state.overview.computer_standing = want; } catch { /* the next refresh tries again */ }
}

async function refreshOverview() {
  try {
    widgetMood.applyOverview(await ctx.engine.overview());
    ctx.state.engineUp = true;
    syncStanding();
  } catch {
    ctx.state.engineUp = false;
  }
  panelWindow.sendPanelState();
  autoApproveNew();
}

function sayHello() {
  if (greeted || ctx.state.hidden) return;
  greeted = true;
  const hello = pickGreeting();
  widgetMood.pushNotice({ id: -Date.now(), kind: 'reply', text: hello, masked: hello, ts: Date.now() / 1000, key: 'startup' });
}

async function healthLoop() {
  let wasUp = null;
  const startedAt = Date.now();
  while (!ctx.quitting) {
    const up = await ctx.engine.health();
    ctx.state.engineUp = up;
    if (up && wasUp !== true) {
      await refreshOverview();
      await voiceService.refreshVoiceStatus(); // the engine was not up yet when the app started: ask now whether the enhanced voice is installed
      voiceService.warmVoice();
    }
    if (!up) ctx.voiceWarmed = false; // a restarted engine has not loaded the voice
    if (!up && wasUp === null) widgetMood.pushNotice({ id: -Date.now(), kind: 'reply', text: '(...)', masked: '(...)', ts: Date.now() / 1000, key: 'booting' }); // starting up
    if (up) sayHello();
    // a real problem, not the normal start-up: it was running and stopped, or it never came up
    if (!up && !ctx.state.warnedDown && ((wasUp === true) || (wasUp === false && Date.now() - startedAt > 90000))) {
      widgetMood.localNotice(wasUp === true ? 'Perdi a conexão com o motor do Chakmati.' : 'O motor do Chakmati não iniciou. Veja o engine.log.');
      ctx.state.warnedDown = true;
    }
    if (up) ctx.state.warnedDown = false;
    if (wasUp !== up) { widgetMood.refreshMood(); panelWindow.sendPanelState(); }
    wasUp = up;
    await sleep(up ? 5000 : 1000);
  }
}

async function noticeLoop() {
  let cursor = null;
  const abort = new AbortController();
  app.once('before-quit', () => abort.abort());
  while (!ctx.quitting) {
    if (!ctx.state.engineUp) { cursor = null; await sleep(2000); continue; }
    try {
      if (cursor === null) { // start from "now": old notices are not replayed when the app opens
        widgetMood.applyOverview(await ctx.engine.overview());
        cursor = ctx.state.overview.last_notice_id;
        panelWindow.sendPanelState();
      }
      const result = await ctx.engine.notices(cursor, 25, abort.signal);
      cursor = result.last_id;
      for (const n of result.notices) widgetMood.pushNotice(n);
      if (result.notices.length) refreshOverview();
    } catch {
      if (ctx.quitting) return;
      cursor = null;
      await sleep(3000);
    }
  }
}

const projectRoot = () => {
  const root = path.resolve(__dirname, '..', '..', '..', '..');
  return fs.existsSync(path.join(root, 'pyproject.toml')) ? root : null;
};

// An app opened from the Finder or with `open` gets a minimal PATH, without the folders where uv and Homebrew live.
const toolPath = () => engineToolPath({ platform: process.platform, base: process.env.PATH || '', home: app.getPath('home') });

// The app starts the engine itself when none is running, with the integrations the person switched on in Ajustes.
// An engine started by hand is left alone (and then the integrations are chosen by its own environment).
async function searxngUp() {
  try { return (await fetch('http://localhost:8080/', { signal: AbortSignal.timeout(1500) })).ok; } catch { return false; }
}

async function startEngine() {
  const launch = engineLaunch({ packaged: app.isPackaged, dataDir: app.getPath('userData'), repoRoot: projectRoot(), platform: process.platform });
  if (!launch || ctx.engineProcess) return false;
  const env = settingsLib.engineEnv(ctx.settings, { searxng: await searxngUp() });
  if (ctx.engineProcess) return false;
  fs.mkdirSync(launch.cwd, { recursive: true });
  const logFile = path.join(app.getPath('userData'), 'engine.log');
  const log = fs.openSync(logFile, 'a');
  ctx.engineProcess = spawn(launch.command, launch.args, {
    cwd: launch.cwd, stdio: ['ignore', log, log], windowsHide: true, env: { ...process.env, PATH: toolPath(), ...launch.env, ...env },
  });
  fs.closeSync(log);
  ctx.engineProcess.on('error', () => { ctx.engineProcess = null; });
  ctx.engineProcess.on('exit', () => { ctx.engineProcess = null; });
  return true;
}

async function restartEngine() {
  if (!ctx.engineProcess) return false;
  const old = ctx.engineProcess;
  await new Promise((resolve) => { old.once('exit', resolve); old.kill(); setTimeout(resolve, 4000); });
  ctx.engineProcess = null;
  await sleep(500);
  return startEngine();
}

Object.assign(module.exports, { projectRoot, refreshOverview, autoApproveNew, syncStanding, restartEngine, healthLoop, noticeLoop, startEngine });
