'use strict';
// What the person is told when the engine refuses or cannot be reached.
const { EngineError } = require('./client');

function friendlyError(e) {
  if (e instanceof EngineError) {
    if (e.status === 410) return 'A proposta expirou. Peça de novo.';
    if (e.status === 409) return 'Esta ação já foi decidida.';
    if (e.status === 403) return 'O motor recusou o pedido.';
    return e.message;
  }
  return e && e.name === 'AbortError' ? 'Cancelado.' : 'Não consegui falar com o motor.';
}

module.exports = { friendlyError };
