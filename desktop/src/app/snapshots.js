'use strict';
// Design snapshots and the screen-capture protection test (development aids, off in normal use).
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app, ipcMain, screen, nativeTheme } = require('electron');
const settingsLib = require('../features/settings').settings;
const { brief } = require('../features/notices').brief;
const ctx = require('../shared/context');
const { PROTECT_TEST, SNAPSHOT } = require('../shared/constants');
const { sleep, sendTo } = require('../shared/util');
const widgetWindow = require('../features/widget').window;
const panelWindow = require('../features/panel').window;
const widgetMood = require('../features/widget').mood;

const SAMPLE_OVERVIEW = {
  whatsapp: { enabled: true, connected: true, state: 'READY', unread: [
    { id: '1@lid', name: 'Maria Victoria', unread: 2, is_group: false },
    { id: '2@g.us', name: 'Família', unread: 5, is_group: true },
    { id: '3@lid', name: 'João Pereira', unread: 1, is_group: false },
  ] },
  automations: [{ id: 'b'.repeat(32), name: 'Resposta automática', enabled: true, runs: 2, description: 'Quando alguém te escrever no WhatsApp, responder: «Estou ocupado».' }],
  calendar: { enabled: true, today: [
    { id: 'e1', title: 'Reunião de planejamento', start: new Date(new Date().setHours(15, 0, 0, 0)).toISOString(), all_day: false },
    { id: 'e2', title: 'Dentista', start: new Date(new Date().setHours(17, 30, 0, 0)).toISOString(), all_day: false },
  ] },
  pending: [{ id: 'a'.repeat(32), kind: 'whatsapp.send', status: 'pending', expires_at: 9e9,
    summary: 'Enviar WhatsApp para Maria Victoria +5551999990000:\nChego em 10 minutos, me espera na portaria.' }],
  last_notice_id: 3,
};

async function capture(win, file) {
  const image = await win.webContents.capturePage();
  fs.writeFileSync(file, image.toPNG());
}

// Asks the OS for a real screenshot with the panel shown, protected and unprotected, so the claim is measured, not assumed.
async function runProtectTest() {
  const out = PROTECT_TEST;
  fs.mkdirSync(out, { recursive: true });
  ctx.settings = { ...settingsLib.DEFAULTS, protect: false };
  ctx.engine = { overview: async () => SAMPLE_OVERVIEW };
  ctx.state.engineUp = true;
  ctx.state.overview = SAMPLE_OVERVIEW;
  ctx.icon = { x: 200, y: 200 };
  panelWindow.createPanel();
  await new Promise((r) => ipcMain.once('panel:ready', r));
  ctx.state.panelOpen = true;
  panelWindow.positionPanel();
  ctx.panelWin.show();
  panelWindow.sendPanelState();
  const run = (file) => new Promise((res) => spawn('screencapture', ['-x', path.join(out, file)]).on('close', res));
  await sleep(800);
  await run('unprotected.png');
  ctx.settings.protect = true;
  widgetWindow.protect(ctx.panelWin);
  await sleep(800);
  await run('protected.png');
  console.log('panel bounds', JSON.stringify(ctx.panelWin.getBounds()));
  app.quit();
}

async function runSnapshots() {
  const out = SNAPSHOT === '1' ? path.join(app.getPath('temp'), 'chakmati-desktop-snapshots') : SNAPSHOT;
  fs.mkdirSync(out, { recursive: true });
  ctx.settings = { ...settingsLib.DEFAULTS, protect: false, hear: true, talk: true };
  const SAMPLE_CHATS = [
    { id: '162457238634742@lid', name: 'Maria Victoria', is_group: false, unread: 2 },
    { id: '120363@g.us', name: 'Família', is_group: true, unread: 5 },
    { id: '222@lid', name: 'João Pereira', is_group: false, unread: 1 },
    { id: '333@lid', name: 'Tio Alex', is_group: false, unread: 0 },
  ];
  const now = new Date().toISOString();
  const SAMPLE_MESSAGES = [
    { id: 'm1', sender: 'Maria Victoria', text: 'Oi! Chego em 10 minutos', ts: now, from_me: false, kind: 'chat', duration: null, audio: false },
    { id: 'm2', sender: 'Maria Victoria', text: '', ts: now, from_me: false, kind: 'ptt', duration: 25, audio: true },
    { id: 'm3', sender: 'eu', text: 'Combinado, te espero na portaria', ts: now, from_me: true, kind: 'chat', duration: null, audio: false },
    { id: 'm4', sender: 'Maria Victoria', text: '', ts: now, from_me: false, kind: 'image', duration: null, audio: false },
  ];
  ctx.engine = { overview: async () => SAMPLE_OVERVIEW, chats: async () => SAMPLE_CHATS, messages: async () => SAMPLE_MESSAGES };
  ctx.state.engineUp = true;
  ctx.state.overview = SAMPLE_OVERVIEW;
  ctx.state.notices = [
    { id: 1, kind: 'whatsapp', text: 'Você recebeu uma nova mensagem de Maria Victoria', masked: 'Você recebeu uma nova mensagem no WhatsApp', ts: Date.now() / 1000 - 40 },
    { id: 2, kind: 'calendar', text: 'Em 10 min: Reunião de planejamento', masked: 'Você tem um compromisso em breve', ts: Date.now() / 1000 - 400 },
    { id: 3, kind: 'approval', text: 'Há uma ação aguardando a sua aprovação: Enviar WhatsApp para Maria Victoria', masked: 'Há uma ação aguardando a sua aprovação', ts: Date.now() / 1000 - 700 },
  ];
  const wa = screen.getPrimaryDisplay().workArea;
  const shot = async (name, win) => { await sleep(450); await capture(win, path.join(out, name)); };

  widgetWindow.createWidget();
  await new Promise((r) => ipcMain.once('widget:ready', r));
  sendTo(ctx.widgetWin, 'widget:backdrop', true);
  ctx.widgetWin.showInactive();

  ctx.icon = { x: wa.x + wa.width - 160, y: wa.y + wa.height - 160 };
  widgetWindow.applyLayout();
  widgetMood.showBubble(ctx.state.notices[0]);
  await shot('widget-top-right.png', ctx.widgetWin);

  ctx.icon = { x: wa.x + 40, y: wa.y + 30 };
  widgetWindow.applyLayout();
  widgetMood.showBubble(ctx.state.notices[2]);
  await shot('widget-bottom-left.png', ctx.widgetWin);

  ctx.settings.bubbleSide = 'left';
  ctx.icon = { x: wa.x + Math.round(wa.width / 2), y: wa.y + Math.round(wa.height / 2) };
  widgetWindow.applyLayout();
  widgetMood.showBubble(ctx.state.notices[1]);
  await shot('widget-left.png', ctx.widgetWin);

  widgetMood.showBubble({ id: 9, kind: 'reply', text: brief('Oé! Se eu somasse 5 e dissesse oé, você ia rir ou me chamar de mentiroso? Mas a resposta correta é 4. Sem truques, só matemática pura. Tamo aqui pra te ajudar com mais esse desafio.'), masked: 'O Chakmati respondeu.', ts: Date.now() / 1000, key: 'r' });
  sendTo(ctx.widgetWin, 'widget:listening', true);
  await shot('widget-reply.png', ctx.widgetWin);
  sendTo(ctx.widgetWin, 'widget:listening', false);

  ctx.state.engineUp = false;
  widgetMood.refreshMood();
  widgetMood.hideBubble();
  await shot('widget-offline.png', ctx.widgetWin);
  ctx.state.engineUp = true;
  widgetMood.hideBubble();

  ctx.icon = { x: wa.x + wa.width - 160, y: wa.y + wa.height - 160 };
  ctx.settings.bubbleSide = 'auto';
  widgetWindow.applyLayout();
  panelWindow.createPanel();
  await new Promise((r) => ipcMain.once('panel:ready', r));
  ctx.state.panelOpen = true;
  panelWindow.positionPanel();
  ctx.panelWin.showInactive();
  panelWindow.sendPanelState();
  await shot('panel.png', ctx.panelWin);

  await ctx.panelWin.webContents.executeJavaScript("document.getElementById('content').scrollTop = 99999; document.getElementById('create-automation').click()");
  await shot('panel-bottom.png', ctx.panelWin);
  await ctx.panelWin.webContents.executeJavaScript("document.getElementById('content').scrollTop = 0; document.getElementById('automation-note').hidden = true");
  await ctx.panelWin.webContents.executeJavaScript("document.getElementById('chips').classList.add('open')");
  await shot('panel-suggestions.png', ctx.panelWin);
  await ctx.panelWin.webContents.executeJavaScript("document.getElementById('chips').classList.remove('open')");
  const click = (sel) => ctx.panelWin.webContents.executeJavaScript(`document.querySelector(${JSON.stringify(sel)}).click()`);
  await click('.more');
  await shot('panel-chats.png', ctx.panelWin);
  await click('#chats-body .row-btn');
  await shot('panel-chat.png', ctx.panelWin);
  await click('#back');
  await click('#back');
  await ctx.panelWin.webContents.executeJavaScript("document.getElementById('open-settings').click()");
  await shot('panel-settings.png', ctx.panelWin);
  await ctx.panelWin.webContents.executeJavaScript("document.getElementById('back').click()");
  nativeTheme.themeSource = 'dark';
  await shot('panel-dark.png', ctx.panelWin);
  nativeTheme.themeSource = 'light';

  ctx.settings.masked = true;
  panelWindow.sendPanelState();
  await shot('panel-masked.png', ctx.panelWin);
  ctx.settings.masked = false;

  ctx.state.overview = { ...SAMPLE_OVERVIEW, pending: [], whatsapp: { enabled: true, connected: false, state: 'UNPAIRED', unread: [] } };
  panelWindow.sendPanelState();
  await shot('panel-wa-down.png', ctx.panelWin);

  ctx.state.engineUp = false;
  ctx.state.overview = null;
  panelWindow.sendPanelState();
  await shot('panel-offline.png', ctx.panelWin);

  console.log(`snapshots written to ${out}`);
  app.quit();
}

Object.assign(module.exports, { runProtectTest, runSnapshots });
