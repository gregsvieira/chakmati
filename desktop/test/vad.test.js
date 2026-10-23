const test = require('node:test');
const assert = require('node:assert/strict');
const { createDetector } = require('../src/lib/vad');

const feed = (d, rms, ms, frame = 80) => { let last = 'continue'; for (let t = 0; t < ms; t += frame) last = d.push(rms, frame); return last; };

test('quiet room, then speech, then silence: stops after the person finishes', () => {
  const d = createDetector({ silenceMs: 1200 });
  assert.equal(feed(d, 0.001, 400), 'continue');   // learns the noise floor
  assert.equal(feed(d, 0.05, 1500), 'continue');   // speaking
  assert.equal(d.speaking, true);
  assert.equal(feed(d, 0.001, 1000), 'continue');  // a pause is not the end
  assert.equal(feed(d, 0.001, 400), 'stop');       // 1200 ms of silence after speech
});

test('speech with short pauses between words never stops early', () => {
  const d = createDetector({ silenceMs: 1200 });
  feed(d, 0.001, 400);
  for (let i = 0; i < 6; i++) { assert.equal(feed(d, 0.04, 600), 'continue'); assert.equal(feed(d, 0.001, 700), 'continue'); }
});

test('nobody speaks: gives up after the wait and reports no speech', () => {
  const d = createDetector({ maxWaitMs: 8000 });
  assert.equal(feed(d, 0.001, 7500), 'continue');
  assert.equal(feed(d, 0.001, 1000), 'no-speech');
});

test('a noisy room raises the bar: steady noise alone is not speech', () => {
  const d = createDetector({ maxWaitMs: 5000 });
  feed(d, 0.02, 400);                      // the floor is 0.02
  assert.equal(feed(d, 0.025, 4000), 'continue');
  assert.equal(d.speaking, false);
  assert.equal(feed(d, 0.025, 1500), 'no-speech');
});

test('a very quiet speaker is still heard in a silent room', () => {
  const d = createDetector({});
  feed(d, 0.0005, 400);
  feed(d, 0.006, 600);
  assert.equal(d.speaking, true);
});

test('a single click or bump is not speech', () => {
  const d = createDetector({});
  feed(d, 0.001, 400);
  feed(d, 0.2, 80);
  feed(d, 0.001, 400);
  assert.equal(d.speaking, false);
});

test('the recording is capped', () => {
  const d = createDetector({ maxMs: 30000 });
  feed(d, 0.001, 400);
  assert.equal(feed(d, 0.05, 29000), 'continue');
  assert.equal(feed(d, 0.05, 2000), 'stop');
});
