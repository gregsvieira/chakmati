// Chakmati: the picture on the left follows the part of the page being read; the decorations drift at their own speed (parallax).
// No libraries. Everything here is optional: without JavaScript the page reads fine, with the first face.
(function () {
  'use strict';
  const imgs = [...document.querySelectorAll('.figure img')];
  const byMood = Object.fromEntries(imgs.map((i) => [i.dataset.mood, i]));
  const name = document.getElementById('mood-name');
  const halo = document.querySelector('.halo');
  const root = document.documentElement;
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // the colour behind him, one per mood
  const HALO = { smile: '#bfe0f3', bored: '#d9dde6', thinking: '#cfe3ff', angry: '#f7c9cf', drunk: '#ffe3a8', sleeping: '#c9d3ea' };

  // the other faces are fetched when the browser is idle (the first one is already on screen): a modest connection is not asked for 1 MB at once
  const load = (img) => { if (img.dataset.src && !img.src) img.src = img.dataset.src; };
  const lazy = () => imgs.forEach(load);
  (window.requestIdleCallback || ((f) => setTimeout(f, 1200)))(lazy);

  // one icon per part of the page, around the circle behind him: the one of the part being read is lit, the others fade. Each is a link to its part.
  const ring = document.querySelector('.orbit.front');
  const links = [];
  const stepsAll = [...document.querySelectorAll('.step')];
  if (ring) {
    stepsAll.forEach((step, i) => {
      const a = document.createElement('a');
      const angle = (-90 + (360 / stepsAll.length) * i) * Math.PI / 180;   // the first at the top, then clockwise
      a.href = `#${step.id}`;
      a.textContent = step.dataset.icon;
      a.title = step.dataset.label;
      a.setAttribute('aria-label', step.dataset.label);
      a.style.left = `${50 + 50 * Math.cos(angle)}%`;
      a.style.top = `${50 + 50 * Math.sin(angle)}%`;
      ring.append(a);
      links.push(a);
    });
  }

  let current = 'smile';
  let shownStep = null;
  let timer = null;
  function label(title, sub) {
    if (!name) return;
    name.textContent = title;
    const s = document.createElement('small');
    s.textContent = sub;
    name.append(s);
  }
  function show(step) {
    if (step === shownStep) return;
    shownStep = step;
    const mood = step.dataset.mood;
    label(step.dataset.name, step.dataset.sub);
    links.forEach((a, i) => { if (stepsAll[i] === step) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current'); });   // two parts of the page may share a face and still say different things
    if (mood === current) return;
    current = mood;
    if (halo) halo.style.background = HALO[mood] || HALO.smile;
    const next = byMood[mood];
    load(next);
    clearTimeout(timer);
    const swap = () => { imgs.forEach((i) => i.classList.toggle('on', i === next)); };
    if (still || mood === 'sleeping') { swap(); return; }
    // like in the app: a quick blink (the sleeping face) between two faces
    const blink = byMood.sleeping;
    load(blink);
    imgs.forEach((i) => i.classList.toggle('on', i === blink));
    timer = setTimeout(swap, 110);
  }

  // the part of the page that crosses the middle of the window decides the face
  const steps = [...document.querySelectorAll('.step')];
  function pick() {
    const middle = window.innerHeight * 0.5;
    let best = steps[0];
    for (const step of steps) {
      const r = step.getBoundingClientRect();
      if (r.top <= middle && r.bottom > middle) { best = step; break; }
      if (r.top <= middle) best = step;
    }
    if (best) show(best);
  }

  // on every scroll: the face, and one number (how far down the page, 0 to 1) for the parallax; the CSS does the rest. Done directly, not through
  // requestAnimationFrame: it is eight measurements, and a frame that never comes (a hidden tab, a slow computer) must not leave the wrong face.
  const frame = () => {
    pick();
    if (still) return;
    const room = document.documentElement.scrollHeight - window.innerHeight;
    root.style.setProperty('--p', room > 0 ? (window.scrollY / room).toFixed(4) : '0');   // 0 at the top, 1 at the end
  };
  window.addEventListener('scroll', frame, { passive: true });
  window.addEventListener('resize', frame);
  window.addEventListener('load', frame);
  frame();
})();
