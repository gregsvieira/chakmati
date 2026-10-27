'use strict';
// Saving the settings and applying a change the person made in Ajustes.
const settingsLib = require('./settings');
const fs = require('node:fs');
const path = require('node:path');
const { app, systemPreferences } = require('electron');
const ctx = require('../../shared/context');
const { alive, sendTo } = require('../../shared/util');
const widgetWindow = require('../widget').window;
const widgetMood = require('../widget').mood;
const panelWindow = require('../panel').window;
const engineService = require('../engine').service;
const trayMenu = require('../tray').menu;
const voiceService = require('../voice').service;

// Saves the settings file; a no-op when there is none (design-snapshot mode), so a stray click can never crash the app.
function persistSettings() {
  if (ctx.settingsFile) settingsLib.save(ctx.settingsFile, ctx.settings);
}

function updateSetting(key, value) {
  if (process.env.CHAKMATI_DEBUG_WINDOWS === '1') { try { fs.appendFileSync(path.join(app.getPath('userData'), 'window-debug.log'), `${new Date().toISOString()} SETTING ${key}=${JSON.stringify(value)}\n`); } catch { /* debugging only */ } }
  if (key === 'protect' && typeof value === 'boolean') ctx.settings.protect = value;
  else if (key === 'masked' && typeof value === 'boolean') ctx.settings.masked = value;
  else if (key === 'bubbleSide' && settingsLib.SIDES.includes(value)) ctx.settings.bubbleSide = value;
  else if (key === 'hear' && typeof value === 'boolean') { ctx.settings.hear = value; voiceService.sendVoice(); }
  else if (key === 'talk' && typeof value === 'boolean') {
    ctx.settings.talk = value;
    widgetMood.syncListening();
    if (value) { // talking to Chakmati also means hearing it
      ctx.settings.hear = true;
      voiceService.sendVoice();
      if (process.platform === 'darwin') systemPreferences.askForMediaAccess('microphone').catch(() => {});
      if (!alive(ctx.panelWin)) panelWindow.createPanel(); // the always-on microphone lives in the panel window, which can stay hidden
    }
  }
  else if (key === 'enhancedVoice' && typeof value === 'boolean') {
    ctx.settings.enhancedVoice = value;
    if (value && !(ctx.state.voice && ctx.state.voice.installed)) voiceService.downloadVoice();
    else if (value) voiceService.warmVoice();
    voiceService.sendVoice();
  }
  else if (key === 'voiceSpeed' && (value === 'normal' || value === 'fast')) { ctx.settings.voiceSpeed = value; voiceService.sendVoice(); }
  else if (key === 'speakEmojis' && typeof value === 'boolean') { ctx.settings.speakEmojis = value; voiceService.sendVoice(); }
  else if (key === 'micSource' && (value === 'computer' || value === 'system')) ctx.settings.micSource = value;
  else if (key === 'autoRunSafe' && typeof value === 'boolean') { ctx.settings.autoRunSafe = value; engineService.syncStanding(); }
  else if (key === 'autoSend' && typeof value === 'boolean') { ctx.settings.autoSend = value; engineService.autoApproveNew(); }
  else if (key === 'still' && typeof value === 'boolean') { ctx.settings.still = value; sendTo(ctx.widgetWin, 'widget:still', value); }
  else if (key === 'mood' && settingsLib.MOODS.includes(value)) ctx.settings.mood = value;
  else if ((key === 'whatsapp' || key === 'calendar' || key === 'research') && typeof value === 'boolean') {
    ctx.settings[key] = value;
    if (ctx.engineProcess) engineService.restartEngine().then(engineService.refreshOverview);
  } else return false;
  persistSettings();
  widgetWindow.protect(ctx.widgetWin);
  widgetWindow.protect(ctx.panelWin);
  widgetWindow.applyLayout();
  widgetMood.refreshMood();
  panelWindow.sendPanelState();
  trayMenu.rebuildMenu();
  return true;
}

Object.assign(module.exports, { updateSetting, persistSettings });
