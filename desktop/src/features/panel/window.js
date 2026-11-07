'use strict';
// The panel window (compact, wide, full), what it is told about the world, opening, closing and hiding everything.
const path = require('node:path');
const { BrowserWindow } = require('electron');
const { panelBounds, expandedBounds, MIN_WIDE } = require('../widget').placement;
const { moodWithBell } = require('../widget').bell;
const ctx = require('../../shared/context');
const { PANEL, isMac, ICON, HOTKEYS } = require('../../shared/constants');
const { alive, sendTo } = require('../../shared/util');
const { webPreferences, traceWindow } = require('../../shared/web-preferences');
const widgetWindow = require('../widget').window;
const widgetMood = require('../widget').mood;
const engineService = require('../engine').service;
const trayMenu = require('../tray').menu;

let panelTimer = null;

function createPanel() {
  ctx.panelWin = new BrowserWindow({
    width: PANEL.w, height: PANEL.h, show: false, frame: false, transparent: true, resizable: false, hasShadow: true, alwaysOnTop: true,
    skipTaskbar: true, fullscreenable: false,
    ...(isMac ? { ...(ctx.settings.glass ? { vibrancy: 'under-window', visualEffectState: 'active' } : {}), backgroundColor: '#00000000' } : {}), // macOS: the real blur of what is behind the glass (only with the glass on)
    webPreferences: { ...webPreferences(), backgroundThrottling: false }, // a hidden panel must keep listening at full speed
  });
  ctx.panelWin.setAlwaysOnTop(true, 'floating');
  ctx.panelWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  widgetWindow.protect(ctx.panelWin);
  traceWindow('painel', ctx.panelWin);
  ctx.panelWin.loadFile(path.join(__dirname, 'renderer', 'panel.html'));
  ctx.panelWin.on('closed', () => { ctx.panelWin = null; ctx.state.panelOpen = false; });
}

// The glass switched on or off while the panel exists: the native blur of macOS goes with it (the page flattens itself from the setting).
function applyGlass() {
  if (isMac && alive(ctx.panelWin)) ctx.panelWin.setVibrancy(ctx.settings.glass ? 'under-window' : null);
}

function positionPanel() {
  if (!alive(ctx.panelWin)) return;
  const wa = widgetWindow.nearestWorkArea({ x: ctx.icon.x + ICON / 2, y: ctx.icon.y + ICON / 2 });
  if (ctx.panelMode === 'compact') ctx.panelWin.setBounds(panelBounds({ icon: ctx.icon, size: ICON, workArea: wa, panel: PANEL }));
  else ctx.panelWin.setBounds(expandedBounds({ workArea: wa, mode: ctx.panelMode }));
}

// In the big window the character stands in the conversation (the page draws it), so the little one on the desktop steps aside.
function syncWidget() {
  if (!alive(ctx.widgetWin) || ctx.state.hidden) return;
  if (ctx.state.panelOpen && ctx.panelMode !== 'compact') ctx.widgetWin.hide(); else ctx.widgetWin.showInactive();
}

function setPanelMode(mode) {
  if (!['compact', 'wide', 'full'].includes(mode) || mode === ctx.panelMode) return;
  ctx.panelMode = mode;
  if (alive(ctx.panelWin)) {
    ctx.panelWin.setResizable(mode !== 'compact');
    ctx.panelWin.setMinimumSize(mode === 'compact' ? 0 : MIN_WIDE.w, mode === 'compact' ? 0 : MIN_WIDE.h);
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
    engineUp: ctx.state.engineUp,
    overview: widgetMood.overviewNow(),
    busy: ctx.state.busy > 0,
    describe: { ...widgetMood.currentDescription(), mood: ctx.settings.mood === 'auto' ? moodWithBell(widgetMood.currentDescription().mood, widgetMood.currentBell()) : widgetMood.effectiveMood(widgetMood.currentDescription().mood) },
    bell: widgetMood.currentBell(),
    notices: ctx.state.notices.slice(-20),
    settings: { protect: ctx.settings.protect, masked: ctx.settings.masked, autoSend: ctx.settings.autoSend, autoRunSafe: ctx.settings.autoRunSafe, hear: ctx.settings.hear, talk: ctx.settings.talk, enhancedVoice: ctx.settings.enhancedVoice, voiceSpeed: ctx.settings.voiceSpeed, speakEmojis: ctx.settings.speakEmojis, micSource: ctx.settings.micSource, still: ctx.settings.still, bubbleSide: ctx.settings.bubbleSide, mood: ctx.settings.mood, glass: ctx.settings.glass, home: ctx.settings.home, cloudProvider: ctx.settings.cloudProvider, cloudModel: ctx.settings.cloudModel, localModel: ctx.settings.localModel, personality: ctx.settings.personality, personalities: ctx.settings.personalities, pronouns: ctx.settings.pronouns, whatsapp: ctx.settings.whatsapp, calendar: ctx.settings.calendar, research: ctx.settings.research },
    homeNote: ctx.state.homeNote || '',
    voice: ctx.state.voice,
    ownsEngine: !!ctx.engineProcess,
    canOpenWa: !!engineService.projectRoot(),
    panelOpen: ctx.state.panelOpen,
    panelMode: ctx.panelMode,
    hotkeys: { toggle: prettyHotkey(HOTKEYS.toggle), panic: prettyHotkey(HOTKEYS.panic) },
  };
}

function sendPanelState() { sendTo(ctx.panelWin, 'panel:state', panelState()); widgetMood.refreshMood(); }

function openPanel() {
  if (ctx.state.hidden) setHidden(false);
  if (!alive(ctx.panelWin)) createPanel();
  widgetMood.hideBubble();
  ctx.state.panelOpen = true;
  ctx.state.unread = 0;  // opening the panel is seeing the news
  widgetMood.syncBell();
  widgetMood.refreshMood();
  positionPanel();
  ctx.panelWin.show();
  ctx.panelWin.focus();
  syncWidget();
  sendPanelState();
  engineService.refreshOverview();
  clearInterval(panelTimer);
  panelTimer = setInterval(engineService.refreshOverview, 15000);
  trayMenu.rebuildMenu();
}

function closePanel() {
  ctx.state.panelOpen = false;
  clearInterval(panelTimer);
  if (alive(ctx.panelWin)) ctx.panelWin.hide();
  syncWidget();
  sendPanelState(); // the panel window keeps running (and listening): it must know it is closed
  trayMenu.rebuildMenu();
}

const togglePanel = () => (ctx.state.panelOpen && alive(ctx.panelWin) && ctx.panelWin.isVisible() ? closePanel() : openPanel());

function setHidden(hidden) {
  ctx.state.hidden = hidden;
  if (hidden) {
    widgetMood.hideBubble();
    closePanel();
    if (alive(ctx.widgetWin)) ctx.widgetWin.hide();
  } else if (alive(ctx.widgetWin)) {
    ctx.widgetWin.showInactive();
  }
  trayMenu.rebuildMenu();
}

Object.assign(module.exports, { applyGlass, positionPanel, sendPanelState, togglePanel, setHidden, createPanel, openPanel, closePanel, setPanelMode });
