'use strict';
// The only bridge between the windows and the app. The windows have no Node and no network; they can call exactly these
// functions, and each one is validated again in the main process.
const { contextBridge, ipcRenderer } = require('electron');

const listen = (channel, cb) => {
  const handler = (_event, payload) => cb(payload);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
};
const send = (channel, payload) => ipcRenderer.send(channel, payload);

contextBridge.exposeInMainWorld('assistant', {
  widget: {
    onLayout: (cb) => listen('widget:layout', cb),
    onBubble: (cb) => listen('widget:bubble', cb),
    onMood: (cb) => listen('widget:mood', cb),
    onStill: (cb) => listen('widget:still', cb),
    onBackdrop: (cb) => listen('widget:backdrop', cb),
    ready: () => send('widget:ready'),
    hover: (inside) => send('widget:hover', !!inside),
    dragStart: () => send('widget:drag-start'),
    dragMove: (dx, dy) => send('widget:drag-move', { dx, dy }),
    dragEnd: (moved) => send('widget:drag-end', !!moved),
    toggle: () => send('widget:toggle'),
    bubbleClick: () => send('widget:bubble-click'),
    menu: () => send('widget:menu'),
  },
  panel: {
    onState: (cb) => listen('panel:state', cb),
    onMessage: (cb) => listen('panel:message', cb),
    ready: () => send('panel:ready'),
    close: () => send('panel:close'),
    refresh: () => send('panel:refresh'),
    panic: () => send('panel:panic'),
    restart: () => send('panel:restart'),
    openWa: () => ipcRenderer.invoke('panel:openwa'),
    chats: () => ipcRenderer.invoke('panel:chats'),
    messages: (chatId) => ipcRenderer.invoke('panel:messages', chatId),
    audio: (chatId, messageId) => ipcRenderer.invoke('panel:audio', chatId, messageId),
    send: (text) => ipcRenderer.invoke('panel:send', text),
    cancel: (id) => send('panel:cancel', id),
    approve: (id) => ipcRenderer.invoke('panel:approve', id),
    reject: (id) => ipcRenderer.invoke('panel:reject', id),
    setSetting: (key, value) => ipcRenderer.invoke('panel:set-setting', { key, value }),
  },
});
