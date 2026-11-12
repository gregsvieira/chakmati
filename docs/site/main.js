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

// Chat demo ("Escreva ou fale"): a message is typed or spoken, sent, and the Chakmati answers. Plays only while on screen, loops.
(function () {
  'use strict';
  const box = document.getElementById('chat-demo');
  if (!box) return;
  const log = box.querySelector('.demo-log');
  const text = box.querySelector('.demo-text');
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SCENES = [
    { via: 'type', ask: 'oi', say: 'klift, kloft, stão! Fala paizão!' },
    { via: 'voice', ask: 'Toca a próxima música na sala.', say: 'Tocando agora na sala: “Trem das Onze”.' },
  ];
  let run = 0, visible = false;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const add = (cls, t) => { const d = document.createElement('div'); d.className = 'demo-msg ' + cls; if (t) d.textContent = t; log.appendChild(d); while (log.children.length > 4) log.firstChild.remove(); return d; };
  const set = (cls, on) => box.classList.toggle(cls, on);
  const setText = (t) => { text.textContent = t; set('empty', !t); set('ready', !!t); };

  async function play(id) {
    for (let i = 0; ; i = (i + 1) % SCENES.length) {
      const s = SCENES[i];
      setText('');
      if (s.via === 'voice') { set('listening', true); await sleep(900); }
      for (let k = 1; k <= s.ask.length; k++) {
        if (id !== run) return;
        setText(s.ask.slice(0, k));
        await sleep(s.via === 'voice' ? 55 : 80);
      }
      set('listening', false);
      await sleep(600); if (id !== run) return;
      set('sending', true); await sleep(180); set('sending', false);
      add('me', s.ask); setText('');
      await sleep(500); if (id !== run) return;
      const dots = add('bot dots'); dots.innerHTML = '<i></i><i></i><i></i>';
      await sleep(1400); if (id !== run) return;
      dots.remove(); add('bot', s.say);
      await sleep(3800); if (id !== run) return;
    }
  }

  if (still) {   // no motion: show the finished scene
    set('empty', false); add('me', SCENES[0].ask); add('bot', SCENES[0].say); return;
  }
  setText('');
  if (!('IntersectionObserver' in window)) { play(++run); return; }
  new IntersectionObserver((es) => {
    const v = es[0].isIntersecting;
    if (v === visible) return;
    visible = v;
    if (v) { log.textContent = ''; play(++run); } else { run++; }
  }, { threshold: 0.4 }).observe(box);
})();

// Web navigation demo: the Chakmati's screen. A fake shop page is "browsed": the address and the step under it change, a cursor clicks. Plays while on screen, loops.
(function () {
  'use strict';
  const box = document.getElementById('nav-demo');
  if (!box) return;
  const view = box.querySelector('.nd-view');
  const addr = box.querySelector('.nd-addr');
  const status = box.querySelector('.nd-status');
  const cursor = box.querySelector('.nd-cursor');
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const top = (q) => `<div class="nd-top"><span class="nd-logo">Loja Exemplo</span><span class="nd-search">${q}</span></div>`;
  const item = (n, p, c) => `<div class="nd-item ${c || ''}"><span class="nd-pic"></span><div><b>${n}</b><span>${p}</span></div></div>`;
  const PAGES = {
    home: top('') + '<div class="nd-sk" style="width:60%"></div><div class="nd-sk" style="width:85%"></div><div class="nd-sk" style="width:45%"></div>',
    typed: (q) => top(q),
    results: top('fone de ouvido') + '<div class="nd-list">' + item('Fone sem fio Soul', 'R$ 129,90', 'first') + item('Fone com fio Basic', 'R$ 49,90') + item('Fone esportivo Run', 'R$ 89,90') + '</div>',
    product: top('fone de ouvido') + '<div class="nd-big"><span class="nd-pic"></span><div><b>Fone sem fio Soul</b><div class="nd-price">R$ 129,90</div><span class="nd-btn">Comprar</span></div></div>',
  };
  let run = 0, visible = false;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const page = (html) => { view.querySelectorAll('.nd-page').forEach((p) => p.remove()); const d = document.createElement('div'); d.className = 'nd-page'; d.innerHTML = html; view.appendChild(d); return d; };
  const say = (t) => { status.textContent = t; };
  const moveTo = (el) => {   // the cursor goes to the middle of an element of the page
    const v = view.getBoundingClientRect(), r = el.getBoundingClientRect();
    cursor.classList.add('on');
    cursor.style.transform = `translate(${r.left - v.left + r.width * 0.5}px, ${r.top - v.top + r.height * 0.55}px)`;
  };
  const click = async () => { cursor.classList.remove('click'); void cursor.offsetWidth; cursor.classList.add('click'); await sleep(450); };

  async function play(id) {
    const ok = () => id === run;
    for (;;) {
      cursor.classList.remove('on'); cursor.style.transform = 'translate(70%, 60%)';
      addr.textContent = ''; say('');
      await sleep(600); if (!ok()) return;
      say('Abrindo o site…');
      for (const c of 'lojaexemplo.com.br') { addr.textContent += c; await sleep(55); if (!ok()) return; }
      page(PAGES.home); await sleep(1100); if (!ok()) return;
      const p = page(PAGES.typed('')); const box2 = p.querySelector('.nd-search');
      say('Clicando no campo de busca'); moveTo(box2); await sleep(1000); if (!ok()) return;
      await click(); box2.classList.add('focus'); if (!ok()) return;
      say('Escrevendo: “fone de ouvido”');
      for (const c of 'fone de ouvido') { box2.textContent += c; await sleep(70); if (!ok()) return; }
      await sleep(500); if (!ok()) return;
      addr.textContent = 'lojaexemplo.com.br/busca?q=fone+de+ouvido';
      say('Procurando…'); page(PAGES.results); await sleep(1200); if (!ok()) return;
      say('Abrindo o primeiro resultado'); moveTo(view.querySelector('.nd-item.first')); await sleep(1000); if (!ok()) return;
      view.querySelector('.nd-item.first').classList.add('hit'); await click(); if (!ok()) return;
      addr.textContent = 'lojaexemplo.com.br/produto/fone-sem-fio-soul';
      page(PAGES.product); cursor.classList.remove('on'); await sleep(700); if (!ok()) return;
      say('Achei: o Fone sem fio Soul custa R$ 129,90.');
      await sleep(4200); if (!ok()) return;
    }
  }

  if (still) { addr.textContent = 'lojaexemplo.com.br/produto/fone-sem-fio-soul'; page(PAGES.product); say('Achei: o Fone sem fio Soul custa R$ 129,90.'); return; }
  if (!('IntersectionObserver' in window)) { play(++run); return; }
  new IntersectionObserver((es) => {
    const v = es[0].isIntersecting;
    if (v === visible) return;
    visible = v;
    if (v) play(++run); else run++;
  }, { threshold: 0.4 }).observe(box);
})();

// WhatsApp demo: the Chakmati's little window says "Você recebeu mensagens de Mãe", the chat opens, and he answers by himself with an audio. Plays while on screen, loops.
(function () {
  'use strict';
  const box = document.getElementById('wa-demo');
  if (!box) return;
  const log = box.querySelector('.wa-log');
  const bubble = box.querySelector('.wa-bubble');
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const BARS = [30, 55, 40, 75, 50, 90, 60, 35, 70, 45, 85, 55, 30, 65, 80, 40, 60, 25, 70, 50, 35, 60, 45, 30];
  const DUR = 12;   // seconds the audio "lasts"
  const ASK = 'Filho, você vai chegar para o almoço?';
  let run = 0, visible = false;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const msg = (cls, build) => { const d = document.createElement('div'); d.className = 'wa-msg ' + cls; build(d); log.appendChild(d); while (log.children.length > 3) log.firstChild.remove(); return d; };
  const mm = (s) => '0:' + String(Math.max(0, s)).padStart(2, '0');

  function audioMsg() {
    let player;
    msg('out', (el) => {
      const lab = document.createElement('span'); lab.className = 'wa-auto'; lab.textContent = 'Resposta Automática Chakmati:'; el.appendChild(lab);
      player = document.createElement('div'); player.className = 'wa-audio';
      player.innerHTML = '<span class="wa-play">▶</span><span class="wa-wave">' + BARS.map((b) => `<i style="height:${b}%"></i>`).join('') + '</span><span class="wa-time"></span>';
      el.appendChild(player);
    });
    player.querySelector('.wa-time').textContent = mm(DUR);
    return player;
  }
  async function playAudio(player, ok) {
    const bars = [...player.querySelectorAll('.wa-wave i')], time = player.querySelector('.wa-time'), btn = player.querySelector('.wa-play');
    btn.textContent = '❚❚';
    const step = (DUR * 1000) / bars.length;
    for (let i = 0; i < bars.length; i++) { await sleep(step); if (!ok()) return; bars[i].classList.add('done'); time.textContent = mm(DUR - Math.round((i + 1) * DUR / bars.length)); }
    btn.textContent = '▶';
  }

  async function play(id) {
    const ok = () => id === run;
    for (;;) {
      box.classList.remove('open'); bubble.classList.remove('show', 'tap'); log.textContent = '';
      await sleep(1000); if (!ok()) return;
      bubble.classList.add('show');                       // 1. the little window: who wrote
      await sleep(3200); if (!ok()) return;
      bubble.classList.add('tap'); await sleep(250); if (!ok()) return;
      box.classList.add('open');                          // 2. the chat opens
      await sleep(900); if (!ok()) return;
      msg('in', (el) => { el.textContent = ASK; });
      await sleep(1500); if (!ok()) return;
      const typing = msg('typing', (el) => { el.textContent = 'Chakmati está gravando um áudio…'; });
      await sleep(1800); if (!ok()) return;
      typing.remove();
      const player = audioMsg();                          // 3. the automatic answer, as an audio
      await sleep(900); if (!ok()) return;
      await playAudio(player, ok); if (!ok()) return;
      await sleep(3200); if (!ok()) return;
    }
  }

  if (still) { box.classList.add('open'); msg('in', (el) => { el.textContent = ASK; }); audioMsg(); return; }
  if (!('IntersectionObserver' in window)) { play(++run); return; }
  new IntersectionObserver((es) => {
    const v = es[0].isIntersecting;
    if (v === visible) return;
    visible = v;
    if (v) play(++run); else run++;
  }, { threshold: 0.4 }).observe(box);
})();

// Download: the arrow on the first step slides the part to the left and shows Mac / Windows / Ubuntu (each one a link to the GitHub page with the file).
(function () {
  'use strict';
  const wrap = document.getElementById('dl');
  const trigger = wrap && wrap.querySelector('.dl-trigger');
  if (!trigger) return;
  const toggle = () => { const open = wrap.classList.toggle('open'); trigger.setAttribute('aria-expanded', String(open)); };
  trigger.addEventListener('click', toggle);
  trigger.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
})();
