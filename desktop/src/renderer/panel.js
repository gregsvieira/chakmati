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
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) node.append(kid);
    return node;
  }
  const fill = (parent, ...kids) => parent.replaceChildren(...kids.flat(Infinity).filter(Boolean));
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

  let waNote = '';
  async function connectWhatsApp() {
    waNote = 'Abrindo o OpenWA…';
    renderMessages();
    const res = await api.openWa();
    waNote = res && res.ok ? res.message || 'OpenWA aberto.' : (res && res.error) || 'Não consegui abrir o OpenWA.';
    renderMessages();
  }

  function renderMessages() {
    const wa = (state.overview && state.overview.whatsapp) || { enabled: false };
    $('messages').hidden = !wa.enabled;
    if (!wa.enabled) return;
    if (wa.error || wa.connected === false) {
      fill($('messages-body'),
        h('p', { class: 'warn' }, 'O WhatsApp está desconectado. Abra o OpenWA e escaneie o QR em Aparelhos conectados.'),
        state.canOpenWa ? h('button', { class: 'primary', type: 'button', id: 'wa-connect-inline', onclick: connectWhatsApp }, 'Conectar WhatsApp via OpenWa') : null,
        h('p', { class: 'hint', id: 'wa-connect-note' }, waNote));
      return;
    }
    const unread = wa.unread || [];
    if (!unread.length) { fill($('messages-body'), h('p', { class: 'empty' }, 'Nenhuma mensagem nova.')); return; }
    const masked = state.settings.masked;
    const shown = unread.slice(0, 2);
    const rowFor = (c) => {
      const label = [h('span', { class: 'name' }, masked ? 'Uma conversa' : c.name, c.is_group && !masked ? h('span', { class: 'tag' }, ' (grupo)') : null),
        h('span', { class: 'badge', 'aria-label': plural(c.unread, 'mensagem nova', 'mensagens novas') }, String(c.unread))];
      return masked ? h('div', { class: 'row' }, label) : h('button', { class: 'row row-btn', type: 'button', onclick: () => openChat(c, 'main') }, label);
    };
    fill($('messages-body'), shown.map(rowFor),
      unread.length > 2 && !masked ? h('button', { class: 'more', type: 'button', onclick: openChats }, `Ver mais (${unread.length - 2})`) : null);
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
    robot.setTalking(thread.some((t) => t.status === 'pending')); // the mouth moves while an answer is on its way
    const content = $('content');
    content.scrollTop = content.scrollHeight;
  }

  function renderSettings() {
    $('set-protect').checked = !!state.settings.protect;
    $('set-masked').checked = !!state.settings.masked;
    $('set-side').value = state.settings.bubbleSide;
    $('set-mood').value = state.settings.mood;
    $('set-still').checked = !!state.settings.still;
    document.body.toggleAttribute('data-still', !!state.settings.still);
    $('set-whatsapp').checked = !!state.settings.whatsapp;
    $('set-calendar').checked = !!state.settings.calendar;
    $('set-research').checked = !!state.settings.research;
    const wa = (state.overview && state.overview.whatsapp) || { enabled: false };
    $('wa-status').textContent = !wa.enabled ? 'Ler, resumir e enviar mensagens (sempre com a sua aprovação).'
      : wa.connected ? 'Conectado.' : 'Ligado, mas sem conexão. Conecte abaixo.';
    $('wa-connect').hidden = !(state.settings.whatsapp && state.canOpenWa && wa.enabled && !wa.connected);
    const hint = $('engine-hint');
    hint.hidden = state.ownsEngine || !state.engineUp;
    hint.textContent = 'O motor foi iniciado por fora do Chakmati: reinicie-o para aplicar estas opções.';
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

  // Each screen replaces the others: main (with the command line), Ajustes, the list of conversations, one conversation.
  const SCREENS = { main: ['content', 'foot'], settings: ['settings-view'], chats: ['chats-view'], chat: ['chat-view'] };
  let screen = 'main';
  let backTo = 'main';
  function showView(name) {
    screen = name;
    for (const [view, ids] of Object.entries(SCREENS)) for (const id of ids) $(id).hidden = view !== name;
    if (name !== 'main') $(SCREENS[name][0]).scrollTop = 0;
    else $('input').focus();
  }
  const showSettings = (on) => showView(on ? 'settings' : 'main');
  $('open-settings').addEventListener('click', () => showView('settings'));
  $('back').addEventListener('click', () => showView('main'));
  for (const b of document.querySelectorAll('[data-back]')) b.addEventListener('click', () => showView(screen === 'chat' ? backTo : 'main'));

  const fmtDuration = (s) => (Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : '');
  const fmtTime = (iso) => new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

  async function openChats() {
    backTo = 'main';
    showView('chats');
    fill($('chats-body'), h('p', { class: 'empty' }, 'Carregando…'));
    const res = await api.chats();
    if (!res || res.error) { fill($('chats-body'), h('p', { class: 'warn' }, (res && res.error) || 'Não consegui carregar as conversas.')); return; }
    const unread = res.chats.filter((c) => c.unread > 0);
    const rest = res.chats.filter((c) => c.unread === 0).slice(0, 30);
    const row = (c) => h('button', { class: 'row row-btn', type: 'button', onclick: () => openChat(c, 'chats') },
      h('span', { class: 'name' }, c.name, c.is_group ? h('span', { class: 'tag' }, ' (grupo)') : null),
      c.unread > 0 ? h('span', { class: 'badge' }, String(c.unread)) : null);
    fill($('chats-body'),
      unread.length ? [h('h3', {}, 'Com mensagens novas'), unread.map(row)] : h('p', { class: 'empty' }, 'Nenhuma mensagem nova.'),
      rest.length ? [h('h3', {}, 'Recentes'), rest.map(row)] : null);
  }

  async function openChat(chat, from) {
    backTo = from;
    showView('chat');
    $('chat-title').textContent = chat.name;
    fill($('chat-body'), h('p', { class: 'empty' }, 'Carregando…'));
    const res = await api.messages(chat.id);
    if (!res || res.error) { fill($('chat-body'), h('p', { class: 'warn' }, (res && res.error) || 'Não consegui carregar as mensagens.')); return; }
    if (!res.messages.length) { fill($('chat-body'), h('p', { class: 'empty' }, 'Nenhuma mensagem carregada.')); return; }
    fill($('chat-body'), res.messages.map((m) => messageNode(chat, m)));
    $('chat-view').scrollTop = $('chat-view').scrollHeight;
  }

  function messageNode(chat, m) {
    let body;
    if (m.audio) body = audioNode(chat, m);
    else if (m.kind !== 'chat') body = h('span', { class: 'media-note' }, `[${m.kind === 'ptt' || m.kind === 'audio' ? 'áudio' : m.kind === 'image' ? 'imagem' : m.kind}]`, m.text ? ` ${m.text}` : '');
    else body = h('span', {}, m.text);
    return h('div', { class: `msg ${m.from_me ? 'out' : 'in'}` }, body, h('span', { class: 'msg-time' }, fmtTime(m.ts)));
  }

  function audioNode(chat, m) {
    const holder = h('div', { class: 'audio' });
    const play = h('button', { class: 'ghost play', type: 'button' }, `▶ Ouvir áudio ${fmtDuration(m.duration)}`.trim());
    play.addEventListener('click', async () => {
      play.disabled = true;
      play.textContent = 'Carregando…';
      const res = await api.audio(chat.id, m.id);
      if (!res || res.error) { play.disabled = false; play.textContent = '▶ Tentar de novo'; holder.append(h('p', { class: 'warn' }, (res && res.error) || 'Não foi possível carregar o áudio.')); return; }
      const player = h('audio', { controls: true, src: res.dataUrl, 'aria-label': 'Áudio de ' + chat.name });
      holder.replaceChildren(player);
      player.play().catch(() => { /* the person can press play */ });
    });
    holder.append(play);
    return holder;
  }

  $('close').addEventListener('click', () => { showSettings(false); api.close(); });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!$('settings-view').hidden) showSettings(false);
    else api.close();
  });
  $('panic').addEventListener('click', () => api.panic());
  $('restart').addEventListener('click', () => api.restart());
  $('set-protect').addEventListener('change', (e) => api.setSetting('protect', e.target.checked));
  $('set-masked').addEventListener('change', (e) => api.setSetting('masked', e.target.checked));
  $('set-whatsapp').addEventListener('change', (e) => api.setSetting('whatsapp', e.target.checked));
  $('set-research').addEventListener('change', (e) => api.setSetting('research', e.target.checked));
  $('set-calendar').addEventListener('change', (e) => api.setSetting('calendar', e.target.checked));
  $('wa-connect').addEventListener('click', connectWhatsApp);
  $('set-still').addEventListener('change', (e) => api.setSetting('still', e.target.checked));
  $('set-mood').addEventListener('change', (e) => api.setSetting('mood', e.target.value));
  $('set-side').addEventListener('change', (e) => api.setSetting('bubbleSide', e.target.value));

  api.onState((s) => { state = s; render(); });
  api.ready();
})();
