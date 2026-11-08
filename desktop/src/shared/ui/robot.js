// Chakmati: a tall, thin tin-can head with a yellow hat, big sleepy eyes under blue eyelids, a red nose and a green chin
// flap for a mouth, on a long spring neck, with a polka-dot bow tie. Shaded like the 3D figure it was drawn from (a lit cylinder, riveted
// metal, a glossy nose). In the big window he stands in his wooden alcove with the green door open beside him (setDoor).
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
    const grad = (id, attrs, list) => stops(el('linearGradient', { id, ...attrs }, d), list);
    grad('g-head', { x1: 0, y1: 0, x2: 1, y2: 0 }, [[0, 'hi'], [0.3, 'hi2'], [0.62, 'mid'], [1, 'lo']]);   // a cylinder: lit on the left, turning away on the right
    grad('g-flap', { x1: 0, y1: 0, x2: 1, y2: 0 }, [[0, 'flap-hi'], [1, 'flap-lo']]);
    grad('g-hat', { x1: 0, y1: 0, x2: 1, y2: 0 }, [[0, 'hat-hi'], [0.4, 'hat'], [1, 'hat-lo']]);
    grad('g-band', { x1: 0, y1: 0, x2: 1, y2: 0 }, [[0, 'band-hi'], [0.5, 'band'], [1, 'band-lo']]);
    grad('g-spring', { x1: 0, y1: 0, x2: 1, y2: 0 }, [[0, 'spring-hi'], [0.5, 'spring'], [1, 'spring-lo']]);
    grad('g-wood', { x1: 0, y1: 0, x2: 1, y2: 1 }, [[0, 'wood-hi'], [1, 'wood-lo']]);
    grad('g-door', { x1: 0, y1: 0, x2: 1, y2: 1 }, [[0, 'door-hi'], [1, 'door-lo']]);
    const ball = (id, cls) => { const g = el('radialGradient', { id, cx: 0.35, cy: 0.3, r: 0.8 }, d); stops(g, [[0, `${cls}-hi`], [1, cls]]); };
    ball('g-nose', 'nose');
    ball('g-rivet', 'rivet');
    const shade = el('radialGradient', { id: 'g-shade', cx: 0.5, cy: 0.5, r: 0.5 }, d);
    el('stop', { offset: 0, 'stop-color': '#000', 'stop-opacity': 0.5 }, shade);
    el('stop', { offset: 1, 'stop-color': '#000', 'stop-opacity': 0 }, shade);
  }

  // The far eye is drawn narrower (scale) because the head is turned slightly toward the door.
  function eye(parent, cx, cy, clipId, side, scaleX) {
    const outer = el('g', { transform: `translate(${cx} ${cy}) scale(${scaleX} 1)` }, parent);
    const clip = el('clipPath', { id: clipId }, outer);
    el('circle', { r: 5.6 }, clip);
    el('ellipse', { class: 'bag', cx: 0, cy: 1.2, rx: 7.2, ry: 6.8 }, outer);          // the puffy blue skin round the eye
    el('circle', { class: 'socket', r: 6.4 }, outer);
    const inner = el('g', { 'clip-path': `url(#${clipId})` }, outer);
    el('circle', { class: 'sclera', r: 5.6 }, inner);
    const look = el('g', { class: 'look' }, inner);
    el('circle', { class: 'iris', r: 3.5, cx: side * 0.5 }, look);
    el('circle', { class: 'iris-ring', r: 3.5, cx: side * 0.5 }, look);
    el('circle', { class: 'pupil', r: 1.7, cx: side * 0.5 }, look);
    el('circle', { class: 'glint', r: 0.75, cx: side * 0.5 - 0.9, cy: -1.1 }, look);
    el('rect', { class: 'lid lid-up', x: -6.4, y: -6.4, width: 12.8, height: 12.8 }, inner);
    el('rect', { class: 'lid lid-down', x: -6.4, y: -6.4, width: 12.8, height: 12.8 }, inner);
    el('path', { class: 'lash', d: `M${5 * side} -5.6 q${2.6 * side} -.6 ${3.1 * side} -3.6` }, outer);
  }

  const rivet = (parent, cx, cy, r) => { el('circle', { class: 'rivet', cx, cy, r }, parent); el('circle', { class: 'rivet-glint', cx: cx - r * 0.3, cy: cy - r * 0.3, r: r * 0.32 }, parent); };

  // the alcove the character lives in (a wooden frame with a black inside) and its green door, open to the left; only in the big window
  function alcove(svg, parent) {
    const door = el('g', { class: 'door', display: 'none' }, parent);
    el('ellipse', { class: 'ground', cx: 30, cy: 98.6, rx: 38, ry: 2.2 }, door);
    el('path', { class: 'frame', d: 'M31 68 Q31 62 37 62 L40 62 Q43 71 47 72 Q52 68 56 62 L66 62 Q72 62 72 68 L72 90 Q72 99 63 99 L40 99 Q31 99 31 90 Z' }, door);
    el('path', { class: 'inside', d: 'M34 70 Q34 65.5 38 65.5 L39.5 65.5 Q43 74.5 47 75.5 Q52 72 55 65.5 L65 65.5 Q69 65.5 69 70 L69 89 Q69 96 63 96 L40 96 Q34 96 34 89 Z' }, door);
    el('path', { class: 'door-panel', d: 'M31 71 Q15 64 4 72 Q-4 79 -3 92 Q-2 100 6 98 L29 97 Z' }, door);
    el('path', { class: 'door-inner', d: 'M27 74.5 Q15 69.5 7 75 Q1.5 80.5 2 90.5 Q2.5 94.5 7 94 L27 93.5 Z' }, door);
    el('rect', { class: 'hinge', x: 29.4, y: 72, width: 3, height: 7, rx: 1 }, door);
    el('rect', { class: 'hinge', x: 29.4, y: 88, width: 3, height: 7, rx: 1 }, door);
    [[7, 71.4], [15, 69.7], [23, 71.5], [-1.2, 80], [-1.6, 90], [8, 96.3], [18, 96.3], [28, 95.6]].forEach(([x, y]) => rivet(door, x, y, 0.9));
    return door;
  }

  function character(svg, parent) {
    // spring neck, white collar and bow tie (the frame's sill hides the bottom of the spring)
    const neck = el('g', { class: 'neck' }, parent);
    el('rect', { class: 'spring', x: 41, y: 74, width: 12, height: 26, rx: 2.5 }, neck);
    [76.5, 79.5, 82.5, 85.5, 88.5, 91.5, 94.5, 97.5].forEach((y) => { el('path', { class: 'spring-line', d: `M41 ${y} q6 2.2 12 0` }, neck); el('path', { class: 'spring-lit', d: `M42.4 ${y - 0.9} q2 .8 4 .8` }, neck); });
    el('path', { class: 'collar', d: 'M41.5 71 L47 79 L52.5 71 L50 69.4 L47 71.4 L44 69.4 Z' }, neck);
    el('path', { class: 'shirt-line', d: 'M47 72 L47 78' }, neck);
    const tie = el('g', { class: 'tie', transform: 'translate(0 0)' }, parent);
    el('path', { class: 'tie-wing', d: 'M47 73.5 L32 67.6 Q29.6 73.5 32 79.6 Z' }, tie);
    el('path', { class: 'tie-wing', d: 'M47 73.5 L62 67.6 Q64.4 73.5 62 79.6 Z' }, tie);
    el('path', { class: 'tie-fold', d: 'M47 73.5 L35 70 M47 73.5 L35 77 M47 73.5 L59 70 M47 73.5 L59 77' }, tie);
    [[35.5, 71], [37.5, 75], [33.6, 74.4], [40.5, 72], [41.6, 76], [56.6, 70.6], [54, 74.4], [59, 74.6], [51.6, 71.4], [51.2, 76.2], [38.4, 69.2]].forEach(([x, y]) => el('circle', { class: 'tie-dot', cx: x, cy: y, r: 0.85 }, tie));
    el('ellipse', { class: 'tie-knot', cx: 47, cy: 73.5, rx: 2.6, ry: 2.9 }, tie);

    // head, leaning slightly out of the alcove
    const lean = el('g', { class: 'lean', transform: 'translate(2.5 0) rotate(3.5 47 82)' }, parent);
    el('rect', { class: 'head', x: 35, y: 17, width: 24, height: 60, rx: 11 }, lean);
    el('path', { class: 'shine', d: 'M38.6 28 q-.9 16 .8 33' }, lean);
    el('path', { class: 'shine-soft', d: 'M41.2 24 q-.6 18 .4 40' }, lean);
    el('path', { class: 'edge', d: 'M57.6 24 q1.6 20 -.3 44' }, lean);
    rivet(lean, 36.4, 47, 1.1);
    rivet(lean, 57.4, 52, 1.1);

    const face = el('g', { class: 'face', transform: 'translate(2 0)' }, lean); // features slide toward the door: the head is turned
    eye(face, 41.2, 33, 'clip-l', -1, 1);
    eye(face, 53.4, 33.8, 'clip-r', 1, 0.66);
    const brows = el('g', { class: 'brows' }, face);
    el('path', { class: 'brow', d: 'M36.4 25.4 q4.6 -2.8 9 -.2' }, brows);
    el('path', { class: 'brow', d: 'M50.6 25.8 q3 -2 6.2 -.3' }, brows);

    el('ellipse', { class: 'nose-shadow', cx: 48.9, cy: 46.2, rx: 4.6, ry: 4 }, face);
    el('circle', { class: 'nose', cx: 48.2, cy: 45, r: 4.2 }, face);
    el('circle', { class: 'nose-shine', cx: 46.9, cy: 43.6, r: 1.2 }, face);

    el('path', { class: 'mouth-in', d: 'M35.5 55 Q47 57.5 58.5 55 L58.5 59 Q47 62 35.5 59 Z' }, face);
    el('path', { class: 'tongue', d: 'M41 57.6 Q47 56.6 53 57.6 Q47 60 41 57.6 Z' }, face);
    const flap = el('g', { class: 'flap' }, face);
    el('path', { class: 'chin', d: 'M35 55.4 Q47 58.4 59 55.4 L57 68 Q47 72.5 37 68 Z' }, flap);
    el('path', { class: 'chin-lit', d: 'M36 57 Q41 59 44 59.2 L43 68.6 Q39.5 68 38 67 Z' }, flap);
    el('path', { class: 'chin-line', d: 'M35 55.4 Q47 58.4 59 55.4' }, flap);
    rivet(flap, 38.6, 62, 1.05);
    rivet(flap, 55.6, 61.5, 1.05);

    // black hair tufts peeking out under the brim
    const hair = el('g', { class: 'hair' }, lean);
    ['M33.4 22 q-1.6 2.6 -1.4 6.4', 'M35 21.6 q-1 2.8 -.6 5.4', 'M60.6 22 q1.6 2.6 1.6 6', 'M59 21.6 q1.2 2.6 1 5.2', 'M39.5 18.6 q-.4 2.2 .5 3.4', 'M43 18.6 q0 2.2 .8 3.2', 'M48 18.6 q.2 2 1 3'].forEach((d) => el('path', { class: 'hair-line', d }, hair));

    const hat = el('g', { class: 'hat' }, lean);
    el('rect', { class: 'crown', x: 31.5, y: 3, width: 31, height: 15, rx: 2.5 }, hat);
    el('path', { class: 'crown-lit', d: 'M34 5.5 q-.6 5 .2 10' }, hat);
    el('path', { class: 'band', d: 'M31.5 11.2 Q47 14.2 62.5 11.2 L62.5 15.6 Q47 18.6 31.5 15.6 Z' }, hat);
    el('path', { class: 'band-lit', d: 'M33 12.4 Q41 14.4 47 14.7' }, hat);
    el('ellipse', { class: 'brim', cx: 47, cy: 18, rx: 18.5, ry: 3.2 }, hat);
    el('path', { class: 'brim-lit', d: 'M30 18.6 Q47 22.6 64 18.4' }, hat);
    el('ellipse', { class: 'crown-top', cx: 47, cy: 3.4, rx: 15.5, ry: 1.6 }, hat);
  }

  const PLAIN = '24 0 46 100';        // the character alone: the header, the floating icon
  const WITH_DOOR = '-6 0 77 100';    // the character in his alcove with the green door open beside him: the big window

  function create(container, { door = false } = {}) {
    const svg = el('svg', { viewBox: door ? WITH_DOOR : PLAIN, class: 'robot', 'data-mood': 'idle', role: 'img', 'aria-label': 'Chakmati' }, container);
    defs(svg);
    const group = el('g', {}, svg);
    const alcoveGroup = alcove(svg, group);   // drawn first: it is behind the character
    character(svg, group);
    const setDoor = (on) => { alcoveGroup.setAttribute('display', on ? 'inline' : 'none'); svg.setAttribute('viewBox', on ? WITH_DOOR : PLAIN); };
    setDoor(door);
    return {
      svg,
      setDoor,
      setTalking(on) { svg.setAttribute('data-talking', on ? 'true' : 'false'); },
      setMood(mood) { svg.setAttribute('data-mood', ['idle', 'alert', 'thinking', 'happy', 'offline'].includes(mood) ? mood : 'idle'); },
    };
  }

  window.Robot = { create };
})();
