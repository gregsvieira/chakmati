'use strict';
// The floating robot window: where it sits and how it is laid out.
const { BrowserWindow, screen } = require('electron');
const path = require('node:path');
const { chooseSide, layoutWidget, clampIcon } = require('./placement');
const ctx = require('../../app/context');
const { ICON, isLinux, BUBBLE } = require('../../app/constants');
const { alive, sendTo } = require('../../app/util');
const hardening = require('../../app/hardening');
const panelWindow = require('../panel/window');

function nearestWorkArea(point) { return screen.getDisplayNearestPoint(point).workArea; }

function defaultIcon() {
  const wa = screen.getPrimaryDisplay().workArea;
  return { x: wa.x + wa.width - ICON - 28, y: wa.y + wa.height - ICON - 28 };
}

function protect(win) {
  if (alive(win)) win.setContentProtection(!!ctx.settings.protect); // best effort: honoured by Windows and by some macOS capture paths
}

function createWidget() {
  ctx.widgetWin = new BrowserWindow({
    width: ICON, height: ICON, show: false, frame: false, transparent: true, resizable: false, movable: false,
    hasShadow: false, alwaysOnTop: true, skipTaskbar: true, focusable: false, fullscreenable: false, webPreferences: hardening.webPreferences(),
  });
  ctx.widgetWin.setAlwaysOnTop(true, 'screen-saver');
  ctx.widgetWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  if (!isLinux) ctx.widgetWin.setIgnoreMouseEvents(true, { forward: true });
  protect(ctx.widgetWin);
  hardening.traceWindow('robô', ctx.widgetWin);
  ctx.widgetWin.loadFile(path.join(__dirname, 'renderer', 'widget.html'));
  ctx.widgetWin.on('closed', () => { ctx.widgetWin = null; });
}

function applyLayout() {
  if (!alive(ctx.widgetWin)) return;
  const wa = nearestWorkArea({ x: ctx.icon.x + ICON / 2, y: ctx.icon.y + ICON / 2 });
  ctx.icon = clampIcon(ctx.icon, ICON, wa);
  const side = chooseSide({ icon: ctx.icon, size: ICON, workArea: wa, bubble: BUBBLE, preference: ctx.settings.bubbleSide });
  ctx.layout = layoutWidget({ icon: ctx.icon, size: ICON, side, bubble: BUBBLE, workArea: wa });
  ctx.widgetWin.setBounds(ctx.layout.bounds);
  sendTo(ctx.widgetWin, 'widget:layout', ctx.layout);
  if (ctx.state.panelOpen) panelWindow.positionPanel();
}

Object.assign(module.exports, { protect, nearestWorkArea, applyLayout, createWidget, defaultIcon });
