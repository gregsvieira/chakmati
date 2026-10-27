'use strict';
// The enhanced voice: status, download, warm-up and what the widget is told to say.
const { EngineError } = require('../engine/client');
const ctx = require('../../app/context');
const { sendTo, sleep, friendlyError } = require('../../app/util');
const panelWindow = require('../panel/window');
const settingsService = require('../settings/service');
const widgetMood = require('../widget/mood');
const trayMenu = require('../../app/tray');

let voiceDownloading = false;

// The enhanced voice is used only once it is installed; until then (and if anything fails) the system voice speaks.
const enhancedReady = () => ctx.settings.enhancedVoice === true && !!(ctx.state.voice && ctx.state.voice.installed);

const sendVoice = () => sendTo(ctx.widgetWin, 'widget:voice', { hear: ctx.settings.hear, emojis: ctx.settings.speakEmojis, enhanced: enhancedReady(), speed: ctx.settings.voiceSpeed });

async function warmVoice() {
  if (ctx.voiceWarmed || !enhancedReady()) return;
  ctx.voiceWarmed = true;
  try { await ctx.engine.speak('ok', ctx.settings.voiceSpeed); } catch { ctx.voiceWarmed = false; }
}

async function refreshVoiceStatus() {
  try { ctx.state.voice = await ctx.engine.voiceStatus(); } catch { ctx.state.voice = null; }
  panelWindow.sendPanelState();
  sendVoice();
}

async function downloadVoice() {
  if (voiceDownloading) return;
  voiceDownloading = true;
  try {
    ctx.state.voice = await ctx.engine.voiceDownload();
    panelWindow.sendPanelState();
    while (!ctx.quitting && ctx.state.voice && ctx.state.voice.downloading) {
      await sleep(600);
      ctx.state.voice = await ctx.engine.voiceStatus();
      panelWindow.sendPanelState();
    }
    if (!ctx.state.voice || !ctx.state.voice.installed) throw new Error((ctx.state.voice && ctx.state.voice.error) || 'não consegui baixar');
    widgetMood.localNotice('Voz melhorada pronta.');
  } catch (e) {
    ctx.settings.enhancedVoice = false;
    settingsService.persistSettings();
    widgetMood.localNotice(`Não consegui baixar a voz melhorada: ${e instanceof EngineError ? friendlyError(e) : (e && e.message) || 'erro'}`);
  } finally {
    voiceDownloading = false;
    sendVoice();
    panelWindow.sendPanelState();
    trayMenu.rebuildMenu();
  }
}

Object.assign(module.exports, { warmVoice, refreshVoiceStatus, sendVoice, downloadVoice, enhancedReady });
