const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ui = path.join(__dirname, '..', '..', 'src', 'shared', 'ui');
const js = fs.readFileSync(path.join(ui, 'robot.js'), 'utf8');
const css = fs.readFileSync(path.join(ui, 'robot.css'), 'utf8');

// a tiny SVG stand-in: elements with attributes and children, enough to see what robot.js draws
function fakeDocument() {
  const make = (name) => ({ name, attrs: {}, kids: [], setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; }, appendChild(n) { this.kids.push(n); return n; } });
  return { createElementNS: (_ns, name) => make(name), container: make('div') };
}
function build(opts) {
  const document = fakeDocument();
  const ctx = { window: {}, document };
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  const robot = ctx.window.Robot.create(document.container, opts);
  const all = [];
  (function walk(n) { all.push(n); n.kids.forEach(walk); })(document.container);
  return { robot, classes: new Set(all.flatMap((n) => String(n.attrs.class || '').split(/\s+/)).filter(Boolean)), all };
}

test('the moods and the talking still have every part they move', () => {
  const { classes } = build();
  for (const part of ['lid-up', 'lid-down', 'look', 'flap', 'hat', 'mouth-in', 'head', 'brow', 'nose', 'tie-wing', 'spring']) assert.ok(classes.has(part), part);
});

test('the character alone uses the tall frame; the big window adds his alcove and the green door', () => {
  const plain = build();
  assert.equal(plain.robot.svg.getAttribute('viewBox'), '24 0 46 100');
  const door = plain.all.find((n) => n.attrs.class === 'door');
  assert.equal(door.attrs.display, 'none');
  plain.robot.setDoor(true);
  assert.equal(door.attrs.display, 'inline');
  assert.equal(plain.robot.svg.getAttribute('viewBox'), '-6 0 77 100');
  plain.robot.setDoor(false);
  assert.equal(plain.robot.svg.getAttribute('viewBox'), '24 0 46 100');
  assert.equal(build({ door: true }).robot.svg.getAttribute('viewBox'), '-6 0 77 100');
});

test('every part the drawing paints is styled, and every gradient it points at exists', () => {
  const { classes, all } = build({ door: true });
  const groups = new Set(['neck', 'lean', 'face', 'brows', 'hair', 'tie', 'door', 'robot']);   // only hold other parts
  const unstyled = [...classes].filter((c) => !groups.has(c) && !css.includes(`.${c}`) && !css.includes(`.${c} {`));
  assert.deepEqual(unstyled, []);
  const ids = new Set(all.map((n) => n.attrs.id).filter(Boolean));
  const used = new Set(all.flatMap((n) => Object.values(n.attrs)).flatMap((v) => [...String(v).matchAll(/url\(#([\w-]+)\)/g)].map((m) => m[1])));
  for (const id of used) assert.ok(ids.has(id), `gradient ${id} is used but not defined`);
});

test('the wide window gives the figure room for the door', () => {
  const layout = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'features', 'panel', 'renderer', 'layout.js'), 'utf8');
  assert.match(layout, /P\.robot\.setDoor\(layout === 'wide'\)/);
  const panelCss = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'features', 'panel', 'renderer', 'panel.css'), 'utf8');
  assert.match(panelCss, /#hero #head-robot \{ width: 84px; height: 104px; \}/);
});
