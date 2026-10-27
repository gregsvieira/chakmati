'use strict';
// Pure geometry for the floating robot. Everything here works in screen coordinates and has no Electron dependency,
// so it can be tested without a display.

const GAP = 10;
const SIDES = ['top', 'bottom', 'left', 'right'];

function spaceAround(icon, size, wa) {
  return {
    top: icon.y - wa.y,
    bottom: wa.y + wa.height - (icon.y + size),
    left: icon.x - wa.x,
    right: wa.x + wa.width - (icon.x + size),
  };
}

function needed(bubble) {
  return { top: bubble.h + GAP, bottom: bubble.h + GAP, left: bubble.w + GAP, right: bubble.w + GAP };
}

// Which side of the robot the speech bubble goes on. A preferred side wins if the bubble fits there; otherwise the first
// side that fits in the order top, bottom, left, right; if none fits, the roomiest one.
function chooseSide({ icon, size, workArea, bubble, preference = 'auto' }) {
  const space = spaceAround(icon, size, workArea);
  const need = needed(bubble);
  const fits = (s) => space[s] >= need[s];
  if (SIDES.includes(preference) && fits(preference)) return preference;
  const first = SIDES.find(fits);
  if (first) return first;
  return SIDES.reduce((best, s) => (space[s] / need[s] > space[best] / need[best] ? s : best));
}

// The overlay window must contain the robot AND the bubble; the robot has to stay exactly where it is on screen, so the
// window is placed relative to it. iconOffset is where the robot sits inside the window.
function layoutWidget({ icon, size, side, bubble, workArea }) {
  let width;
  let height;
  let iconOffset;
  let alignRight = false;
  if (side === 'left' || side === 'right') {
    width = size + GAP + bubble.w;
    height = Math.max(size, bubble.h);
    iconOffset = { x: side === 'right' ? 0 : width - size, y: Math.round((height - size) / 2) };
  } else {
    width = Math.max(size, bubble.w);
    height = size + GAP + bubble.h;
    const iconCenter = icon.x + size / 2;
    alignRight = iconCenter > workArea.x + workArea.width / 2; // robot on the right half: the bubble extends leftwards
    iconOffset = { x: alignRight ? width - size : 0, y: side === 'top' ? height - size : 0 };
  }
  return {
    side,
    alignRight,
    size,
    bubble,
    gap: GAP,
    iconOffset,
    bounds: { x: icon.x - iconOffset.x, y: icon.y - iconOffset.y, width, height },
  };
}

function clampIcon(icon, size, wa) {
  return {
    x: Math.min(Math.max(icon.x, wa.x), wa.x + wa.width - size),
    y: Math.min(Math.max(icon.y, wa.y), wa.y + wa.height - size),
  };
}

// Where the expanded panel goes: beside the robot, on the side with room, aligned with it, always inside the screen.
function panelBounds({ icon, size, workArea, panel }) {
  const wa = workArea;
  const right = icon.x + size + GAP;
  const leftX = icon.x - GAP - panel.w;
  let x = right + panel.w <= wa.x + wa.width ? right : leftX;
  const lowerHalf = icon.y + size / 2 > wa.y + wa.height / 2;
  let y = lowerHalf ? icon.y + size - panel.h : icon.y;
  x = Math.min(Math.max(x, wa.x), Math.max(wa.x, wa.x + wa.width - panel.w));
  y = Math.min(Math.max(y, wa.y), Math.max(wa.y, wa.y + wa.height - panel.h));
  return { x, y, width: panel.w, height: panel.h };
}

// The expanded panel: "wide" is a big window in the middle of the screen (the person can still drag its edges); "full" fills the usable area.
const WIDE = { maxW: 1440, maxH: 900, share: 0.92 };
const MIN_WIDE = { w: 1000, h: 600 };
function expandedBounds({ workArea, mode }) {
  const wa = workArea;
  if (mode === 'full') return { x: wa.x, y: wa.y, width: wa.width, height: wa.height };
  const width = Math.max(Math.min(WIDE.maxW, Math.round(wa.width * WIDE.share)), Math.min(MIN_WIDE.w, wa.width));
  const height = Math.max(Math.min(WIDE.maxH, Math.round(wa.height * WIDE.share)), Math.min(MIN_WIDE.h, wa.height));
  return { x: wa.x + Math.round((wa.width - width) / 2), y: wa.y + Math.round((wa.height - height) / 2), width, height };
}

module.exports = { GAP, SIDES, MIN_WIDE, chooseSide, layoutWidget, clampIcon, panelBounds, expandedBounds };
