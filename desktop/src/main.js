'use strict';
// Floating robot assistant for lite-agent. This process owns the windows and is the only one that talks to the engine.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app, BrowserWindow, Tray, Menu, ipcMain, screen, globalShortcut, nativeImage, nativeTheme } = require('electron');

const { EngineClient, EngineError } = require('./lib/engine-client');
const settingsLib = require('./lib/settings');
const { chooseSide, layoutWidget, clampIcon, panelBounds } = require('./lib/placement');
const { NoticeQueue, present, bubbleDuration } = require('./lib/notice-queue');
const { describe } = require('./lib/describe');
const { robotPng } = require('./lib/trayicon');

const ICON = 72;
const BUBBLE = { w: 320, h: 120 };
const PANEL = { w: 400, h: 640 };
const HOTKEYS = { toggle: 'CommandOrControl+Shift+Space', panic: 'CommandOrControl+Shift+H' };
const MAX_TEXT = 2000;
const SNAPSHOT = process.env.LITEAGENT_DESKTOP_SNAPSHOT;
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
const state = { engineUp: false, overview: null, notices: [], busy: 0, hidden: false, panelOpen: false, bubbleVisible: false, warnedDown: false };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = (w) => w && !w.isDestroyed();
const sendTo = (w, channel, payload) => { if (alive(w) && !w.webContents.isDestroyed()) w.webContents.send(channel, payload); };

// ---------------------------------------------------------------------------------------------------- hardening
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-navigate', (e) => e.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
});

const webPreferences = () => ({
  preload: path.join(__dirname, 'preload.js'),
  contextIsolation: true,
  sandbox: true,
  nodeIntegration: false,
  webSecurity: true,
  spellcheck: false,
});

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
function currentDescription() {
  return describe({ engineUp: state.engineUp, overview: state.overview, busy: state.busy > 0 });
}

function refreshMood() {
  let mood = currentDescription().mood;
  if (mood !== 'offline' && mood !== 'thinking') {
    if (Date.now() < happyUntil) mood = 'happy';
    else if (state.bubbleVisible) mood = 'alert';
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
    ...PANEL, show: false, frame: false, transparent: true, resizable: false, hasShadow: true, alwaysOnTop: true,
    skipTaskbar: true, fullscreenable: false, webPreferences: webPreferences(),
  });
  panelWin.setAlwaysOnTop(true, 'floating');
  panelWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  protect(panelWin);
  panelWin.loadFile(path.join(__dirname, 'renderer', 'panel.html'));
  panelWin.on('closed', () => { panelWin = null; state.panelOpen = false; });
}

function positionPanel() {
  if (!alive(panelWin)) return;
  const wa = nearestWorkArea({ x: icon.x + ICON / 2, y: icon.y + ICON / 2 });
  panelWin.setBounds(panelBounds({ icon, size: ICON, workArea: wa, panel: PANEL }));
}

function prettyHotkey(accel) {
  const parts = accel.split('+').map((p) => (p === 'CommandOrControl' ? (isMac ? '⌘' : 'Ctrl') : p === 'Shift' ? (isMac ? '⇧' : 'Shift') : p === 'Space' ? 'Espaço' : p));
  return isMac ? parts.join('') : parts.join('+');
}

function panelState() {
  return {
    engineUp: state.engineUp,
    overview: state.overview,
    busy: state.busy > 0,
    describe: currentDescription(),
    notices: state.notices.slice(-20),
    settings: { protect: settings.protect, masked: settings.masked, bubbleSide: settings.bubbleSide },
    hotkeys: { toggle: prettyHotkey(HOTKEYS.toggle), panic: prettyHotkey(HOTKEYS.panic) },
  };
}

function sendPanelState() { sendTo(panelWin, 'panel:state', panelState()); refreshMood(); }

function openPanel() {
  if (state.hidden) setHidden(false);
  if (!alive(panelWin)) createPanel();
  hideBubble();
  state.panelOpen = true;
  positionPanel();
  panelWin.show();
  panelWin.focus();
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
async function refreshOverview() {
  try {
    state.overview = await engine.overview();
    state.engineUp = true;
  } catch {
    state.engineUp = false;
  }
  sendPanelState();
}

async function healthLoop() {
  let wasUp = null;
  while (!quitting) {
    const up = await engine.health();
    state.engineUp = up;
    if (up && wasUp !== true) await refreshOverview();
    if (!up && wasUp !== false && !state.warnedDown) {
      localNotice(wasUp === null ? 'O motor do lite-agent não está rodando. Inicie-o e eu volto sozinho.' : 'Perdi a conexão com o motor do lite-agent.');
      state.warnedDown = true;
    }
    if (up) state.warnedDown = false;
    if (wasUp !== up) { refreshMood(); sendPanelState(); }
    wasUp = up;
    await sleep(5000);
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
        state.overview = await engine.overview();
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

function startEngineIfAsked() {
  if (process.env.LITEAGENT_DESKTOP_SPAWN !== '1') return;
  const root = path.resolve(__dirname, '..', '..');
  if (!fs.existsSync(path.join(root, 'pyproject.toml'))) return;
  engineProcess = spawn('uv', ['run', 'python', '-m', 'liteagent.main'], { cwd: root, stdio: 'ignore' });
  engineProcess.on('error', () => { engineProcess = null; });
}

// ---------------------------------------------------------------------------------------------------- tray and shortcuts
function buildMenu() {
  return Menu.buildFromTemplate([
    { label: state.panelOpen ? 'Fechar painel' : 'Abrir painel', click: togglePanel },
    { label: state.hidden ? 'Mostrar o robô' : 'Ocultar tudo agora', click: () => setHidden(!state.hidden) },
    { type: 'separator' },
    { label: 'Esconder do compartilhamento de tela', type: 'checkbox', checked: settings.protect, click: (i) => updateSetting('protect', i.checked) },
    { label: 'Modo discreto (sem nomes nos avisos)', type: 'checkbox', checked: settings.masked, click: (i) => updateSetting('masked', i.checked) },
    { type: 'separator' },
    { label: 'Sair', click: () => app.quit() },
  ]);
}

function rebuildMenu() { if (tray) tray.setContextMenu(buildMenu()); }

function createTray() {
  const image = nativeImage.createFromBuffer(robotPng({ size: 32, template: isMac }), { scaleFactor: 2 });
  if (isMac) image.setTemplateImage(true);
  tray = new Tray(image);
  tray.setToolTip('Robô assistente');
  rebuildMenu();
}

function registerShortcuts() {
  const ok = [globalShortcut.register(HOTKEYS.toggle, togglePanel), globalShortcut.register(HOTKEYS.panic, () => setHidden(!state.hidden))];
  if (ok.includes(false)) console.warn('Some global shortcuts could not be registered (another app may be using them).');
}

// ---------------------------------------------------------------------------------------------------- settings
function updateSetting(key, value) {
  if (key === 'protect' && typeof value === 'boolean') settings.protect = value;
  else if (key === 'masked' && typeof value === 'boolean') settings.masked = value;
  else if (key === 'bubbleSide' && settingsLib.SIDES.includes(value)) settings.bubbleSide = value;
  else return false;
  settingsLib.save(settingsFile, settings);
  protect(widgetWin);
  protect(panelWin);
  applyLayout();
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
  ipcMain.on('widget:ready', () => { applyLayout(); sendTo(widgetWin, 'widget:mood', currentDescription().mood); });
  ipcMain.on('widget:hover', (_e, inside) => { if (!isLinux && alive(widgetWin)) widgetWin.setIgnoreMouseEvents(!inside, { forward: true }); });
  ipcMain.on('widget:drag-start', () => { dragStart = { ...icon }; });
  ipcMain.on('widget:drag-move', (_e, d) => {
    if (!dragStart || !d || !isNum(d.dx) || !isNum(d.dy)) return;
    icon = { x: Math.round(dragStart.x + d.dx), y: Math.round(dragStart.y + d.dy) };
    applyLayout();
  });
  ipcMain.on('widget:drag-end', (_e, moved) => {
    dragStart = null;
    if (moved === true) { settings.icon = { ...icon }; settingsLib.save(settingsFile, settings); }
  });
  ipcMain.on('widget:toggle', togglePanel);
  ipcMain.on('widget:bubble-click', openPanel);
  ipcMain.on('widget:menu', () => buildMenu().popup({ window: widgetWin }));

  ipcMain.on('panel:ready', sendPanelState);
  ipcMain.on('panel:close', closePanel);
  ipcMain.on('panel:refresh', refreshOverview);
  ipcMain.on('panel:panic', () => setHidden(true));
  ipcMain.on('panel:cancel', (_e, id) => { const ac = streams.get(id); if (ac) ac.abort(); });

  ipcMain.handle('panel:set-setting', (_e, payload) => (payload && updateSetting(payload.key, payload.value) ? { ok: true } : { ok: false }));

  ipcMain.handle('panel:send', async (_e, text) => {
    if (typeof text !== 'string' || !text.trim() || text.length > MAX_TEXT) return { error: 'Pedido inválido.' };
    if (!state.engineUp) return { error: 'O motor não está rodando. Inicie o lite-agent.' };
    const id = crypto.randomUUID();
    const ac = new AbortController();
    streams.set(id, ac);
    state.busy += 1;
    sendPanelState();
    (async () => {
      let failed = false;
      try {
        for await (const event of engine.streamMessage(text, ac.signal)) sendTo(panelWin, 'panel:message', { id, event });
      } catch (e) {
        failed = true;
        sendTo(panelWin, 'panel:message', { id, event: { type: 'error', error: friendlyError(e) } });
      } finally {
        sendTo(panelWin, 'panel:message', { id, event: { type: 'end' } });
        streams.delete(id);
        state.busy -= 1;
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

async function runSnapshots() {
  const out = SNAPSHOT === '1' ? path.join(app.getPath('temp'), 'liteagent-desktop-snapshots') : SNAPSHOT;
  fs.mkdirSync(out, { recursive: true });
  settings = { ...settingsLib.DEFAULTS, protect: false };
  engine = { overview: async () => SAMPLE_OVERVIEW };
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

  nativeTheme.themeSource = 'dark';
  await shot('panel-dark.png', panelWin);
  nativeTheme.themeSource = 'light';

  settings.masked = true;
  sendPanelState();
  await shot('panel-masked.png', panelWin);
  settings.masked = false;

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

    settingsFile = path.join(app.getPath('userData'), 'settings.json');
    settings = settingsLib.load(settingsFile);
    engine = new EngineClient({ baseUrl: settings.engineUrl });
    icon = settings.icon || defaultIcon();

    startEngineIfAsked();
    createWidget();
    await new Promise((resolve) => ipcMain.once('widget:ready', resolve));
    widgetWin.showInactive();
    createTray();
    registerShortcuts();
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
