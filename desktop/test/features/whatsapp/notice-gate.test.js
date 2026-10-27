const test = require('node:test');
const assert = require('node:assert/strict');
const { createGate } = require('../../../src/features/whatsapp/notice-gate');

const memory = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v) }; };

test('the first time the notice is shown and the action waits for the acknowledgement', () => {
  const gate = createGate(memory(), 'k');
  const calls = [];
  let ack;
  const ranAtOnce = gate.run((onAck) => { calls.push('shown'); ack = onAck; }, () => calls.push('action'));
  assert.equal(ranAtOnce, false);
  assert.deepEqual(calls, ['shown']);
  ack();
  assert.deepEqual(calls, ['shown', 'action']);
});

test('after it was acknowledged the action runs at once and the notice is not shown again', () => {
  const storage = memory();
  const first = createGate(storage, 'k');
  first.run((onAck) => onAck(), () => {});
  const again = createGate(storage, 'k');   // a new window, the same memory
  const calls = [];
  assert.equal(again.run(() => calls.push('shown'), () => calls.push('action')), true);
  assert.deepEqual(calls, ['action']);
  assert.equal(again.acknowledged(), true);
});

test('closing the notice without the button does not run the action and does not remember anything', () => {
  const gate = createGate(memory(), 'k');
  const calls = [];
  let cancel;
  gate.run((onAck, onCancel) => { cancel = onCancel; }, () => calls.push('action'), () => calls.push('cancelled'));
  cancel();
  assert.deepEqual(calls, ['cancelled']);
  assert.equal(gate.acknowledged(), false);
});

test('a memory that fails never blocks anything: the notice just shows each time', () => {
  const broken = { getItem() { throw new Error('off'); }, setItem() { throw new Error('off'); } };
  const gate = createGate(broken, 'k');
  const calls = [];
  gate.run((onAck) => { calls.push('shown'); onAck(); }, () => calls.push('action'));
  assert.deepEqual(calls, ['shown', 'action']);
  assert.equal(gate.acknowledged(), false);
});
