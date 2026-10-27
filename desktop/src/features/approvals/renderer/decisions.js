// Approvals on the panel: what waits for a decision, approving, rejecting, and the buttons on a message.

(function () {
  const P = window.Panel;
  const { $, decided, fill, api } = P;

  function renderDecisions() {
    const pending = (P.state.overview && P.state.overview.pending) || [];
    const ids = new Set(pending.map((p) => p.id));
    const shown = [...pending, ...[...decided.keys()].filter((id) => !ids.has(id)).map((id) => ({ id, summary: '', gone: true }))];
    $('decisions').hidden = shown.length === 0;
    fill($('decision-list'), shown.map((p) => {
      const result = decided.get(p.id);
      if (p.gone) return P.h('div', { class: 'decision' }, P.h('p', { class: `decision-result${result.error ? ' error' : ''}` }, result.text));
      const [first, ...rest] = (p.summary || '').split('\n');
      const buttons = [
        p.voice ? P.h('button', { class: 'ghost', type: 'button', onclick: (e) => P.previewVoice(p.id, e.currentTarget) }, 'Ouvir') : null,
        P.h('button', { class: 'ghost', type: 'button', disabled: !!result, onclick: () => decide(p.id, false) }, 'Recusar'),
        p.auto_ok ? P.h('button', { class: 'ghost', type: 'button', disabled: !!result, onclick: () => decide(p.id, true, true) }, 'Aprovar e manter aprovado') : null,
        P.h('button', { class: 'primary', type: 'button', disabled: !!result, onclick: () => decide(p.id, true) }, 'Aprovar'),
      ];
      return P.h('div', { class: 'decision' },
        P.h('p', { class: 'decision-title' }, first),
        rest.length ? P.h('p', { class: 'decision-body' }, rest.join('\n')) : null,
        result ? P.h('p', { class: `decision-result${result.error ? ' error' : ''}` }, result.text) : P.h('div', { class: 'decision-actions' }, buttons));
    }));
  }

  async function decide(id, approve, keep = false) {
    decided.set(id, { text: approve ? 'Executando…' : 'Recusando…' });
    renderDecisions();
    if (keep) await api.setSetting('autoRunSafe', true);
    const res = await (approve ? api.approve(id) : api.reject(id));
    if (res && res.ok) decided.set(id, { text: res.text });
    else decided.set(id, { text: (res && res.error) || 'Não foi possível concluir.', error: true });
    renderDecisions();
    setTimeout(() => { decided.delete(id); if (P.state) renderDecisions(); }, 5000);
  }

  async function decideTurn(turn, mode) {
    turn.decision = { text: mode === 'reject' ? 'Recusando…' : 'Executando…' };
    P.renderThread();
    if (mode === 'always') await api.setSetting('autoSend', true);
    if (mode === 'keep') await api.setSetting('autoRunSafe', true);
    const res = await (mode === 'reject' ? api.reject(turn.actionId) : api.approve(turn.actionId));
    turn.decision = res && res.ok ? { text: res.text } : { text: (res && res.error) || 'Não foi possível concluir.', error: true };
    P.renderThread();
  }

  function approvalNode(turn) {
    if (!turn.actionId) return null;
    const item = ((P.state && P.state.overview && P.state.overview.pending) || []).find((p) => p.id === turn.actionId);
    const pending = !!item;
    if (turn.decision) return P.h('p', { class: `decision-result${turn.decision.error ? ' error' : ''}` }, turn.decision.text);
    if (!pending) return P.stateVersion > turn.sinceState ? P.h('p', { class: 'decision-result' }, 'Concluído.') : null;
    if (P.state.settings.autoSend && item.kind === 'whatsapp.send') return P.h('p', { class: 'decision-result' }, 'Envio automático ligado: enviando…');
    if (turn.own) {
      return P.h('div', { class: 'decision-actions turn-actions' },
        P.h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'reject') }, 'Cancelar'),
        P.h('button', { class: 'ghost', type: 'button', onclick: () => P.redoOwnVoice(turn) }, 'Regravar'),
        P.h('button', { class: 'primary', type: 'button', onclick: () => decideTurn(turn, 'approve') }, 'Confirmar'));
    }
    return P.h('div', { class: 'decision-actions turn-actions' },
      item.voice ? P.h('button', { class: 'ghost', type: 'button', onclick: (e) => P.previewVoice(item.id, e.currentTarget) }, 'Ouvir') : null,
      P.h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'reject') }, 'Recusar'),
      item.kind === 'whatsapp.send' ? P.h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'always') }, 'Aprovar para as próximas') : null,
      item.auto_ok ? P.h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'keep') }, 'Aprovar e manter aprovado') : null,
      P.h('button', { class: 'primary', type: 'button', onclick: () => decideTurn(turn, 'approve') }, 'Aprovar'));
  }

  Object.assign(P, { renderDecisions, approvalNode });

})();
