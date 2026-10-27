'use strict';
// The start of the app: single instance, the install wizard or the floating robot, the loops that keep it alive.
const path = require('node:path');
const { app, ipcMain, screen, globalShortcut } = require('electron');
const { EngineClient } = require('../features/engine').client;
const settingsLib = require('../features/settings').settings;
const { openSetup } = require('../features/installer');
const { needsSetup } = require('../features/installer').firstRun;
const ctx = require('../shared/context');
const { NoticeQueue } = require('../features/notices').queue;
const { SNAPSHOT, PROTECT_TEST, SETUP, isMac } = require('../shared/constants');
const { alive } = require('../shared/util');
const { webPreferences } = require('../shared/web-preferences');
const widgetWindow = require('../features/widget').window;
const panelWindow = require('../features/panel').window;
const engineService = require('../features/engine').service;
const trayMenu = require('../features/tray').menu;
const voiceService = require('../features/voice').service;
const ipc = require('./ipc');
const snapshots = require('./snapshots');

ctx.queue = new NoticeQueue();

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(async () => {
    if (isMac) { app.dock?.hide(); app.setActivationPolicy?.('accessory'); }
    ipc.registerIpc();
    if (SNAPSHOT) { await snapshots.runSnapshots(); return; }
    if (PROTECT_TEST) { await snapshots.runProtectTest(); return; }
    const firstRun = needsSetup({ packaged: app.isPackaged, dataDir: app.getPath('userData'), platform: process.platform });
    if (SETUP || firstRun) { // the install wizard: --setup, or the first run of an installed app; the normal app starts after it
      ctx.settingsFile = path.join(app.getPath('userData'), 'settings.json');
      if (isMac) { app.setActivationPolicy?.('regular'); app.dock?.show(); }
      openSetup({
        ipcMain, webPreferences: webPreferences, settingsFile: ctx.settingsFile,
        engine: app.isPackaged ? { resourcesPath: process.resourcesPath, dataDir: app.getPath('userData') } : null,
        onClosed: () => app.quit(),
        onFinish: () => { app.relaunch({ args: process.argv.slice(1).filter((a) => a !== '--setup') }); app.exit(0); },
      });
      return;
    }

    ctx.settingsFile = path.join(app.getPath('userData'), 'settings.json');
    ctx.settings = settingsLib.load(ctx.settingsFile);
    ctx.engine = new EngineClient({ baseUrl: ctx.settings.engineUrl });
    ctx.icon = ctx.settings.icon || widgetWindow.defaultIcon();

    widgetWindow.createWidget();
    await new Promise((resolve) => ipcMain.once('widget:ready', resolve));
    ctx.widgetWin.showInactive();
    if (ctx.settings.talk) panelWindow.createPanel(); // keep the microphone listening even with the panel closed
    trayMenu.createTray();
    trayMenu.registerShortcuts();
    if (!(await ctx.engine.health())) await engineService.startEngine();
    await voiceService.refreshVoiceStatus();
    if (ctx.settings.enhancedVoice && ctx.state.voice && !ctx.state.voice.installed) voiceService.downloadVoice(); // chosen (and approved) in the setup wizard; a failure turns it off again
    engineService.healthLoop();
    engineService.noticeLoop();
    screen.on('display-metrics-changed', widgetWindow.applyLayout);
    screen.on('display-removed', widgetWindow.applyLayout);
  });

  app.on('second-instance', () => { if (alive(ctx.widgetWin)) panelWindow.openPanel(); });
  app.on('window-all-closed', () => { /* a tray app: closing a window does not quit */ });
  app.on('before-quit', () => {
    ctx.quitting = true;
    globalShortcut.unregisterAll();
    for (const ac of ctx.streams.values()) ac.abort();
    if (ctx.engineProcess) ctx.engineProcess.kill();
  });
}

