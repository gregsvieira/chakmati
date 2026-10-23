(function () {
  const api = window.assistant.panel;
  const $ = (id) => document.getElementById(id);
  const robot = window.Robot.create($('head-robot'));
  const { relativeTime } = window.RelTime;

  let state = null;
  let stateVersion = 0; // counts the states received; a card only says "Concluído." after a state newer than its answer
  let speaking = false;
  const syncTalking = () => robot.setTalking(speaking || thread.some((t) => t.status === 'pending')); // the mouth moves while answering and while speaking
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

  // The engine marks a proposal with [[action:<id>]]; the person sees one short sentence and the approval buttons instead.
  function setTurnText(turn, text) {
    const m = /\[\[action:([0-9a-f]{32})\]\]/.exec(text || '');
    turn.actionId = m ? m[1] : null;
    turn.sinceState = stateVersion;
    turn.raw = text || ''; // the marker can arrive split across chunks, so the raw text is kept and the shown text derived from it
    turn.text = (text || '').replace(/\s*\[\[action:[0-9a-f]{32}\]\]\s*/g, '').replace(/\s*\[\[[^\]]*$/, '').trim();
  }

  async function decideTurn(turn, mode) {
    turn.decision = { text: mode === 'reject' ? 'Recusando…' : 'Enviando…' };
    renderThread();
    if (mode === 'always') await api.setSetting('autoSend', true);
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
    if (state.settings.autoSend) return h('p', { class: 'decision-result' }, 'Envio automático ligado: enviando…');
    return h('div', { class: 'decision-actions turn-actions' },
      h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'reject') }, 'Recusar'),
      item.kind === 'whatsapp.send' ? h('button', { class: 'ghost', type: 'button', onclick: () => decideTurn(turn, 'always') }, 'Aprovar para as próximas') : null,
      h('button', { class: 'primary', type: 'button', onclick: () => decideTurn(turn, 'approve') }, 'Aprovar'));
  }

  function renderThread(scroll = true) {
    $('thread-section').hidden = thread.length === 0;
    fill($('thread'), thread.map((t) => h('div', { class: `turn ${t.role}${t.status === 'pending' ? ' pending' : ''}${t.status === 'error' ? ' error' : ''}` }, t.text || '…', approvalNode(t))));
    syncTalking();
    if (!scroll) return;
    const content = $('content');
    content.scrollTop = content.scrollHeight;
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
    $('set-mic').value = state.settings.micSource;
    $('set-autosend').checked = !!state.settings.autoSend;
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
  async function submit(text, { voice = false } = {}) {
    const clean = text.trim();
    if (!clean || (state && state.busy)) return;
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
    if (event.type === 'job') turn.text = turn.text || 'Trabalhando nisso…';
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
    window.Voice.speak(text, { emojis: !!state.settings.speakEmojis, onStart: () => { speaking = true; speakingSince = Date.now(); syncTalking(); }, onEnd: () => { speaking = false; quietUntil = Date.now() + 700; syncTalking(); updateHint(); chimeIfWaiting(); } });
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

  function updateHint() {
    if (!state) return;
    const talk = state.settings.talk;
    const awake = !!(state.overview && state.overview.awake);
    input.placeholder = !talk ? 'Peça algo ao Chakmati…' : awake ? 'Aguardando seu comando… fale agora' : 'Escutando… diga “Ôh, Xácmáti”';
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
    if (state && state.settings.talk && state.overview && state.overview.awake) chime();
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
      if (!window.ListenPolicy.shouldAct({ text, wake: res.wake, awake: res.awake })) return;
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
  fill($('chips'), CHIPS.map((c) => h('button', {
    class: 'chip', type: 'button',
    onclick: () => {
      showSuggestions(false);
      if (c.run) submit(c.run);
      else { $('input').value = c.fill; $('input').focus(); }
    },
  }, c.label)));

  // The shortcuts are suggestions: they rise above the command line when the person clicks it, and go away again.
  const showSuggestions = (on) => $('chips').classList.toggle('open', on);
  $('chips').addEventListener('mousedown', (e) => e.preventDefault()); // clicking a suggestion must not take the focus from the field

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
  $('set-autosend').addEventListener('change', (e) => api.setSetting('autoSend', e.target.checked));
  $('set-emojis').addEventListener('change', (e) => api.setSetting('speakEmojis', e.target.checked));
  $('set-mic').addEventListener('change', (e) => api.setSetting('micSource', e.target.value));
  $('set-hear').addEventListener('change', (e) => api.setSetting('hear', e.target.checked));
  $('set-talk').addEventListener('change', (e) => api.setSetting('talk', e.target.checked));
  micButton.addEventListener('click', () => api.setSetting('talk', !state.settings.talk));
  $('set-still').addEventListener('change', (e) => api.setSetting('still', e.target.checked));
  $('set-mood').addEventListener('change', (e) => api.setSetting('mood', e.target.value));
  $('set-side').addEventListener('change', (e) => api.setSetting('bubbleSide', e.target.value));

  api.onOtherSpeaking((on) => { otherSpeaking = on; if (!on) { quietUntil = Date.now() + 700; chimeIfWaiting(); } });
  api.onState((s) => { state = s; stateVersion += 1; render(); if (thread.length) renderThread(false); runQueued(); });
  api.ready();
})();
