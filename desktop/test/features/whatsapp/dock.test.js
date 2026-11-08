const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..', '..', '..', 'src', 'features');
const src = fs.readFileSync(path.join(root, 'whatsapp', 'renderer', 'dock.js'), 'utf8');

// a tiny stand-in for the page: just the elements dock.js touches
function build({ layout = 'compact', reply = { ok: true } } = {}) {
  const els = {};
  const el = (id, extra = {}) => (els[id] = { id, hidden: false, value: '', dataset: {}, style: {}, textContent: '', parentNode: null, listeners: {}, disabled: false, scrollHeight: 20,
    attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, focus() { els.focused = id; }, requestSubmit() { (this.listeners.submit || []).forEach((f) => f({ preventDefault() {} })); },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }, insertBefore(node) { node.parentNode = this; }, appendChild(node) { node.parentNode = this; }, ...extra });
  for (const id of ['wa-dock', 'dock-ask', 'dock-direct', 'dock-thread', 'wa-reply', 'reply-collapse', 'wa-reply-input', 'wa-reply-send', 'wa-reply-note', 'composer', 'input', 'ask-collapse', 'chat-view', 'content', 'screen', 'page']) el(id);
  els.panel = { dataset: { screen: 'main', layout }, id: 'panel' };
  els['chat-view'].parentNode = els.page;
  els.content.hidden = true;
  const sent = [];
  const calls = { shown: [], reloaded: 0 };
  const P = {
    $: (id) => els[id], inits: [], state: { busy: false }, currentChat: { id: '1@lid', name: 'Maria' }, store: { set() {} },
    api: { sendWa: async (id, text) => { sent.push([id, text]); return reply; } },
    showView: (n) => { els.panel.dataset.screen = n; P.onScreen(n); calls.shown.push(n); }, applyLayout() {}, renderThread() {}, reloadChat() { calls.reloaded += 1; },
  };
  const ctx = { window: { Panel: P }, setTimeout: (f) => f() };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  P.inits.forEach((f) => f());
  const open = () => { els.panel.dataset.screen = 'chat'; P.onScreen('chat'); };
  return { els, P, sent, calls, open };
}

const boxesShown = (els) => [!els.composer.hidden, !els['wa-reply'].hidden].filter(Boolean).length;

test('a conversation opens with both boxes folded into the bar', () => {
  const { els, open } = build();
  open();
  assert.equal(els['wa-dock'].hidden, false);
  assert.equal(els.composer.hidden, true);
  assert.equal(els['wa-reply'].hidden, true);
});

test('outside a conversation the command line is the usual one and the bar is gone', () => {
  const { els, P } = build();
  P.onScreen('main');
  assert.equal(els['wa-dock'].hidden, true);
  assert.equal(els.composer.hidden, false);
  assert.equal(els['wa-reply'].hidden, true);
  assert.equal(els['ask-collapse'].hidden, true);
});

test('the two boxes are never open together', () => {
  const { els, open } = build();
  open();
  els['dock-ask'].listeners.click[0]();
  assert.equal(boxesShown(els), 1);
  assert.equal(els.composer.hidden, false);
  assert.equal(els.focused, 'input');
  els['ask-collapse'].listeners.click[0]();
  els['dock-direct'].listeners.click[0]();
  assert.equal(boxesShown(els), 1);
  assert.equal(els['wa-reply'].hidden, false);
  assert.equal(els.focused, 'wa-reply-input');
  assert.equal(els['wa-dock'].hidden, true);
});

test('a direct reply goes to WhatsApp as typed, then the box folds and the conversation reloads', async () => {
  const { els, sent, calls, open } = build();
  open();
  els['dock-direct'].listeners.click[0]();
  els['wa-reply-input'].value = '  chego em 10 min ';
  els['wa-reply'].requestSubmit();
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(sent, [['1@lid', 'chego em 10 min']]);
  assert.equal(els['wa-reply'].hidden, true);
  assert.equal(els['wa-dock'].hidden, false);
  assert.equal(els['wa-reply-input'].value, '');
  assert.equal(calls.reloaded, 1);
});

test('a failed direct reply keeps the text and the box, and says why', async () => {
  const { els, open } = build({ reply: { error: 'O WhatsApp não respondeu.' } });
  open();
  els['dock-direct'].listeners.click[0]();
  els['wa-reply-input'].value = 'oi';
  els['wa-reply'].requestSubmit();
  await new Promise((r) => setImmediate(r));
  assert.equal(els['wa-reply'].hidden, false);
  assert.equal(els['wa-reply-input'].value, 'oi');
  assert.equal(els['wa-reply-note'].textContent, 'O WhatsApp não respondeu.');
});

test('an empty direct reply sends nothing', async () => {
  const { els, sent, open } = build();
  open();
  els['dock-direct'].listeners.click[0]();
  els['wa-reply-input'].value = '   ';
  els['wa-reply'].requestSubmit();
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(sent, []);
});

test('asking the Chakmati from a conversation folds the box and offers the way to his conversation', () => {
  const { els, calls, open } = build();
  open();
  els['dock-ask'].listeners.click[0]();
  els.input.value = 'resuma esta conversa';
  els.composer.listeners.submit[0]();   // the capture listener runs before the command line empties the box
  assert.equal(els.composer.hidden, true);
  assert.equal(els['wa-dock'].hidden, false);
  assert.equal(els['dock-thread'].hidden, false);
  els['dock-thread'].listeners.click[0]();
  assert.deepEqual(calls.shown, ['main']);
  assert.equal(els['dock-thread'].hidden, true);
});

test('opening a conversation again folds everything again', () => {
  const { els, P, open } = build();
  open();
  els['dock-direct'].listeners.click[0]();
  P.onScreen('chats');
  open();
  assert.equal(els['wa-reply'].hidden, true);
  assert.equal(els['wa-dock'].hidden, false);
});

test('big window: the conversation moves into the middle column and the sides stay; small card: it is a page of its own', () => {
  const wide = build({ layout: 'wide' });
  wide.open();
  assert.equal(wide.els['chat-view'].parentNode, wide.els.content);
  assert.equal(wide.els.content.hidden, false);
  wide.els.panel.dataset.screen = 'main';
  wide.P.onScreen('main');
  assert.equal(wide.els['chat-view'].parentNode, wide.els.page);
  const small = build({ layout: 'compact' });
  small.open();
  assert.equal(small.els['chat-view'].parentNode, small.els.page);
  assert.equal(small.els.content.hidden, true);
});

test('the stylesheet keeps the sides and the thread out of the way in the big window', () => {
  const css = fs.readFileSync(path.join(root, 'panel', 'renderer', 'panel.css'), 'utf8');
  assert.match(css, /\[data-layout="wide"\]\[data-screen="chat"\] #thread-section \{ display: none !important; \}/);
  assert.match(css, /\[data-layout="wide"\] #content > #chat-view \{ grid-column: 2;/);
  const html = fs.readFileSync(path.join(root, 'panel', 'renderer', 'panel.html'), 'utf8');
  assert.ok(html.includes('renderer/dock.js'));
});
