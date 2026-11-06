'use strict';
// The public API of the home feature (connecting to Home Assistant, which is how the Alexa is reached): what the rest of the app may require.
// (Getters, so the parts that need each other at run time never meet half-loaded.)
module.exports = {
  get ipc() { return require('./ipc'); },
  get lan() { return require('./lan'); },
};
