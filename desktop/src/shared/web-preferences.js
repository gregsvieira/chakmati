'use strict';
// How every window is created (isolated, sandboxed, no Node) and the debugging trace of its size and place.
const fs = require('node:fs');
const path = require('node:path');
const { app } = require('electron');

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

module.exports = { webPreferences, traceWindow };
