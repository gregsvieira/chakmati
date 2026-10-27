'use strict';
// Small helpers every part of the main process uses.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const alive = (w) => w && !w.isDestroyed();

const sendTo = (w, channel, payload) => { if (alive(w) && !w.webContents.isDestroyed()) w.webContents.send(channel, payload); };

const isId = (v) => typeof v === 'string' && /^[0-9a-f]{32}$/.test(v);

const isNum = (v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) < 1e5;



Object.assign(module.exports, { sleep, alive, sendTo, isId, isNum });
