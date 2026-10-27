'use strict';
// OpenWA (the WhatsApp bridge): linking by QR code and keeping the session.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app } = require('electron');
const ctx = require('../../app/context');
const { sleep } = require('../../app/util');
const engineService = require('../engine/service');

let owaWatch = null;

// ---- OpenWA (the WhatsApp bridge). Its browser window is only needed once, to scan the QR code; closing that window
// stops the session, so after the link is made the app restarts OpenWA without a window (the login stays saved).
const OPENWA_URL = process.env.CHAKMATI_OPENWA_URL || 'http://127.0.0.1:8081';

async function owaHealth() {
  try {
    const res = await fetch(`${OPENWA_URL}/health`, { signal: AbortSignal.timeout(2500) });
    return res.ok ? await res.json() : null;
  } catch { return null; }
}

function owaScript(arg, { detached = false } = {}) {
  const root = engineService.projectRoot();
  const logFile = path.join(app.getPath('userData'), 'openwa.log');
  const log = fs.openSync(logFile, 'a');
  const env = { ...process.env, PATH: `${process.env.PATH || ''}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` };
  const child = spawn('bash', [path.join(root, 'scripts', 'openwa.sh'), arg], { cwd: root, stdio: ['ignore', log, log], env, detached });
  fs.closeSync(log);
  if (detached) child.unref();
  return child;
}

const owaRun = (arg) => new Promise((resolve) => { const c = owaScript(arg); c.once('exit', resolve); c.once('error', resolve); setTimeout(resolve, 25000); });

// Watches a link attempt. OpenWA often stays "ready but not connected" after the QR is scanned until it is restarted, so
// the watcher does not wait for `connected`: it restarts OpenWA (without a window) once the scan happened, or once the
// session has been READY for a while, or as soon as it reports connected.
async function owaEventsSawScan(signal, onScan) {
  try {
    const key = (() => { try { return fs.readFileSync(path.join(require('node:os').homedir(), '.lite-agent', 'openwa', 'api_key.txt'), 'utf8').trim(); } catch { return ''; } })();
    const res = await fetch(`${OPENWA_URL}/api/events?topics=*&api_key=${encodeURIComponent(key)}`, { signal, headers: { Accept: 'text/event-stream' } });
    const decoder = new TextDecoder();
    for await (const chunk of res.body) {
      if (/event:\s*launch\.auth\.qr\.scanned/.test(decoder.decode(chunk, { stream: true }))) onScan();
    }
  } catch { /* the stream ends when the watcher is aborted or OpenWA restarts */ }
}

async function finishOwaLink() {
  // restart without a window: closing the Chrome window would end the session, and the login stays saved
  for (let attempt = 0; attempt < 2 && !ctx.quitting; attempt += 1) {
    await owaRun('stop');
    for (let i = 0; i < 10 && (await owaHealth()); i += 1) await sleep(1000);
    owaScript('start-bg', { detached: true });
    for (let i = 0; i < 30 && !ctx.quitting; i += 1) {
      await sleep(3000);
      const h = await owaHealth();
      if (h && h.connected) return true;
    }
  }
  return false;
}

async function watchOwaLink() {
  if (owaWatch) owaWatch.abort.abort();
  const abort = new AbortController();
  const me = { abort };
  owaWatch = me;
  let scannedAt = 0;
  let readySince = 0;
  owaEventsSawScan(abort.signal, () => { scannedAt = Date.now(); });
  try {
    const deadline = Date.now() + 15 * 60 * 1000;
    while (!ctx.quitting && !abort.signal.aborted && Date.now() < deadline) {
      await sleep(3000);
      const h = await owaHealth();
      if (!h) continue;
      const ready = h.session && h.session.state === 'READY';
      readySince = ready ? readySince || Date.now() : 0;
      if (h.connected || (scannedAt && Date.now() - scannedAt > 15000) || (readySince && Date.now() - readySince > 15000)) {
        await finishOwaLink();
        break;
      }
    }
  } finally {
    abort.abort();
    if (owaWatch === me) owaWatch = null;
    engineService.refreshOverview();
  }
}

async function openWaSetup() {
  const root = engineService.projectRoot();
  if (!root) return { ok: false, error: 'Não encontrei a pasta do Chakmati.' };
  const health = await owaHealth();
  if (health && health.connected) { engineService.refreshOverview(); return { ok: true, message: 'O WhatsApp já está conectado.' }; }
  // Not connected: always start again with a fresh visible window. An old one may be minimized, hidden or stuck, and
  // there is no way to reopen it from here.
  if (owaWatch) owaWatch.abort.abort();
  if (health) {
    await owaRun('stop');
    for (let i = 0; i < 10 && (await owaHealth()); i += 1) await sleep(1000);
  }
  const child = owaScript('start', { detached: true });
  const early = await new Promise((resolve) => {
    child.once('error', (e) => resolve({ code: -1, message: e.message }));
    child.once('exit', (code) => resolve({ code }));
    setTimeout(() => resolve(null), 2500);
  });
  if (early && early.code !== 0) {
    let tail = '';
    try { tail = fs.readFileSync(path.join(app.getPath('userData'), 'openwa.log'), 'utf8').trim().split('\n').slice(-2).join(' '); } catch { /* no log */ }
    if (/not installed|setup/.test(tail)) return { ok: false, error: 'O OpenWA não está instalado. Rode scripts/openwa.sh setup uma vez.' };
    return { ok: false, error: early.message || tail || 'Não consegui abrir o OpenWA.' };
  }
  spawn('osascript', ['-e', 'tell application "Google Chrome" to activate'], { stdio: 'ignore' }).on('error', () => {}); // best effort
  watchOwaLink();
  return { ok: true, message: 'Janela do OpenWA aberta. Escaneie o QR nela; depois pode fechá-la, eu mantenho o WhatsApp conectado.' };
}

Object.assign(module.exports, { openWaSetup });
