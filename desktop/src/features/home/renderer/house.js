// "Casa e Alexa" on the main page, above the automations: the speakers, each one opening to what is playing and its buttons (previous, pause/play, next, volume, and
// "Trocar música", which asks the Echo for something else). It only exists while the house is connected, and it only asks the engine while it is on screen and open.

(function () {
  const P = window.Panel;
  const { api, $, fill, plural } = P;

  const open = new Set();        // the speakers that are expanded
  const searching = new Set();   // the ones showing the "Trocar música" field
  const drafts = new Map();      // what was typed in each field: the list is redrawn every few seconds and must not take it away
  const infoOpen = new Set();    // the speakers whose (i) is open: the list is redrawn every few seconds and must not close it
  const UNAVAILABLE_INFO = 'A Amazon limita os pedidos do Home Assistant, e por isso a Alexa não está dizendo o que toca agora. Pedir uma música pelo botão abaixo ou por voz ainda funciona.';
  let players = [];
  let note = '';                 // the last answer of a button, or the problem
  let busy = '';                 // the speaker whose button was just pressed
  let timer = null;

  const connected = () => !!(P.state && P.state.overview && P.state.overview.home && P.state.overview.home.connected);
  const onScreen = () => connected() && !document.hidden && P.state.panelOpen !== false && !$('house').hidden && !$('house').dataset.collapsed;
  const word = { playing: 'tocando', paused: 'pausado', idle: 'parado', unavailable: 'sem informação agora', standby: 'em espera' };

  async function refresh() {
    if (!connected()) return;
    const res = await api.homePlayers();
    players = (res && res.players) || [];
    if (res && res.error) note = res.error;
    draw();
  }

  async function press(player, action, text = '') {
    busy = player.id;
    note = '';
    draw();
    const res = await api.homePlayerControl(player.id, action, text);
    busy = '';
    note = (res && (res.error || res.message)) || '';
    if (action === 'search' && res && res.ok) { searching.delete(player.id); drafts.delete(player.id); }
    draw();
    setTimeout(refresh, 1500);   // Alexa takes a moment to start the new song: the panel shows it as soon as it does
  }

  const button = (label, title, onclick, disabled) => P.h('button', { class: 'ghost small', type: 'button', title, 'aria-label': title, onclick, disabled: disabled || undefined }, label);

  function card(p) {
    const expanded = open.has(p.id);
    const playing = p.state === 'playing';
    const sub = (playing || p.state === 'paused') && p.title ? `♪ ${p.title}${p.artist ? ` — ${p.artist}` : ''}${p.state === 'paused' ? ' (pausada)' : ''}` : (word[p.state] || p.state);
    const unavailable = p.state === 'unavailable';
    const moreInfo = unavailable && infoOpen.has(p.id);   // the reason sits behind the (i): one short line is enough until the person asks
    const say = unavailable ? 'A Alexa não está mandando informações agora.' : (playing || p.state === 'paused') && !p.title ? 'Tocando algo sem título' : '';
    const head = P.h('button', {
      class: 'house-head', type: 'button', 'aria-expanded': String(expanded), onclick: () => { if (expanded) open.delete(p.id); else open.add(p.id); draw(); },
    }, P.h('span', { class: 'house-name' }, p.name), P.h('span', { class: 'house-state', 'data-playing': (playing || p.state === 'paused') && p.title ? '1' : undefined }, sub));
    if (!expanded) return P.h('div', { class: 'house-card' }, head);
    const off = busy === p.id;
    const field = searching.has(p.id) ? (() => {
      const input = P.h('input', { type: 'text', class: 'house-search', maxlength: '100', placeholder: 'O que tocar? (ex.: Raul Seixas)', 'aria-label': 'O que tocar', 'data-player': p.id });
      input.value = drafts.get(p.id) || '';
      const go = () => { const q = input.value.trim(); if (q) press(p, 'search', q); };
      input.addEventListener('input', () => drafts.set(p.id, input.value));
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); if (e.key === 'Escape') { searching.delete(p.id); drafts.delete(p.id); draw(); } });
      if (!drafts.has(p.id) && !focusedField()) setTimeout(() => input.focus(), 0);   // a field that just opened gets the cursor; a redraw gives it back to the one that had it (draw)
      return P.h('div', { class: 'house-searchrow' }, input, button('Tocar', 'Pedir esta música à Alexa', go, off));
    })() : null;
    return P.h('div', { class: 'house-card', 'data-open': '1' }, head,
      P.h('div', { class: 'house-body' },
        (say ? P.h('p', { class: 'house-now' }, say, unavailable ? P.h('button', {
          class: 'info-btn', type: 'button', title: 'Por que isso acontece?', 'aria-label': 'Por que isso acontece?', 'aria-expanded': String(moreInfo),
          onclick: () => { if (infoOpen.has(p.id)) infoOpen.delete(p.id); else infoOpen.add(p.id); draw(); },
        }, 'i') : null) : null),
        (moreInfo ? P.h('p', { class: 'house-info', role: 'note' }, UNAVAILABLE_INFO) : null),
        P.h('div', { class: 'house-buttons' },
          button('⏮', 'Música anterior', () => press(p, 'previous'), off || !p.can.previous),
          playing ? button('⏸', 'Pausar', () => press(p, 'pause'), off || !p.can.pause) : button('▶', 'Continuar tocando', () => press(p, 'play'), off || !p.can.play),
          button('⏭', 'Próxima música', () => press(p, 'next'), off || !p.can.next),
          button('−', 'Diminuir o volume', () => press(p, 'volume_down'), off || !p.can.volume),
          P.h('span', { class: 'house-volume', 'aria-label': 'Volume' }, p.volume === null ? 'volume' : `${p.volume}%`),
          button('+', 'Aumentar o volume', () => press(p, 'volume_up'), off || !p.can.volume),
          button('Trocar música', 'Pedir outra música à Alexa', () => { if (searching.has(p.id)) searching.delete(p.id); else searching.add(p.id); draw(); }, off)),
        field));
  }

  // the search field that has the cursor, with where the cursor is: the list is rebuilt, and the cursor must stay where the person is typing
  const focusedField = () => { const a = document.activeElement; return a && a.classList && a.classList.contains('house-search') ? a : null; };

  function draw() {
    const had = focusedField();
    const keep = had ? { id: had.dataset.player, from: had.selectionStart, to: had.selectionEnd } : null;
    $('house-empty').hidden = players.length > 0;
    $('house-empty').textContent = 'Nenhum aparelho de música apareceu ainda.';
    fill($('house-list'), players.map(card));
    if (keep) {
      const again = $('house-list').querySelector(`.house-search[data-player="${keep.id}"]`);
      if (again) { again.focus(); try { again.setSelectionRange(keep.from, keep.to); } catch { /* the cursor position is a nicety */ } }
    }
    $('house-note').hidden = !note;
    $('house-note').textContent = note;
    hint();
  }

  function hint() {
    const e = $('hint-house');
    if (!e) return;
    const list = players.length ? players : ((P.state && P.state.overview && P.state.overview.home && P.state.overview.home.players) || []);
    const playing = list.filter((x) => x.state === 'playing');
    e.textContent = playing.length ? (playing[0].title ? `tocando: ${playing[0].title}` : `${playing[0].name} tocando`) : list.length ? plural(list.length, 'aparelho', 'aparelhos') : 'nenhum aparelho';
  }

  function renderHouse() {
    const on = connected();
    $('house').hidden = !on;
    if (!on) { players = []; return; }
    hint();
    if (!players.length) refresh();
  }

  P.inits.push(function () {
    // while it is on screen and open, the speakers are read now and then: the song changes by itself
    timer = setInterval(() => { if (onScreen()) refresh(); }, 6000);
    $('house').querySelector('h2').addEventListener('click', () => setTimeout(() => { if (onScreen()) refresh(); }, 50));
  });

  Object.assign(P, { renderHouse, houseHint: hint, houseRefresh: refresh });
  void timer;
})();
