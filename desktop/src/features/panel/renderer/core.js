// The panel page: shared state and helpers, the header, the views (main, settings, chats) and the render that redraws it all.

(function () {
  const P = window.Panel = { inits: [] };

  const api = window.assistant.panel;
  const $ = (id) => document.getElementById(id);
  const robot = window.Robot.create($('head-robot'));
  const { relativeTime } = window.RelTime;

  P.state = null;
  P.stateVersion = 0;
  P.speaking = false;
  const syncTalking = () => robot.setTalking(P.speaking || thread.some((t) => t.status === 'pending'));

  const thread = [];
  const decided = new Map();

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

  function renderHeader() {
    const d = P.state.describe;
    if (screen === 'main') {
      $('title').textContent = d.title;
      $('detail').textContent = d.detail;
    }
    robot.setMood(d.mood);
    $('retry').hidden = !!P.state.engineUp || screen !== 'main';   // the engine is not answering: one button to try again (restarts it when the app started it)
    if (P.state.overview && P.state.overview.awake && screen === 'main') $('input').focus();
  }

  function render() {
    if (!P.state) return;
    renderHeader();
    P.renderDecisions();
    P.renderMessages();
    P.renderAgenda();
    P.renderRecent();
    if (P.renderHouse) P.renderHouse();
    P.renderAutomations();
    P.renderPendingMark();
    P.renderTopicHints();
    P.renderSettings();
    P.syncSendButton();
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Each screen replaces the others: main (with the command line), Ajustes, the list of conversations, one conversation.
  // The frame never moves: header (arrow + title), the page (the only part that scrolls) and the footer. Pages swap inside it.
  const PAGES = { main: 'content', settings: 'settings-view', chats: 'chats-view', chat: 'chat-view' };
  const TITLES = { settings: 'Ajustes', chats: 'Conversas' };
  let screen = 'main';
  P.backTo = 'main';
  function setTitle(text) { if (screen !== 'main') $('title').textContent = text; }
  function showView(name, title) {
    screen = name;
    $('panel').dataset.screen = name;
    for (const [view, id] of Object.entries(PAGES)) $(id).hidden = view !== name;
    $('foot').hidden = name === 'settings';           // the command line is on every page except Ajustes
    $('foot-settings').hidden = name !== 'settings';  // Ajustes has its own fixed footer
    $(PAGES[name]).scrollTop = 0;
    if (name === 'settings' && P.showSettingsMenu) P.showSettingsMenu();   // Ajustes always opens on its list (features/settings/renderer/menu.js)
    if (name === 'main') { renderHeader(); $('input').focus(); } else $('title').textContent = title || TITLES[name] || '';
    if (P.onScreen) P.onScreen(name);   // the WhatsApp conversation folds its boxes and, in the big window, keeps the sides (features/whatsapp/renderer/dock.js)
  }
  // from an open item of Ajustes the arrow goes back to the list of items; only from the list does it leave Ajustes
  const goBack = () => { if (screen === 'settings' && P.settingsBack && P.settingsBack()) return; showView(screen === 'chat' ? P.backTo : 'main'); };

  P.inits.push(function () {
    if (/Mac/.test(navigator.platform || navigator.userAgent)) document.body.dataset.blur = '';

    $('open-settings').addEventListener('click', () => showView('settings'));
    $('retry').addEventListener('click', () => { $('retry').textContent = 'Tentando…'; if (P.state && P.state.ownsEngine) api.restart(); else api.refresh(); setTimeout(() => { $('retry').textContent = 'Tentar de novo'; }, 4000); });
    $('back').addEventListener('click', goBack);

    $('close').addEventListener('click', () => { showView('main'); api.close(); });
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (screen !== 'main') goBack();
      else if (document.activeElement && document.activeElement.matches('input, textarea') && document.activeElement.value.trim()) document.activeElement.blur();  // a half-written message is not thrown away by a stray Esc
      else api.close();
    });
    $('panic').addEventListener('click', () => api.panic());
    $('restart').addEventListener('click', () => api.restart());

    // second line of defence: whatever asks the page to scroll (focus, find, a keyboard shortcut) is put back at the top
    window.addEventListener('scroll', () => { if (window.scrollY || document.scrollingElement.scrollTop) window.scrollTo(0, 0); });
  });

  P.robot = robot;   // layout.js shows his alcove and door in the big window
  Object.assign(P, { api, $, relativeTime, syncTalking, thread, decided, h, fill, plural, render, sleep, showView });

})();
