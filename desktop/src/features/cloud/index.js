'use strict';
// The paid AI in Ajustes: change the key or the model, or remove it. (Getters, so the parts never meet half-loaded.)
module.exports = {
  get ipc() { return require('./ipc'); },
};
