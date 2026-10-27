const test = require('node:test');
const assert = require('node:assert/strict');
const { shouldAct } = require('../../../src/features/voice/listen-policy');

const base = { text: 'que horas são', wake: false, awake: false };

test('talk in the room is ignored', () => {
  assert.equal(shouldAct(base), false);
});

test('a wake phrase, or the engine waiting for its one command, is acted on', () => {
  assert.equal(shouldAct({ ...base, wake: true }), true);
  assert.equal(shouldAct({ ...base, awake: true }), true);
});

test('there is no open-ended conversation: without the wait for a command, the next sentence is ignored', () => {
  assert.equal(shouldAct({ ...base, text: 'e a capital da França?' }), false);
});

test('empty text and the phrases a recogniser invents from noise are never acted on', () => {
  assert.equal(shouldAct({ ...base, text: '  ', awake: true }), false);
  assert.equal(shouldAct({ ...base, text: 'Obrigado.', awake: true }), false);
  assert.equal(shouldAct({ ...base, text: 'Thank you.', awake: true }), false);
  assert.equal(shouldAct({ ...base, text: 'Legendas pela comunidade Amara.org', awake: true }), false);
  assert.equal(shouldAct({ ...base, text: 'Obrigado, Xácmáti', wake: true }), true);
});
