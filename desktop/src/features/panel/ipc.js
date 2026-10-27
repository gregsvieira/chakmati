'use strict';
// IPC of the panel: messages, Parar, replies, links and settings.
const { ipcMain, shell } = require('electron');
const { brief } = require('../notices').brief;
const links = require('./links');
const crypto = require('node:crypto');
const ctx = require('../../shared/context');
const { MAX_TEXT } = require('../../shared/constants');
const { sendTo } = require('../../shared/util');
const { friendlyError } = require('../engine').errors;
const panelWindow = require('./window');
const widgetMood = require('../widget').mood;
const engineService = require('../engine').service;
const trayMenu = require('../tray').menu;
const settingsService = require('../settings').service;

function register() {
  ipcMain.on('panel:ready', panelWindow.sendPanelState);

  ipcMain.on('panel:close', panelWindow.closePanel);

  ipcMain.on('panel:layout', (_e, mode) => panelWindow.setPanelMode(mode));

    // With the panel closed, what Chakmati answers appears the way notices do: a bubble by the character (and spoken, if on).
    ipcMain.on('panel:reply', (_e, p) => {
      if (ctx.state.panelOpen || ctx.state.hidden || !p || typeof p.text !== 'string' || !p.text.trim()) return;
      const text = brief(p.text); // at most two lines
      if (!text) return;
      widgetMood.pushNotice({ id: -Date.now(), kind: 'reply', text, masked: 'O Chakmati respondeu.', ts: Date.now() / 1000, key: `reply:${Date.now()}` });
    });

    // A link icon in a message: opened in the person's own browser, only http(s) and only what was in the conversation's text
    ipcMain.on('panel:open-link', (_e, url) => { const safe = links.safeLink(url); if (safe) shell.openExternal(safe); });

  ipcMain.on('panel:refresh', engineService.refreshOverview);

  ipcMain.on('panel:panic', () => panelWindow.setHidden(true));

  ipcMain.on('panel:restart', trayMenu.restartApp);

    // Parar: a job (browser, files) is stopped in the engine and its own stream says so; a plain answer is simply no longer waited for.
    ipcMain.on('panel:cancel', async (_e, id) => {
      const ac = ctx.streams.get(id);
      if (!ac) return;
      ctx.stopped.add(id);
      const jobId = ctx.jobOf.get(id);
      if (jobId) { try { await ctx.engine.cancelJob(jobId); return; } catch { /* the engine could not be asked: stop waiting for it instead */ } }
      ac.abort();
    });

  ipcMain.handle('panel:set-setting', (_e, payload) => (payload && settingsService.updateSetting(payload.key, payload.value) ? { ok: true } : { ok: false }));

  ipcMain.handle('panel:input', async (_e, jobId, requestId, value) => {
    try { return await ctx.engine.sendInput(jobId, requestId, value); } catch { return { ok: false, error: 'Não consegui enviar a resposta. Tente de novo.' }; }
  });

  ipcMain.handle('panel:send', async (_e, text) => {
      if (typeof text !== 'string' || !text.trim() || text.length > MAX_TEXT) return { error: 'Pedido inválido.' };
      if (!ctx.state.engineUp) return { error: 'O motor não está rodando. Inicie o Chakmati.' };
      // a command arrived: the microphone stops waiting for one (the wake phrase itself starts the wait again once answered)
      ctx.state.awakeUntil = 0;
      widgetMood.syncListening();
      const id = crypto.randomUUID();
      const ac = new AbortController();
      ctx.streams.set(id, ac);
      let timedOut = false;
      const timeout = setTimeout(() => { timedOut = true; ac.abort(); }, 4 * 60 * 1000); // an answer that never ends must not block everything else
      ctx.state.busy += 1;
      panelWindow.sendPanelState();
      (async () => {
        let failed = false;
        try {
          for await (const event of ctx.engine.streamMessage(text, ac.signal)) {
            if (event.type === 'job' && event.job_id) ctx.jobOf.set(id, event.job_id);
            if (event.type === 'input') { ctx.state.asking = true; widgetMood.syncBell(); widgetMood.refreshMood(); } else if (event.type === 'input_done') { ctx.state.asking = false; widgetMood.syncBell(); widgetMood.refreshMood(); }
            sendTo(ctx.panelWin, 'panel:message', { id, event });
          }
        } catch (e) {
          failed = !ctx.stopped.has(id);
          if (ctx.stopped.has(id)) sendTo(ctx.panelWin, 'panel:message', { id, event: { type: 'cancelled', text: 'Interrompido por você.' } });
          else sendTo(ctx.panelWin, 'panel:message', { id, event: { type: 'error', error: timedOut ? 'Demorei demais e parei de esperar. Pode pedir de novo.' : friendlyError(e) } });
        } finally {
          if (ctx.state.asking) { ctx.state.asking = false; widgetMood.syncBell(); widgetMood.refreshMood(); }
          sendTo(ctx.panelWin, 'panel:message', { id, event: { type: 'end' } });
          clearTimeout(timeout);
          ctx.streams.delete(id);
          ctx.jobOf.delete(id);
          ctx.stopped.delete(id);
          ctx.state.busy = Math.max(0, ctx.state.busy - 1);
          if (!failed) ctx.happyUntil = Date.now() + 3000;
          clearTimeout(ctx.moodTimer);
          ctx.moodTimer = setTimeout(widgetMood.refreshMood, 3100);
          engineService.refreshOverview();
        }
      })();
      return { id };
    });

    // A line that changes every second (the countdown) shown by the character with the panel closed. Never spoken, never queued.
    ipcMain.on('panel:live', (_e, text) => {
      if (ctx.state.panelOpen || ctx.state.hidden) return;
      clearTimeout(ctx.bubbleTimer);
      if (typeof text !== 'string' || !text.trim()) { widgetMood.nextBubble(); return; }
      ctx.state.bubbleVisible = true;
      sendTo(ctx.widgetWin, 'widget:bubble', { text: text.slice(0, 140), kind: 'system', id: -1, silent: true });
      widgetMood.refreshMood();
      ctx.bubbleTimer = setTimeout(widgetMood.nextBubble, 3000);
    });
}

Object.assign(module.exports, { register });
