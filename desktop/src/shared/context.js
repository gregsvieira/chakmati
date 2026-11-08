'use strict';
// The mutable state the parts of the main process share (windows, settings, the engine client, what is happening). One object, so every part
// sees the same values; a value used by a single part lives in that part instead.
const ctx = {
  settings: undefined,
  settingsFile: undefined,
  engine: undefined,
  widgetWin: null,
  panelWin: null,
  tray: null,
  engineProcess: null,
  icon: { x: 0, y: 0 },
  layout: null,
  dragStart: null,
  bubbleTimer: null,
  moodTimer: null,
  quitting: false,
  happyUntil: 0,
  panelMood: null,   // the mood the panel was last told (the panel's face follows the widget's)
  angryUntil: 0,   // something failed a moment ago (an answer that did not work, an automation that failed): the face is angry until then
  queue: null, // the NoticeQueue, created at start
  streams: new Map(),
  jobOf: new Map(),
  stopped: new Set(),
  state: { voice: null, engineUp: false, overview: null, notices: [], busy: 0, hidden: false, panelOpen: false, bubbleVisible: false, warnedDown: false, unread: 0, asking: false },
  bellShown: '',
  listeningShown: null,
  panelMode: 'compact',
  voiceWarmed: false,
};

module.exports = ctx;
