'use strict';
// Floating robot assistant for Chakmati. This process owns the windows and is the only one that talks to the engine.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app, BrowserWindow, Tray, Menu, ipcMain, screen, globalShortcut, nativeImage, nativeTheme, systemPreferences, shell } = require('electron');

const { EngineClient, EngineError } = require('./lib/engine-client');
const settingsLib = require('./lib/settings');
const links = require('./lib/links');
const { bellState, moodWithBell, countsAsNotice } = require('./lib/bell');
const { chooseSide, layoutWidget, clampIcon, panelBounds, expandedBounds, MIN_WIDE } = require('./lib/placement');
const { NoticeQueue, present, bubbleDuration } = require('./lib/notice-queue');
const { describe } = require('./lib/describe');
const { brief } = require('./lib/brief');
const { pickGreeting } = require('./lib/greetings');
const { robotPng } = require('./lib/trayicon');
const { openSetup } = require('./installer');
const { engineLaunch, toolPath: engineToolPath } = require('./lib/engine-launch');
const { needsSetup } = require('./installer/first-run');

const ICON = 124;
const BUBBLE = { w: 320, h: 120 };
const PANEL = { w: 400, h: 640 };
const HOTKEYS = { toggle: 'CommandOrControl+Shift+Space', panic: 'CommandOrControl+Shift+H' };
const MAX_TEXT = 2000;
const SNAPSHOT = process.env.CHAKMATI_DESKTOP_SNAPSHOT;
const PROTECT_TEST = process.env.CHAKMATI_DESKTOP_PROTECT_TEST;
const SETUP = process.argv.includes('--setup') || process.env.CHAKMATI_DESKTOP_SETUP === '1';
const isMac = process.platform === 'darwin';
const isLinux = process.platform === 'linux';

let settings;
let settingsFile;
let engine;
let widgetWin = null;
let panelWin = null;
let tray = null;
let engineProcess = null;
let icon = { x: 0, y: 0 };
let layout = null;
let dragStart = null;
let bubbleTimer = null;
let moodTimer = null;
let panelTimer = null;
let quitting = false;
let happyUntil = 0;
const queue = new NoticeQueue();
const streams = new Map();
const jobOf = new Map();   // stream id -> the engine's job id, once the engine says it queued one
const stopped = new Set(); // streams the person stopped with Parar
const state = { voice: null, engineUp: false, overview: null, notices: [], busy: 0, hidden: false, panelOpen: false, bubbleVisible: false, warnedDown: false, unread: 0, asking: false };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = (w) => w && !w.isDestroyed();
const sendTo = (w, channel, payload) => { if (alive(w) && !w.webContents.isDestroyed()) w.webContents.send(channel, payload); };

// ---------------------------------------------------------------------------------------------------- hardening
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-navigate', (e) => e.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  // Everything is denied except the microphone, and only for the panel and only while "Ouvir e falar" is on.
  const micAllowed = (wc, permission, details) => permission === 'media' && !!settings && settings.talk === true
    && !!wc && wc.getURL().endsWith('panel.html') && (!details || !details.mediaTypes || details.mediaTypes.every((t) => t === 'audio'));
  contents.session.setPermissionRequestHandler((wc, permission, callback, details) => callback(micAllowed(wc, permission, details)));
  contents.session.setPermissionCheckHandler((wc, permission, _origin, details) => micAllowed(wc, permission, details));
});

const webPreferences = () => ({
  preload: path.join(__dirname, 'preload.js'),
  contextIsolation: true,
  sandbox: true,
  nodeIntegration: false,
  webSecurity: true,
  spellcheck: false,
});

// Debugging aid (CHAKMATI_DEBUG_WINDOWS=1): every time a window changes size or place, write who did it to a log file.
function traceWindow(name, win) {
  if (process.env.CHAKMATI_DEBUG_WINDOWS !== '1' || !win) return;
  const file = path.join(app.getPath('userData'), 'window-debug.log');
  const log = (what, extra = '') => {
    try { fs.appendFileSync(file, `${new Date().toISOString()} ${name} ${what} ${JSON.stringify(win.getBounds())} ${extra}\n`); } catch { /* debugging only */ }
  };
  win.on('resize', () => log('resize', new Error().stack.split('\n').slice(2, 5).join(' < ').replace(/\s+/g, ' ')));
  win.on('move', () => log('move'));
  win.on('show', () => log('show'));
  win.on('hide', () => log('hide'));
  log('created');
}

// Saves the settings file; a no-op when there is none (design-snapshot mode), so a stray click can never crash the app.
function persistSettings() {
  if (settingsFile) settingsLib.save(settingsFile, settings);
}

// ---------------------------------------------------------------------------------------------------- display helpers
function nearestWorkArea(point) { return screen.getDisplayNearestPoint(point).workArea; }

function defaultIcon() {
  const wa = screen.getPrimaryDisplay().workArea;
  return { x: wa.x + wa.width - ICON - 28, y: wa.y + wa.height - ICON - 28 };
}

function protect(win) {
  if (alive(win)) win.setContentProtection(!!settings.protect); // best effort: honoured by Windows and by some macOS capture paths
}

// ---------------------------------------------------------------------------------------------------- the floating robot
function createWidget() {
  widgetWin = new BrowserWindow({
    width: ICON, height: ICON, show: false, frame: false, transparent: true, resizable: false, movable: false,
    hasShadow: false, alwaysOnTop: true, skipTaskbar: true, focusable: false, fullscreenable: false, webPreferences: webPreferences(),
  });
  widgetWin.setAlwaysOnTop(true, 'screen-saver');
  widgetWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  if (!isLinux) widgetWin.setIgnoreMouseEvents(true, { forward: true });
  protect(widgetWin);
  traceWindow('robô', widgetWin);
  widgetWin.loadFile(path.join(__dirname, 'renderer', 'widget.html'));
  widgetWin.on('closed', () => { widgetWin = null; });
}

function applyLayout() {
  if (!alive(widgetWin)) return;
  const wa = nearestWorkArea({ x: icon.x + ICON / 2, y: icon.y + ICON / 2 });
  icon = clampIcon(icon, ICON, wa);
  const side = chooseSide({ icon, size: ICON, workArea: wa, bubble: BUBBLE, preference: settings.bubbleSide });
  layout = layoutWidget({ icon, size: ICON, side, bubble: BUBBLE, workArea: wa });
  widgetWin.setBounds(layout.bounds);
  sendTo(widgetWin, 'widget:layout', layout);
  if (state.panelOpen) positionPanel();
}

// ---------------------------------------------------------------------------------------------------- mood and bubble
// "Waiting for a command" is a few seconds long, so it is tracked here with the local clock instead of waiting for the
// next refresh: it ends on time and the face and the hint go back to normal.
let awakeTimer = null;
function applyOverview(o) {
  state.overview = o;
  syncPending();
  state.awakeUntil = o && o.awake_for > 0 ? Date.now() + o.awake_for * 1000 : 0;
  clearTimeout(awakeTimer);
  if (state.awakeUntil) awakeTimer = setTimeout(() => { sendPanelState(); syncListening(); }, state.awakeUntil - Date.now() + 300);
  syncListening();
}
// The bell behind the character's head: yellow while something waits for the person (an approval, a question), red while there is news
// they have not seen (it clears when the panel is opened), a plain outline otherwise. The face follows it (see refreshMood).
let bellShown = '';
function currentBell() {
  const pending = (state.overview && Array.isArray(state.overview.pending)) ? state.overview.pending.length : 0;
  return bellState({ pending, asking: state.asking === true, unread: state.unread || 0 });
}
function syncBell() {
  const bell = currentBell();
  const key = `${bell.state}|${bell.label}`;
  if (key === bellShown) return;
  bellShown = key;
  sendTo(widgetWin, 'widget:bell', bell);
  sendPanelState();
}
const syncPending = syncBell;
// The blinking microphone beside the character: shown while the microphone waits for a command, gone as soon as it stops.
let listeningShown = null;
function syncListening() {
  const on = settings.talk === true && Date.now() < (state.awakeUntil || 0);
  if (on === listeningShown) return;
  listeningShown = on;
  sendTo(widgetWin, 'widget:listening', on);
}

const overviewNow = () => (state.overview ? { ...state.overview, awake: Date.now() < (state.awakeUntil || 0) } : null);

function currentDescription() {
  return describe({ engineUp: state.engineUp, overview: overviewNow(), busy: state.busy > 0 });
}

// the face: what is happening, unless the person pinned a mood in Ajustes (an unreachable engine always shows as offline)
function effectiveMood(base) {
  if (base === 'offline' || settings.mood === 'auto') return base;
  return settings.mood;
}

function refreshMood() {
  let mood = currentDescription().mood;
  if (settings.mood !== 'auto') mood = effectiveMood(mood);
  else {
    mood = moodWithBell(mood, currentBell());
    if (mood !== 'offline' && mood !== 'thinking' && mood !== 'alert' && mood !== 'happy') {
      if (Date.now() < happyUntil) mood = 'happy';
      else if (state.bubbleVisible) mood = 'alert';
    }
  }
  sendTo(widgetWin, 'widget:mood', mood);
}

function showBubble(notice) {
  const text = present(notice, settings.masked);
  state.bubbleVisible = true;
  sendTo(widgetWin, 'widget:bubble', { text, kind: notice.kind, id: notice.id });
  refreshMood();
  clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(nextBubble, bubbleDuration(text));
}

function hideBubble() {
  clearTimeout(bubbleTimer);
  queue.clear();
  state.bubbleVisible = false;
  sendTo(widgetWin, 'widget:bubble', null);
  refreshMood();
}

function nextBubble() {
  const { show } = queue.done();
  if (show) { showBubble(show); return; }
  state.bubbleVisible = false;
  sendTo(widgetWin, 'widget:bubble', null);
  refreshMood();
}

function pushNotice(notice) {
  state.notices.push(notice);
  if (!state.panelOpen && countsAsNotice(notice)) { state.unread = (state.unread || 0) + 1; syncBell(); refreshMood(); }
  if (state.notices.length > 50) state.notices.shift();
  if (state.panelOpen) { sendPanelState(); return; } // the panel is open: the notice shows up in its list instead of a bubble
  if (state.hidden) return;
  const { show } = queue.push(notice);
  if (show) showBubble(show);
}

function localNotice(text, kind = 'system') {
  pushNotice({ id: -Date.now(), kind, text, masked: text, ts: Date.now() / 1000, key: `local:${text}` });
}

// ---------------------------------------------------------------------------------------------------- the panel
function createPanel() {
  panelWin = new BrowserWindow({
    width: PANEL.w, height: PANEL.h, show: false, frame: false, transparent: true, resizable: false, hasShadow: true, alwaysOnTop: true,
    skipTaskbar: true, fullscreenable: false,
    ...(isMac ? { vibrancy: 'under-window', visualEffectState: 'active', backgroundColor: '#00000000' } : {}), // macOS: the real blur of what is behind the glass
    webPreferences: { ...webPreferences(), backgroundThrottling: false }, // a hidden panel must keep listening at full speed
  });
  panelWin.setAlwaysOnTop(true, 'floating');
  panelWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  protect(panelWin);
  traceWindow('painel', panelWin);
  panelWin.loadFile(path.join(__dirname, 'renderer', 'panel.html'));
  panelWin.on('closed', () => { panelWin = null; state.panelOpen = false; });
}

// "compact" is the small card beside the robot; "wide" is a big window in the middle of the screen; "full" fills the usable area.
// In the big ones the window can be resized by its edges (the page lays itself out from its width).
let panelMode = 'compact';

function positionPanel() {
  if (!alive(panelWin)) return;
  const wa = nearestWorkArea({ x: icon.x + ICON / 2, y: icon.y + ICON / 2 });
  if (panelMode === 'compact') panelWin.setBounds(panelBounds({ icon, size: ICON, workArea: wa, panel: PANEL }));
  else panelWin.setBounds(expandedBounds({ workArea: wa, mode: panelMode }));
}

// In the big window the character stands in the conversation (the page draws it), so the little one on the desktop steps aside.
function syncWidget() {
  if (!alive(widgetWin) || state.hidden) return;
  if (state.panelOpen && panelMode !== 'compact') widgetWin.hide(); else widgetWin.showInactive();
}

function setPanelMode(mode) {
  if (!['compact', 'wide', 'full'].includes(mode) || mode === panelMode) return;
  panelMode = mode;
  if (alive(panelWin)) {
    panelWin.setResizable(mode !== 'compact');
    panelWin.setMinimumSize(mode === 'compact' ? 0 : MIN_WIDE.w, mode === 'compact' ? 0 : MIN_WIDE.h);
    positionPanel();
  }
  syncWidget();
  sendPanelState();
}

function prettyHotkey(accel) {
  const parts = accel.split('+').map((p) => (p === 'CommandOrControl' ? (isMac ? '⌘' : 'Ctrl') : p === 'Shift' ? (isMac ? '⇧' : 'Shift') : p === 'Space' ? 'Espaço' : p));
  return isMac ? parts.join('') : parts.join('+');
}

function panelState() {
  return {
    engineUp: state.engineUp,
    overview: overviewNow(),
    busy: state.busy > 0,
    describe: { ...currentDescription(), mood: settings.mood === 'auto' ? moodWithBell(currentDescription().mood, currentBell()) : effectiveMood(currentDescription().mood) },
    bell: currentBell(),
    notices: state.notices.slice(-20),
    settings: { protect: settings.protect, masked: settings.masked, autoSend: settings.autoSend, autoRunSafe: settings.autoRunSafe, hear: settings.hear, talk: settings.talk, enhancedVoice: settings.enhancedVoice, voiceSpeed: settings.voiceSpeed, speakEmojis: settings.speakEmojis, micSource: settings.micSource, still: settings.still, bubbleSide: settings.bubbleSide, mood: settings.mood, whatsapp: settings.whatsapp, calendar: settings.calendar, research: settings.research },
    voice: state.voice,
    ownsEngine: !!engineProcess,
    canOpenWa: !!projectRoot(),
    panelOpen: state.panelOpen,
    panelMode,
    hotkeys: { toggle: prettyHotkey(HOTKEYS.toggle), panic: prettyHotkey(HOTKEYS.panic) },
  };
}

function sendPanelState() { sendTo(panelWin, 'panel:state', panelState()); refreshMood(); }

function openPanel() {
  if (state.hidden) setHidden(false);
  if (!alive(panelWin)) createPanel();
  hideBubble();
  state.panelOpen = true;
  state.unread = 0;  // opening the panel is seeing the news
  syncBell();
  refreshMood();
  positionPanel();
  panelWin.show();
  panelWin.focus();
  syncWidget();
  sendPanelState();
  refreshOverview();
  clearInterval(panelTimer);
  panelTimer = setInterval(refreshOverview, 15000);
  rebuildMenu();
}

function closePanel() {
  state.panelOpen = false;
  clearInterval(panelTimer);
  if (alive(panelWin)) panelWin.hide();
  syncWidget();
  sendPanelState(); // the panel window keeps running (and listening): it must know it is closed
  rebuildMenu();
}

const togglePanel = () => (state.panelOpen && alive(panelWin) && panelWin.isVisible() ? closePanel() : openPanel());

function setHidden(hidden) {
  state.hidden = hidden;
  if (hidden) {
    hideBubble();
    closePanel();
    if (alive(widgetWin)) widgetWin.hide();
  } else if (alive(widgetWin)) {
    widgetWin.showInactive();
  }
  rebuildMenu();
}

// ---------------------------------------------------------------------------------------------------- engine
// With the person's standing permission ("Ajustes > Enviar mensagens do WhatsApp sem pedir aprovação"), WhatsApp sends the
// person asked for are approved here. Only sends: calendar changes still wait. The engine keeps its hourly limit and gap.
const autoTried = new Set();
async function autoApproveNew() {
  if (!settings || !settings.autoSend || !state.overview) return;
  for (const item of state.overview.pending || []) {
    if (item.kind !== 'whatsapp.send' || autoTried.has(item.id)) continue;
    autoTried.add(item.id);
    try {
      await engine.approve(item.id);
      localNotice('Mensagem enviada.');
    } catch (e) {
      localNotice(`Não consegui enviar a mensagem: ${friendlyError(e)}`);
    }
    refreshOverview();
  }
}

// The engine forgets "manter aprovado" when it restarts, so it is told again whenever it disagrees with the setting.
async function syncStanding() {
  if (!state.overview || state.overview.computer_standing === undefined) return;
  const want = settings.autoRunSafe === true;
  if (state.overview.computer_standing === want) return;
  try { await engine.setStanding(want); state.overview.computer_standing = want; } catch { /* the next refresh tries again */ }
}

async function refreshOverview() {
  try {
    applyOverview(await engine.overview());
    state.engineUp = true;
    syncStanding();
  } catch {
    state.engineUp = false;
  }
  sendPanelState();
  autoApproveNew();
}

// The character says hello once, when it is ready (not "the engine is not running": while it boots it only shows "(...)").
let greeted = false;
function sayHello() {
  if (greeted || state.hidden) return;
  greeted = true;
  const hello = pickGreeting();
  pushNotice({ id: -Date.now(), kind: 'reply', text: hello, masked: hello, ts: Date.now() / 1000, key: 'startup' });
}

async function healthLoop() {
  let wasUp = null;
  const startedAt = Date.now();
  while (!quitting) {
    const up = await engine.health();
    state.engineUp = up;
    if (up && wasUp !== true) {
      await refreshOverview();
      await refreshVoiceStatus(); // the engine was not up yet when the app started: ask now whether the enhanced voice is installed
      warmVoice();
    }
    if (!up) voiceWarmed = false; // a restarted engine has not loaded the voice
    if (!up && wasUp === null) pushNotice({ id: -Date.now(), kind: 'reply', text: '(...)', masked: '(...)', ts: Date.now() / 1000, key: 'booting' }); // starting up
    if (up) sayHello();
    // a real problem, not the normal start-up: it was running and stopped, or it never came up
    if (!up && !state.warnedDown && ((wasUp === true) || (wasUp === false && Date.now() - startedAt > 90000))) {
      localNotice(wasUp === true ? 'Perdi a conexão com o motor do Chakmati.' : 'O motor do Chakmati não iniciou. Veja o engine.log.');
      state.warnedDown = true;
    }
    if (up) state.warnedDown = false;
    if (wasUp !== up) { refreshMood(); sendPanelState(); }
    wasUp = up;
    await sleep(up ? 5000 : 1000);
  }
}

async function noticeLoop() {
  let cursor = null;
  const abort = new AbortController();
  app.once('before-quit', () => abort.abort());
  while (!quitting) {
    if (!state.engineUp) { cursor = null; await sleep(2000); continue; }
    try {
      if (cursor === null) { // start from "now": old notices are not replayed when the app opens
        applyOverview(await engine.overview());
        cursor = state.overview.last_notice_id;
        sendPanelState();
      }
      const result = await engine.notices(cursor, 25, abort.signal);
      cursor = result.last_id;
      for (const n of result.notices) pushNotice(n);
      if (result.notices.length) refreshOverview();
    } catch {
      if (quitting) return;
      cursor = null;
      await sleep(3000);
    }
  }
}

const projectRoot = () => {
  const root = path.resolve(__dirname, '..', '..');
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
  if (!launch || engineProcess) return false;
  const env = settingsLib.engineEnv(settings, { searxng: await searxngUp() });
  if (engineProcess) return false;
  fs.mkdirSync(launch.cwd, { recursive: true });
  const logFile = path.join(app.getPath('userData'), 'engine.log');
  const log = fs.openSync(logFile, 'a');
  engineProcess = spawn(launch.command, launch.args, {
    cwd: launch.cwd, stdio: ['ignore', log, log], windowsHide: true, env: { ...process.env, PATH: toolPath(), ...launch.env, ...env },
  });
  fs.closeSync(log);
  engineProcess.on('error', () => { engineProcess = null; });
  engineProcess.on('exit', () => { engineProcess = null; });
  return true;
}

async function restartEngine() {
  if (!engineProcess) return false;
  const old = engineProcess;
  await new Promise((resolve) => { old.once('exit', resolve); old.kill(); setTimeout(resolve, 4000); });
  engineProcess = null;
  await sleep(500);
  return startEngine();
}

// ---- OpenWA (the WhatsApp bridge). Its browser window is only needed once, to scan the QR code; closing that window
// stops the session, so after the link is made the app restarts OpenWA without a window (the login stays saved).
const OPENWA_URL = process.env.CHAKMATI_OPENWA_URL || 'http://127.0.0.1:8081';
let owaWatch = null; // { abort: AbortController } while a link attempt is being watched

async function owaHealth() {
  try {
    const res = await fetch(`${OPENWA_URL}/health`, { signal: AbortSignal.timeout(2500) });
    return res.ok ? await res.json() : null;
  } catch { return null; }
}

function owaScript(arg, { detached = false } = {}) {
  const root = projectRoot();
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
  for (let attempt = 0; attempt < 2 && !quitting; attempt += 1) {
    await owaRun('stop');
    for (let i = 0; i < 10 && (await owaHealth()); i += 1) await sleep(1000);
    owaScript('start-bg', { detached: true });
    for (let i = 0; i < 30 && !quitting; i += 1) {
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
    while (!quitting && !abort.signal.aborted && Date.now() < deadline) {
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
    refreshOverview();
  }
}

async function openWaSetup() {
  const root = projectRoot();
  if (!root) return { ok: false, error: 'Não encontrei a pasta do Chakmati.' };
  const health = await owaHealth();
  if (health && health.connected) { refreshOverview(); return { ok: true, message: 'O WhatsApp já está conectado.' }; }
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

// ---------------------------------------------------------------------------------------------------- tray and shortcuts
// Quits and starts again (the engine started by the app is stopped and started with it).
function restartApp() {
  app.relaunch();
  app.quit();
}

function buildMenu() {
  return Menu.buildFromTemplate([
    { label: state.panelOpen ? 'Fechar painel' : 'Abrir painel', click: togglePanel },
    { label: state.hidden ? 'Mostrar o Chakmati' : 'Ocultar tudo agora', click: () => setHidden(!state.hidden) },
    { type: 'separator' },
    { label: 'Esconder do compartilhamento de tela', type: 'checkbox', checked: settings.protect, click: (i) => updateSetting('protect', i.checked) },
    { label: 'Modo discreto (sem nomes nos avisos)', type: 'checkbox', checked: settings.masked, click: (i) => updateSetting('masked', i.checked) },
    { type: 'separator' },
    { label: 'Reiniciar o Chakmati', click: restartApp },
    { label: 'Sair', click: () => app.quit() },
  ]);
}

function rebuildMenu() { if (tray) tray.setContextMenu(buildMenu()); }

function createTray() {
  const image = nativeImage.createFromBuffer(robotPng({ size: 32, template: isMac }), { scaleFactor: 2 });
  if (isMac) image.setTemplateImage(true);
  tray = new Tray(image);
  tray.setToolTip('Chakmati');
  rebuildMenu();
}

function registerShortcuts() {
  const ok = [globalShortcut.register(HOTKEYS.toggle, togglePanel), globalShortcut.register(HOTKEYS.panic, () => setHidden(!state.hidden))];
  if (ok.includes(false)) console.warn('Some global shortcuts could not be registered (another app may be using them).');
}

// ---------------------------------------------------------------------------------------------------- settings
// The enhanced voice is used only once it is installed; until then (and if anything fails) the system voice speaks.
const enhancedReady = () => settings.enhancedVoice === true && !!(state.voice && state.voice.installed);
const sendVoice = () => sendTo(widgetWin, 'widget:voice', { hear: settings.hear, emojis: settings.speakEmojis, enhanced: enhancedReady(), speed: settings.voiceSpeed });

// The first sentence with the enhanced voice loads its model (about a second): do it once, silently, when the engine is up,
// so the first thing Chakmati says is not late.
let voiceWarmed = false;
async function warmVoice() {
  if (voiceWarmed || !enhancedReady()) return;
  voiceWarmed = true;
  try { await engine.speak('ok', settings.voiceSpeed); } catch { voiceWarmed = false; }
}

async function refreshVoiceStatus() {
  try { state.voice = await engine.voiceStatus(); } catch { state.voice = null; }
  sendPanelState();
  sendVoice();
}

// Turning the enhanced voice on downloads it the first time (about 63 MB); the panel shows the progress. If the download
// fails the switch goes back off and the system voice keeps speaking.
let voiceDownloading = false;
async function downloadVoice() {
  if (voiceDownloading) return;
  voiceDownloading = true;
  try {
    state.voice = await engine.voiceDownload();
    sendPanelState();
    while (!quitting && state.voice && state.voice.downloading) {
      await sleep(600);
      state.voice = await engine.voiceStatus();
      sendPanelState();
    }
    if (!state.voice || !state.voice.installed) throw new Error((state.voice && state.voice.error) || 'não consegui baixar');
    localNotice('Voz melhorada pronta.');
  } catch (e) {
    settings.enhancedVoice = false;
    persistSettings();
    localNotice(`Não consegui baixar a voz melhorada: ${e instanceof EngineError ? friendlyError(e) : (e && e.message) || 'erro'}`);
  } finally {
    voiceDownloading = false;
    sendVoice();
    sendPanelState();
    rebuildMenu();
  }
}

function updateSetting(key, value) {
  if (process.env.CHAKMATI_DEBUG_WINDOWS === '1') { try { fs.appendFileSync(path.join(app.getPath('userData'), 'window-debug.log'), `${new Date().toISOString()} SETTING ${key}=${JSON.stringify(value)}\n`); } catch { /* debugging only */ } }
  if (key === 'protect' && typeof value === 'boolean') settings.protect = value;
  else if (key === 'masked' && typeof value === 'boolean') settings.masked = value;
  else if (key === 'bubbleSide' && settingsLib.SIDES.includes(value)) settings.bubbleSide = value;
  else if (key === 'hear' && typeof value === 'boolean') { settings.hear = value; sendVoice(); }
  else if (key === 'talk' && typeof value === 'boolean') {
    settings.talk = value;
    syncListening();
    if (value) { // talking to Chakmati also means hearing it
      settings.hear = true;
      sendVoice();
      if (process.platform === 'darwin') systemPreferences.askForMediaAccess('microphone').catch(() => {});
      if (!alive(panelWin)) createPanel(); // the always-on microphone lives in the panel window, which can stay hidden
    }
  }
  else if (key === 'enhancedVoice' && typeof value === 'boolean') {
    settings.enhancedVoice = value;
    if (value && !(state.voice && state.voice.installed)) downloadVoice();
    else if (value) warmVoice();
    sendVoice();
  }
  else if (key === 'voiceSpeed' && (value === 'normal' || value === 'fast')) { settings.voiceSpeed = value; sendVoice(); }
  else if (key === 'speakEmojis' && typeof value === 'boolean') { settings.speakEmojis = value; sendVoice(); }
  else if (key === 'micSource' && (value === 'computer' || value === 'system')) settings.micSource = value;
  else if (key === 'autoRunSafe' && typeof value === 'boolean') { settings.autoRunSafe = value; syncStanding(); }
  else if (key === 'autoSend' && typeof value === 'boolean') { settings.autoSend = value; autoApproveNew(); }
  else if (key === 'still' && typeof value === 'boolean') { settings.still = value; sendTo(widgetWin, 'widget:still', value); }
  else if (key === 'mood' && settingsLib.MOODS.includes(value)) settings.mood = value;
  else if ((key === 'whatsapp' || key === 'calendar' || key === 'research') && typeof value === 'boolean') {
    settings[key] = value;
    if (engineProcess) restartEngine().then(refreshOverview);
  } else return false;
  persistSettings();
  protect(widgetWin);
  protect(panelWin);
  applyLayout();
  refreshMood();
  sendPanelState();
  rebuildMenu();
  return true;
}

// ---------------------------------------------------------------------------------------------------- IPC (every input is validated)
const isId = (v) => typeof v === 'string' && /^[0-9a-f]{32}$/.test(v);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) < 1e5;

function friendlyError(e) {
  if (e instanceof EngineError) {
    if (e.status === 410) return 'A proposta expirou. Peça de novo.';
    if (e.status === 409) return 'Esta ação já foi decidida.';
    if (e.status === 403) return 'O motor recusou o pedido.';
    return e.message;
  }
  return e && e.name === 'AbortError' ? 'Cancelado.' : 'Não consegui falar com o motor.';
}

function registerIpc() {
  // The floating widget reads notices aloud; tell the panel's microphone so it does not hear (and transcribe) them.
  ipcMain.on('widget:speaking', (_e, on) => sendTo(panelWin, 'panel:other-speaking', on === true));
  ipcMain.on('widget:ready', () => { applyLayout(); refreshMood(); sendTo(widgetWin, 'widget:still', settings.still); sendVoice(); listeningShown = null; syncListening(); bellShown = ''; syncBell(); });
  ipcMain.on('widget:hover', (_e, inside) => { if (!isLinux && alive(widgetWin)) widgetWin.setIgnoreMouseEvents(!inside, { forward: true }); });
  ipcMain.on('widget:drag-start', () => { dragStart = { ...icon }; });
  ipcMain.on('widget:drag-move', (_e, d) => {
    if (!dragStart || !d || !isNum(d.dx) || !isNum(d.dy)) return;
    icon = { x: Math.round(dragStart.x + d.dx), y: Math.round(dragStart.y + d.dy) };
    applyLayout();
  });
  ipcMain.on('widget:drag-end', (_e, moved) => {
    dragStart = null;
    if (moved === true) { settings.icon = { ...icon }; persistSettings(); }
  });
  ipcMain.on('widget:toggle', togglePanel);
  ipcMain.on('widget:bubble-click', openPanel);
  ipcMain.on('widget:menu', () => buildMenu().popup({ window: widgetWin }));

  ipcMain.on('panel:ready', sendPanelState);
  ipcMain.on('panel:close', closePanel);
ipcMain.on('panel:layout', (_e, mode) => setPanelMode(mode));
  // With the panel closed, what Chakmati answers appears the way notices do: a bubble by the character (and spoken, if on).
  ipcMain.on('panel:reply', (_e, p) => {
    if (state.panelOpen || state.hidden || !p || typeof p.text !== 'string' || !p.text.trim()) return;
    const text = brief(p.text); // at most two lines
    if (!text) return;
    pushNotice({ id: -Date.now(), kind: 'reply', text, masked: 'O Chakmati respondeu.', ts: Date.now() / 1000, key: `reply:${Date.now()}` });
  });
  // A link icon in a message: opened in the person's own browser, only http(s) and only what was in the conversation's text
  ipcMain.on('panel:open-link', (_e, url) => { const safe = links.safeLink(url); if (safe) shell.openExternal(safe); });
  ipcMain.on('panel:refresh', refreshOverview);
  ipcMain.on('panel:panic', () => setHidden(true));
  ipcMain.on('panel:restart', restartApp);
  // Parar: a job (browser, files) is stopped in the engine and its own stream says so; a plain answer is simply no longer waited for.
  ipcMain.on('panel:cancel', async (_e, id) => {
    const ac = streams.get(id);
    if (!ac) return;
    stopped.add(id);
    const jobId = jobOf.get(id);
    if (jobId) { try { await engine.cancelJob(jobId); return; } catch { /* the engine could not be asked: stop waiting for it instead */ } }
    ac.abort();
  });

  // Reading a conversation. Names and texts are hidden in discreet mode, so these refuse to run then.
  const guard = () => (settings.masked ? 'Modo discreto ligado: desligue em Ajustes para ver as conversas.' : state.engineUp ? null : 'O motor não está rodando.');
  ipcMain.handle('panel:chats', async () => {
    const blocked = guard();
    if (blocked) return { error: blocked };
    try { return { chats: await engine.chats(80) }; } catch (e) { return { error: friendlyError(e) }; }
  });
  ipcMain.handle('panel:messages', async (_e, chatId) => {
    const blocked = guard();
    if (blocked || typeof chatId !== 'string') return { error: blocked || 'Conversa inválida.' };
    try { return { messages: await engine.messages(chatId, 40) }; } catch (e) { return { error: friendlyError(e) }; }
  });
  ipcMain.handle('panel:audio', async (_e, chatId, messageId) => {
    const blocked = guard();
    if (blocked || typeof chatId !== 'string' || typeof messageId !== 'string') return { error: blocked || 'Áudio inválido.' };
    try {
      const a = await engine.audio(chatId, messageId);
      return { dataUrl: `data:${a.mime};base64,${a.base64}` };
    } catch (e) { return { error: e instanceof EngineError && e.status === 404 ? 'Este áudio não pode ser reproduzido.' : friendlyError(e) }; }
  });
  ipcMain.handle('panel:transcribe', async (_e, bytes, mime) => {
    if (!settings.talk) return { error: 'Ative "Falar com o Chakmati" em Ajustes.' };
    if (!state.engineUp) return { error: 'O motor não está rodando.' };
    if (!(bytes instanceof Uint8Array) || typeof mime !== 'string') return { error: 'Gravação inválida.' };
    try {
      const timeout = new Promise((_resolve, reject) => setTimeout(() => reject(new Error('timeout')), 90000));
      return await Promise.race([engine.transcribe(bytes, mime), timeout]);
    } catch (e) {
      if (e && e.message === 'timeout') return { error: 'O reconhecimento de voz demorou demais.' };
      return { error: e instanceof EngineError && e.status === 503 ? 'O reconhecimento de voz está desligado no motor.' : friendlyError(e) };
    }
  });
  // Speaking with the enhanced voice: the engine synthesizes the text on this computer and sends the audio back.
  ipcMain.handle('voice:synthesize', async (_e, text, speed) => {
    if (!enhancedReady() || typeof text !== 'string' || !text.trim() || text.length > 600) return { error: 'unavailable' };
    try {
      const a = await engine.speak(text, speed === 'fast' ? 'fast' : 'normal');
      return { dataUrl: `data:${a.mime};base64,${a.base64}` };
    } catch (e) { return { error: friendlyError(e) }; } // the renderer falls back to the system voice
  });
  ipcMain.handle('panel:voice-remove', async () => {
    try {
      state.voice = await engine.voiceRemove();
      settings.enhancedVoice = false;
      persistSettings();
      sendVoice();
      sendPanelState();
      return { ok: true };
    } catch (e) { return { ok: false, error: friendlyError(e) }; }
  });
  ipcMain.handle('panel:openwa', () => openWaSetup());
  ipcMain.handle('panel:set-setting', (_e, payload) => (payload && updateSetting(payload.key, payload.value) ? { ok: true } : { ok: false }));

  ipcMain.handle('panel:input', async (_e, jobId, requestId, value) => {
  try { return await engine.sendInput(jobId, requestId, value); } catch { return { ok: false, error: 'Não consegui enviar a resposta. Tente de novo.' }; }
});
ipcMain.handle('panel:send', async (_e, text) => {
    if (typeof text !== 'string' || !text.trim() || text.length > MAX_TEXT) return { error: 'Pedido inválido.' };
    if (!state.engineUp) return { error: 'O motor não está rodando. Inicie o Chakmati.' };
    // a command arrived: the microphone stops waiting for one (the wake phrase itself starts the wait again once answered)
    state.awakeUntil = 0;
    syncListening();
    const id = crypto.randomUUID();
    const ac = new AbortController();
    streams.set(id, ac);
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; ac.abort(); }, 4 * 60 * 1000); // an answer that never ends must not block everything else
    state.busy += 1;
    sendPanelState();
    (async () => {
      let failed = false;
      try {
        for await (const event of engine.streamMessage(text, ac.signal)) {
          if (event.type === 'job' && event.job_id) jobOf.set(id, event.job_id);
          if (event.type === 'input') { state.asking = true; syncBell(); refreshMood(); } else if (event.type === 'input_done') { state.asking = false; syncBell(); refreshMood(); }
          sendTo(panelWin, 'panel:message', { id, event });
        }
      } catch (e) {
        failed = !stopped.has(id);
        if (stopped.has(id)) sendTo(panelWin, 'panel:message', { id, event: { type: 'cancelled', text: 'Interrompido por você.' } });
        else sendTo(panelWin, 'panel:message', { id, event: { type: 'error', error: timedOut ? 'Demorei demais e parei de esperar. Pode pedir de novo.' : friendlyError(e) } });
      } finally {
        if (state.asking) { state.asking = false; syncBell(); refreshMood(); }
        sendTo(panelWin, 'panel:message', { id, event: { type: 'end' } });
        clearTimeout(timeout);
        streams.delete(id);
        jobOf.delete(id);
        stopped.delete(id);
        state.busy = Math.max(0, state.busy - 1);
        if (!failed) happyUntil = Date.now() + 3000;
        clearTimeout(moodTimer);
        moodTimer = setTimeout(refreshMood, 3100);
        refreshOverview();
      }
    })();
    return { id };
  });

  const decide = (verb) => async (_e, id) => {
    if (!isId(id)) return { ok: false, error: 'Pedido inválido.' };
    try {
      const action = await engine[verb](id);
      refreshOverview();
      if (action.status === 'failed') return { ok: false, error: action.error || 'Não foi possível concluir.' };
      return { ok: true, text: verb === 'approve' ? action.result || 'Feito.' : 'Recusado.' };
    } catch (e) {
      refreshOverview();
      return { ok: false, error: friendlyError(e) };
    }
  };
  ipcMain.handle('panel:automation', async (_e, id, op) => {
    if (!isId(id) || !['enable', 'disable', 'delete'].includes(op)) return { ok: false, error: 'Pedido inválido.' };
    try { await engine.setAutomation(id, op); refreshOverview(); return { ok: true }; } catch (e) { return { ok: false, error: friendlyError(e) }; }
  });
  ipcMain.handle('panel:preview', async (_e, id) => {
    if (!isId(id)) return { error: 'Pedido inválido.' };
    try { const a = await engine.preview(id); return { dataUrl: `data:${a.mime};base64,${a.base64}` }; } catch (e) { return { error: friendlyError(e) }; }
  });
  ipcMain.handle('panel:propose-recorded', async (_e, bytes) => {
    if (!(bytes instanceof Uint8Array) || !bytes.length) return { error: 'Gravação inválida.' };
    try { const action = await engine.proposeRecorded(bytes); refreshOverview(); return { action }; } catch (e) { return { error: friendlyError(e) }; }
  });
  // A line that changes every second (the countdown) shown by the character with the panel closed. Never spoken, never queued.
  ipcMain.on('panel:live', (_e, text) => {
    if (state.panelOpen || state.hidden) return;
    clearTimeout(bubbleTimer);
    if (typeof text !== 'string' || !text.trim()) { nextBubble(); return; }
    state.bubbleVisible = true;
    sendTo(widgetWin, 'widget:bubble', { text: text.slice(0, 140), kind: 'system', id: -1, silent: true });
    refreshMood();
    bubbleTimer = setTimeout(nextBubble, 3000);
  });
  ipcMain.handle('panel:approve', decide('approve'));
  ipcMain.handle('panel:reject', decide('reject'));
}

// ---------------------------------------------------------------------------------------------------- design snapshots
const SAMPLE_OVERVIEW = {
  whatsapp: { enabled: true, connected: true, state: 'READY', unread: [
    { id: '1@lid', name: 'Maria Victoria', unread: 2, is_group: false },
    { id: '2@g.us', name: 'Família', unread: 5, is_group: true },
    { id: '3@lid', name: 'João Pereira', unread: 1, is_group: false },
  ] },
  automations: [{ id: 'b'.repeat(32), name: 'Resposta automática', enabled: true, runs: 2, description: 'Quando alguém te escrever no WhatsApp, responder: «Estou ocupado».' }],
  calendar: { enabled: true, today: [
    { id: 'e1', title: 'Reunião de planejamento', start: new Date(new Date().setHours(15, 0, 0, 0)).toISOString(), all_day: false },
    { id: 'e2', title: 'Dentista', start: new Date(new Date().setHours(17, 30, 0, 0)).toISOString(), all_day: false },
  ] },
  pending: [{ id: 'a'.repeat(32), kind: 'whatsapp.send', status: 'pending', expires_at: 9e9,
    summary: 'Enviar WhatsApp para Maria Victoria +5551999990000:\nChego em 10 minutos, me espera na portaria.' }],
  last_notice_id: 3,
};

async function capture(win, file) {
  const image = await win.webContents.capturePage();
  fs.writeFileSync(file, image.toPNG());
}

// Asks the OS for a real screenshot with the panel shown, protected and unprotected, so the claim is measured, not assumed.
async function runProtectTest() {
  const out = PROTECT_TEST;
  fs.mkdirSync(out, { recursive: true });
  settings = { ...settingsLib.DEFAULTS, protect: false };
  engine = { overview: async () => SAMPLE_OVERVIEW };
  state.engineUp = true;
  state.overview = SAMPLE_OVERVIEW;
  icon = { x: 200, y: 200 };
  createPanel();
  await new Promise((r) => ipcMain.once('panel:ready', r));
  state.panelOpen = true;
  positionPanel();
  panelWin.show();
  sendPanelState();
  const run = (file) => new Promise((res) => spawn('screencapture', ['-x', path.join(out, file)]).on('close', res));
  await sleep(800);
  await run('unprotected.png');
  settings.protect = true;
  protect(panelWin);
  await sleep(800);
  await run('protected.png');
  console.log('panel bounds', JSON.stringify(panelWin.getBounds()));
  app.quit();
}

async function runSnapshots() {
  const out = SNAPSHOT === '1' ? path.join(app.getPath('temp'), 'liteagent-desktop-snapshots') : SNAPSHOT;
  fs.mkdirSync(out, { recursive: true });
  settings = { ...settingsLib.DEFAULTS, protect: false, hear: true, talk: true };
  const SAMPLE_CHATS = [
    { id: '162457238634742@lid', name: 'Maria Victoria', is_group: false, unread: 2 },
    { id: '120363@g.us', name: 'Família', is_group: true, unread: 5 },
    { id: '222@lid', name: 'João Pereira', is_group: false, unread: 1 },
    { id: '333@lid', name: 'Tio Alex', is_group: false, unread: 0 },
  ];
  const now = new Date().toISOString();
  const SAMPLE_MESSAGES = [
    { id: 'm1', sender: 'Maria Victoria', text: 'Oi! Chego em 10 minutos', ts: now, from_me: false, kind: 'chat', duration: null, audio: false },
    { id: 'm2', sender: 'Maria Victoria', text: '', ts: now, from_me: false, kind: 'ptt', duration: 25, audio: true },
    { id: 'm3', sender: 'eu', text: 'Combinado, te espero na portaria', ts: now, from_me: true, kind: 'chat', duration: null, audio: false },
    { id: 'm4', sender: 'Maria Victoria', text: '', ts: now, from_me: false, kind: 'image', duration: null, audio: false },
  ];
  engine = { overview: async () => SAMPLE_OVERVIEW, chats: async () => SAMPLE_CHATS, messages: async () => SAMPLE_MESSAGES };
  state.engineUp = true;
  state.overview = SAMPLE_OVERVIEW;
  state.notices = [
    { id: 1, kind: 'whatsapp', text: 'Você recebeu uma nova mensagem de Maria Victoria', masked: 'Você recebeu uma nova mensagem no WhatsApp', ts: Date.now() / 1000 - 40 },
    { id: 2, kind: 'calendar', text: 'Em 10 min: Reunião de planejamento', masked: 'Você tem um compromisso em breve', ts: Date.now() / 1000 - 400 },
    { id: 3, kind: 'approval', text: 'Há uma ação aguardando a sua aprovação: Enviar WhatsApp para Maria Victoria', masked: 'Há uma ação aguardando a sua aprovação', ts: Date.now() / 1000 - 700 },
  ];
  const wa = screen.getPrimaryDisplay().workArea;
  const shot = async (name, win) => { await sleep(450); await capture(win, path.join(out, name)); };

  createWidget();
  await new Promise((r) => ipcMain.once('widget:ready', r));
  sendTo(widgetWin, 'widget:backdrop', true);
  widgetWin.showInactive();

  icon = { x: wa.x + wa.width - 160, y: wa.y + wa.height - 160 };
  applyLayout();
  showBubble(state.notices[0]);
  await shot('widget-top-right.png', widgetWin);

  icon = { x: wa.x + 40, y: wa.y + 30 };
  applyLayout();
  showBubble(state.notices[2]);
  await shot('widget-bottom-left.png', widgetWin);

  settings.bubbleSide = 'left';
  icon = { x: wa.x + Math.round(wa.width / 2), y: wa.y + Math.round(wa.height / 2) };
  applyLayout();
  showBubble(state.notices[1]);
  await shot('widget-left.png', widgetWin);

  showBubble({ id: 9, kind: 'reply', text: brief('Oé! Se eu somasse 5 e dissesse oé, você ia rir ou me chamar de mentiroso? Mas a resposta correta é 4. Sem truques, só matemática pura. Tamo aqui pra te ajudar com mais esse desafio.'), masked: 'O Chakmati respondeu.', ts: Date.now() / 1000, key: 'r' });
  sendTo(widgetWin, 'widget:listening', true);
  await shot('widget-reply.png', widgetWin);
  sendTo(widgetWin, 'widget:listening', false);

  state.engineUp = false;
  refreshMood();
  hideBubble();
  await shot('widget-offline.png', widgetWin);
  state.engineUp = true;
  hideBubble();

  icon = { x: wa.x + wa.width - 160, y: wa.y + wa.height - 160 };
  settings.bubbleSide = 'auto';
  applyLayout();
  createPanel();
  await new Promise((r) => ipcMain.once('panel:ready', r));
  state.panelOpen = true;
  positionPanel();
  panelWin.showInactive();
  sendPanelState();
  await shot('panel.png', panelWin);

  await panelWin.webContents.executeJavaScript("document.getElementById('content').scrollTop = 99999; document.getElementById('create-automation').click()");
  await shot('panel-bottom.png', panelWin);
  await panelWin.webContents.executeJavaScript("document.getElementById('content').scrollTop = 0; document.getElementById('automation-note').hidden = true");
  await panelWin.webContents.executeJavaScript("document.getElementById('chips').classList.add('open')");
  await shot('panel-suggestions.png', panelWin);
  await panelWin.webContents.executeJavaScript("document.getElementById('chips').classList.remove('open')");
  const click = (sel) => panelWin.webContents.executeJavaScript(`document.querySelector(${JSON.stringify(sel)}).click()`);
  await click('.more');
  await shot('panel-chats.png', panelWin);
  await click('#chats-body .row-btn');
  await shot('panel-chat.png', panelWin);
  await click('#back');
  await click('#back');
  await panelWin.webContents.executeJavaScript("document.getElementById('open-settings').click()");
  await shot('panel-settings.png', panelWin);
  await panelWin.webContents.executeJavaScript("document.getElementById('back').click()");
  nativeTheme.themeSource = 'dark';
  await shot('panel-dark.png', panelWin);
  nativeTheme.themeSource = 'light';

  settings.masked = true;
  sendPanelState();
  await shot('panel-masked.png', panelWin);
  settings.masked = false;

  state.overview = { ...SAMPLE_OVERVIEW, pending: [], whatsapp: { enabled: true, connected: false, state: 'UNPAIRED', unread: [] } };
  sendPanelState();
  await shot('panel-wa-down.png', panelWin);

  state.engineUp = false;
  state.overview = null;
  sendPanelState();
  await shot('panel-offline.png', panelWin);

  console.log(`snapshots written to ${out}`);
  app.quit();
}

// ---------------------------------------------------------------------------------------------------- start
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(async () => {
    if (isMac) { app.dock?.hide(); app.setActivationPolicy?.('accessory'); }
    registerIpc();
    if (SNAPSHOT) { await runSnapshots(); return; }
    if (PROTECT_TEST) { await runProtectTest(); return; }
    const firstRun = needsSetup({ packaged: app.isPackaged, dataDir: app.getPath('userData'), platform: process.platform });
    if (SETUP || firstRun) { // the install wizard: --setup, or the first run of an installed app; the normal app starts after it
      settingsFile = path.join(app.getPath('userData'), 'settings.json');
      if (isMac) { app.setActivationPolicy?.('regular'); app.dock?.show(); }
      openSetup({
        ipcMain, webPreferences, settingsFile,
        engine: app.isPackaged ? { resourcesPath: process.resourcesPath, dataDir: app.getPath('userData') } : null,
        onClosed: () => app.quit(),
        onFinish: () => { app.relaunch({ args: process.argv.slice(1).filter((a) => a !== '--setup') }); app.exit(0); },
      });
      return;
    }

    settingsFile = path.join(app.getPath('userData'), 'settings.json');
    settings = settingsLib.load(settingsFile);
    engine = new EngineClient({ baseUrl: settings.engineUrl });
    icon = settings.icon || defaultIcon();

    createWidget();
    await new Promise((resolve) => ipcMain.once('widget:ready', resolve));
    widgetWin.showInactive();
    if (settings.talk) createPanel(); // keep the microphone listening even with the panel closed
    createTray();
    registerShortcuts();
    if (!(await engine.health())) await startEngine();
    await refreshVoiceStatus();
    if (settings.enhancedVoice && state.voice && !state.voice.installed) downloadVoice(); // chosen (and approved) in the setup wizard; a failure turns it off again
    healthLoop();
    noticeLoop();
    screen.on('display-metrics-changed', applyLayout);
    screen.on('display-removed', applyLayout);
  });

  app.on('second-instance', () => { if (alive(widgetWin)) openPanel(); });
  app.on('window-all-closed', () => { /* a tray app: closing a window does not quit */ });
  app.on('before-quit', () => {
    quitting = true;
    globalShortcut.unregisterAll();
    for (const ac of streams.values()) ac.abort();
    if (engineProcess) engineProcess.kill();
  });
}
