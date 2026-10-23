const test = require('node:test');
const assert = require('node:assert/strict');
const { shouldAct, followUpUntil, FOLLOW_UP_MS } = require('../src/lib/listen-policy');

const base = { text: 'que horas são', wake: false, awake: false, now: 1000, conversationUntil: 0 };

test('talk in the room is ignored', () => {
  assert.equal(shouldAct(base), false);
});

test('a wake phrase, or the engine waiting for a command, is acted on', () => {
  assert.equal(shouldAct({ ...base, wake: true }), true);
  assert.equal(shouldAct({ ...base, awake: true }), true);
});

test('after an answer the conversation stays open for a while, then closes', () => {
  const until = followUpUntil(1000);
  assert.equal(until, 1000 + FOLLOW_UP_MS);
  assert.equal(shouldAct({ ...base, now: 1000 + FOLLOW_UP_MS - 1, conversationUntil: until }), true);
  assert.equal(shouldAct({ ...base, now: 1000 + FOLLOW_UP_MS + 1, conversationUntil: until }), false);
});

test('empty text and the phrases a recogniser invents from noise are never acted on', () => {
  assert.equal(shouldAct({ ...base, text: '  ', awake: true }), false);
  assert.equal(shouldAct({ ...base, text: 'Obrigado.', awake: true }), false);
  assert.equal(shouldAct({ ...base, text: 'Legendas pela comunidade Amara.org', conversationUntil: 5000 }), false);
  assert.equal(shouldAct({ ...base, text: 'Obrigado, Xácmáti', wake: true }), true); // a real call still works
});
