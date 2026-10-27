'use strict';
// Small helpers every part of the main process uses.
const { EngineError } = require('../features/engine/client');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const alive = (w) => w && !w.isDestroyed();

const sendTo = (w, channel, payload) => { if (alive(w) && !w.webContents.isDestroyed()) w.webContents.send(channel, payload); };

const isId = (v) => typeof v === 'string' && /^[0-9a-f]{32}$/.test(v);

const isNum = (v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) < 1e5;

function friendlyError(e) {
  if (e instanceof EngineError) {
    if (e.status === 410) return 'A proposta expirou. Peça de novo.';
    if (e.status === 409) return 'Esta ação já foi decidida.';
    if (e.status === 403) return 'O motor recusou o pedido.';
    return e.message;
  }
  return e && e.name === 'AbortError' ? 'Cancelado.' : 'Não consegui falar com o motor.';
}


Object.assign(module.exports, { sleep, alive, sendTo, isId, isNum, friendlyError });
