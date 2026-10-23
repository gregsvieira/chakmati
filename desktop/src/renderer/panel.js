(function () {
  const api = window.assistant.panel;
  const $ = (id) => document.getElementById(id);
  const robot = window.Robot.create($('head-robot'));
  const { relativeTime } = window.RelTime;

  let state = null;
  const thread = []; // {id, role, text, status: 'pending'|'done'|'error'}
  const decided = new Map(); // action id -> {text, error} shown briefly after the person decides

  // tiny element helper: text always goes through textContent, never innerHTML
  function h(tag, props = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === 'class') node.className = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, '');
      else if (v !== false && v != null) node.setAttribute(k, String(v));
    }
    for (const kid of kids.flat()) if (kid != null) node.append(kid);
    return node;
  }
  const fill = (parent, ...kids) => parent.replaceChildren(...kids.flat().filter(Boolean));
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  // ------------------------------------------------------------------ rendering
  function renderHeader() {
    const d = state.describe;
    $('title').textContent = d.title;
    $('detail').textContent = d.detail;
    robot.setMood(d.mood);
  }

  function renderDecisions() {
    const pending = (state.overview && state.overview.pending) || [];
    const ids = new Set(pending.map((p) => p.id));
    const shown = [...pending, ...[...decided.keys()].filter((id) => !ids.has(id)).map((id) => ({ id, summary: '', gone: true }))];
    $('decisions').hidden = shown.length === 0;
    fill($('decision-list'), shown.map((p) => {
      const result = decided.get(p.id);
      if (p.gone) return h('div', { class: 'decision' }, h('p', { class: `decision-result${result.error ? ' error' : ''}` }, result.text));
      const [first, ...rest] = (p.summary || '').split('\n');
      const buttons = [
        h('button', { class: 'ghost', type: 'button', disabled: !!result, onclick: () => decide(p.id, false) }, 'Recusar'),
        h('button', { class: 'primary', type: 'button', disabled: !!result, onclick: () => decide(p.id, true) }, 'Aprovar'),
      ];
      return h('div', { class: 'decision' },
        h('p', { class: 'decision-title' }, first),
        rest.length ? h('p', { class: 'decision-body' }, rest.join('\n')) : null,
        result ? h('p', { class: `decision-result${result.error ? ' error' : ''}` }, result.text) : h('div', { class: 'decision-actions' }, buttons));
    }));
  }

  async function decide(id, approve) {
    decided.set(id, { text: approve ? 'Enviando…' : 'Recusando…' });
    renderDecisions();
    const res = await (approve ? api.approve(id) : api.reject(id));
    if (res && res.ok) decided.set(id, { text: res.text });
    else decided.set(id, { text: (res && res.error) || 'Não foi possível concluir.', error: true });
    renderDecisions();
    setTimeout(() => { decided.delete(id); if (state) renderDecisions(); }, 5000);
  }

  function renderMessages() {
    const wa = (state.overview && state.overview.whatsapp) || { enabled: false };
    $('messages').hidden = !wa.enabled;
    if (!wa.enabled) return;
    if (wa.error || wa.connected === false) {
      fill($('messages-body'), h('p', { class: 'warn' }, 'O WhatsApp está desconectado. Abra o OpenWA e escaneie o QR em Aparelhos conectados.'));
      return;
    }
    const unread = wa.unread || [];
    if (!unread.length) { fill($('messages-body'), h('p', { class: 'empty' }, 'Nenhuma mensagem nova.')); return; }
    const masked = state.settings.masked;
    fill($('messages-body'), unread.map((c) => h('div', { class: 'row' },
      h('span', { class: 'name' }, masked ? 'Uma conversa' : c.name, c.is_group && !masked ? h('span', { class: 'tag' }, ' (grupo)') : null),
      h('span', { class: 'badge', 'aria-label': plural(c.unread, 'mensagem nova', 'mensagens novas') }, String(c.unread)))));
  }

  function renderAgenda() {
    const cal = (state.overview && state.overview.calendar) || { enabled: false };
    $('agenda').hidden = !cal.enabled;
    if (!cal.enabled) return;
    if (cal.error) { fill($('agenda-body'), h('p', { class: 'warn' }, 'Não consegui ler a agenda.')); return; }
    const events = cal.today || [];
    if (!events.length) { fill($('agenda-body'), h('p', { class: 'empty' }, 'Nada marcado para hoje.')); return; }
    const masked = state.settings.masked;
    fill($('agenda-body'), events.map((e) => {
      const time = e.all_day ? 'dia todo' : new Date(e.start).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      return h('div', { class: 'row' }, h('span', { class: 'name' }, masked ? 'Compromisso' : e.title), h('span', { class: 'time' }, time));
    }));
  }

  function renderRecent() {
    const notices = (state.notices || []).slice(-6).reverse();
    if (!notices.length) { fill($('recent-body'), h('p', { class: 'empty' }, 'Quando algo acontecer, eu aviso aqui.')); return; }
    const now = Date.now() / 1000;
    fill($('recent-body'), notices.map((n) => h('div', { class: 'row' },
      h('span', {}, state.settings.masked && n.masked ? n.masked : n.text), h('span', { class: 'when' }, relativeTime(n.ts, now)))));
  }

  function renderThread() {
    $('thread-section').hidden = thread.length === 0;
    fill($('thread'), thread.map((t) => h('div', { class: `turn ${t.role}${t.status === 'pending' ? ' pending' : ''}${t.status === 'error' ? ' error' : ''}` }, t.text || '…')));
    const content = $('content');
    content.scrollTop = content.scrollHeight;
  }

  function renderSettings() {
    $('set-protect').checked = !!state.settings.protect;
    $('set-masked').checked = !!state.settings.masked;
    $('set-side').value = state.settings.bubbleSide;
    $('hotkeys').textContent = `Atalhos: abrir ou fechar ${state.hotkeys.toggle}; ocultar tudo ${state.hotkeys.panic}.`;
  }

  function render() {
    if (!state) return;
    renderHeader();
    renderDecisions();
    renderMessages();
    renderAgenda();
    renderRecent();
    renderSettings();
    $('send').disabled = !!state.busy;
  }

  // ------------------------------------------------------------------ conversation
  async function submit(text) {
    const clean = text.trim();
    if (!clean || (state && state.busy)) return;
    thread.push({ role: 'user', text: clean, status: 'done' });
    const res = await api.send(clean);
    if (!res || res.error) {
      thread.push({ role: 'assistant', text: (res && res.error) || 'Não consegui enviar o pedido.', status: 'error' });
    } else {
      thread.push({ id: res.id, role: 'assistant', text: '', status: 'pending' });
    }
    while (thread.length > 10) thread.shift();
    renderThread();
  }

  api.onMessage(({ id, event }) => {
    const turn = thread.find((t) => t.id === id);
    if (!turn) return;
    if (event.type === 'job') turn.text = turn.text || 'Trabalhando nisso…';
    else if (event.type === 'delta') { if (turn.text === 'Trabalhando nisso…') turn.text = ''; turn.text += event.text; }
    else if (event.type === 'done') { turn.text = event.result || turn.text; turn.status = 'done'; }
    else if (event.type === 'error') { turn.text = event.error || 'Algo deu errado.'; turn.status = 'error'; }
    else if (event.type === 'end' && turn.status === 'pending') turn.status = 'done';
    renderThread();
  });

  // ------------------------------------------------------------------ wiring
  const CHIPS = [
    { label: 'Mensagens novas', run: 'tenho mensagens novas no whatsapp?' },
    { label: 'Agenda de hoje', run: 'o que tenho na agenda hoje?' },
    { label: 'Resumir uma conversa', fill: 'resuma a conversa com ' },
    { label: 'Enviar mensagem', fill: 'manda no whatsapp pra ' },
    { label: 'Marcar compromisso', fill: 'marque ' },
  ];
  fill($('chips'), CHIPS.map((c) => h('button', {
    class: 'chip', type: 'button',
    onclick: () => {
      if (c.run) submit(c.run);
      else { $('input').value = c.fill; $('input').focus(); }
    },
  }, c.label)));

  const input = $('input');
  const grow = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 110)}px`; };
  input.addEventListener('input', grow);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('composer').requestSubmit(); }
  });
  $('composer').addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = '';
    grow();
    submit(text);
  });

  $('close').addEventListener('click', () => api.close());
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') api.close(); });
  $('panic').addEventListener('click', () => api.panic());
  $('set-protect').addEventListener('change', (e) => api.setSetting('protect', e.target.checked));
  $('set-masked').addEventListener('change', (e) => api.setSetting('masked', e.target.checked));
  $('set-side').addEventListener('change', (e) => api.setSetting('bubbleSide', e.target.value));

  api.onState((s) => { state = s; render(); });
  api.ready();
})();
