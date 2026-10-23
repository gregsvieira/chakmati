'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { assertLoopback } = require('./engine-client');

const SIDES = ['auto', 'top', 'bottom', 'left', 'right'];
const DEFAULTS = Object.freeze({
  protect: true,          // ask the OS to leave the windows out of screen sharing and recordings (best effort)
  masked: false,          // discreet mode: bubbles never show names or titles
  bubbleSide: 'auto',
  icon: null,             // {x, y} of the robot on screen, null = default corner
  engineUrl: 'http://127.0.0.1:8765',
});

function normalize(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const s = { ...DEFAULTS };
  if (typeof r.protect === 'boolean') s.protect = r.protect;
  if (typeof r.masked === 'boolean') s.masked = r.masked;
  if (SIDES.includes(r.bubbleSide)) s.bubbleSide = r.bubbleSide;
  if (r.icon && Number.isFinite(r.icon.x) && Number.isFinite(r.icon.y)) s.icon = { x: Math.round(r.icon.x), y: Math.round(r.icon.y) };
  if (typeof r.engineUrl === 'string') {
    try { assertLoopback(r.engineUrl); s.engineUrl = r.engineUrl; } catch { /* keep the default */ }
  }
  return s;
}

function load(file) {
  try { return normalize(JSON.parse(fs.readFileSync(file, 'utf8'))); } catch { return { ...DEFAULTS }; }
}

function save(file, settings) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(normalize(settings), null, 2));
  fs.renameSync(tmp, file); // atomic: a crash never leaves a half-written file
}

module.exports = { DEFAULTS, SIDES, normalize, load, save };
