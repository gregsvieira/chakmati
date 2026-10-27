(function () {
  const api = window.assistant.panel;
  const $ = (id) => document.getElementById(id);
  const robot = window.Robot.create($('head-robot'));
  const { relativeTime } = window.RelTime;

  let state = null;
  let stateVersion = 0; // counts the states received; a card only says "Concluído." after a state newer than its answer
  let speaking = false;
  const syncTalking = () => robot.setTalking(speaking || thread.some((t) => t.status === 'pending')); // the mouth moves while answering and while speaking
  if (/Mac/.test(navigator.platform || navigator.userAgent)) document.body.dataset.blur = ''; // the system blurs what is behind the window only on macOS
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
  // The notice before WhatsApp and automations: read once ("Compreendi e estou ciente!"), then never again. Esc or a click outside closes it
  // without doing the action. Remembered in this window's storage.
  const waGate = window.NoticeGate.createGate((() => { try { return window.localStorage; } catch { return { getItem: () => null, setItem: () => {} }; } })(), 'chakmati.whatsapp-notice');
  let closeNotice = null;
  function showWhatsAppNotice(onAck, onCancel) {
    const modal = $('notice-modal');
    const finish = (fn) => { modal.hidden = true; closeNotice = null; document.removeEventListener('keydown', onKey, true); modal.removeEventListener('mousedown', onOutside); fn(); };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); finish(onCancel); }
      else if (e.key === 'Tab') { e.preventDefault(); $('notice-ok').focus(); }   // the only thing to press is the button
    };
    const onOutside = (e) => { if (e.target === modal) finish(onCancel); };
    $('notice-ok').onclick = () => finish(onAck);
    modal.hidden = false;
    closeNotice = () => finish(onCancel);
    document.addEventListener('keydown', onKey, true);
    modal.addEventListener('mousedown', onOutside);
    $('notice-ok').focus();
  }

  function renderHeader() {
    const d = state.describe;
    if (screen === 'main') {
      $('title').textContent = d.title;
      $('detail').textContent = d.detail;
    }
    robot.setMood(d.mood);
    $('retry').hidden = !!state.engineUp || screen !== 'main';   // the engine is not answering: one button to try again (restarts it when the app started it)
    if (state.overview && state.overview.awake && screen === 'main') $('input').focus();
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
        p.voice ? h('button', { class: 'ghost', type: 'button', onclick: (e) => previewVoice(p.id, e.currentTarget) }, 'Ouvir') : null,
        h('button', { class: 'ghost', type: 'button', disabled: !!result, onclick: () => decide(p.id, false) }, 'Recusar'),
        p.auto_ok ? h('button', { class: 'ghost', type: 'button', disabled: !!result, onclick: () => decide(p.id, true, true) }, 'Aprovar e manter aprovado') : null,
        h('button', { class: 'primary', type: 'button', disabled: !!result, onclick: () => decide(p.id, true) }, 'Aprovar'),
      ];
      return h('div', { class: 'decision' },
        h('p', { class: 'decision-title' }, first),
        rest.length ? h('p', { class: 'decision-body' }, rest.join('\n')) : null,
        result ? h('p', { class: `decision-result${result.error ? ' error' : ''}` }, result.text) : h('div', { class: 'decision-actions' }, buttons));
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
    setTimeout(() => { decided.delete(id); if (state) renderDecisions(); }, 5000);
  }

  let waNote = '';
  async function connectWhatsApp() {
    return waGate.run(showWhatsAppNotice, doConnectWhatsApp);
  }
  async function doConnectWhatsApp() {
    waNote = 'Abrindo o OpenWA…';
    renderMessages();
    const res = await api.openWa();
    waNote = res && res.ok ? res.message || 'OpenWA aberto.' : (res && res.error) || 'Não consegui abrir o OpenWA.';
    renderMessages();
  }

  // A titled sub-block; sub-blocks sit one under the other.
  const subgroup = (title, ...kids) => h('div', { class: 'subgroup' }, h('h3', {}, title), kids);

  function whatsappNodes() {
    const wa = (state.overview && state.overview.whatsapp) || { enabled: false };
    if (!wa.enabled) return [h('p', { class: 'empty' }, 'WhatsApp desativado em Ajustes.')];
    if (wa.error || wa.connected === false) {
      return [
        h('p', { class: 'warn' }, 'O WhatsApp está desconectado. Abra o OpenWA e escaneie o QR em Aparelhos conectados.'),
        state.canOpenWa ? h('button', { class: 'primary', type: 'button', id: 'wa-connect-inline', onclick: connectWhatsApp }, 'Conectar WhatsApp via OpenWa') : null,
        h('p', { class: 'hint', id: 'wa-connect-note' }, waNote)];
    }
    const unread = wa.unread || [];
    if (!unread.length) return [h('p', { class: 'empty' }, 'Nenhuma mensagem nova.')];
    const masked = state.settings.masked;
    const rowFor = (c) => {
      const label = [h('span', { class: 'name' }, masked ? 'Uma conversa' : c.name, c.is_group && !masked ? h('span', { class: 'tag' }, ' (grupo)') : null),
        h('span', { class: 'badge', 'aria-label': plural(c.unread, 'mensagem nova', 'mensagens novas') }, String(c.unread))];
      return masked ? h('div', { class: 'row' }, label) : h('button', { class: 'row row-btn', type: 'button', onclick: () => openChat(c, 'main') }, label);
    };
    return [unread.slice(0, 2).map(rowFor),
      unread.length > 2 && !masked ? h('button', { class: 'more', type: 'button', onclick: openChats }, `Ver mais (${unread.length - 2})`) : null];
  }

  function renderMessages() {
    $('messages').hidden = false;
    fill($('messages-body'),
      subgroup('WhatsApp', whatsappNodes()),
      subgroup('Email', h('p', { class: 'empty' }, 'Email ainda não está conectado.')));
  }

  function renderPendingMark() {
    const n = ((state && state.overview && state.overview.pending) || []).length;
    const bell = (state && state.bell) || { state: 'idle', label: 'Nenhuma novidade' };
    const mark = $('head-approval');
    mark.dataset.state = bell.state;                  // idle (outline) | notice (red) | request (yellow)
    mark.setAttribute('aria-label', bell.label);
    mark.title = bell.label;
    const badge = $('fold-left-badge');  // the list of decisions is on the left: when it is minimized the number stays on its button
    badge.hidden = !(n > 0);
    badge.textContent = String(n);
    badge.setAttribute('aria-label', plural(n, 'aprovação pendente', 'aprovações pendentes'));
  }

  function renderAutomations() {
    const list = (state.overview && state.overview.automations) || [];
    $('automations-empty').hidden = list.length > 0;
    const card = (a) => h('div', { class: 'row automation' },
      h('div', { class: 'grow' }, h('p', { class: 'decision-title' }, a.name), h('p', { class: 'decision-body' }, a.description + (a.runs ? ` (${plural(a.runs, 'vez', 'vezes')})` : ''))),
      h('div', { class: 'decision-actions' },
        h('button', { class: 'ghost small', type: 'button', onclick: () => api.automation(a.id, a.enabled ? 'disable' : 'enable') }, a.enabled ? 'Pausar' : 'Ativar'),
        h('button', { class: 'ghost small', type: 'button', onclick: () => api.automation(a.id, 'delete') }, 'Apagar')));
    // One sub-block per channel that has automations; none for the channels without any.
    const channels = [['whatsapp', 'WhatsApp'], ['email', 'Email'], ['home', 'Casa']];
    fill($('automation-list'), channels
      .map(([key, title]) => [title, list.filter((a) => (a.channel || 'whatsapp') === key)])
      .filter(([, items]) => items.length)
      .map(([title, items]) => subgroup(title, items.map(card))));
  }

  async function previewVoice(id, button) {
    const res = await api.preview(id);
    if (res && res.dataUrl) { button.replaceWith(h('audio', { controls: true, autoplay: true, src: res.dataUrl, 'aria-label': 'Prévia da resposta em áudio' })); }
    else button.textContent = (res && res.error) || 'Sem prévia';
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
    // messages live under "Mensagens", and what Chakmati itself said is not a notice: here only agenda, approvals and system
    const notices = (state.notices || []).filter((n) => n.kind !== 'whatsapp' && n.kind !== 'reply').slice(-6).reverse();
    if (!notices.length) { fill($('recent-body'), h('p', { class: 'empty' }, 'Quando algo acontecer, eu aviso aqui.')); return; }
    const now = Date.now() / 1000;
    fill($('recent-body'), notices.map((n) => h('div', { class: 'row' },
      h('span', { title: n.text.split('\n')[0] }, state.settings.masked && n.masked ? n.masked : window.NoticeTitle.noticeTitle(n)), h('span', { class: 'when' }, relativeTime(n.ts, now)))));
  }

  // The engine marks a proposal with [[action:<id>]]; the person sees one short sentence and the approval buttons instead.
  function setTurnText(turn, text) {
    const m = /\[\[action:([0-9a-f]{32})\]\]/.exec(text || '');
    turn.actionId = m ? m[1] : null;
    turn.sinceState = stateVersion;
    turn.raw = text || ''; // the marker can arrive split across chunks, so the raw text is kept and the shown text derived from it
    turn.text = (text || '').replace(/\s*\[\[action:[0-9a-f]{32}\]\]\s*/g, '').replace(/\s*\[\[[^\]]*$/, '').trim();
  }

  async function decideTurn(turn, mode) {
    turn.decision = { text: mode === 'reject' ? 'Recusando…' : 'Executando…' };
    renderThread();
    if (mode === 'always') await api.setSetting('autoSend', true);
    if (mode === 'keep') await api.setSetting('autoRunSafe', true);
    const res = await (mode === 'reject' ? api.reject(turn.actionId) : api.approve(turn.actionId));
    turn.decision = res && res.ok ? { text: res.text } : { text: (res && res.error) || 'Não foi possível concluir.', error: true };
    renderThread();
  }

  function approvalNode(turn) {
    if (!turn.actionId) return null;
    const item = ((state && state.overview && state.overview.pending) || []).find((p) => p.id === turn.actionId);
    const pending = !!item;
    if (turn.decision) return h('p', { class: `decision-result${turn.decision.error ? ' error' : ''}` }, turn.decision.text);
    if (!pending) return stateVersion > turn.sinceState ? h('p', { class: 'decision-result' }, 'Concluído.') : null;
    if (state.settings.autoSend && item.kind === 'whatsapp.send') return h('p', { class: 'decision-result' }, 'Envio automático ligado: enviando…');
    if (turn.own) {
      return h('div', { class: 'decision-actions turn-actions' },
        h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'reject') }, 'Cancelar'),
        h('button', { class: 'ghost', type: 'button', onclick: () => redoOwnVoice(turn) }, 'Regravar'),
        h('button', { class: 'primary', type: 'button', onclick: () => decideTurn(turn, 'approve') }, 'Confirmar'));
    }
    return h('div', { class: 'decision-actions turn-actions' },
      item.voice ? h('button', { class: 'ghost', type: 'button', onclick: (e) => previewVoice(item.id, e.currentTarget) }, 'Ouvir') : null,
      h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'reject') }, 'Recusar'),
      item.kind === 'whatsapp.send' ? h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'always') }, 'Aprovar para as próximas') : null,
      item.auto_ok ? h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'keep') }, 'Aprovar e manter aprovado') : null,
      h('button', { class: 'primary', type: 'button', onclick: () => decideTurn(turn, 'approve') }, 'Aprovar'));
  }

  // The browser at work: the screenshot of the latest step, replaced as each new one arrives, with what it was doing.
  function shotNode(turn) {
    if (!turn.shot || !turn.shot.image) return null;
    return h('figure', { class: 'shot' },
      h('img', { src: turn.shot.image, alt: turn.shot.title || 'navegador' }),
      h('figcaption', {}, turn.shot.note, h('span', {}, turn.shot.url)));
  }

  // The question of the browser ("qual é o seu usuário?", the password): an input in the conversation. The node is made once and kept
  // across redraws, so what is being typed is not lost; a password input is masked, and what is typed is cleared as soon as it is sent.
  function askNode(turn) {
    if (turn.askSent) return h('p', { class: 'hint' }, 'Resposta enviada.');
    if (!turn.ask) return null;
    if (!turn.askEl) {
      const ask = turn.ask;
      const input = h('input', { type: ask.secret ? 'password' : 'text', class: 'ask-input', autocomplete: ask.secret ? 'new-password' : 'off', spellcheck: 'false',
        maxlength: 500, 'aria-label': ask.prompt, placeholder: ask.secret ? 'Digite a senha (ela fica oculta)' : 'Digite aqui' });
      const send = h('button', { type: 'submit', class: 'primary small' }, ask.confirm ? 'Já resolvi' : 'Enviar');
      const fail = ask.confirm ? h('button', { type: 'button', class: 'small', onclick: () => { value = 'nao'; form.requestSubmit(); } }, 'Não consegui') : null;
      let value = null;
      const problem = h('p', { class: 'warn', hidden: true }, 'Não consegui enviar. Tente de novo.');
      const form = turn.askEl = h('form', { class: 'ask', autocomplete: 'off', onsubmit: async (e) => {
        e.preventDefault();
        const answer = ask.confirm ? (value || 'ok') : input.value;   // a confirmation has nothing to type: "Já resolvi" is ok, "Não consegui" is nao
        value = null;
        if (!answer) return;
        input.disabled = true; send.disabled = true; if (fail) fail.disabled = true;
        const res = await api.answerInput(ask.job_id, ask.request_id, answer);
        input.value = '';
        if (res && res.ok) { turn.ask = null; turn.askEl = null; turn.askInput = null; turn.askSent = true; } else { input.disabled = false; send.disabled = false; if (fail) fail.disabled = false; problem.hidden = false; }
        renderThread(false);
      } }, h('label', { class: 'ask-label' }, ask.prompt), h('div', { class: 'ask-row' }, input, send, fail), problem);
      if (ask.confirm) input.hidden = true;
      turn.askInput = input;
    }
    return turn.askEl;
  }

  // "Plano:\n1. ...\n2. ..." at the start of an answer is a card: open while the Chakmati works, folded when it is done (the person can open it again)
  const PLAN = /^Plano:\n((?:\d+\.[^\n]*\n?)+)\n*/;
  function bodyNodes(turn) {
    const text = turn.text || '…';
    const m = PLAN.exec(text);
    if (!m) return [h('span', { class: 'turn-text' }, text)];
    const steps = m[1].trim().split('\n').map((l) => l.replace(/^\d+\.\s*/, ''));
    const open = turn.planOpen !== undefined ? turn.planOpen : turn.status === 'pending';
    const card = h('details', { class: 'plan', open, ontoggle: (e) => { turn.planOpen = e.currentTarget.open; } },
      h('summary', {}, `Plano (${steps.length} ${steps.length === 1 ? 'passo' : 'passos'})`), h('ol', {}, steps.map((t) => h('li', {}, t))));
    const rest = text.slice(m[0].length).trim();
    return rest ? [card, h('span', { class: 'turn-text' }, rest)] : [card];
  }

  function renderThread(scroll = true) {
    $('thread-section').hidden = thread.length === 0;
    const box = $('thread');
    const typing = thread.find((t) => t.askInput && t.askInput === document.activeElement);
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40; // do not yank the reader away from older messages
    fill(box, thread.map((t) => h('div', { class: `turn ${t.role}${t.status === 'pending' ? ' pending' : ''}${t.status === 'error' ? ' error' : ''}` }, shotNode(t), bodyNodes(t), approvalNode(t), askNode(t))));
    syncTalking();
    renderScreen();
    const wanted = typing || thread.find((t) => t.focusAsk && t.askInput);
    if (wanted) { wanted.focusAsk = false; wanted.askInput.focus(); }
    if (scroll || atBottom) box.scrollTop = box.scrollHeight;  // the conversation has its own scroll: it follows the newest message
    if (scroll) $('thread-section').scrollIntoView({ block: 'end' }); // and a new message brings the conversation into view on the page
  }

  function renderSettings() {
    $('set-protect').checked = !!state.settings.protect;
    $('set-masked').checked = !!state.settings.masked;
    $('set-side').value = state.settings.bubbleSide;
    $('set-mood').value = state.settings.mood;
    $('set-still').checked = !!state.settings.still;
    $('set-hear').checked = !!state.settings.hear;
    $('set-talk').checked = !!state.settings.talk;
    $('set-emojis').checked = !!state.settings.speakEmojis;
    renderVoiceSettings();
    $('set-mic').value = state.settings.micSource;
    $('set-autosend').checked = !!state.settings.autoSend;
    $('set-autorun').checked = !!state.settings.autoRunSafe;
    if (!state.settings.hear) { window.Voice.stop(); speaking = false; }
    syncAmbient();
    updateHint();
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

  // Ajustes > Voz melhorada: off by default (the voice of the system); turning it on downloads the voice the first time.
  function renderVoiceSettings() {
    const v = state.voice;
    const on = !!state.settings.enhancedVoice;
    $('set-enhanced').checked = on;
    $('set-voicespeed').value = state.settings.voiceSpeed;
    const downloading = !!(v && v.downloading);
    let text = `Usa a voz do sistema. Ligando, o Chakmati baixa uma voz neural em português do Brasil (cerca de ${v ? Math.round(v.size_mb) : 63} MB, uma única vez) e fala com ela, no seu computador.`;
    if (downloading) text = `Baixando a voz melhorada… ${Math.round((v.progress || 0) * 100)}%`;
    else if (on && v && v.installed) text = 'Voz melhorada ligada. Funciona sem internet.';
    else if (v && v.error) text = `Não consegui baixar: ${v.error}`;
    $('enhanced-status').textContent = text;
    $('voice-progress').hidden = !downloading;
    $('voice-progress').value = downloading ? Math.round((v.progress || 0) * 100) : 0;
    $('remove-voice').hidden = !(v && v.installed) || downloading;
    $('set-voicespeed').closest('.field').hidden = !on;
  }

  function render() {
    if (!state) return;
    renderHeader();
    renderDecisions();
    renderMessages();
    renderAgenda();
    renderRecent();
    renderAutomations();
    renderPendingMark();
    renderTopicHints();
    renderSettings();
    syncSendButton();
  }

  // ------------------------------------------------------------------ conversation
  // Settings by conversation: "liga a voz melhorada". Rules on the person's own words, so it never reaches the engine.
  let pendingSetting = null; // a sensitive change waiting for the person's yes / no
  const awaitingSetting = () => !!(pendingSetting && Date.now() < pendingSetting.until);
  function trySettings(clean) {
    const SI = window.SettingsIntent;
    let result = null;
    if (awaitingSetting()) {
      const answer = SI.verdict(clean);
      if (answer) { result = { answer, change: pendingSetting }; pendingSetting = null; }
      else pendingSetting = null; // anything else cancels the question
    }
    if (result) {
      thread.push({ role: 'user', text: clean, status: 'done' });
      if (result.answer === 'yes') applyIntent(result.change); else tell('Certo, não mudei nada.');
      return true;
    }
    const intent = SI.parse(clean);
    if (!intent) return false;
    thread.push({ role: 'user', text: clean, status: 'done' });
    if (intent.sensitive) { pendingSetting = { ...intent, until: Date.now() + 30000 }; tell(intent.ask); } else applyIntent(intent);
    return true;
  }
  async function applyIntent(intent) {
    const res = await api.setSetting(intent.key, intent.value);
    tell(res && res.ok ? intent.done : 'Não consegui mudar essa configuração.');
  }

  async function submit(text, { voice = false } = {}) {
    const clean = text.trim();
    if (!clean || (state && state.busy)) return;
    if (trySettings(clean)) return;
    const waiting = thread.slice().reverse().find((t) => t.own && !t.decision);
    if (waiting && /regrav|grav\w* (de novo|novamente)/i.test(clean)) { redoOwnVoice(waiting); return; }
    thread.push({ role: 'user', text: clean, status: 'done' });
    const res = await api.send(clean);
    if (!res || res.error) {
      thread.push({ role: 'assistant', text: (res && res.error) || 'Não consegui enviar o pedido.', status: 'error' });
    } else {
      thread.push({ id: res.id, role: 'assistant', text: '', status: 'pending', voice });
    }
    while (thread.length > 10) thread.shift();
    renderThread();
  }

  api.onMessage(({ id, event }) => {
    const turn = thread.find((t) => t.id === id);
    if (!turn) return;
    if (event.type === 'screenshot') { Shots.addShot(turn, event); pickedStep = null; turn.text = turn.text || 'Usando o navegador…'; }
    else if (event.type === 'input') {
      turn.ask = { job_id: event.job_id, request_id: event.request_id, prompt: event.prompt, secret: !!event.secret, confirm: !!event.confirm };
      turn.askEl = null; turn.askSent = false; turn.focusAsk = true;
      if ($('panel').dataset.layout === 'compact' && !store.get('chakmati.focus', false)) { store.set('chakmati.focus', true); applyLayout(); }
      if (state && !state.panelOpen) api.reply(`${event.prompt} (abra o painel para responder)`);
    } else if (event.type === 'input_done') { turn.ask = null; turn.askEl = null; }
    else if (event.type === 'cancelled') {
      setTurnText(turn, `${turn.raw || (turn.text === 'Trabalhando nisso…' || turn.text === 'Usando o navegador…' ? '' : turn.text) || ''}\n\n${event.text || 'Interrompido por você.'}`.trim());
      turn.status = 'done'; turn.ask = null; turn.askEl = null;
    } else if (event.type === 'job') turn.text = turn.text || 'Trabalhando nisso…';
    else if (event.type === 'delta') { if (turn.text === 'Trabalhando nisso…') turn.raw = ''; setTurnText(turn, (turn.raw || '') + event.text); }
    else if (event.type === 'done') { setTurnText(turn, event.result || turn.text); turn.status = 'done'; deliver(turn); }
    else if (event.type === 'error') { turn.text = event.error || 'Algo deu errado.'; turn.status = 'error'; deliver(turn); }
    else if (event.type === 'end' && turn.status === 'pending') turn.status = 'done';
    renderThread();
  });

  // ------------------------------------------------------------------ hear and talk
  // The answer is done. With the panel open it is spoken here; with the panel closed it appears as a bubble by the
  // character (the floating window speaks it if "Ouvir" is on), and nothing opens by itself.
  function deliver(turn) {
    if (!turn.text) return;
    if (state && !state.panelOpen) { if (!turn.actionId) api.reply(turn.text); return; }
    sayAloud(turn.text);
  }

  function sayAloud(text) {
    if (!state || !state.settings.hear) return;
    window.Voice.speak(text, { emojis: !!state.settings.speakEmojis, enhanced: !!(state.settings.enhancedVoice && state.voice && state.voice.installed), speed: state.settings.voiceSpeed, onStart: () => { speaking = true; speakingSince = Date.now(); syncTalking(); }, onEnd: () => { speaking = false; quietUntil = Date.now() + 700; syncTalking(); updateHint(); chimeIfWaiting(); } });
  }

  // "Falar com o Chakmati": the microphone is always listening, with no button to press. It acts only on a wake phrase
  // ("Ôh, Xácmáti") or while it is already waiting for a command, so conversation in the room never reaches the assistant.
  const micButton = $('mic');
  const JUNK = /^(obrigad[oa]\.?|tchau\.?|legendas.*|\.+|…)$/i; // what the recogniser invents from noise
  let ambient = null;
  let starting = false;
  let transcribing = false;
  let speechInProgress = false;
  let ambientWarned = false;
  const diag = (window.__listening = { frames: 0, starts: 0, ends: 0, drops: 0, sent: 0, heard: [], peak: 0, floor: 0, muted: 0, restarts: 0 }); // for support: what the microphone loop saw
  let speakingSince = 0;
  let queued = null;         // a command heard while an answer was still being produced
  let otherSpeaking = false; // the floating widget is reading a notice
  let quietUntil = 0;        // a short tail after any speech, while the room still echoes
  const isMuted = () => {
    if (speaking && Date.now() - speakingSince > 90000) { speaking = false; window.Voice.stop(); } // a voice that never reports its end must not mute the microphone for good
    return speaking || otherSpeaking || Date.now() < quietUntil; // not while Chakmati talks: it would hear itself
  }; // not while Chakmati talks or works: it would hear itself

  // Busy: the send button is "Parar" and the field says what is going on (nothing is silently ignored)
  function syncSendButton() {
    const busy = !!(state && state.busy);
    const btn = $('send');
    btn.dataset.mode = busy ? 'stop' : 'send';
    btn.disabled = false;
    btn.setAttribute('aria-label', busy ? 'Parar' : 'Enviar');
    btn.title = busy ? 'Parar o que o Chakmati está fazendo' : 'Enviar';
    updateHint();
  }

  function stopWork() {
    const turn = thread.slice().reverse().find((t) => t.status === 'pending');
    if (turn) api.cancel(turn.id);
  }

  function updateHint() {
    if (!state) return;
    const talk = state.settings.talk;
    const awake = !!(state.overview && state.overview.awake);
    input.placeholder = state.busy ? 'Trabalhando nisso… toque em Parar para interromper' : !talk ? 'Peça algo ao Chakmati…' : awake ? 'Aguardando seu comando… fale agora' : 'Escutando… diga “Ôh, Xácmáti”';
    micButton.classList.toggle('on', talk);
    micButton.classList.toggle('recording', talk && speechInProgress);
    micButton.hidden = !talk;
    micButton.title = talk ? 'Escutando. Clique para desligar.' : 'Falar com o Chakmati';
  }

  // A short "plim": the assistant finished talking and is now waiting for the command.
  let chimeCtx = null;
  function chime() {
    diag.chimes = (diag.chimes || 0) + 1;
    try {
      chimeCtx = chimeCtx || new AudioContext();
      if (chimeCtx.state === 'suspended') chimeCtx.resume();
      const t0 = chimeCtx.currentTime + 0.02;
      [[660, 0], [990, 0.11]].forEach(([freq, offset]) => {
        const osc = chimeCtx.createOscillator();
        const gain = chimeCtx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, t0 + offset);
        gain.gain.exponentialRampToValueAtTime(0.18, t0 + offset + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, t0 + offset + 0.16);
        osc.connect(gain);
        gain.connect(chimeCtx.destination);
        osc.start(t0 + offset);
        osc.stop(t0 + offset + 0.18);
      });
      quietUntil = Date.now() + 1000; // do not listen to our own chime
    } catch { /* no sound is not a problem */ }
  }
  diag.chime = chime;

  // Only when the speech that just ended leaves the assistant waiting for a command (not after an ordinary answer).
  function chimeIfWaiting() {
    if (state && state.settings.talk && ((state.overview && state.overview.awake) || awaitingSetting())) chime();
  }

  function say(text) { thread.push({ role: 'assistant', text, status: 'error' }); renderThread(); }

  async function handleUtterance(chunks, rate) {
    if (transcribing) return;
    transcribing = true;
    try {
      diag.sent += 1;
      const wait = new Promise((resolve) => setTimeout(() => resolve({ error: 'O reconhecimento de voz demorou demais.' }), 70000));
      const res = await Promise.race([api.transcribe(window.Wav.encodeWav(chunks, rate), 'audio/wav'), wait]);
      diag.heard.push(res && (res.text || res.error)); if (diag.heard.length > 8) diag.heard.shift();
      if (!res || res.error) {
        if (!ambientWarned) { ambientWarned = true; say((res && res.error) || 'Não consegui entender o áudio.'); }
        return;
      }
      const text = (res.text || '').trim();
      if (!window.ListenPolicy.shouldAct({ text, wake: res.wake, awake: res.awake || awaitingSetting() })) return;
      if (state && state.busy) { queued = { text, at: Date.now() }; return; } // still answering the last one: do this next
      submit(text, { voice: true });
    } finally {
      transcribing = false;
    }
  }

  // A command heard while the answer to the previous one was still being produced runs as soon as that one ends.
  function runQueued() {
    if (!queued || (state && state.busy)) return;
    const item = queued;
    queued = null;
    if (Date.now() - item.at < 30000) submit(item.text, { voice: true });
  }

  // The computer's own microphone (the built-in one), not whatever virtual or Bluetooth device the system made the default.
  // The names of the devices are only readable after the first permission, hence the second open.
  async function openMicrophone() {
    const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
    let stream = await navigator.mediaDevices.getUserMedia({ audio: base });
    ambientSource = state.settings.micSource;
    if (ambientSource !== 'computer') return stream;
    const builtIn = /built-?in|macbook|interno|integrado|internal|imac|studio display/i;
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput' && !['default', 'communications'].includes(d.deviceId));
    const wanted = devices.find((d) => builtIn.test(d.label));
    if (wanted && !builtIn.test(stream.getAudioTracks()[0].label || '')) {
      stream.getTracks().forEach((t) => t.stop());
      stream = await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { exact: wanted.deviceId } } });
    }
    diag.microphone = stream.getAudioTracks()[0].label;
    return stream;
  }

  async function startAmbient() {
    if (ambient || starting || !state || !state.settings.talk) return;
    starting = true;
    let stream;
    try {
      stream = await openMicrophone();
    } catch {
      starting = false;
      say('Não consegui usar o microfone. Libere em Ajustes do Sistema > Privacidade > Microfone e ligue de novo.');
      api.setSetting('talk', false);
      return;
    }
    starting = false;
    if (!state || !state.settings.talk) { stream.getTracks().forEach((t) => t.stop()); return; }
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const silent = ctx.createGain();
    silent.gain.value = 0; // the processor must be connected to run, but nothing is played back
    source.connect(node);
    node.connect(silent);
    silent.connect(ctx.destination);
    const detector = window.Vad.createAmbient({});
    const preRoll = [];
    let utterance = null;
    node.onaudioprocess = (e) => {
      if (ambient) ambient.lastFrame = Date.now();
      const data = new Float32Array(e.inputBuffer.getChannelData(0));
      let sum = 0;
      for (const v of data) sum += v * v;
      const rms = Math.sqrt(sum / data.length);
      micButton.style.setProperty('--level', String(Math.min(rms * 6, 0.6)));
      diag.frames += 1; diag.peak = Math.max(diag.peak, rms); diag.floor = detector.floor || 0;
      if (isMuted()) { diag.muted += 1; utterance = null; preRoll.length = 0; if (speechInProgress) { speechInProgress = false; updateHint(); } return; }
      const event = detector.push(rms, (data.length / ctx.sampleRate) * 1000);
      if (utterance) utterance.push(data);
      if (event === 'start') diag.starts += 1;
      if (event === 'end') diag.ends += 1;
      if (event === 'drop') diag.drops += 1;
      if (event === 'start') { utterance = [...preRoll, data]; speechInProgress = true; updateHint(); }
      else if (!utterance) { preRoll.push(data); if (preRoll.length > 8) preRoll.shift(); }
      if (event === 'end' || event === 'drop') {
        const chunks = utterance;
        utterance = null;
        preRoll.length = 0;
        speechInProgress = false;
        updateHint();
        if (event === 'end' && chunks) handleUtterance(chunks, ctx.sampleRate);
      }
    };
    ambient = { ctx, lastFrame: Date.now(), stop() { node.onaudioprocess = null; stream.getTracks().forEach((t) => { t.onended = null; t.stop(); }); ctx.close().catch(() => {}); } };
    // the microphone was taken away (unplugged, another app, the Mac went to sleep): start listening again
    stream.getAudioTracks().forEach((track) => { track.onended = () => { diag.restarts += 1; stopAmbient(); setTimeout(syncAmbient, 800); }; });
  }

  function stopAmbient() {
    if (!ambient) return;
    ambient.stop();
    ambient = null;
    speechInProgress = false;
    micButton.style.setProperty('--level', '0');
  }

  // ------------------------------------------------------------------ "Minha fala": the reply recorded in the person's own voice
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let recordingOwn = false;

  // Chakmati says something: in the thread when the panel is open (and spoken), as a bubble by the character when it is closed.
  function tell(text, extra = {}) {
    const turn = { role: 'assistant', text, status: 'done', ...extra };
    thread.push(turn);
    while (thread.length > 10) thread.shift();
    renderThread();
    if (state && state.panelOpen) sayAloud(text); else api.reply(text);
    return turn;
  }

  async function waitQuiet(maxMs) {
    const end = Date.now() + maxMs;
    await sleep(500); // the speech has not started yet at this point
    while (Date.now() < end && (speaking || otherSpeaking)) await sleep(120);
    await sleep(250);
  }

  // The countdown is silent: one line that changes every second, in the panel or in a bubble.
  let countdownTurn = null;
  function showCount(text) {
    if (state && state.panelOpen) {
      if (!countdownTurn || !thread.includes(countdownTurn)) { countdownTurn = { role: 'assistant', text, status: 'done' }; thread.push(countdownTurn); }
      countdownTurn.text = text;
      renderThread(false);
    } else api.live(text);
  }
  function endCount() {
    if (countdownTurn) { const i = thread.indexOf(countdownTurn); if (i >= 0) thread.splice(i, 1); countdownTurn = null; renderThread(false); }
    api.live(null);
  }

  async function recordOwnVoice() {
    if (recordingOwn) return;
    recordingOwn = true;
    stopAmbient(); // the recorder takes the microphone
    let stream;
    try { stream = await openMicrophone(); } catch {
      recordingOwn = false; syncAmbient();
      say('Não consegui usar o microfone. Libere em Ajustes do Sistema > Privacidade > Microfone.');
      return;
    }
    const ctx = new AudioContext();
    try {
      tell('Fale por no máximo 10 segundos depois que ouvir o som plim no 3... 2... 1...');
      await waitQuiet(9000);
      const chunks = [];
      let peak = 0, spoke = false, quietSince = 0, floor = 0, frames = 0;
      const source = ctx.createMediaStreamSource(stream);
      const node = ctx.createScriptProcessor(4096, 1, 1);
      const mute = ctx.createGain(); mute.gain.value = 0;
      source.connect(node); node.connect(mute); mute.connect(ctx.destination);
      let capturing = false;
      node.onaudioprocess = (e) => {
        if (!capturing) return;
        const data = new Float32Array(e.inputBuffer.getChannelData(0));
        let sum = 0; for (const v of data) sum += v * v;
        const rms = Math.sqrt(sum / data.length);
        frames += 1; peak = Math.max(peak, rms);
        if (frames <= 3) floor = Math.max(floor, rms);  // the room before the person speaks
        else if (rms > Math.max(0.02, floor * 3)) { spoke = true; quietSince = 0; }
        else if (spoke && !quietSince) quietSince = Date.now();
        chunks.push(data);
      };
      chime();
      await sleep(450); // do not record the chime itself
      capturing = true;
      const started = Date.now();
      for (let left = 10; left >= 0; left--) {
        showCount(`${left}...`);
        const until = started + (10 - left + 1) * 1000;
        while (Date.now() < until) {
          await sleep(100);
          if (spoke && quietSince && Date.now() - quietSince > 1600) { left = -1; break; } // finished speaking: do not wait for the rest
        }
      }
      capturing = false;
      node.onaudioprocess = null;
      endCount();
      if (!spoke) { tell('Não ouvi nada. Clique em “Minha fala” para tentar de novo.'); return; }
      const wav = window.Wav.encodeWav(chunks, ctx.sampleRate);
      const res = await api.proposeRecorded(wav);
      if (!res || res.error) { tell((res && res.error) || 'Não consegui guardar a gravação.'); return; }
      const id = res.action.id;
      const audio = await api.preview(id);
      if (audio && audio.dataUrl) {
        await new Promise((resolve) => {
          const player = new Audio(audio.dataUrl);
          player.onended = player.onerror = resolve;
          player.play().catch(resolve);
        });
        quietUntil = Date.now() + 700;
      }
      tell('Ouviu como ficou? Diga sim para confirmar, regravar ou cancelar.', { actionId: id, own: true, sinceState: stateVersion });
    } finally {
      endCount();
      releaseMic(stream, ctx);
      recordingOwn = false;
      syncAmbient();
    }
  }
  function releaseMic(stream, ctx) { stream.getTracks().forEach((t) => t.stop()); ctx.close().catch(() => {}); }

  async function redoOwnVoice(turn) {
    turn.decision = { text: 'Regravando…' };
    renderThread();
    await api.reject(turn.actionId);
    turn.decision = { text: 'Gravação descartada.' };
    renderThread();
    recordOwnVoice();
  }

  let ambientSource = null;
  // Watchdog: if the audio stops flowing (suspended after sleep, device gone) the loop is rebuilt, never left deaf.
  setInterval(() => {
    updateHint();
    if (!ambient || !state || !state.settings.talk) return;
    if (ambient.ctx.state !== 'running') ambient.ctx.resume().catch(() => {});
    if (Date.now() - ambient.lastFrame > 5000) { diag.restarts += 1; stopAmbient(); startAmbient(); }
  }, 4000);

  const syncAmbient = () => {
    if (ambient && state && ambientSource !== state.settings.micSource) stopAmbient(); // the person chose another microphone
    if (state && state.settings.talk) startAmbient(); else stopAmbient();
  };

  // ------------------------------------------------------------------ wiring
  const CHIPS = [
    { label: 'Mensagens novas', run: 'tenho mensagens novas no whatsapp?' },
    { label: 'Agenda de hoje', run: 'o que tenho na agenda hoje?' },
    { label: 'Resumir uma conversa', fill: 'resuma a conversa com ' },
    { label: 'Enviar mensagem', fill: 'manda no whatsapp pra ' },
    { label: 'Marcar compromisso', fill: 'marque ' },
  ];
  const WHATSAPP_PROMPT = 'Crie uma automação: sempre que alguém me escrever no WhatsApp, responda';
  // Stage 2: how the reply is made. Text and audio are written by the person (the audio is recorded by Chakmati in the
  // voice in use); "Minha fala" is recorded by the person.
  const MODE_CHIPS = [
    { label: 'Áudio', media: true, fill: `${WHATSAPP_PROMPT} em áudio: ` },
    { label: 'Texto', fill: `${WHATSAPP_PROMPT}: ` },
    { label: 'Minha fala', media: true, own: true },
  ];
  // Stage 1: the channel.
  const AUTOMATION_CHIPS = [
    { label: 'WhatsApp', fill: `${WHATSAPP_PROMPT}: `, next: MODE_CHIPS },
    { label: 'Email (em breve)', soon: true },
    { label: 'Alexa (em breve)', soon: true },
  ];
  // This OpenWA may not be able to send files at all; then audio choices are shown as unavailable instead of failing later.
  const noMedia = () => !!(state && state.overview && state.overview.whatsapp && state.overview.whatsapp.media === false);
  const renderChips = (list) => fill($('chips'), list.map((c) => h('button', {
    class: 'chip', type: 'button', disabled: !!c.soon || (!!c.media && noMedia()), title: c.media && noMedia() ? 'O OpenWA instalado não envia áudio.' : null,
    onclick: () => {
      if (c.own) { showSuggestions(false); $('input').value = ''; recordOwnVoice(); return; }
      if (c.run) { showSuggestions(false); submit(c.run); return; }
      $('input').value = c.fill; $('input').focus(); grow();
      if (c.next) renderChips(c.next); else showSuggestions(false); // the next choice stays on screen
    },
  }, c.media && noMedia() ? `${c.label} (indisponível)` : c.label)));
  renderChips(CHIPS);

  // The shortcuts are suggestions: they rise above the command line when the person clicks it, and go away again.
  const showSuggestions = (on) => {
    $('chips').classList.toggle('open', on);
    if (!on) renderChips(CHIPS); // the automation choices last only until the field loses focus
  };
  $('chips').addEventListener('mousedown', (e) => e.preventDefault()); // clicking a suggestion must not take the focus from the field

  const showSuggestions2 = () => $('chips').classList.add('open'); // open without resetting the chips
  const input = $('input');
  const grow = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 110)}px`; };
  input.addEventListener('input', grow);
  input.addEventListener('pointerdown', () => { if (!input.value.trim()) showSuggestions(true); });
  input.addEventListener('input', () => { if (input.value.trim()) showSuggestions(false); });
  input.addEventListener('blur', () => showSuggestions(false));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('composer').requestSubmit(); }
  });
  $('composer').addEventListener('submit', (e) => {
    e.preventDefault();
    if (state && state.busy) {   // working: the button stops it; Enter alone does not (so a stray Enter never kills a long job)
      if (e.submitter && e.submitter.id === 'send') stopWork();
      return;
    }
    const text = input.value;
    input.value = '';
    grow();
    submit(text);
  });

  // Each screen replaces the others: main (with the command line), Ajustes, the list of conversations, one conversation.
  // The frame never moves: header (arrow + title), the page (the only part that scrolls) and the footer. Pages swap inside it.
  const PAGES = { main: 'content', settings: 'settings-view', chats: 'chats-view', chat: 'chat-view' };
  const TITLES = { settings: 'Ajustes', chats: 'Conversas' };
  let screen = 'main';
  let backTo = 'main';
  function setTitle(text) { if (screen !== 'main') $('title').textContent = text; }
  function showView(name, title) {
    screen = name;
    $('panel').dataset.screen = name;
    for (const [view, id] of Object.entries(PAGES)) $(id).hidden = view !== name;
    $('foot').hidden = name === 'settings';           // the command line is on every page except Ajustes
    $('foot-settings').hidden = name !== 'settings';  // Ajustes has its own fixed footer
    $(PAGES[name]).scrollTop = 0;
    if (name === 'main') { renderHeader(); $('input').focus(); } else $('title').textContent = title || TITLES[name] || '';
  }
  const goBack = () => showView(screen === 'chat' ? backTo : 'main');
  $('open-settings').addEventListener('click', () => showView('settings'));
  $('retry').addEventListener('click', () => { $('retry').textContent = 'Tentando…'; if (state && state.ownsEngine) api.restart(); else api.refresh(); setTimeout(() => { $('retry').textContent = 'Tentar de novo'; }, 4000); });
  $('back').addEventListener('click', goBack);

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
    showView('chat', chat.name);
    $('title').textContent = chat.name;
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

  // Automações: nothing to show yet; the button only says what is coming
  $('create-automation').addEventListener('click', () => waGate.run(showWhatsAppNotice, () => { $('automation-note').hidden = false; $('input').value = ''; renderChips(AUTOMATION_CHIPS); $('input').focus(); showSuggestions2(); }));

  $('close').addEventListener('click', () => { showView('main'); api.close(); });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (screen !== 'main') goBack();
    else if (document.activeElement && document.activeElement.matches('input, textarea') && document.activeElement.value.trim()) document.activeElement.blur();  // a half-written message is not thrown away by a stray Esc
    else api.close();
  });
  $('panic').addEventListener('click', () => api.panic());
  $('restart').addEventListener('click', () => api.restart());
  $('set-protect').addEventListener('change', (e) => api.setSetting('protect', e.target.checked));
  $('set-masked').addEventListener('change', (e) => api.setSetting('masked', e.target.checked));
  $('set-whatsapp').addEventListener('change', (e) => {
    const box = e.target;
    if (!box.checked) { api.setSetting('whatsapp', false); return; }
    box.checked = false;  // it only turns on after the notice was acknowledged
    waGate.run(showWhatsAppNotice, () => { box.checked = true; api.setSetting('whatsapp', true); });
  });
  $('set-research').addEventListener('change', (e) => api.setSetting('research', e.target.checked));
  $('set-calendar').addEventListener('change', (e) => api.setSetting('calendar', e.target.checked));
  $('wa-connect').addEventListener('click', connectWhatsApp);
  $('set-autosend').addEventListener('change', (e) => api.setSetting('autoSend', e.target.checked));
  $('set-autorun').addEventListener('change', (e) => api.setSetting('autoRunSafe', e.target.checked));
  $('set-enhanced').addEventListener('change', (e) => api.setSetting('enhancedVoice', e.target.checked));
  $('set-voicespeed').addEventListener('change', (e) => api.setSetting('voiceSpeed', e.target.value));
  $('remove-voice').addEventListener('click', async () => { await api.removeVoice(); });
  $('set-emojis').addEventListener('change', (e) => api.setSetting('speakEmojis', e.target.checked));
  $('set-mic').addEventListener('change', (e) => api.setSetting('micSource', e.target.value));
  $('set-hear').addEventListener('change', (e) => api.setSetting('hear', e.target.checked));
  $('set-talk').addEventListener('change', (e) => api.setSetting('talk', e.target.checked));
  micButton.addEventListener('click', () => api.setSetting('talk', !state.settings.talk));
  $('set-still').addEventListener('change', (e) => api.setSetting('still', e.target.checked));
  $('set-mood').addEventListener('change', (e) => api.setSetting('mood', e.target.value));
  $('set-side').addEventListener('change', (e) => api.setSetting('bubbleSide', e.target.value));

  // ------------------------------------------------------------------ the big window: layout, folding topics, the screen on the right
  const store = {
    get(key, fallback) { try { const v = window.localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(key, value) { try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* private window or storage off: the choice just is not remembered */ } },
  };
  const TOPICS = ['decisions', 'messages', 'agenda', 'automations', 'recent'];
  // Which topics are folded: in the small card they start folded (one line each, with a hint of what is inside), in the big window open (there is room).
  // Each layout remembers its own choices.
  const foldedBy = {
    compact: new Set(store.get('chakmati.folded-compact', TOPICS.filter((t) => t !== 'decisions'))),
    wide: new Set(store.get('chakmati.folded-wide', [])),
  };
  const layoutNow = () => ($('panel').dataset.layout === 'wide' ? 'wide' : 'compact');
  const folded = { has: (id) => foldedBy[layoutNow()].has(id) };
  let pickedStep = null;

  const folds = { left: store.get('chakmati.left', false) === true, right: store.get('chakmati.right', false) === true };
  function applyFolds() {
    $('panel').dataset.left = folds.left ? 'folded' : '';
    $('panel').dataset.right = folds.right ? 'folded' : '';
    for (const side of ['left', 'right']) {
      const btn = $(`fold-${side}`);
      const name = side === 'left' ? 'a lateral esquerda' : 'a Tela do Chakmati';
      btn.setAttribute('aria-expanded', String(!folds[side]));
      btn.setAttribute('aria-label', `${folds[side] ? 'Mostrar' : 'Minimizar'} ${name}`);
      btn.title = `${folds[side] ? 'Mostrar' : 'Minimizar'} ${name}`;
    }
    renderPendingMark();
  }
  for (const side of ['left', 'right']) $(`fold-${side}`).addEventListener('click', () => { folds[side] = !folds[side]; store.set(`chakmati.${side}`, folds[side]); applyFolds(); });

  function applyLayout() {
    const layout = Shots.layoutFor(window.innerWidth);
    $('panel').dataset.layout = layout;
    placeRobot(layout);
    syncTopics();
    renderTopicHints();
    applyFolds();
    $('panel').dataset.focus = store.get('chakmati.focus', false) ? 'thread' : '';
    $('focus-thread').setAttribute('aria-pressed', String(!!store.get('chakmati.focus', false)));
    $('focus-thread').textContent = store.get('chakmati.focus', false) ? 'Reduzir' : 'Ampliar';
    const mode = (state && state.panelMode) || 'compact';
    $('expand').setAttribute('aria-label', mode === 'compact' ? 'Expandir a janela' : 'Voltar ao tamanho pequeno');
    $('expand').title = mode === 'compact' ? 'Expandir a janela' : 'Voltar ao tamanho pequeno';
    $('maximize').hidden = mode === 'compact';
    $('maximize').setAttribute('aria-label', mode === 'full' ? 'Sair da tela cheia' : 'Tela cheia');
    $('maximize').title = mode === 'full' ? 'Sair da tela cheia' : 'Tela cheia';
    renderScreen();
  }
  window.addEventListener('resize', applyLayout);
  $('expand').addEventListener('click', () => api.setLayout(((state && state.panelMode) || 'compact') === 'compact' ? 'wide' : 'compact'));
  $('maximize').addEventListener('click', () => api.setLayout(((state && state.panelMode) || 'compact') === 'full' ? 'wide' : 'full'));

  // each topic folds by its title (Enter or Space too); the choice is remembered
  const topicSyncs = [];
  for (const id of TOPICS) {
    const section = $(id);
    const title = section.querySelector('h2');
    title.setAttribute('role', 'button');
    title.tabIndex = 0;
    const hint = h('small', { class: 'topic-hint', id: `hint-${id}` });
    title.append(hint);
    const sync = () => { if (folded.has(id)) section.dataset.collapsed = '1'; else delete section.dataset.collapsed; title.setAttribute('aria-expanded', String(!folded.has(id))); };
    const toggle = () => {
      const set = foldedBy[layoutNow()];
      if (set.has(id)) set.delete(id); else set.add(id);
      store.set(`chakmati.folded-${layoutNow()}`, [...set]);
      sync();
    };
    title.addEventListener('click', toggle);
    title.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    topicSyncs.push(sync);
    sync();
  }
  const syncTopics = () => topicSyncs.forEach((f) => f());

  // what is inside a folded topic, in a few words (so folding it does not hide whether anything is there)
  function renderTopicHints() {
    if (!state) return;
    const o = state.overview || {};
    const wa = o.whatsapp || {};
    const unread = (wa.unread || []).length;
    const set = (id, text) => { const e = $(`hint-${id}`); if (e) e.textContent = text; };
    set('messages', !wa.enabled ? 'WhatsApp desligado' : (wa.error || wa.connected === false) ? 'WhatsApp desconectado' : unread ? plural(unread, 'conversa com novidade', 'conversas com novidade') : 'nada novo');
    set('automations', (o.automations || []).length ? plural(o.automations.length, 'automação', 'automações') : 'nenhuma');
    set('agenda', (((o.calendar || {}).today) || []).length ? plural(o.calendar.today.length, 'compromisso hoje', 'compromissos hoje') : 'livre hoje');
    set('recent', (state.notices || []).length ? plural(state.notices.length, 'aviso', 'avisos') : 'nenhum');
  }
  // "Ampliar": the conversation takes the card and every other topic folds (their own choices come back when it is reduced)
  function setFocus(on) { store.set('chakmati.focus', on); applyLayout(); renderThread(true); }
  $('focus-thread').addEventListener('click', () => setFocus(!store.get('chakmati.focus', false)));
  // the strip of two lines opens when it is clicked; a question for the person (the user name, a password) opens it by itself
  $('thread').addEventListener('click', () => { if ($('panel').dataset.layout === 'compact' && !store.get('chakmati.focus', false)) setFocus(true); });

  // the screen: the browser as it is right now. Each new picture fades in over the last one: nothing says it is a sequence of pictures.
  let frontImg = $('screen-img-a');
  let backImg = $('screen-img-b');
  let shownSrc = '';
  function renderScreen() {
    const view = Shots.screenView(thread, null);
    $('screen-empty').hidden = !!view;
    $('screen-view').hidden = !view;
    $('screen-live').hidden = !(view && view.live);
    $('fold-right-live').hidden = !(view && view.live);
    if (!view) { shownSrc = ''; return; }
    const cur = view.current;
    $('screen-url').textContent = cur.url;
    $('screen-note').textContent = cur.note;
    if (cur.image && cur.image !== shownSrc) {
      shownSrc = cur.image;
      const next = backImg;
      next.setAttribute('src', cur.image);
      const show = () => { next.classList.add('on'); frontImg.classList.remove('on'); [frontImg, backImg] = [next, frontImg]; };
      if (typeof next.decode === 'function') next.decode().then(show, show); else show();
    }
  }

  // the big robot: in the expanded window it leaves the header and stands above the conversation
  const robotBox = $('head-robot');
  const robotHome = robotBox.parentNode;
  const robotNext = robotBox.nextSibling;
  function placeRobot(layout) {
    if (layout === 'wide') { if (robotBox.parentNode !== $('hero')) $('hero').appendChild(robotBox); }
    else if (robotBox.parentNode !== robotHome) robotHome.insertBefore(robotBox, robotNext);
  }

  api.onOtherSpeaking((on) => { otherSpeaking = on; if (!on) { quietUntil = Date.now() + 700; chimeIfWaiting(); } });
  // second line of defence: whatever asks the page to scroll (focus, find, a keyboard shortcut) is put back at the top
  window.addEventListener('scroll', () => { if (window.scrollY || document.scrollingElement.scrollTop) window.scrollTo(0, 0); });
  api.onState((s) => { state = s; stateVersion += 1; render(); applyLayout(); if (thread.length) renderThread(false); runQueued(); });
  applyLayout();
  api.ready();
})();
