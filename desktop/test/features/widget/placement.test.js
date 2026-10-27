const test = require('node:test');
const assert = require('node:assert/strict');
const { chooseSide, layoutWidget, clampIcon, panelBounds, GAP } = require('../../../src/features/widget/placement');

const WA = { x: 0, y: 0, width: 1440, height: 900 };
const BUBBLE = { w: 300, h: 100 };
const SIZE = 72;

test('auto picks the bubble above the robot when there is room (bottom-right corner)', () => {
  assert.equal(chooseSide({ icon: { x: 1340, y: 800 }, size: SIZE, workArea: WA, bubble: BUBBLE }), 'top');
});

test('auto falls back to below when the robot is at the top, then to the sides', () => {
  assert.equal(chooseSide({ icon: { x: 600, y: 4 }, size: SIZE, workArea: WA, bubble: BUBBLE }), 'bottom');
  const tiny = { x: 0, y: 0, width: 500, height: 150 }; // no vertical room at all
  assert.equal(chooseSide({ icon: { x: 20, y: 40 }, size: SIZE, workArea: tiny, bubble: BUBBLE }), 'right');
  assert.equal(chooseSide({ icon: { x: 420, y: 40 }, size: SIZE, workArea: tiny, bubble: BUBBLE }), 'left');
});

test('a preferred side is honoured only when the bubble fits there', () => {
  assert.equal(chooseSide({ icon: { x: 600, y: 400 }, size: SIZE, workArea: WA, bubble: BUBBLE, preference: 'left' }), 'left');
  assert.equal(chooseSide({ icon: { x: 20, y: 400 }, size: SIZE, workArea: WA, bubble: BUBBLE, preference: 'left' }), 'top'); // no room on the left
  assert.equal(chooseSide({ icon: { x: 600, y: 400 }, size: SIZE, workArea: WA, bubble: BUBBLE, preference: 'auto' }), 'top');
});

test('nothing fits: still returns a side (the roomiest one) instead of failing', () => {
  const tiny = { x: 0, y: 0, width: 200, height: 120 };
  assert.ok(['top', 'bottom', 'left', 'right'].includes(chooseSide({ icon: { x: 60, y: 20 }, size: SIZE, workArea: tiny, bubble: BUBBLE })));
});

test('vertical layout: the window grows upward and the robot stays exactly where it is on screen', () => {
  const icon = { x: 1340, y: 800 };
  const l = layoutWidget({ icon, size: SIZE, side: 'top', bubble: BUBBLE, workArea: WA });
  assert.equal(l.bounds.width, 300);
  assert.equal(l.bounds.height, SIZE + GAP + BUBBLE.h);
  assert.equal(l.alignRight, true);                      // robot on the right half: bubble extends to the left
  assert.deepEqual({ x: l.bounds.x + l.iconOffset.x, y: l.bounds.y + l.iconOffset.y }, icon);
});

test('vertical layout on the left half extends to the right; bottom puts the robot at the top of the window', () => {
  const icon = { x: 100, y: 50 };
  const l = layoutWidget({ icon, size: SIZE, side: 'bottom', bubble: BUBBLE, workArea: WA });
  assert.equal(l.alignRight, false);
  assert.deepEqual(l.iconOffset, { x: 0, y: 0 });
  assert.deepEqual({ x: l.bounds.x + l.iconOffset.x, y: l.bounds.y + l.iconOffset.y }, icon);
});

test('horizontal layout keeps the robot in place for both sides', () => {
  const icon = { x: 700, y: 400 };
  for (const side of ['left', 'right']) {
    const l = layoutWidget({ icon, size: SIZE, side, bubble: BUBBLE, workArea: WA });
    assert.equal(l.bounds.width, SIZE + GAP + BUBBLE.w);
    assert.equal(l.bounds.height, Math.max(SIZE, BUBBLE.h));
    assert.deepEqual({ x: l.bounds.x + l.iconOffset.x, y: l.bounds.y + l.iconOffset.y }, icon);
  }
  assert.equal(layoutWidget({ icon, size: SIZE, side: 'right', bubble: BUBBLE, workArea: WA }).iconOffset.x, 0);
});

test('clampIcon keeps the whole robot inside the work area', () => {
  assert.deepEqual(clampIcon({ x: -50, y: -9 }, SIZE, WA), { x: 0, y: 0 });
  assert.deepEqual(clampIcon({ x: 5000, y: 5000 }, SIZE, WA), { x: 1440 - SIZE, y: 900 - SIZE });
  assert.deepEqual(clampIcon({ x: 300, y: 300 }, SIZE, WA), { x: 300, y: 300 });
});

test('the panel opens beside the robot, on the side with room, and never leaves the screen', () => {
  const panel = { w: 400, h: 640 };
  const left = panelBounds({ icon: { x: 40, y: 700 }, size: SIZE, workArea: WA, panel });
  assert.equal(left.x, 40 + SIZE + GAP);                       // room on the right
  assert.ok(left.y >= 0 && left.y + panel.h <= WA.height);
  const right = panelBounds({ icon: { x: 1340, y: 100 }, size: SIZE, workArea: WA, panel });
  assert.equal(right.x, 1340 - GAP - panel.w);                 // no room on the right: opens to the left
  assert.equal(right.y, 100);                                  // robot in the upper half: panel top aligned with it
  const bottom = panelBounds({ icon: { x: 1340, y: 800 }, size: SIZE, workArea: WA, panel });
  assert.equal(bottom.y + panel.h, 800 + SIZE);                // lower half: bottoms aligned
});

test('on a screen smaller than the panel it is clamped instead of overflowing', () => {
  const b = panelBounds({ icon: { x: 10, y: 10 }, size: SIZE, workArea: { x: 0, y: 0, width: 380, height: 500 }, panel: { w: 400, h: 640 } });
  assert.ok(b.x >= 0 && b.y >= 0);
});

test('the layout carries the gap so the renderer can place the bubble without knowing the constants', () => {
  assert.equal(layoutWidget({ icon: { x: 100, y: 100 }, size: SIZE, side: 'top', bubble: BUBBLE, workArea: WA }).gap, GAP);
});
