const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const zlib = require('node:zlib');

const ui = path.join(__dirname, '..', '..', 'src', 'shared', 'ui');
const js = fs.readFileSync(path.join(ui, 'robot.js'), 'utf8');
const css = fs.readFileSync(path.join(ui, 'robot.css'), 'utf8');
const FACES = ['smile', 'bored', 'thinking', 'angry', 'drunk', 'sleeping'];

// ---- the pictures
function decode(file) {
  const png = fs.readFileSync(file);
  let off = 8; const idat = [];
  while (off < png.length) { const len = png.readUInt32BE(off); if (png.toString('ascii', off + 4, off + 8) === 'IDAT') idat.push(png.subarray(off + 8, off + 8 + len)); off += 12 + len; }
  const w = png.readUInt32BE(16); const h = png.readUInt32BE(20);
  assert.equal(png[24], 8); assert.equal(png[25], 6, `${path.basename(file)} is RGBA`);
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = w * 4; const out = Buffer.alloc(h * stride);
  for (let y = 0; y < h; y += 1) {
    const f = raw[y * (stride + 1)]; const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x += 1) {
      const a = x >= 4 ? out[y * stride + x - 4] : 0; const b = y ? out[(y - 1) * stride + x] : 0; const c = x >= 4 && y ? out[(y - 1) * stride + x - 4] : 0;
      const pred = f === 0 ? 0 : f === 1 ? a : f === 2 ? b : f === 3 ? (a + b) >> 1 : (() => { const p = a + b - c; const pa = Math.abs(p - a); const pb = Math.abs(p - b); const pc = Math.abs(p - c); return pa <= pb && pa <= pc ? a : pb <= pc ? b : c; })();
      out[y * stride + x] = (line[x] + pred) & 255;
    }
  }
  return { w, h, px: (x, y) => { const i = y * stride + x * 4; return [out[i], out[i + 1], out[i + 2], out[i + 3]]; } };
}
function hsv([r, g, b]) {
  const max = Math.max(r, g, b) / 255; const min = Math.min(r, g, b) / 255; const d = max - min;
  let h = 0;
  if (d) { if (max === r / 255) h = ((g - b) / 255 / d) % 6; else if (max === g / 255) h = (b - r) / 255 / d + 2; else h = (r - g) / 255 / d + 4; h /= 6; if (h < 0) h += 1; }
  return { h, s: max ? d / max : 0, v: max };
}
const pictures = {};
const pic = (name) => (pictures[name] ||= decode(path.join(ui, 'moods', `${name}.png`)));

test('there is one picture for each face, and a twin with the wooden frame, all on the same canvas', () => {
  for (const face of FACES) for (const name of [face, `${face}-wood`]) {
    const p = pic(name);
    assert.deepEqual([p.w, p.h], [472, 891], name);
  }
});

test('every picture is aligned on his bow tie, so changing faces never moves his body', () => {
  const centre = (name) => {   // the middle of the box that holds the yellow of the tie (the hat is above row 560)
    const p = pic(name); let x0 = 1e9; let y0 = 1e9; let x1 = -1; let y1 = -1;
    for (let y = 560; y < p.h; y += 1) for (let x = 0; x < p.w; x += 1) { const px = p.px(x, y); if (px[3] < 200) continue; const c = hsv(px); if (c.h >= 0.12 && c.h <= 0.18 && c.s > 0.4 && c.v > 0.62) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); } }
    return [(x0 + x1) / 2, (y0 + y1) / 2];
  };
  const [cx, cy] = centre('smile');
  for (const face of FACES) for (const name of [face, `${face}-wood`]) {
    const [x, y] = centre(name);
    assert.ok(Math.abs(x - cx) < 4 && Math.abs(y - cy) < 4, `${name} tie is ${(x - cx).toFixed(1)}, ${(y - cy).toFixed(1)} off`);
  }
});

test('the plain pictures have no wooden frame; the twins do', () => {
  const wood = (name) => {
    const p = pic(name); let n = 0;
    for (let y = 440; y < p.h; y += 1) for (let x = 0; x < p.w; x += 1) { if (Math.abs(x - 158) < 70) continue; const px = p.px(x, y); if (px[3] < 200) continue; const c = hsv(px); if (c.h >= 0.03 && c.h <= 0.1 && c.s > 0.4 && c.v > 0.2 && c.v < 0.65) n += 1; }
    return n;
  };
  for (const face of FACES) {
    assert.ok(wood(face) < 700, `${face} has ${wood(face)} wood pixels`);
    assert.ok(wood(`${face}-wood`) > 1500, `${face}-wood has only ${wood(`${face}-wood`)}`);
  }
});

// ---- the drawing
function build({ still = false, matchMedia } = {}) {
  const make = (name) => ({ name, attrs: {}, kids: [], setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; }, appendChild(n) { this.kids.push(n); return n; } });
  const document = { currentScript: { src: 'file:///app/src/shared/ui/robot.js' }, createElementNS: (_ns, name) => make(name), body: { hasAttribute: (a) => still && a === 'data-still' }, container: make('div') };
  const timers = [];
  const ctx = { window: { matchMedia }, document, URL, Math: Object.create(Math, { random: { value: () => 0 } }), setTimeout: (f, ms) => { timers.push({ f, ms, live: true }); return timers.length; }, clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].live = false; } };
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  const robot = ctx.window.Robot.create(document.container);
  const images = () => { const all = []; (function walk(n) { all.push(n); n.kids.forEach(walk); })(document.container); return all.filter((n) => n.name === 'image'); };
  const run = (ms) => { for (const t of timers.filter((x) => x.live && x.ms === ms)) { t.live = false; t.f(); } };
  return { robot, images, svg: robot.svg, timers, run, Robot: ctx.window.Robot };
}

test('the pictures come from next to the script, whichever page loads it; the frame twins only when the whole chat opens', () => {
  const { robot, images } = build();
  assert.deepEqual(images().map((n) => n.attrs.href), FACES.map((f) => `file:///app/src/shared/ui/moods/${f}.png`));
  assert.ok(images().every((n) => n.attrs.width === '472' && n.attrs.height === '891'));
  robot.setWood(true);
  assert.equal(images().length, 12);
  assert.ok(images().slice(6).every((n) => /-wood\.png$/.test(n.attrs.href)));
  robot.setWood(false);
  robot.setWood(true);
  assert.equal(images().length, 12, 'loaded once');
});

test('each mood has its face: bored when idle, working = thinking, failed = angry, offline = asleep', () => {
  const expected = { idle: 'bored', alert: 'smile', happy: 'smile', thinking: 'thinking', angry: 'angry', drunk: 'drunk', offline: 'sleeping', sleeping: 'sleeping' };
  assert.deepEqual({ ...build().Robot.FACE_OF }, expected);
});

test('changing faces goes through a blink: the eyes shut for an instant, then the new face', () => {
  const { robot, svg, run } = build();
  assert.equal(svg.getAttribute('data-face'), 'bored');
  robot.setMood('thinking');
  assert.equal(svg.getAttribute('data-mood'), 'thinking');
  assert.equal(svg.getAttribute('data-face'), 'sleeping');   // the blink
  run(120);
  assert.equal(svg.getAttribute('data-face'), 'thinking');
  robot.setMood('angry');
  assert.equal(svg.getAttribute('data-face'), 'sleeping');
  run(120);
  assert.equal(svg.getAttribute('data-face'), 'angry');
});

test('going to sleep or waking up has no blink in between, and the same face does not blink at all', () => {
  const { robot, svg, timers } = build();
  robot.setMood('offline');
  assert.equal(svg.getAttribute('data-face'), 'sleeping');
  robot.setMood('thinking');                                // waking: straight to the new face
  assert.equal(svg.getAttribute('data-face'), 'thinking');
  const before = timers.length;
  robot.setMood('thinking');
  robot.setMood('thinking');
  assert.equal(svg.getAttribute('data-face'), 'thinking');
  assert.equal(timers.length, before);
});

test('a second change before the first blink ends goes straight to the last face', () => {
  const { robot, svg, run } = build();
  robot.setMood('thinking');
  robot.setMood('drunk');
  run(120);
  assert.equal(svg.getAttribute('data-face'), 'drunk');
});

test('with animations off he changes face at once', () => {
  const { robot, svg } = build({ still: true });
  robot.setMood('angry');
  assert.equal(svg.getAttribute('data-face'), 'angry');
  const reduced = build({ matchMedia: () => ({ matches: true }) });
  reduced.robot.setMood('drunk');
  assert.equal(reduced.svg.getAttribute('data-face'), 'drunk');
});

test('he blinks now and then on his own, and goes back to the face he had', () => {
  const { robot, svg, run } = build();
  robot.setMood('thinking'); run(120);
  run(3500);                                                 // the next ambient blink (random fixed at 0 in this test)
  assert.equal(svg.getAttribute('data-face'), 'sleeping');
  run(120);
  assert.equal(svg.getAttribute('data-face'), 'thinking');
});

test('angry stares and sleeping stays shut: neither blinks on its own', () => {
  const angry = build(); angry.robot.setMood('angry'); angry.run(120); angry.run(3500);
  assert.equal(angry.svg.getAttribute('data-face'), 'angry');
  const asleep = build(); asleep.robot.setMood('offline'); asleep.run(3500);
  assert.equal(asleep.svg.getAttribute('data-face'), 'sleeping');
});

test('an unknown mood is bored and the voice is a flag', () => {
  const { robot, svg } = build();
  robot.setMood('nonsense');
  assert.equal(svg.getAttribute('data-mood'), 'idle');
  robot.setTalking(true);
  assert.equal(svg.getAttribute('data-talking'), 'true');
  robot.setWood(true);
  assert.equal(svg.getAttribute('data-wood'), 'true');
});

test('the stylesheet shows exactly one face, with or without the frame, and moves the figure for each mood', () => {
  for (const face of FACES) {
    assert.ok(css.includes(`.robot[data-face="${face}"]:not([data-wood="true"]) .f-${face}`), face);
    assert.ok(css.includes(`.robot[data-face="${face}"][data-wood="true"] .w-${face}`), face);
  }
  for (const mood of ['idle', 'alert', 'thinking', 'happy', 'angry', 'drunk']) assert.ok(css.includes(`[data-mood="${mood}"] .fig`), mood);
  assert.ok(css.includes('[data-talking="true"] .fig'));
  assert.match(css, /\.robot \{[^}]*overflow: hidden/);
});

test('the frame keeps a margin, so a hop, a sway or a breath never push him out of it', () => {
  assert.equal(build().svg.getAttribute('viewBox'), '-40 -40 552 971');
});

test('the big window turns the frame on, and Ajustes can pin the new faces', () => {
  const layout = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'features', 'panel', 'renderer', 'layout.js'), 'utf8');
  assert.match(layout, /P\.robot\.setWood\(layout === 'wide'\)/);
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'features', 'panel', 'renderer', 'panel.html'), 'utf8');
  for (const mood of ['angry', 'drunk', 'sleeping']) assert.ok(html.includes(`<option value="${mood}">`), mood);
});
