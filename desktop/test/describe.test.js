const test = require('node:test');
const assert = require('node:assert/strict');
const { describe, plural } = require('../src/lib/describe');

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
