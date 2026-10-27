'use strict';
// The menu-bar / tray icon, its menu, the global shortcuts and restarting the app.
const { app, Tray, Menu, globalShortcut, nativeImage } = require('electron');
const { robotPng } = require('./icon');
const ctx = require('../../shared/context');
const { isMac, HOTKEYS } = require('../../shared/constants');
const panelWindow = require('../panel').window;
const settingsService = require('../settings').service;

// Quits and starts again (the engine started by the app is stopped and started with it).
function restartApp() {
  app.relaunch();
  app.quit();
}

function buildMenu() {
  return Menu.buildFromTemplate([
    { label: ctx.state.panelOpen ? 'Fechar painel' : 'Abrir painel', click: panelWindow.togglePanel },
    { label: ctx.state.hidden ? 'Mostrar o Chakmati' : 'Ocultar tudo agora', click: () => panelWindow.setHidden(!ctx.state.hidden) },
    { type: 'separator' },
    { label: 'Esconder do compartilhamento de tela', type: 'checkbox', checked: ctx.settings.protect, click: (i) => settingsService.updateSetting('protect', i.checked) },
    { label: 'Modo discreto (sem nomes nos avisos)', type: 'checkbox', checked: ctx.settings.masked, click: (i) => settingsService.updateSetting('masked', i.checked) },
    { type: 'separator' },
    { label: 'Reiniciar o Chakmati', click: restartApp },
    { label: 'Sair', click: () => app.quit() },
  ]);
}

function rebuildMenu() { if (ctx.tray) ctx.tray.setContextMenu(buildMenu()); }

function createTray() {
  const image = nativeImage.createFromBuffer(robotPng({ size: 32, template: isMac }), { scaleFactor: 2 });
  if (isMac) image.setTemplateImage(true);
  ctx.tray = new Tray(image);
  ctx.tray.setToolTip('Chakmati');
  rebuildMenu();
}

function registerShortcuts() {
  const ok = [globalShortcut.register(HOTKEYS.toggle, panelWindow.togglePanel), globalShortcut.register(HOTKEYS.panic, () => panelWindow.setHidden(!ctx.state.hidden))];
  if (ok.includes(false)) console.warn('Some global shortcuts could not be registered (another app may be using them).');
}

Object.assign(module.exports, { rebuildMenu, buildMenu, restartApp, createTray, registerShortcuts });
