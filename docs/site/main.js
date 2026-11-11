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

  // the column of buttons (one per part of the page): built from the parts, so the two never disagree. Each button is a link to its part.
  const list = document.querySelector('.rail ol');
  const stepsAll = [...document.querySelectorAll('.step')];
  const items = [];
  const STEP = 12;     // degrees between two buttons along the arc
  const GAP = 30;      // pixels between the circle and the buttons
  if (list) {
    for (const step of stepsAll) {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = `#${step.id}`;
      a.textContent = step.dataset.icon;
      a.title = step.dataset.label;
      a.setAttribute('aria-label', step.dataset.label);
      li.append(a);
      list.append(li);
      items.push({ li, a });
    }
  }
  // where the reading is, as a fraction of a part (2.5 = halfway from the third part to the fourth): the column rolls with it
  function position() {
    const middle = window.innerHeight * 0.5;
    const centers = stepsAll.map((s) => { const r = s.getBoundingClientRect(); return r.top + r.height / 2; });
    if (middle <= centers[0]) return 0;
    for (let i = 0; i < centers.length - 1; i++) {
      if (middle < centers[i + 1]) return i + (middle - centers[i]) / (centers[i + 1] - centers[i]);
    }
    return centers.length - 1;
  }
  function roll(pos, active) {
    const stage = list.closest('.stage').getBoundingClientRect();
    const circle = document.querySelector('.halo').getBoundingClientRect();   // where the circle is now (it drifts with the scroll)
    const cx = circle.left + circle.width / 2 - stage.left;
    const cy = circle.top + circle.height / 2 - stage.top;
    const radius = circle.width / 2 + GAP + 18;
    items.forEach((it, i) => {
      const d = Math.abs(i - pos);
      const angle = ((i - pos) * STEP * Math.PI) / 180;   // 0 = the middle of the circle's right side; later parts go down the arc, earlier ones up
      const scale = 0.72 + 0.68 * Math.max(0, 1 - d);     // 1.4 when it is the one being read, 0.72 from a step away
      it.li.style.transform = `translate(${(cx + radius * Math.cos(angle)).toFixed(1)}px, ${(cy + radius * Math.sin(angle)).toFixed(1)}px) scale(${scale.toFixed(3)})`;
      const fade = Math.min(1, Math.max(0, (6.5 - d) / 2));   // gone at the far ends of the arc, so it never wraps round the whole circle
      it.li.style.opacity = (Math.max(0.25, 1 - 0.5 * d) * fade).toFixed(2);
      it.li.style.visibility = fade === 0 ? 'hidden' : 'visible';
      if (i === active) it.a.setAttribute('aria-current', 'true'); else it.a.removeAttribute('aria-current');
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
    if (!still) {
      const room = document.documentElement.scrollHeight - window.innerHeight;
      root.style.setProperty('--p', room > 0 ? (window.scrollY / room).toFixed(4) : '0');   // 0 at the top, 1 at the end
    }
    if (list) roll(position(), stepsAll.indexOf(shownStep));   // after --p: the circle's place is read from the page
  };
  window.addEventListener('scroll', frame, { passive: true });
  window.addEventListener('resize', frame);
  window.addEventListener('load', frame);
  frame();
})();

// Reveal on scroll: phrases and cards fade up when they enter the screen. Without JavaScript (or with reduced motion) everything is simply shown.
(function () {
  'use strict';
  if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const items = [...document.querySelectorAll('.step > *:not(.cards):not(.steps), .cards li, .steps li, .step details')];
  document.documentElement.classList.add('reveal-on');
  const seen = new Map();   // parent -> how many siblings already queued in this burst, so cards come one after another
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const p = e.target.parentElement;
      const n = seen.get(p) || 0;
      seen.set(p, n + 1);
      setTimeout(() => seen.set(p, Math.max(0, (seen.get(p) || 1) - 1)), 400);
      e.target.style.setProperty('--d', n * 120 + 'ms');
      e.target.classList.add('in');
      io.unobserve(e.target);
    }
  }, { threshold: 0.15, rootMargin: '0px 0px -8% 0px' });
  items.forEach((el) => { el.classList.add('rv'); io.observe(el); });
})();
