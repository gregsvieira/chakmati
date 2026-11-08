// Ajustes as a menu: a list of the items (an icon and the title of each), and a click opens only that item on a page of its own. To change another item the
// person goes back (the arrow, or Esc) to the list and picks it. The sections are the ones already on the page; this only chooses which one shows.

(function () {
  const P = window.Panel;
  const { $ } = P;
  const SVG = 'http://www.w3.org/2000/svg';

  // The title (as the section's own heading says it) -> its icon and the name in the list.
  const ITEMS = {
    'Integrações': { name: 'Integrações', icon: 'M9 3v4M15 3v4M7 7h10v5a5 5 0 01-10 0V7zM12 17v4' },
    'Voz': { name: 'Voz', icon: 'M12 3a3 3 0 013 3v5a3 3 0 01-6 0V6a3 3 0 013-3zM6 11a6 6 0 0012 0M12 17v4' },
    'IA paga': { name: 'IA paga', icon: 'M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2L12 3z' },
    'Assistente de Casa e Alexa': { name: 'Casa e Alexa', icon: 'M4 11l8-7 8 7v9H4zM10 20v-6h4v6' },
    'Jeito de falar': { name: 'Jeito de falar', icon: 'M4 5h16v11H9l-5 4V5z' },
    'Aparência': { name: 'Aparência', icon: 'M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2' },
    'Privacidade e envio': { name: 'Privacidade e envio', icon: 'M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3z' },
    'Atalhos': { name: 'Atalhos', icon: 'M3 7h18v10H3zM7 11h2M11 11h2M15 11h2M7 14h10' },
  };
  const FALLBACK = 'M5 12h14M12 5v14';
  let current = null;   // the section open, or null: the list

  const sections = () => [...$('settings-view').querySelectorAll(':scope > section.cat')];
  const titleOf = (section) => (section.querySelector('h3') || { textContent: '' }).textContent.trim();

  function svg(path, size = 22) {
    const node = document.createElementNS(SVG, 'svg');
    for (const [k, v] of Object.entries({ viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.9, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) node.setAttribute(k, v);
    const p = document.createElementNS(SVG, 'path');
    p.setAttribute('d', path);
    node.append(p);
    return node;
  }

  function buildMenu() {
    $('settings-menu').replaceChildren(...sections().map((section) => {
      const item = ITEMS[titleOf(section)] || { name: titleOf(section), icon: FALLBACK };
      const button = P.h('button', { type: 'button', class: 'menu-item', role: 'menuitem', onclick: () => showSection(section) },
        P.h('span', { class: 'menu-icon' }, svg(item.icon)), P.h('span', { class: 'menu-name' }, item.name), P.h('span', { class: 'menu-go' }, svg('M9 5l7 7-7 7', 18)));
      return button;
    }));
  }

  function showMenu() {
    current = null;
    if (!$('settings-menu').children.length) buildMenu();
    $('settings-menu').hidden = false;
    for (const s of sections()) { s.hidden = true; delete s.dataset.current; }
    $('title').textContent = 'Ajustes';
    $('settings-view').scrollTop = 0;
  }

  function showSection(section) {
    current = section;
    $('settings-menu').hidden = true;
    for (const s of sections()) { s.hidden = s !== section; if (s === section) s.dataset.current = '1'; else delete s.dataset.current; }
    const item = ITEMS[titleOf(section)];
    $('title').textContent = item ? item.name : titleOf(section);   // the header says which item this is, so the heading inside is not repeated
    $('settings-view').scrollTop = 0;
  }

  // The arrow (and Esc): from an item back to the list; from the list the panel goes back to the main page. true = handled here.
  P.settingsBack = () => { if (!current) return false; showMenu(); return true; };
  P.showSettingsMenu = showMenu;
})();
