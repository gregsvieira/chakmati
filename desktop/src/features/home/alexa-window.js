'use strict';
// The sign-in to Amazon, in a small window of the app itself (not the browser). The page is the one Home Assistant serves on this computer
// (a proxy of Amazon's sign-in page: Amazon may ask for a captcha or a code there). The window is locked to that address: it cannot go anywhere else,
// open other windows, ask for permissions, or keep anything (its storage lives only in memory and goes away when it closes).
const { BrowserWindow } = require('electron');
const { isLocalHttpUrl } = require('./lan');

function openLoginWindow(url, { parent = null, onClosed = () => {} } = {}) {
  const origin = new URL(url).origin;
  const win = new BrowserWindow({
    width: 520, height: 780, title: 'Entrar na Amazon', autoHideMenuBar: true, parent: parent || undefined, show: false,
    webPreferences: { partition: `alexa-login-${Date.now()}`, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, spellcheck: false },
  });
  win.removeMenu?.();
  const ses = win.webContents.session;
  ses.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  const stay = (event, target) => { if (!isLocalHttpUrl(target) || new URL(target).origin !== origin) event.preventDefault(); };
  win.webContents.on('will-navigate', stay);
  win.webContents.on('will-redirect', stay);
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => { ses.clearStorageData().catch(() => {}); onClosed(); });
  win.loadURL(url);
  return win;
}

module.exports = { openLoginWindow };
