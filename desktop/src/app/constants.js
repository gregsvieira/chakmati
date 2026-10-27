'use strict';
// Sizes, shortcuts and the switches read from the environment.
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

module.exports = { ICON, BUBBLE, PANEL, HOTKEYS, MAX_TEXT, SNAPSHOT, PROTECT_TEST, SETUP, isMac, isLinux };
