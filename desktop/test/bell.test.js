const test = require('node:test');
const assert = require('node:assert/strict');
const { bellState, moodWithBell, countsAsNotice } = require('../src/lib/bell');

test('nothing to see: a plain bell, no mood of its own', () => {
  assert.deepEqual(bellState({}), { state: 'idle', mood: null, label: 'Nenhuma novidade' });
});

test('a notice makes the bell red and the face happy', () => {
  assert.deepEqual(bellState({ unread: 1 }), { state: 'notice', mood: 'happy', label: '1 novidade' });
  assert.equal(bellState({ unread: 3 }).label, '3 novidades');
});

test('a request (an action to approve, a question) makes it yellow and the face alert', () => {
  assert.deepEqual(bellState({ pending: 2 }), { state: 'request', mood: 'alert', label: '2 aprovações pendentes' });
  const asking = bellState({ asking: true });
  assert.equal(asking.state, 'request');
  assert.equal(asking.mood, 'alert');
  assert.match(asking.label, /precisa de uma resposta/);
});

test('a request wins over a notice', () => {
  assert.equal(bellState({ pending: 1, unread: 5 }).state, 'request');
  assert.equal(bellState({ asking: true, unread: 5 }).state, 'request');
  assert.match(bellState({ asking: true, pending: 1 }).label, /1 aprovação pendente/);
});

test('the face follows the bell only when the mood is automatic', () => {
  const notice = bellState({ unread: 1 });
  const request = bellState({ pending: 1 });
  assert.equal(moodWithBell('idle', notice), 'happy');
  assert.equal(moodWithBell('idle', request), 'alert');
  assert.equal(moodWithBell('idle', notice, { pinned: true }), 'idle');   // pinned in Ajustes: it stays
  assert.equal(moodWithBell('idle', bellState({})), 'idle');
});

test('an engine that is down always shows as offline; a request still interrupts thinking, a notice does not', () => {
  assert.equal(moodWithBell('offline', bellState({ pending: 1 })), 'offline');
  assert.equal(moodWithBell('thinking', bellState({ asking: true })), 'alert');   // the job waits for the person: the face says so
  assert.equal(moodWithBell('thinking', bellState({ unread: 1 })), 'thinking');
});

test('what is news: not the hello at startup, not the starting-up dots, not the approvals', () => {
  assert.equal(countsAsNotice({ kind: 'reply', key: 'reply:1' }), true);
  assert.equal(countsAsNotice({ kind: 'system', key: 'local:x' }), true);
  assert.equal(countsAsNotice({ kind: 'reply', key: 'startup' }), false);
  assert.equal(countsAsNotice({ kind: 'reply', key: 'booting' }), false);
  assert.equal(countsAsNotice({ kind: 'approval', key: 'a' }), false);
  assert.equal(countsAsNotice(null), false);
});
