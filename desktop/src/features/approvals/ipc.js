'use strict';
// IPC of approvals and automations: approve, reject, enable, delete, preview, record.
const { ipcMain } = require('electron');
const ctx = require('../../shared/context');
const { isId } = require('../../shared/util');
const { friendlyError } = require('../engine').errors;
const engineService = require('../engine').service;

function register() {
  const decide = (verb) => async (_e, id) => {
      if (!isId(id)) return { ok: false, error: 'Pedido inválido.' };
      try {
        const action = await ctx.engine[verb](id);
        engineService.refreshOverview();
        if (action.status === 'failed') return { ok: false, error: action.error || 'Não foi possível concluir.' };
        return { ok: true, text: verb === 'approve' ? action.result || 'Feito.' : 'Recusado.' };
      } catch (e) {
        engineService.refreshOverview();
        return { ok: false, error: friendlyError(e) };
      }
    };

  ipcMain.handle('panel:automation', async (_e, id, op) => {
      if (!isId(id) || !['enable', 'disable', 'delete'].includes(op)) return { ok: false, error: 'Pedido inválido.' };
      try { await ctx.engine.setAutomation(id, op); engineService.refreshOverview(); return { ok: true }; } catch (e) { return { ok: false, error: friendlyError(e) }; }
    });

  ipcMain.handle('panel:preview', async (_e, id) => {
      if (!isId(id)) return { error: 'Pedido inválido.' };
      try { const a = await ctx.engine.preview(id); return { dataUrl: `data:${a.mime};base64,${a.base64}` }; } catch (e) { return { error: friendlyError(e) }; }
    });

  ipcMain.handle('panel:propose-recorded', async (_e, bytes, hours) => {
      if (!(bytes instanceof Uint8Array) || !bytes.length) return { error: 'Gravação inválida.' };
      const when = hours && typeof hours === 'object' && typeof hours.from === 'string' && typeof hours.to === 'string' ? { from: hours.from, to: hours.to } : null;
      try { const action = await ctx.engine.proposeRecorded(bytes, when); engineService.refreshOverview(); return { action }; } catch (e) { return { error: friendlyError(e) }; }
    });

  ipcMain.handle('panel:approve', decide('approve'));

  ipcMain.handle('panel:reject', decide('reject'));
}

Object.assign(module.exports, { register });
