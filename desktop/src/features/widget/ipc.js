'use strict';
// IPC of the floating robot (drag, hover, bubble, menu).
const { ipcMain } = require('electron');
const ctx = require('../../app/context');
const { isLinux } = require('../../app/constants');
const { sendTo, alive, isNum } = require('../../app/util');
const widgetWindow = require('./window');
const widgetMood = require('./mood');
const voiceService = require('../voice/service');
const settingsService = require('../settings/service');
const panelWindow = require('../panel/window');
const trayMenu = require('../../app/tray');

function register() {
    // The floating widget reads notices aloud; tell the panel's microphone so it does not hear (and transcribe) them.
    ipcMain.on('widget:speaking', (_e, on) => sendTo(ctx.panelWin, 'panel:other-speaking', on === true));

  ipcMain.on('widget:ready', () => { widgetWindow.applyLayout(); widgetMood.refreshMood(); sendTo(ctx.widgetWin, 'widget:still', ctx.settings.still); voiceService.sendVoice(); ctx.listeningShown = null; widgetMood.syncListening(); ctx.bellShown = ''; widgetMood.syncBell(); });

  ipcMain.on('widget:hover', (_e, inside) => { if (!isLinux && alive(ctx.widgetWin)) ctx.widgetWin.setIgnoreMouseEvents(!inside, { forward: true }); });

  ipcMain.on('widget:drag-start', () => { ctx.dragStart = { ...ctx.icon }; });

  ipcMain.on('widget:drag-move', (_e, d) => {
      if (!ctx.dragStart || !d || !isNum(d.dx) || !isNum(d.dy)) return;
      ctx.icon = { x: Math.round(ctx.dragStart.x + d.dx), y: Math.round(ctx.dragStart.y + d.dy) };
      widgetWindow.applyLayout();
    });

  ipcMain.on('widget:drag-end', (_e, moved) => {
      ctx.dragStart = null;
      if (moved === true) { ctx.settings.icon = { ...ctx.icon }; settingsService.persistSettings(); }
    });

  ipcMain.on('widget:toggle', panelWindow.togglePanel);

  ipcMain.on('widget:bubble-click', panelWindow.openPanel);

  ipcMain.on('widget:menu', () => trayMenu.buildMenu().popup({ window: ctx.widgetWin }));
}

Object.assign(module.exports, { register });
