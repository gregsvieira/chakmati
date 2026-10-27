'use strict';
// Locks the windows down (no navigation, no new windows, permissions denied) and builds their webPreferences.
const { app } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const ctx = require('./context');

app.on('web-contents-created', (_event, contents) => {
  contents.on('will-navigate', (e) => e.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  // Everything is denied except the microphone, and only for the panel and only while "Ouvir e falar" is on.
  const micAllowed = (wc, permission, details) => permission === 'media' && !!ctx.settings && ctx.settings.talk === true
    && !!wc && wc.getURL().endsWith('panel.html') && (!details || !details.mediaTypes || details.mediaTypes.every((t) => t === 'audio'));
  contents.session.setPermissionRequestHandler((wc, permission, callback, details) => callback(micAllowed(wc, permission, details)));
  contents.session.setPermissionCheckHandler((wc, permission, _origin, details) => micAllowed(wc, permission, details));
});

const webPreferences = () => ({
  preload: path.join(__dirname, '..', 'preload.js'),
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

Object.assign(module.exports, { webPreferences, traceWindow });
