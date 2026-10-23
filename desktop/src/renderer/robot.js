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
    el('path', { class: 'frame', 'fill-rule': 'evenodd', d: 'M8 32 Q8 8 34 8 L54 8 Q80 8 80 32 L80 82 Q80 96 66 96 L22 96 Q8 96 8 82 Z M16 33 Q16 14 34 14 L54 14 Q72 14 72 33 L72 80 Q72 90 62 90 L26 90 Q16 90 16 80 Z' }, svg);
    el('path', { class: 'inside', d: 'M16 33 Q16 14 34 14 L54 14 Q72 14 72 33 L72 80 Q72 90 62 90 L26 90 Q16 90 16 80 Z' }, svg);
    el('path', { class: 'fold', d: 'M22 30 q4 25 -1 55 M62 26 q-4 28 1 58' }, svg);
    // door, swung open in perspective (far edge shorter)
    el('path', { class: 'door-edge', d: 'M71 12 L96 19 L96 87 L71 93 Z' }, svg);
    el('path', { class: 'door', d: 'M73 15 L93.5 21 L93.5 85 L73 90 Z' }, svg);
    [26, 38, 50, 62, 74].forEach((y, i) => el('circle', { class: 'rivet', cx: 91.5, cy: y + 0.6 * i, r: 0.9 }, svg));
    el('rect', { class: 'hinge', x: 70, y: 18, width: 3.5, height: 68, rx: 1 }, svg);
  }

  function character(svg, parent) {
    // soft shadow of the head on the cloth behind it
    el('ellipse', { cx: 50, cy: 84, rx: 18, ry: 3.5, fill: 'url(#g-shade)' }, parent);

    // spring neck and bow tie (the frame's sill hides the bottom of the spring)
    const neck = el('g', { class: 'neck' }, parent);
    el('rect', { class: 'spring', x: 41, y: 76, width: 12, height: 14, rx: 2 }, neck);
    [78, 81, 84, 87].forEach((y) => el('path', { class: 'spring-line', d: `M41 ${y} q6 2 12 0` }, neck));
    const tie = el('g', { class: 'tie', transform: 'translate(0 4.5)' }, parent);
    el('path', { class: 'tie-wing', d: 'M47 73.5 L33 68 Q31 73.5 33 79 Z' }, tie);
    el('path', { class: 'tie-wing', d: 'M47 73.5 L61 68 Q63 73.5 61 79 Z' }, tie);
    [[37, 73], [39.5, 76], [56, 71], [53, 76.5]].forEach(([x, y]) => el('circle', { class: 'tie-dot', cx: x, cy: y, r: 0.9 }, tie));
    el('circle', { class: 'tie-knot', cx: 47, cy: 73.5, r: 2.5 }, tie);

    // head, leaning slightly out of the alcove
    const lean = el('g', { class: 'lean', transform: 'rotate(-2.5 47 78)' }, parent);
    el('rect', { class: 'head', x: 35, y: 17, width: 24, height: 60, rx: 11 }, lean);
    el('path', { class: 'shine', d: 'M38.8 30 q-.8 15 .8 30' }, lean);
    el('path', { class: 'edge', d: 'M58 26 q1 18 -.5 40' }, lean);

    eye(lean, 41.2, 33, 'clip-l', -1, 1);
    eye(lean, 53, 33.6, 'clip-r', 1, 0.82);

    el('circle', { class: 'nose', cx: 47.4, cy: 45, r: 4.4 }, lean);
    el('circle', { class: 'nose-shine', cx: 46, cy: 43.6, r: 1.1 }, lean);

    el('path', { class: 'mouth-in', d: 'M35.5 55 Q47 57.5 58.5 55 L58.5 59 Q47 62 35.5 59 Z' }, lean);
    const flap = el('g', { class: 'flap' }, lean);
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
    const svg = el('svg', { viewBox: withScene ? '0 0 100 100' : '27 0 40 82', class: 'robot', 'data-mood': 'idle', role: 'img', 'aria-label': 'Chakmati' }, container);
    defs(svg);
    if (withScene) scene(svg);
    const group = el('g', {}, svg);
    character(svg, group);
    if (withScene) el('path', { class: 'sill', d: 'M12 86.5 Q12 90.5 26 90.5 L62 90.5 Q76 90.5 76 86.5 L76 92 Q76 96 62 96 L26 96 Q12 96 12 92 Z' }, svg);
    return {
      svg,
      setMood(mood) { svg.setAttribute('data-mood', ['idle', 'alert', 'thinking', 'happy', 'offline'].includes(mood) ? mood : 'idle'); },
    };
  }

  window.Robot = { create };
})();
