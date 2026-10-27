'use strict';
// The public API of the whatsapp feature: what the rest of the app may require. Everything else in this folder is private to it.
// (Getters, so the parts that need each other at run time never meet half-loaded.)
module.exports = {
  get ipc() { return require('./ipc'); },
};
