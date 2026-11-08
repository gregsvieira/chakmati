// The big window: layout (compact, wide, full), folding topics and rails, the robot standing above the conversation.

(function () {
  const P = window.Panel;
  const { $, api, plural } = P;

  const store = {
    get(key, fallback) { try { const v = window.localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(key, value) { try { window.localStorage.setItem(key, JSON.stringify(value)); } catch { /* private window or storage off: the choice just is not remembered */ } },
  };
  const TOPICS = ['decisions', 'messages', 'agenda', 'house', 'automations', 'recent'];
  // Which topics are folded: in the small card they start folded (one line each, with a hint of what is inside), in the big window open (there is room).
  // Each layout remembers its own choices.
  const foldedBy = {
    compact: new Set(store.get('chakmati.folded-compact', TOPICS.filter((t) => t !== 'decisions'))),
    wide: new Set(store.get('chakmati.folded-wide', [])),
  };
  const layoutNow = () => ($('panel').dataset.layout === 'wide' ? 'wide' : 'compact');
  const folded = { has: (id) => foldedBy[layoutNow()].has(id) };
  P.pickedStep = null;

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
    P.renderPendingMark();
  }

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
    const mode = (P.state && P.state.panelMode) || 'compact';
    $('expand').setAttribute('aria-label', mode === 'compact' ? 'Expandir a janela' : 'Voltar ao tamanho pequeno');
    $('expand').title = mode === 'compact' ? 'Expandir a janela' : 'Voltar ao tamanho pequeno';
    $('maximize').hidden = mode === 'compact';
    $('maximize').setAttribute('aria-label', mode === 'full' ? 'Sair da tela cheia' : 'Tela cheia');
    $('maximize').title = mode === 'full' ? 'Sair da tela cheia' : 'Tela cheia';
    P.renderScreen();
  }

  // each topic folds by its title (Enter or Space too); the choice is remembered
  const topicSyncs = [];

  const syncTopics = () => topicSyncs.forEach((f) => f());

  // what is inside a folded topic, in a few words (so folding it does not hide whether anything is there)
  function renderTopicHints() {
    if (!P.state) return;
    const o = P.state.overview || {};
    const wa = o.whatsapp || {};
    const unread = (wa.unread || []).length;
    const set = (id, text) => { const e = $(`hint-${id}`); if (e) e.textContent = text; };
    set('messages', !wa.enabled ? 'WhatsApp desligado' : (wa.error || wa.connected === false) ? 'WhatsApp desconectado' : unread ? plural(unread, 'conversa com novidade', 'conversas com novidade') : 'nada novo');
    if (P.houseHint) P.houseHint();   // the house topic says what plays (features/home/renderer/house.js)
    set('automations', (o.automations || []).length ? plural(o.automations.length, 'automação', 'automações') : 'nenhuma');
    set('agenda', (((o.calendar || {}).today) || []).length ? plural(o.calendar.today.length, 'compromisso hoje', 'compromissos hoje') : 'livre hoje');
    set('recent', (P.state.notices || []).length ? plural(P.state.notices.length, 'aviso', 'avisos') : 'nenhum');
  }
  // "Ampliar": the conversation takes the card and every other topic folds (their own choices come back when it is reduced)
  function setFocus(on) { store.set('chakmati.focus', on); applyLayout(); P.renderThread(true); }

  // the big robot: in the expanded window it leaves the header and stands above the conversation
  const robotBox = $('head-robot');
  const robotHome = robotBox.parentNode;
  const robotNext = robotBox.nextSibling;
  function placeRobot(layout) {
    if (layout === 'wide') { if (robotBox.parentNode !== $('hero')) $('hero').appendChild(robotBox); }
    else if (robotBox.parentNode !== robotHome) robotHome.insertBefore(robotBox, robotNext);
  }

  P.inits.push(function () {
    for (const side of ['left', 'right']) $(`fold-${side}`).addEventListener('click', () => { folds[side] = !folds[side]; store.set(`chakmati.${side}`, folds[side]); applyFolds(); });

    window.addEventListener('resize', applyLayout);
    $('expand').addEventListener('click', () => api.setLayout(((P.state && P.state.panelMode) || 'compact') === 'compact' ? 'wide' : 'compact'));
    $('maximize').addEventListener('click', () => api.setLayout(((P.state && P.state.panelMode) || 'compact') === 'full' ? 'wide' : 'full'));

    for (const id of TOPICS) {
      const section = $(id);
      const title = section.querySelector('h2');
      title.setAttribute('role', 'button');
      title.tabIndex = 0;
      const hint = P.h('small', { class: 'topic-hint', id: `hint-${id}` });
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

    $('focus-thread').addEventListener('click', () => setFocus(!store.get('chakmati.focus', false)));
    // the strip of two lines opens when it is clicked; a question for the person (the user name, a password) opens it by itself
    $('thread').addEventListener('click', () => { if ($('panel').dataset.layout === 'compact' && !store.get('chakmati.focus', false)) setFocus(true); });
  });

  Object.assign(P, { store, applyLayout, renderTopicHints });

})();
