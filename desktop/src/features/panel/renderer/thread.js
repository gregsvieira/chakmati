// The conversation: the thread, the message bubbles (plan card, links), sending, Parar, the suggestion chips and the composer.

(function () {
  const P = window.Panel;
  const { $, syncTalking, thread, fill, api, store } = P;

  // The engine marks a proposal with [[action:<id>]]; the person sees one short sentence and the approval buttons instead.
  function setTurnText(turn, text) {
    const m = /\[\[action:([0-9a-f]{32})\]\]/.exec(text || '');
    turn.actionId = m ? m[1] : null;
    turn.sinceState = P.stateVersion;
    turn.raw = text || ''; // the marker can arrive split across chunks, so the raw text is kept and the shown text derived from it
    turn.text = (text || '').replace(/\s*\[\[action:[0-9a-f]{32}\]\]\s*/g, '').replace(/\s*\[\[[^\]]*$/, '').trim();
  }

  // Addresses in a message: the text stays and a small link icon follows it; the icon opens the address in the person's own browser
  function linkNodes(text) {
    return window.Links.splitLinks(text).map((part) => part.url
      ? P.h('span', { class: 'link' }, part.url, P.h('button', { type: 'button', class: 'link-open', title: 'Abrir o link no navegador', 'aria-label': `Abrir ${part.url} no navegador`,
        onclick: (e) => { e.stopPropagation(); window.assistant.panel.openLink(part.url); } }, linkIcon()))
      : part.text);
  }
  function linkIcon() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('width', '14'); svg.setAttribute('height', '14'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M14 3h7v7h-2V6.4l-8.3 8.3-1.4-1.4L17.6 5H14V3zM5 5h6v2H5v12h12v-6h2v8H3V5h2z');
    path.setAttribute('fill', 'currentColor');
    svg.appendChild(path);
    return svg;
  }

  // "Plano:\n1. ...\n2. ..." at the start of an answer is a card: open while the Chakmati works, folded when it is done (the person can open it again)
  const PLAN = /^Plano:\n((?:\d+\.[^\n]*\n?)+)\n*/;
  function bodyNodes(turn) {
    const text = turn.text || '…';
    const m = PLAN.exec(text);
    if (!m) return [P.h('span', { class: 'turn-text' }, linkNodes(text))];
    const steps = m[1].trim().split('\n').map((l) => l.replace(/^\d+\.\s*/, ''));
    const open = turn.planOpen !== undefined ? turn.planOpen : turn.status === 'pending';
    const card = P.h('details', { class: 'plan', open, ontoggle: (e) => { turn.planOpen = e.currentTarget.open; } },
      P.h('summary', {}, `Plano (${steps.length} ${steps.length === 1 ? 'passo' : 'passos'})`), P.h('ol', {}, steps.map((t) => P.h('li', {}, t))));
    const rest = text.slice(m[0].length).trim();
    return rest ? [card, P.h('span', { class: 'turn-text' }, linkNodes(rest))] : [card];
  }

  // The reduced card (small window, conversation not enlarged) shows only the newest message, in two lines: a longer one shows its first line and its last (fold.js).
  const reducedNow = () => { const p = $('panel'); return p.dataset.layout === 'compact' && p.dataset.focus !== 'thread'; };
  let measureCanvas = null;
  function foldReduced() {
    const last = $('thread').querySelector(':scope > .turn:last-child .turn-text');
    const folded = $('thread').querySelector('.turn-text[data-folded]');
    if (!reducedNow()) { if (folded) renderThread(false); return; }   // enlarged or wide again: the whole text comes back (a fresh render)
    if (!last || last.dataset.folded || !last.clientWidth) return;
    measureCanvas = measureCanvas || document.createElement('canvas').getContext('2d');
    measureCanvas.font = getComputedStyle(last).font;
    const full = last.textContent;
    const result = window.Fold.fold(full, last.clientWidth - 6, (t) => measureCanvas.measureText(t).width);   // a little margin: the canvas and the page do not wrap to the pixel
    if (!result.folded) return;
    last.textContent = result.text;
    last.dataset.folded = '1';
    last.title = full;   // the whole text, on hover
  }
  P.foldReduced = foldReduced;

  function renderThread(scroll = true) {
    $('thread-section').hidden = thread.length === 0;
    const box = $('thread');
    const typing = thread.find((t) => t.askInput && t.askInput === document.activeElement);
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40; // do not yank the reader away from older messages
    fill(box, thread.map((t) => P.h('div', { class: `turn ${t.role}${t.status === 'pending' ? ' pending' : ''}${t.status === 'error' ? ' error' : ''}` }, P.shotNode(t), bodyNodes(t), P.approvalNode(t), P.askNode(t))));
    syncTalking();
    P.renderScreen();
    const wanted = typing || thread.find((t) => t.focusAsk && t.askInput);
    if (wanted) { wanted.focusAsk = false; wanted.askInput.focus(); }
    if (scroll || atBottom) box.scrollTop = box.scrollHeight;  // the conversation has its own scroll: it follows the newest message
    if (scroll) $('thread-section').scrollIntoView({ block: 'end' }); // and a new message brings the conversation into view on the page
    foldReduced();
  }

  async function submit(text, { voice = false } = {}) {
    stage = null;   // the request is sent: the automation choices are over
    const clean = text.trim();
    if (!clean || (P.state && P.state.busy)) return;
    if (P.trySettings(clean)) return;
    const waiting = thread.slice().reverse().find((t) => t.own && !t.decision);
    if (waiting && /regrav|grav\w* (de novo|novamente)/i.test(clean)) { P.redoOwnVoice(waiting); return; }
    thread.push({ role: 'user', text: clean, status: 'done' });
    const res = await api.send(clean, P.attachedIds ? P.attachedIds() : []);
    if (!res || res.error) {
      thread.push({ role: 'assistant', text: (res && res.error) || 'Não consegui enviar o pedido.', status: 'error' });
    } else {
      thread.push({ id: res.id, role: 'assistant', text: '', status: 'pending', voice });
    }
    while (thread.length > 10) thread.shift();
    renderThread();
  }

  // Busy: the send button is "Parar" and the field says what is going on (nothing is silently ignored)
  function syncSendButton() {
    const busy = !!(P.state && P.state.busy);
    const btn = $('send');
    btn.dataset.mode = busy ? 'stop' : 'send';
    btn.disabled = false;
    btn.setAttribute('aria-label', busy ? 'Parar' : 'Enviar');
    btn.title = busy ? 'Parar o que o Chakmati está fazendo' : 'Enviar';
    P.updateHint();
  }

  function stopWork() {
    const turn = thread.slice().reverse().find((t) => t.status === 'pending');
    if (turn) api.cancel(turn.id);
  }

  function say(text) { thread.push({ role: 'assistant', text, status: 'error' }); renderThread(); }

  const CHIPS = [
    { label: 'Mensagens novas', run: 'tenho mensagens novas no whatsapp?' },
    { label: 'Agenda de hoje', run: 'o que tenho na agenda hoje?' },
    { label: 'Resumir uma conversa', fill: 'resuma a conversa com ' },
    { label: 'Enviar mensagem', fill: 'manda no whatsapp pra ' },
    { label: 'Marcar compromisso', fill: 'marque ' },
  ];
  // The request grows as the person picks: the channel, the hours it works, then how it answers. "Crie uma automação: sempre que alguém me escrever no WhatsApp
  // entre as 22:00 e as 07:00, responda em áudio: " (the person adds the reply).
  const BASE = 'Crie uma automação: sempre que alguém me escrever no WhatsApp';
  const when = (h) => (h ? ` entre as ${h.from} e as ${h.to}` : '');
  const prompt = (h, tail) => `${BASE}${when(h)}, responda${tail}`;
  // Stage 3: how the reply is made. Text and audio are written by the person (the audio is recorded by Chakmati in the
  // voice in use); "Minha fala" is recorded by the person.
  const modeChips = (h) => [
    { label: 'Áudio', media: true, fill: prompt(h, ' em áudio: ') },
    { label: 'Texto', fill: prompt(h, ': ') },
    { label: 'Minha fala', media: true, own: true, hours: h },
  ];
  // Stage 2: the hours the automation works ("horário de funcionamento"); outside them it does nothing. A window may cross midnight.
  const hoursChip = (label, h) => ({ label, fill: `${BASE}${when(h)}`, next: modeChips(h) });
  const HOURS_CHIPS = [
    hoursChip('Sempre', null),
    hoursChip('À noite (22:00 às 07:00)', { from: '22:00', to: '07:00' }),
    hoursChip('Fora do expediente (18:00 às 08:00)', { from: '18:00', to: '08:00' }),
    hoursChip('Madrugada (00:00 às 06:00)', { from: '00:00', to: '06:00' }),
    { label: 'Outro horário', fill: `${BASE} entre as ` },   // the person types the hours ("22:00 e as 07:50, responda: ...")
  ];
  // The house and the Alexa: at a time of day, do things in the house or play music. The request grows as the person picks: when, then what.
  const HOUSE_BASE = 'Crie uma automação:';
  const houseWhat = (when) => [
    { label: 'Ligar a luz e abrir a cortina', fill: `${HOUSE_BASE} ${when} ligue a luz do quarto e abra a cortina do quarto` },
    { label: 'Fechar a cortina e apagar a luz', fill: `${HOUSE_BASE} ${when} feche a cortina do quarto e apague a luz do quarto` },
    { label: 'Tocar uma música', fill: `${HOUSE_BASE} ${when} toque Raul Seixas na Alexa` },
    { label: 'Outra coisa', fill: `${HOUSE_BASE} ${when} ` },
  ];
  const houseWhenChip = (label, when) => ({ label, fill: `${HOUSE_BASE} ${when} `, next: houseWhat(when) });
  const HOUSE_WHEN_CHIPS = [
    houseWhenChip('Todo dia às 07:00', 'todo dia às 7h'),
    houseWhenChip('Dias úteis às 06:30', 'de segunda a sexta às 6h30'),
    houseWhenChip('Fim de semana às 09:00', 'no fim de semana às 9h'),
    houseWhenChip('Todo dia às 22:00', 'todo dia às 22h'),
    { label: 'Outro horário', fill: `${HOUSE_BASE} todo dia às ` },   // the person types the time and what to do ("7h30 ligue a luz da sala")
  ];
  // Stage 1: the channel.
  P.AUTOMATION_CHIPS = [
    { label: 'WhatsApp', fill: `${BASE}: `, next: HOURS_CHIPS },
    { label: 'Casa e Alexa', fill: `${HOUSE_BASE} `, next: HOUSE_WHEN_CHIPS },
    { label: 'Email (em breve)', soon: true },
  ];
  let stage = null;   // the automation choices on screen now (null = the ordinary shortcuts): they stay until the request is sent or the field is edited by hand
  // This OpenWA may not be able to send files at all; then audio choices are shown as unavailable instead of failing later.
  const noMedia = () => !!(P.state && P.state.overview && P.state.overview.whatsapp && P.state.overview.whatsapp.media === false);
  P.renderChips = (list) => fill($('chips'), list.map((c) => P.h('button', {
    class: 'chip', type: 'button', disabled: !!c.soon || (!!c.media && noMedia()), title: c.media && noMedia() ? 'O OpenWA instalado não envia áudio.' : null,
    onclick: () => {
      if (c.own) { stage = null; showSuggestions(false); $('input').value = ''; P.recordOwnVoice(c.hours || null); return; }
      if (c.run) { showSuggestions(false); submit(c.run); return; }
      $('input').value = c.fill; $('input').focus(); grow();
      if (c.next) { stage = c.next; P.renderChips(c.next); } else { stage = null; showSuggestions(false); } // the next choice stays on screen
    },
  }, c.media && noMedia() ? `${c.label} (indisponível)` : c.label)));

  // The shortcuts are suggestions: they rise above the command line when the person clicks it, and go away again.
  const showSuggestions = (on) => {
    $('chips').classList.toggle('open', on);
    if (!on && !stage) P.renderChips(CHIPS);   // the automation choices are kept while the request is being built: clicking elsewhere (to open a topic, to scroll) only hides them
  };

  // "Criar" in Automações starts the choices from the channel
  P.startAutomationChips = () => { stage = P.AUTOMATION_CHIPS; P.renderChips(stage); };
  P.showSuggestions2 = () => $('chips').classList.add('open');
  const input = $('input');
  const grow = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 110)}px`; };

  P.inits.push(function () {
    api.onMessage(({ id, event }) => {
      const turn = thread.find((t) => t.id === id);
      if (!turn) return;
      if (event.type === 'screenshot') { Shots.addShot(turn, event); P.pickedStep = null; turn.text = turn.text || 'Usando o navegador…'; }
      else if (event.type === 'input') {
        turn.ask = { job_id: event.job_id, request_id: event.request_id, prompt: event.prompt, secret: !!event.secret, confirm: !!event.confirm };
        turn.askEl = null; turn.askSent = false; turn.focusAsk = true;
        if ($('panel').dataset.layout === 'compact' && !store.get('chakmati.focus', false)) { store.set('chakmati.focus', true); P.applyLayout(); }
        if (P.state && !P.state.panelOpen) api.reply(`${event.prompt} (abra o painel para responder)`);
      } else if (event.type === 'input_done') { turn.ask = null; turn.askEl = null; }
      else if (event.type === 'cancelled') {
        setTurnText(turn, `${turn.raw || (turn.text === 'Trabalhando nisso…' || turn.text === 'Usando o navegador…' ? '' : turn.text) || ''}\n\n${event.text || 'Interrompido por você.'}`.trim());
        turn.status = 'done'; turn.ask = null; turn.askEl = null;
      } else if (event.type === 'job') turn.text = turn.text || 'Trabalhando nisso…';
      else if (event.type === 'delta') { if (turn.text === 'Trabalhando nisso…') turn.raw = ''; setTurnText(turn, (turn.raw || '') + event.text); }
      else if (event.type === 'done') { setTurnText(turn, event.result || turn.text); turn.status = 'done'; P.deliver(turn); }
      else if (event.type === 'error') { turn.text = event.error || 'Algo deu errado.'; turn.status = 'error'; P.deliver(turn); }
      else if (event.type === 'end' && turn.status === 'pending') turn.status = 'done';
      renderThread();
    });

    P.renderChips(CHIPS);

    $('chips').addEventListener('mousedown', (e) => e.preventDefault());

    input.addEventListener('input', grow);
    // the suggestions rise when the field is clicked: when it is empty, or while an automation request is being built (its text is only the start of the request)
    input.addEventListener('pointerdown', () => { if (!input.value.trim() || stage) { if (stage) P.renderChips(stage); showSuggestions(true); } });
    input.addEventListener('input', () => { if (input.value.trim()) { stage = null; showSuggestions(false); } });   // typing by hand ends the choices
    input.addEventListener('blur', () => showSuggestions(false));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('composer').requestSubmit(); }
    });
    $('composer').addEventListener('submit', (e) => {
      e.preventDefault();
      if (P.state && P.state.busy) {   // working: the button stops it; Enter alone does not (so a stray Enter never kills a long job)
        if (e.submitter && e.submitter.id === 'send') stopWork();
        return;
      }
      const text = input.value;
      input.value = '';
      grow();
      submit(text);
    });
  });

  Object.assign(P, { renderThread, submit, syncSendButton, say, input });

})();
