// Chakmati: a tall, thin tin-can head with a yellow hat, big sleepy eyes under blue eyelids, a red nose and a green chin
// flap for a mouth. In the widget it leans out of a wooden alcove with a green door swung open beside it.
// Built with DOM calls (no innerHTML). setMood(): idle, alert, thinking, happy, offline.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const el = (name, attrs = {}, parent) => {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    if (parent) parent.appendChild(node);
    return node;
  };
  const stops = (parent, list) => list.forEach(([offset, cls]) => el('stop', { offset, class: cls }, parent));

  function defs(svg) {
    const d = el('defs', {}, svg);
    const head = el('linearGradient', { id: 'g-head', x1: 0, y1: 0, x2: 1, y2: 0 }, d);
    stops(head, [[0, 'hi'], [0.45, 'mid'], [1, 'lo']]);
    const wood = el('linearGradient', { id: 'g-wood', x1: 0, y1: 0, x2: 1, y2: 1 }, d);
    stops(wood, [[0, 'wood-hi'], [1, 'wood-lo']]);
    const door = el('linearGradient', { id: 'g-door', x1: 0, y1: 0, x2: 1, y2: 1 }, d);
    stops(door, [[0, 'door-hi'], [1, 'door-lo']]);
    const flap = el('linearGradient', { id: 'g-flap', x1: 0, y1: 0, x2: 1, y2: 0 }, d);
    stops(flap, [[0, 'flap-hi'], [1, 'flap-lo']]);
    const shade = el('radialGradient', { id: 'g-shade', cx: 0.5, cy: 0.5, r: 0.5 }, d);
    el('stop', { offset: 0, 'stop-color': '#000', 'stop-opacity': 0.5 }, shade);
    el('stop', { offset: 1, 'stop-color': '#000', 'stop-opacity': 0 }, shade);
  }

  // The far eye is drawn narrower (scale) because the head is turned slightly toward the door.
  function eye(parent, cx, cy, clipId, side, scaleX) {
    const outer = el('g', { transform: `translate(${cx} ${cy}) scale(${scaleX} 1)` }, parent);
    const clip = el('clipPath', { id: clipId }, outer);
    el('circle', { r: 5.6 }, clip);
    el('circle', { class: 'socket', r: 6.4 }, outer);
    const inner = el('g', { 'clip-path': `url(#${clipId})` }, outer);
    el('circle', { class: 'sclera', r: 5.6 }, inner);
    const look = el('g', { class: 'look' }, inner);
    el('circle', { class: 'iris', r: 3.5, cx: side * 0.5 }, look);
    el('circle', { class: 'pupil', r: 1.7, cx: side * 0.5 }, look);
    el('circle', { class: 'glint', r: 0.75, cx: side * 0.5 - 0.9, cy: -1.1 }, look);
    el('rect', { class: 'lid lid-up', x: -6.4, y: -6.4, width: 12.8, height: 12.8 }, inner);
    el('rect', { class: 'lid lid-down', x: -6.4, y: -6.4, width: 12.8, height: 12.8 }, inner);
    el('path', { class: 'lash', d: `M${5 * side} -5.6 q${2.6 * side} -.6 ${3.1 * side} -3.6` }, outer);
  }

  function scene(svg) {
    // wooden frame with a dark opening (even-odd hole), cloth folds inside
    el('path', { class: 'frame', 'fill-rule': 'evenodd', d: 'M8 40 Q8 26 26 26 L62 26 Q80 26 80 40 L80 74 Q80 86 68 86 L20 86 Q8 86 8 74 Z M16 41 Q16 32 28 32 L58 32 Q72 32 72 41 L72 72 Q72 80 62 80 L26 80 Q16 80 16 72 Z' }, svg);
    el('path', { class: 'inside', d: 'M16 41 Q16 32 28 32 L58 32 Q72 32 72 41 L72 72 Q72 80 62 80 L26 80 Q16 80 16 72 Z' }, svg);
    el('path', { class: 'fold', d: 'M22 42 q3 12 -1 32 M62 40 q-3 14 1 34' }, svg);
    // door, swung open in perspective (far edge shorter)
    el('path', { class: 'door-edge', d: 'M72 31 L86 35 L86 77 L72 81 Z' }, svg);
    el('path', { class: 'door', d: 'M73.5 33 L84.6 36.4 L84.6 75.4 L73.5 78.8 Z' }, svg);
    [44, 56, 68].forEach((y, i) => el('circle', { class: 'rivet', cx: 82.8, cy: y + 0.3 * i, r: 0.8 }, svg));
    el('rect', { class: 'hinge', x: 70.5, y: 33, width: 3.2, height: 46, rx: 1 }, svg);
  }

  function character(svg, parent) {
    // soft shadow of the head on the cloth behind it
    el('ellipse', { cx: 50, cy: 79, rx: 18, ry: 3.5, fill: 'url(#g-shade)' }, parent);

    // spring neck and bow tie (the frame's sill hides the bottom of the spring)
    const neck = el('g', { class: 'neck' }, parent);
    el('rect', { class: 'spring', x: 41, y: 74, width: 12, height: 7, rx: 2 }, neck);
    [76, 79].forEach((y) => el('path', { class: 'spring-line', d: `M41 ${y} q6 2 12 0` }, neck));
    const tie = el('g', { class: 'tie', transform: 'translate(0 0)' }, parent);
    el('path', { class: 'tie-wing', d: 'M47 73.5 L33 68 Q31 73.5 33 79 Z' }, tie);
    el('path', { class: 'tie-wing', d: 'M47 73.5 L61 68 Q63 73.5 61 79 Z' }, tie);
    [[37, 73], [39.5, 76], [56, 71], [53, 76.5]].forEach(([x, y]) => el('circle', { class: 'tie-dot', cx: x, cy: y, r: 0.9 }, tie));
    el('circle', { class: 'tie-knot', cx: 47, cy: 73.5, r: 2.5 }, tie);

    // head, leaning slightly out of the alcove
    const lean = el('g', { class: 'lean', transform: 'translate(2.5 0) rotate(3.5 47 82)' }, parent);
    el('rect', { class: 'head', x: 35, y: 17, width: 24, height: 60, rx: 11 }, lean);
    el('path', { class: 'shine', d: 'M38.8 30 q-.8 15 .8 30' }, lean);
    el('path', { class: 'edge', d: 'M57.6 24 q1.6 20 -.3 44' }, lean);

    const face = el('g', { class: 'face', transform: 'translate(2 0)' }, lean); // features slide toward the door: the head is turned
    eye(face, 41.2, 33, 'clip-l', -1, 1);
    eye(face, 53.4, 33.8, 'clip-r', 1, 0.66);

    el('circle', { class: 'nose', cx: 48.2, cy: 45, r: 4.2 }, face);
    el('circle', { class: 'nose-shine', cx: 46.9, cy: 43.6, r: 1.1 }, face);

    el('path', { class: 'mouth-in', d: 'M35.5 55 Q47 57.5 58.5 55 L58.5 59 Q47 62 35.5 59 Z' }, face);
    const flap = el('g', { class: 'flap' }, face);
    el('path', { class: 'chin', d: 'M35 55.4 Q47 58.4 59 55.4 L57 68 Q47 72.5 37 68 Z' }, flap);
    el('path', { class: 'chin-line', d: 'M35 55.4 Q47 58.4 59 55.4' }, flap);
    el('circle', { class: 'screw', cx: 38.6, cy: 62, r: 1 }, flap);
    el('circle', { class: 'screw', cx: 55.6, cy: 61.5, r: 1 }, flap);

    const hat = el('g', { class: 'hat' }, lean);
    el('path', { class: 'curl', d: 'M34 25 q-3.4 .6 -3.8 3.4 q1.6 -1.3 3.2 -.6 q-2.4 .8 -1.8 2.8' }, lean);
    el('path', { class: 'curl', d: 'M60 25 q3.2 .6 3.4 3.2 q-1.5 -1.2 -3 -.6 q2.2 .8 1.6 2.6' }, lean);
    el('rect', { class: 'crown', x: 31.5, y: 3, width: 31, height: 15, rx: 2.5 }, hat);
    el('rect', { class: 'band', x: 31.5, y: 11.6, width: 31, height: 4 }, hat);
    el('ellipse', { class: 'brim', cx: 47, cy: 18, rx: 18.5, ry: 3.2 }, hat);
    el('ellipse', { class: 'crown-top', cx: 47, cy: 3.4, rx: 15.5, ry: 1.6 }, hat);
  }

  function create(container, { scene: withScene = true } = {}) {
    const svg = el('svg', { viewBox: withScene ? '2 0 88 100' : '27 0 40 82', class: 'robot', 'data-mood': 'idle', role: 'img', 'aria-label': 'Chakmati' }, container);
    defs(svg);
    if (withScene) scene(svg);
    const group = el('g', {}, svg);
    character(svg, group);
    if (withScene) el('path', { class: 'sill', d: 'M12 76.5 Q12 80.5 26 80.5 L62 80.5 Q76 80.5 76 76.5 L76 82 Q76 86 62 86 L26 86 Q12 86 12 82 Z' }, svg);
    return {
      svg,
      setTalking(on) { svg.setAttribute('data-talking', on ? 'true' : 'false'); },
      setMood(mood) { svg.setAttribute('data-mood', ['idle', 'alert', 'thinking', 'happy', 'offline'].includes(mood) ? mood : 'idle'); },
    };
  }

  window.Robot = { create };
})();
