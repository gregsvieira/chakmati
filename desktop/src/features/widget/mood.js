'use strict';
// The robot's face, the bell behind its head, the speech bubble and the queue of notices.
const { bellState, moodWithBell, countsAsNotice } = require('./bell');
const { describe } = require('./describe');
const { present, bubbleDuration } = require('../notices').queue;
const ctx = require('../../shared/context');
const { sendTo } = require('../../shared/util');
const panelWindow = require('../panel').window;

let awakeTimer = null;

function applyOverview(o) {
  ctx.state.overview = o;
  syncPending();
  ctx.state.awakeUntil = o && o.awake_for > 0 ? Date.now() + o.awake_for * 1000 : 0;
  clearTimeout(awakeTimer);
  if (ctx.state.awakeUntil) awakeTimer = setTimeout(() => { panelWindow.sendPanelState(); syncListening(); }, ctx.state.awakeUntil - Date.now() + 300);
  syncListening();
}

function currentBell() {
  const pending = (ctx.state.overview && Array.isArray(ctx.state.overview.pending)) ? ctx.state.overview.pending.length : 0;
  return bellState({ pending, asking: ctx.state.asking === true, unread: ctx.state.unread || 0 });
}

function syncBell() {
  const bell = currentBell();
  const key = `${bell.state}|${bell.label}`;
  if (key === ctx.bellShown) return;
  ctx.bellShown = key;
  sendTo(ctx.widgetWin, 'widget:bell', bell);
  panelWindow.sendPanelState();
}

const syncPending = syncBell;

function syncListening() {
  const on = ctx.settings.talk === true && Date.now() < (ctx.state.awakeUntil || 0);
  if (on === ctx.listeningShown) return;
  ctx.listeningShown = on;
  sendTo(ctx.widgetWin, 'widget:listening', on);
}

const overviewNow = () => (ctx.state.overview ? { ...ctx.state.overview, awake: Date.now() < (ctx.state.awakeUntil || 0) } : null);

function currentDescription() {
  return describe({ engineUp: ctx.state.engineUp, overview: overviewNow(), busy: ctx.state.busy > 0 });
}

// the face: what is happening, unless the person pinned a mood in Ajustes (an unreachable engine always shows as offline)
function effectiveMood(base) {
  if (base === 'offline' || ctx.settings.mood === 'auto') return base;
  return ctx.settings.mood;
}

function refreshMood() {
  let mood = currentDescription().mood;
  if (ctx.settings.mood !== 'auto') mood = effectiveMood(mood);
  else {
    mood = moodWithBell(mood, currentBell());
    if (mood !== 'offline' && mood !== 'thinking' && mood !== 'alert' && mood !== 'happy') {
      if (Date.now() < ctx.happyUntil) mood = 'happy';
      else if (ctx.state.bubbleVisible) mood = 'alert';
    }
  }
  sendTo(ctx.widgetWin, 'widget:mood', mood);
}

function showBubble(notice) {
  const text = present(notice, ctx.settings.masked);
  ctx.state.bubbleVisible = true;
  sendTo(ctx.widgetWin, 'widget:bubble', { text, kind: notice.kind, id: notice.id });
  refreshMood();
  clearTimeout(ctx.bubbleTimer);
  ctx.bubbleTimer = setTimeout(nextBubble, bubbleDuration(text));
}

function hideBubble() {
  clearTimeout(ctx.bubbleTimer);
  ctx.queue.clear();
  ctx.state.bubbleVisible = false;
  sendTo(ctx.widgetWin, 'widget:bubble', null);
  refreshMood();
}

function nextBubble() {
  const { show } = ctx.queue.done();
  if (show) { showBubble(show); return; }
  ctx.state.bubbleVisible = false;
  sendTo(ctx.widgetWin, 'widget:bubble', null);
  refreshMood();
}

function pushNotice(notice) {
  ctx.state.notices.push(notice);
  if (!ctx.state.panelOpen && countsAsNotice(notice)) { ctx.state.unread = (ctx.state.unread || 0) + 1; syncBell(); refreshMood(); }
  if (ctx.state.notices.length > 50) ctx.state.notices.shift();
  if (ctx.state.panelOpen) { panelWindow.sendPanelState(); return; } // the panel is open: the notice shows up in its list instead of a bubble
  if (ctx.state.hidden) return;
  const { show } = ctx.queue.push(notice);
  if (show) showBubble(show);
}

function localNotice(text, kind = 'system') {
  pushNotice({ id: -Date.now(), kind, text, masked: text, ts: Date.now() / 1000, key: `local:${text}` });
}

Object.assign(module.exports, { currentBell, overviewNow, currentDescription, effectiveMood, refreshMood, syncBell, hideBubble, localNotice, applyOverview, pushNotice, syncListening, nextBubble, showBubble });
