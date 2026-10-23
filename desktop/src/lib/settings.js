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
  whatsapp: false,        // integrations the app switches on when it starts the engine itself
  calendar: false,
});

function normalize(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const s = { ...DEFAULTS };
  if (typeof r.protect === 'boolean') s.protect = r.protect;
  if (typeof r.masked === 'boolean') s.masked = r.masked;
  if (typeof r.whatsapp === 'boolean') s.whatsapp = r.whatsapp;
  if (typeof r.calendar === 'boolean') s.calendar = r.calendar;
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

// Environment the engine is started with, so the person never has to type LITEAGENT_* variables.
function engineEnv(settings) {
  return {
    LITEAGENT_WHATSAPP_BACKEND: settings.whatsapp ? 'openwa' : 'off',
    LITEAGENT_CALENDAR_BACKEND: settings.calendar ? 'auto' : 'off',
  };
}

module.exports = { DEFAULTS, SIDES, normalize, load, save, engineEnv };
