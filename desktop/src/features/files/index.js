'use strict';
// The public API of the files feature: what the rest of the app may require. Everything else in this folder is private to it.
module.exports = {
  get ipc() { return require('./ipc'); },
  get logic() { return require('./attach-logic'); },
};
