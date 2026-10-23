// Builds the robot's SVG with DOM calls (no innerHTML) and exposes setMood(). Moods: idle, alert, thinking, happy, offline.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const el = (name, attrs = {}, parent) => {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    if (parent) parent.appendChild(node);
    return node;
  };

  function create(container) {
    const svg = el('svg', { viewBox: '0 0 80 80', class: 'robot', 'data-mood': 'idle', role: 'img', 'aria-label': 'Robô assistente' }, container);
    el('ellipse', { class: 'shadow', cx: 40, cy: 76, rx: 20, ry: 3 }, svg);
    el('line', { class: 'mast', x1: 40, y1: 14, x2: 40, y2: 7 }, svg);
    el('circle', { class: 'lamp', cx: 40, cy: 6, r: 3.6 }, svg);
    el('rect', { class: 'ear', x: 3, y: 34, width: 6, height: 16, rx: 3 }, svg);
    el('rect', { class: 'ear', x: 71, y: 34, width: 6, height: 16, rx: 3 }, svg);
    el('rect', { class: 'head', x: 8, y: 14, width: 64, height: 56, rx: 20 }, svg);
    el('rect', { class: 'screen', x: 16, y: 23, width: 48, height: 38, rx: 14 }, svg);
    el('rect', { class: 'eye', x: 26, y: 35, width: 8, height: 13, rx: 4 }, svg);
    el('rect', { class: 'eye', x: 46, y: 35, width: 8, height: 13, rx: 4 }, svg);
    el('rect', { class: 'eye-flat', x: 25, y: 41, width: 10, height: 2.4, rx: 1.2 }, svg);
    el('rect', { class: 'eye-flat', x: 45, y: 41, width: 10, height: 2.4, rx: 1.2 }, svg);
    el('path', { class: 'arc', d: 'M25.5 43 q4.5 -9 9 0' }, svg);
    el('path', { class: 'arc', d: 'M45.5 43 q4.5 -9 9 0' }, svg);
    el('path', { class: 'smile', d: 'M34 52 q6 5 12 0' }, svg);
    const dots = el('g', { class: 'dots' }, svg);
    [30, 40, 50].forEach((cx) => el('circle', { cx, cy: 42, r: 3.2 }, dots));
    return {
      svg,
      setMood(mood) { svg.setAttribute('data-mood', ['idle', 'alert', 'thinking', 'happy', 'offline'].includes(mood) ? mood : 'idle'); },
    };
  }

  window.Robot = { create };
})();
