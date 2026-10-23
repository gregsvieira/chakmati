// Chakmati: a tin-can head with a yellow hat, big sleepy eyes under blue eyelids, a red nose and a green chin flap for a mouth.
// Built with DOM calls (no innerHTML). setMood(): idle, alert, thinking, happy, offline.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const el = (name, attrs = {}, parent) => {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    if (parent) parent.appendChild(node);
    return node;
  };

  function eye(svg, cx, cy, clipId, side) {
    const outer = el('g', { transform: `translate(${cx} ${cy})` }, svg);
    const clip = el('clipPath', { id: clipId }, outer);
    el('circle', { r: 7.6 }, clip);
    el('circle', { class: 'socket', r: 8.6 }, outer);
    const inner = el('g', { 'clip-path': `url(#${clipId})` }, outer);
    el('circle', { class: 'sclera', r: 7.6 }, inner);
    const look = el('g', { class: 'look' }, inner);
    el('circle', { class: 'iris', r: 4.6, cx: side * 0.4 }, look);
    el('circle', { class: 'pupil', r: 2.2, cx: side * 0.4 }, look);
    el('circle', { class: 'glint', r: 0.9, cx: side * 0.4 - 1, cy: -1.2 }, look);
    el('rect', { class: 'lid lid-up', x: -8.2, y: -8.2, width: 16.4, height: 16.4 }, inner);
    el('rect', { class: 'lid lid-down', x: -8.2, y: -8.2, width: 16.4, height: 16.4 }, inner);
    el('path', { class: 'lash', d: `M${6 * side} -6.5 q${3 * side} -1 ${3.4 * side} -4` }, outer);
  }

  function create(container) {
    const svg = el('svg', { viewBox: '0 0 80 80', class: 'robot', 'data-mood': 'idle', role: 'img', 'aria-label': 'Chakmati' }, container);
    el('ellipse', { class: 'shadow', cx: 40, cy: 77, rx: 18, ry: 2.6 }, svg);

    // bow tie (behind the chin)
    const tie = el('g', { class: 'tie' }, svg);
    el('path', { class: 'tie-wing', d: 'M40 70 L26 64 Q24 70 26 76 Z' }, tie);
    el('path', { class: 'tie-wing', d: 'M40 70 L54 64 Q56 70 54 76 Z' }, tie);
    [[30, 70], [34, 72.5], [49, 67.5], [46, 72]].forEach(([x, y]) => el('circle', { class: 'tie-dot', cx: x, cy: y, r: 1 }, tie));
    el('circle', { class: 'tie-knot', cx: 40, cy: 70, r: 2.6 }, tie);

    // head: a metal cylinder
    el('rect', { class: 'head', x: 20, y: 12, width: 40, height: 54, rx: 17 }, svg);
    el('path', { class: 'shine', d: 'M25 26 q-1 14 1 26' }, svg);

    eye(svg, 31, 31, 'clip-l', -1);
    eye(svg, 49, 31, 'clip-r', 1);

    // nose
    el('circle', { class: 'nose', cx: 40, cy: 43, r: 5.6 }, svg);
    el('circle', { class: 'nose-shine', cx: 38.2, cy: 41, r: 1.4 }, svg);

    // mouth: red inside, green chin flap on top that drops when Chakmati is happy
    el('path', { class: 'mouth-in', d: 'M25 51.5 Q40 55 55 51.5 L55 56 Q40 59.5 25 56 Z' }, svg);
    const flap = el('g', { class: 'flap' }, svg);
    el('path', { class: 'chin', d: 'M24.5 52 Q40 56 55.5 52 L52.5 63.5 Q40 69 27.5 63.5 Z' }, flap);
    el('path', { class: 'chin-line', d: 'M24.5 52 Q40 56 55.5 52' }, flap);
    el('circle', { class: 'screw', cx: 29.5, cy: 59, r: 1.1 }, flap);
    el('circle', { class: 'screw', cx: 51, cy: 59, r: 1.1 }, flap);

    // hat: crown, red band, brim
    const hat = el('g', { class: 'hat' }, svg);
    el('rect', { class: 'crown', x: 20.5, y: 2.5, width: 39, height: 13, rx: 3 }, hat);
    el('rect', { class: 'band', x: 20.5, y: 10.8, width: 39, height: 3.6 }, hat);
    el('ellipse', { class: 'brim', cx: 40, cy: 16.2, rx: 25, ry: 3.4 }, hat);
    el('path', { class: 'curl', d: 'M17 22 q-3 1 -3 3.6 q1.6 -1.4 3.2 -.8 q-2.6 .6 -2.4 2.6' }, svg);
    el('path', { class: 'curl', d: 'M63 22 q3 1 3 3.6 q-1.6 -1.4 -3.2 -.8 q2.6 .6 2.4 2.6' }, svg);

    return {
      svg,
      setMood(mood) { svg.setAttribute('data-mood', ['idle', 'alert', 'thinking', 'happy', 'offline'].includes(mood) ? mood : 'idle'); },
    };
  }

  window.Robot = { create };
})();
