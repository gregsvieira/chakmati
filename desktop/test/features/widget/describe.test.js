const test = require('node:test');
const assert = require('node:assert/strict');
const { describe, plural } = require('../../../src/features/widget/describe');

const ok = (over = {}) => ({
  whatsapp: { enabled: true, connected: true, state: 'READY', unread: [] },
  calendar: { enabled: true, today: [] },
  pending: [],
  ...over,
});

test('plural', () => {
  assert.equal(plural(1, 'conversa', 'conversas'), '1 conversa');
  assert.equal(plural(3, 'conversa', 'conversas'), '3 conversas');
  assert.equal(plural(0, 'conversa', 'conversas'), '0 conversas');
});

test('engine down: says so, mood offline', () => {
  const d = describe({ engineUp: false });
  assert.equal(d.mood, 'offline');
  assert.match(d.title, /motor/i);
});

test('nothing happening', () => {
  const d = describe({ engineUp: true, overview: ok() });
  assert.deepEqual([d.title, d.detail, d.mood], ['Tudo certo por aqui.', 'Nada novo por enquanto.', 'idle']);
});

test('unread conversations and events today are summarised in one sentence', () => {
  const d = describe({ engineUp: true, overview: ok({
    whatsapp: { enabled: true, connected: true, state: 'READY', unread: [{ name: 'Maria', unread: 2 }, { name: 'João', unread: 1 }] },
    calendar: { enabled: true, today: [{ title: 'Dentista' }] },
  }) });
  assert.equal(d.detail, 'Você tem 2 conversas com mensagens não lidas e 1 compromisso hoje.');
});

test('only events, only unread', () => {
  assert.equal(describe({ engineUp: true, overview: ok({ calendar: { enabled: true, today: [{}, {}] } }) }).detail, 'Você tem 2 compromissos hoje.');
  assert.equal(describe({ engineUp: true, overview: ok({ whatsapp: { enabled: true, connected: true, state: 'READY', unread: [{ unread: 4 }] } }) }).detail,
    'Você tem 1 conversa com mensagens não lidas.');
});

test('pending approvals take over the headline and set the alert mood', () => {
  const d = describe({ engineUp: true, overview: ok({ pending: [{}, {}] }) });
  assert.deepEqual([d.title, d.detail, d.mood], ['Preciso da sua decisão.', 'Há 2 ações aguardando a sua aprovação.', 'alert']);
  assert.equal(describe({ engineUp: true, overview: ok({ pending: [{}] }) }).detail, 'Há 1 ação aguardando a sua aprovação.');
});

test('a disconnected WhatsApp is mentioned without hiding the rest', () => {
  const d = describe({ engineUp: true, overview: ok({ whatsapp: { enabled: true, connected: false, state: 'AUTHENTICATING', unread: [] } }) });
  assert.match(d.detail, /WhatsApp está desconectado/);
  const err = describe({ engineUp: true, overview: ok({ whatsapp: { enabled: true, error: 'unreachable' } }) });
  assert.match(err.detail, /WhatsApp está desconectado/);
});

test('online and idle he is bored; with the WhatsApp cut off he is drunk; working or alert still win', () => {
  assert.equal(describe({ engineUp: true, overview: ok() }).mood, 'idle');
  assert.equal(describe({ engineUp: true, overview: ok({ whatsapp: { enabled: true, connected: false, state: 'X', unread: [] } }) }).mood, 'drunk');
  assert.equal(describe({ engineUp: true, overview: ok({ whatsapp: { enabled: true, error: 'unreachable' } }) }).mood, 'drunk');
  assert.equal(describe({ engineUp: true, busy: true, overview: ok({ whatsapp: { enabled: true, error: 'x' } }) }).mood, 'thinking');
  assert.equal(describe({ engineUp: true, overview: ok({ pending: [{}], whatsapp: { enabled: true, error: 'x' } }) }).mood, 'alert');
  assert.equal(describe({ engineUp: false }).mood, 'offline');
});

test('disabled integrations are not mentioned', () => {
  const d = describe({ engineUp: true, overview: { whatsapp: { enabled: false }, calendar: { enabled: false }, pending: [] } });
  assert.equal(d.detail, 'Nada novo por enquanto.');
});

test('busy wins over everything else but offline', () => {
  assert.equal(describe({ engineUp: true, busy: true, overview: ok({ pending: [{}] }) }).mood, 'thinking');
  assert.equal(describe({ engineUp: false, busy: true }).mood, 'offline');
});

test('no overview yet (first seconds) does not crash', () => {
  assert.equal(describe({ engineUp: true, overview: null }).mood, 'idle');
});

test('after a wake phrase it waits for the command, ahead of everything but being offline or busy', () => {
  const awake = { awake: true, pending: [{ id: 'a' }] };
  assert.deepEqual(describe({ engineUp: true, overview: awake }), { title: 'Aguardando seu comando.', detail: 'Pode falar ou digitar.', mood: 'alert' });
  assert.equal(describe({ engineUp: true, overview: awake, busy: true }).mood, 'thinking');
  assert.equal(describe({ engineUp: false, overview: awake }).mood, 'offline');
});

// ---- refreshMood and the panel's state send each other: it has to end
test('refreshMood and sendPanelState do not call each other forever', () => {
  const Module = require('node:module');
  const origLoad = Module._load;
  const sent = [];
  Module._load = function (request, ...rest) {
    if (request === 'electron') {   // anything the app asks of electron answers with a function that does nothing
      const quiet = () => new Proxy(function () {}, { get: (_t, k) => (k === Symbol.toPrimitive ? () => '' : k === 'getPath' ? () => '/tmp' : quiet()), apply: () => quiet(), construct: () => quiet() });
      return quiet();
    }
    return origLoad.call(this, request, ...rest);
  };
  try {
    const ctx = require('../../../src/shared/context');
    const widgetMood = require('../../../src/features/widget').mood;
    ctx.settings = { mood: 'auto', masked: false };
    ctx.state.engineUp = true; ctx.state.overview = null; ctx.state.busy = 0; ctx.state.notices = [];
    ctx.panelMood = null;
    ctx.panelWin = { isDestroyed: () => false, webContents: { isDestroyed: () => false, send: (...a) => sent.push(a) } };
    ctx.widgetWin = null;
    assert.doesNotThrow(() => { widgetMood.refreshMood(); widgetMood.refreshMood(); });
    ctx.state.busy = 1;                       // a new mood: the panel is told once
    assert.doesNotThrow(() => widgetMood.refreshMood());
    assert.equal(ctx.panelMood, 'thinking');
  } finally {
    Module._load = origLoad;
  }
});
