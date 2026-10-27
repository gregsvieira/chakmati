'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { assertLoopback } = require('./engine-client');

const SIDES = ['auto', 'top', 'bottom', 'left', 'right'];
const MOODS = ['auto', 'idle', 'alert', 'thinking', 'happy'];
const DEFAULTS = Object.freeze({
  protect: true,          // ask the OS to leave the windows out of screen sharing and recordings (best effort)
  still: false,           // true = no animations: Chakmati stays still
  hear: false,            // "Ouvir o Chakmati": answers and notices are spoken aloud
  enhancedVoice: false,   // false = the voice of the operating system; true = the small neural voice (downloaded when turned on)
  voiceSpeed: 'normal',   // 'normal' | 'fast' (enhanced voice only)
  speakEmojis: false,     // read emojis aloud ("rosto sorrindo"); off: they are skipped when speaking
  micSource: 'computer',  // 'computer' = the computer's own microphone, 'system' = whatever the system default is
  laya: false,            // the Laya relevance filter for the web search (opt-in; the setup wizard says it is not recommended)
  talk: false,            // "Falar com o Chakmati": the microphone is always listening for the wake phrases and commands
  autoRunSafe: false,     // keep SAFE computer commands approved (never scripts, downloads, edits, the trash or opening programs)
  autoSend: false,        // approve WhatsApp sends automatically (the person's standing permission; the engine still rate-limits)
  masked: false,          // discreet mode: bubbles never show names or titles
  bubbleSide: 'auto',
  mood: 'auto',           // 'auto' follows what is happening; the others pin Chakmati's face (offline still shows)
  icon: null,             // {x, y} of the robot on screen, null = default corner
  engineUrl: 'http://127.0.0.1:8765',
  whatsapp: false,        // integrations the app switches on when it starts the engine itself
  calendar: false,
  research: true,         // answer questions that need the web by searching it
  chatModel: 'qwen3.5:latest', // the Ollama model the engine chats with (the setup wizard picks the one that fits this computer)
});

function normalize(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const s = { ...DEFAULTS };
  if (typeof r.protect === 'boolean') s.protect = r.protect;
  if (typeof r.masked === 'boolean') s.masked = r.masked;
  if (typeof r.autoSend === 'boolean') s.autoSend = r.autoSend;
  if (typeof r.autoRunSafe === 'boolean') s.autoRunSafe = r.autoRunSafe;
  if (typeof r.hear === 'boolean') s.hear = r.hear;
  if (typeof r.talk === 'boolean') s.talk = r.talk;
  if (typeof r.laya === 'boolean') s.laya = r.laya;
  if (typeof r.speakEmojis === 'boolean') s.speakEmojis = r.speakEmojis;
  if (typeof r.enhancedVoice === 'boolean') s.enhancedVoice = r.enhancedVoice;
  if (r.voiceSpeed === 'normal' || r.voiceSpeed === 'fast') s.voiceSpeed = r.voiceSpeed;
  if (r.micSource === 'computer' || r.micSource === 'system') s.micSource = r.micSource;
  if (typeof r.still === 'boolean') s.still = r.still;
  if (typeof r.whatsapp === 'boolean') s.whatsapp = r.whatsapp;
  if (typeof r.calendar === 'boolean') s.calendar = r.calendar;
  if (typeof r.research === 'boolean') s.research = r.research;
  if (typeof r.chatModel === 'string' && /^[a-z0-9][a-z0-9._:-]{0,63}$/i.test(r.chatModel)) s.chatModel = r.chatModel;
  if (SIDES.includes(r.bubbleSide)) s.bubbleSide = r.bubbleSide;
  if (MOODS.includes(r.mood)) s.mood = r.mood;
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

// Environment the engine is started with, so the person never has to type CHAKMATI_* variables.
function engineEnv(settings, { searxng = false } = {}) {
  return {
    CHAKMATI_CHAT_MODEL: settings.chatModel,
    CHAKMATI_RESEARCH_BACKEND: !settings.research ? 'off' : searxng ? 'searxng' : 'ddg',
    CHAKMATI_WHATSAPP_BACKEND: settings.whatsapp ? 'openwa' : 'off',
    CHAKMATI_CALENDAR_BACKEND: settings.calendar ? 'auto' : 'off',
    CHAKMATI_RESEARCH_SCORER: settings.laya ? 'laya' : 'keepall',
  };
}

module.exports = { DEFAULTS, SIDES, MOODS, normalize, load, save, engineEnv };
