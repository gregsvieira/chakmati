'use strict';
// The public API of the notices feature: what the rest of the app may require. Everything else in this folder is private to it.
// (Getters, so the parts that need each other at run time never meet half-loaded.)
module.exports = {
  get brief() { return require('./brief'); },
  get greetings() { return require('./greetings'); },
  get queue() { return require('./queue'); },
};
