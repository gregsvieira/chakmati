'use strict';
// The public API of the widget feature: what the rest of the app may require. Everything else in this folder is private to it.
// (Getters, so the parts that need each other at run time never meet half-loaded.)
module.exports = {
  get bell() { return require('./bell'); },
  get ipc() { return require('./ipc'); },
  get mood() { return require('./mood'); },
  get placement() { return require('./placement'); },
  get window() { return require('./window'); },
};
