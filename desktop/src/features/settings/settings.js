'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { assertLoopback } = require('../engine').client;

const SIDES = ['auto', 'top', 'bottom', 'left', 'right'];
const MOODS = ['auto', 'idle', 'alert', 'thinking', 'happy'];
const PERSONALITIES = ['padrao', 'carioca', 'paulista', 'gaucho', 'nordestino', 'mineiro']; // the regional way of speaking (the engine adds it to short chat answers)
const PERSONALITY_NAMES = Object.freeze({ padrao: 'Padrão', carioca: 'Carioca', paulista: 'Paulista', gaucho: 'Gaúcho', nordestino: 'Nordestino', mineiro: 'Mineiro' });
const PRONOUNS = ['none', 'ele', 'ela', 'elu']; // how the person is addressed; 'none' = prefers not to say (nothing is assumed)
const PRONOUN_NAMES = Object.freeze({ none: 'Prefiro não informar', ele: 'ele/dele', ela: 'ela/dela', elu: 'elu/delu' });
const DEFAULTS = Object.freeze({
  protect: true,          // ask the OS to leave the windows out of screen sharing and recordings (best effort)
  still: true,            // true = no animations: Chakmati stays still (the default: animations cost about 70 MB of memory; the setup wizard offers them)
  glass: false,           // the "liquid glass" look of the panel (blur of what is behind it); off = flat panes, about 80 MB of memory less
  hear: false,            // "Ouvir o Chakmati": answers and notices are spoken aloud
  enhancedVoice: false,   // false = the voice of the operating system; true = the small neural voice (downloaded when turned on)
  voiceSpeed: 'normal',   // 'normal' | 'fast' (enhanced voice only)
  speakEmojis: false,     // read emojis aloud ("rosto sorrindo"); off: they are skipped when speaking
  micSource: 'computer',  // 'computer' = the computer's own microphone, 'system' = whatever the system default is
  laya: false,            // the Laya relevance filter for the web search (opt-in; the setup wizard says it is not recommended)
  talk: false,            // "Falar com o Chakmati": the microphone is always listening for the wake phrases and commands
  autoRunSafe: false,     // keep SAFE computer commands approved (never scripts, downloads, edits, the trash or opening programs)
  keepAwake: true,        // keep the computer from sleeping by idleness while an automation is on (the screen may still turn off); on by default
  autoSend: false,        // approve WhatsApp sends automatically (the person's standing permission; the engine still rate-limits)
  masked: false,          // discreet mode: bubbles never show names or titles
  bubbleSide: 'auto',
  personalities: [...PERSONALITIES], // the personalities the person has installed (the setup wizard narrows it); the active one is always in it
  pronouns: 'none',       // 'none' | 'ele' | 'ela' | 'elu': how the Chakmati addresses the person
  personality: 'padrao',  // 'padrao' = no regional flavour; the engine changes at once (PUT /personality) and starts with it (CHAKMATI_PERSONALITY)
  mood: 'auto',           // 'auto' follows what is happening; the others pin Chakmati's face (offline still shows)
  icon: null,             // {x, y} of the robot on screen, null = default corner
  engineUrl: 'http://127.0.0.1:8765',
  whatsapp: false,        // integrations the app switches on when it starts the engine itself
  calendar: false,
  research: true,         // answer questions that need the web by searching it
  home: false,            // the smart house and the Alexa's music, through Home Assistant (connected from Ajustes)
  cloudProvider: '',      // '' | 'anthropic' | 'openai': the paid AI the person connected (its key lives in the system's store, never here); used first
  cloudModel: '',
  localModel: true,       // false = only the paid AI (no local model behind it when its limit is over)
  chatModel: 'qwen3.5:latest', // the Ollama model the engine chats with (the setup wizard picks the one that fits this computer)
});

function normalize(raw) {
  const r = raw && typeof raw === 'object' ? raw : {};
  const s = { ...DEFAULTS };
  if (typeof r.protect === 'boolean') s.protect = r.protect;
  if (typeof r.masked === 'boolean') s.masked = r.masked;
  if (typeof r.autoSend === 'boolean') s.autoSend = r.autoSend;
  if (typeof r.keepAwake === 'boolean') s.keepAwake = r.keepAwake;
  if (typeof r.autoRunSafe === 'boolean') s.autoRunSafe = r.autoRunSafe;
  if (typeof r.hear === 'boolean') s.hear = r.hear;
  if (typeof r.talk === 'boolean') s.talk = r.talk;
  if (typeof r.laya === 'boolean') s.laya = r.laya;
  if (typeof r.speakEmojis === 'boolean') s.speakEmojis = r.speakEmojis;
  if (typeof r.enhancedVoice === 'boolean') s.enhancedVoice = r.enhancedVoice;
  if (r.voiceSpeed === 'normal' || r.voiceSpeed === 'fast') s.voiceSpeed = r.voiceSpeed;
  if (r.micSource === 'computer' || r.micSource === 'system') s.micSource = r.micSource;
  if (typeof r.still === 'boolean') s.still = r.still;
  if (typeof r.glass === 'boolean') s.glass = r.glass;
  if (typeof r.whatsapp === 'boolean') s.whatsapp = r.whatsapp;
  if (typeof r.calendar === 'boolean') s.calendar = r.calendar;
  if (typeof r.research === 'boolean') s.research = r.research;
  if (typeof r.home === 'boolean') s.home = r.home;
  if (r.cloudProvider === 'anthropic' || r.cloudProvider === 'openai') s.cloudProvider = r.cloudProvider;
  if (typeof r.cloudModel === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$/.test(r.cloudModel)) s.cloudModel = r.cloudModel;
  if (typeof r.localModel === 'boolean') s.localModel = r.localModel;
  if (!s.cloudProvider || !s.cloudModel) { s.cloudProvider = ''; s.cloudModel = ''; s.localModel = true; }   // half a connection is no connection
  if (typeof r.chatModel === 'string' && /^[a-z0-9][a-z0-9._:-]{0,63}$/i.test(r.chatModel)) s.chatModel = r.chatModel;
  if (SIDES.includes(r.bubbleSide)) s.bubbleSide = r.bubbleSide;
  if (MOODS.includes(r.mood)) s.mood = r.mood;
  if (PERSONALITIES.includes(r.personality)) s.personality = r.personality;
  if (PRONOUNS.includes(r.pronouns)) s.pronouns = r.pronouns;
  if (Array.isArray(r.personalities)) s.personalities = PERSONALITIES.filter((p) => r.personalities.includes(p)); // known ones only, in the catalog's order
  s.personalities = PERSONALITIES.filter((p) => p === 'padrao' || p === s.personality || s.personalities.includes(p)); // Padrão and the active one are always there
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
    CHAKMATI_CLOUD_PROVIDER: settings.cloudProvider,
    CHAKMATI_CLOUD_MODEL: settings.cloudModel,
    CHAKMATI_LOCAL_MODEL: settings.localModel ? '1' : '0',
    CHAKMATI_PERSONALITY: settings.personality,
    CHAKMATI_PRONOUNS: settings.pronouns,
    CHAKMATI_RESEARCH_BACKEND: !settings.research ? 'off' : searxng ? 'searxng' : 'ddg',
    CHAKMATI_WHATSAPP_BACKEND: settings.whatsapp ? 'openwa' : 'off',
    CHAKMATI_CALENDAR_BACKEND: settings.calendar ? 'auto' : 'off',
    CHAKMATI_HOME_BACKEND: settings.home ? 'homeassistant' : 'off',
    CHAKMATI_RESEARCH_SCORER: settings.laya ? 'laya' : 'keepall',
  };
}

module.exports = { DEFAULTS, SIDES, MOODS, PERSONALITIES, PERSONALITY_NAMES, PRONOUNS, PRONOUN_NAMES, normalize, load, save, engineEnv };
