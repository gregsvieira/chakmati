'use strict';
// Registers every feature's IPC handlers. Every input is validated by the handler that receives it.
const widgetIpc = require('../features/widget').ipc;
const panelIpc = require('../features/panel').ipc;
const whatsappIpc = require('../features/whatsapp').ipc;
const homeIpc = require('../features/home').ipc;
const cloudIpc = require('../features/cloud').ipc;
const voiceIpc = require('../features/voice').ipc;
const approvalsIpc = require('../features/approvals').ipc;

function registerIpc() {
  widgetIpc.register();
  panelIpc.register();
  whatsappIpc.register();
  homeIpc.register();
  cloudIpc.register();
  voiceIpc.register();
  approvalsIpc.register();
}

module.exports = { registerIpc };
