const test = require('node:test');
const assert = require('node:assert/strict');
const { layoutFor, addShot, screenView, KEEP_IMAGES, MAX_STEPS } = require('../src/lib/shots');
const { expandedBounds, MIN_WIDE } = require('../src/lib/placement');

test('three columns from 1000 px wide, the single column below', () => {
  assert.equal(layoutFor(400), 'compact');
  assert.equal(layoutFor(999), 'compact');
  assert.equal(layoutFor(1000), 'wide');
  assert.equal(layoutFor(2560), 'wide');
});

test('a screenshot event joins the turn history and becomes the current picture', () => {
  const turn = {};
  addShot(turn, { step: 1, note: 'Chrome aberto', url: 'https://a', image: 'data:1' });
  addShot(turn, { step: 2, note: 'Clicando', url: 'https://b', title: 'B', image: 'data:2' });
  assert.deepEqual(turn.shots.map((s) => s.step), [1, 2]);
  assert.equal(turn.shot.note, 'Clicando');
  assert.equal(turn.shots[1].title, 'B');
});

test('the same step twice replaces it, and steps stay in order', () => {
  const turn = {};
  addShot(turn, { step: 2, image: 'b' });
  addShot(turn, { step: 1, image: 'a' });
  addShot(turn, { step: 2, image: 'b2' });
  assert.deepEqual(turn.shots.map((s) => [s.step, s.image]), [[1, 'a'], [2, 'b2']]);
});

test('old pictures are let go of, their captions are kept', () => {
  const turn = {};
  for (let i = 1; i <= KEEP_IMAGES + 5; i += 1) addShot(turn, { step: i, note: `passo ${i}`, image: `img${i}` });
  assert.equal(turn.shots[0].image, '');
  assert.equal(turn.shots[0].note, 'passo 1');
  assert.equal(turn.shots[turn.shots.length - 1].image, `img${KEEP_IMAGES + 5}`);
  assert.equal(turn.shots.filter((s) => s.image).length, KEEP_IMAGES);
});

test('the history is capped', () => {
  const turn = {};
  for (let i = 1; i <= MAX_STEPS + 10; i += 1) addShot(turn, { step: i });
  assert.equal(turn.shots.length, MAX_STEPS);
  assert.equal(turn.shots[0].step, 11);
});

test('the screen shows the latest turn that used the browser, live while it is pending', () => {
  const turns = [{ id: 'a', status: 'done', shots: [{ step: 1 }, { step: 2 }] }, { id: 'b', status: 'pending', text: 'sem navegador' }];
  const view = screenView(turns);
  assert.equal(view.turnId, 'a');
  assert.equal(view.current.step, 2);
  assert.equal(view.live, false);
  turns.push({ id: 'c', status: 'pending', shots: [{ step: 1 }] });
  assert.equal(screenView(turns).turnId, 'c');
  assert.equal(screenView(turns).live, true);
});

test('a step picked in the strip is shown; one that is not there falls back to the latest', () => {
  const turns = [{ id: 'a', status: 'done', shots: [{ step: 1 }, { step: 2 }, { step: 3 }] }];
  assert.equal(screenView(turns, 1).current.step, 1);
  assert.equal(screenView(turns, 9).current.step, 3);
});

test('nothing to show before the browser is used', () => {
  assert.equal(screenView([]), null);
  assert.equal(screenView([{ id: 'a', status: 'done' }]), null);
});

test('the wide window sits in the middle of the work area, big but not past the screen', () => {
  const wa = { x: 0, y: 25, width: 1920, height: 1055 };
  const b = expandedBounds({ workArea: wa, mode: 'wide' });
  assert.deepEqual(b, { x: 240, y: 25 + Math.round((1055 - 900) / 2), width: 1440, height: 900 });
  const small = expandedBounds({ workArea: { x: 0, y: 0, width: 1280, height: 720 }, mode: 'wide' });
  assert.equal(small.width, Math.round(1280 * 0.92));
  assert.ok(small.x >= 0 && small.x + small.width <= 1280 && small.y + small.height <= 720);
});

test('a tiny screen still gets a usable window, never bigger than the screen', () => {
  const b = expandedBounds({ workArea: { x: 0, y: 0, width: 800, height: 500 }, mode: 'wide' });
  assert.equal(b.width, 800);
  assert.equal(b.height, 500);
  assert.ok(MIN_WIDE.w > 800);
});

test('full fills the usable area exactly', () => {
  const wa = { x: 0, y: 38, width: 1512, height: 944 };
  assert.deepEqual(expandedBounds({ workArea: wa, mode: 'full' }), wa);
});
