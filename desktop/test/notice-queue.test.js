const test = require('node:test');
const assert = require('node:assert/strict');
const { NoticeQueue, present, bubbleDuration } = require('../src/lib/notice-queue');

const n = (id, text, extra = {}) => ({ id, kind: 'whatsapp', text, masked: 'Você recebeu uma nova mensagem no WhatsApp', key: `k${id}`, ts: 1, ...extra });

test('present chooses the full or the masked text', () => {
  const notice = n(1, 'Você recebeu uma nova mensagem de Maria Victoria');
  assert.equal(present(notice, false), 'Você recebeu uma nova mensagem de Maria Victoria');
  assert.equal(present(notice, true), 'Você recebeu uma nova mensagem no WhatsApp');
  assert.equal(present({ id: 2, kind: 'system', text: 'ok' }, true), 'ok'); // no masked text: fall back to the text
});

test('bubbleDuration grows with the text but stays between 4 and 10 seconds', () => {
  assert.equal(bubbleDuration('oi'), 4000);
  assert.ok(bubbleDuration('x'.repeat(80)) > 4000 && bubbleDuration('x'.repeat(80)) < 10000);
  assert.equal(bubbleDuration('x'.repeat(1000)), 10000);
});

test('the first notice is shown at once; the next ones wait their turn in order', () => {
  const q = new NoticeQueue();
  assert.equal(q.push(n(1, 'um')).show.id, 1);
  assert.equal(q.push(n(2, 'dois')).show, null);
  assert.equal(q.push(n(3, 'três')).show, null);
  assert.equal(q.done().show.id, 2);
  assert.equal(q.done().show.id, 3);
  assert.equal(q.done().show, null);
});

test('a notice with the same key replaces the one waiting instead of piling up', () => {
  const q = new NoticeQueue();
  q.push(n(1, 'um'));
  q.push(n(2, 'dois', { key: 'same' }));
  q.push(n(3, 'três', { key: 'same' }));
  assert.equal(q.done().show.id, 3);
  assert.equal(q.done().show, null);
});

test('the waiting line is bounded; the oldest waiting notice is dropped', () => {
  const q = new NoticeQueue({ maxWaiting: 2 });
  q.push(n(1, 'um'));
  for (let i = 2; i <= 6; i++) q.push(n(i, `n${i}`));
  const order = [q.done().show.id, q.done().show.id];
  assert.deepEqual(order, [5, 6]);
});

test('urgent kinds (approval) jump ahead of ordinary ones', () => {
  const q = new NoticeQueue();
  q.push(n(1, 'um'));
  q.push(n(2, 'dois'));
  q.push(n(3, 'pede decisão', { kind: 'approval' }));
  assert.equal(q.done().show.id, 3);
  assert.equal(q.done().show.id, 2);
});

test('clear empties the line', () => {
  const q = new NoticeQueue();
  q.push(n(1, 'um'));
  q.push(n(2, 'dois'));
  q.clear();
  assert.equal(q.done().show, null);
});

test('a notice with the key of the one on screen replaces it right away', () => {
  const q = new NoticeQueue();
  q.push(n(1, 'uma mensagem', { key: 'maria' }));
  assert.equal(q.push(n(2, 'duas mensagens', { key: 'maria' })).show.id, 2);
  assert.equal(q.done().show, null);
});
