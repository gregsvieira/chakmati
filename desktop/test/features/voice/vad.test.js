const test = require('node:test');
const assert = require('node:assert/strict');
const { createDetector, createAmbient } = require('../../../src/features/voice/vad');

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

const run = (a, rms, ms, frame = 80) => { const seen = []; for (let t = 0; t < ms; t += frame) { const e = a.push(rms, frame); if (e) seen.push(e); } return seen; };

test('ambient: reports each utterance as start then end, and keeps listening for the next one', () => {
  const a = createAmbient({});
  assert.deepEqual(run(a, 0.001, 800), []);
  assert.deepEqual(run(a, 0.05, 1200), ['start']);
  assert.deepEqual(run(a, 0.001, 1200), ['end']);
  assert.deepEqual(run(a, 0.001, 3000), []);
  assert.deepEqual(run(a, 0.05, 1000), ['start']);
  assert.deepEqual(run(a, 0.001, 1000), ['end']);
});

test('ambient: a pause inside a sentence does not split the utterance', () => {
  const a = createAmbient({ silenceMs: 900 });
  run(a, 0.001, 800);
  assert.deepEqual(run(a, 0.05, 800), ['start']);
  assert.deepEqual(run(a, 0.001, 600), []);
  assert.deepEqual(run(a, 0.05, 800), []);
  assert.deepEqual(run(a, 0.001, 1000), ['end']);
});

test('ambient: a short blip is dropped, not sent', () => {
  const a = createAmbient({ minSpeechMs: 400 });
  run(a, 0.001, 800);
  assert.deepEqual(run(a, 0.05, 280), ['start']);
  assert.deepEqual(run(a, 0.001, 1000), ['drop']);
});

test('ambient: it follows a slowly rising noise floor without mistaking it for speech', () => {
  const a = createAmbient({});
  run(a, 0.002, 800);
  let seen = [];
  for (let level = 0.002; level < 0.02; level += 0.0005) seen = seen.concat(run(a, level, 400));
  assert.deepEqual(seen, []);
  assert.deepEqual(run(a, 0.2, 800), ['start']);
});

test('ambient: speech that never pauses for the whole cap is dropped (not sent), and the floor learns that level', () => {
  const a = createAmbient({ maxMs: 5000 });
  run(a, 0.001, 800);
  assert.deepEqual(run(a, 0.05, 6000), ['start', 'drop']);   // nobody talks for five seconds straight: it is a noise, so nothing goes to the recogniser
  assert.deepEqual(run(a, 0.05, 6000), []);                 // and the same level no longer counts as speech
});

test('ambient: the room gets suddenly louder (music, the Echo) and the microphone does not go deaf', () => {
  const a = createAmbient({});
  run(a, 0.002, 800);
  const seen = run(a, 0.03, 60000);                        // a full minute of the new noise level
  assert.deepEqual(seen, ['start', 'drop']);                // one false start, cut at the cap, and then it is quiet again
  assert.deepEqual(run(a, 0.2, 1200), ['start']);           // a voice above the NEW level is heard...
  assert.deepEqual(run(a, 0.03, 1200), ['end']);            // ...and ends normally
});

test('ambient: an honest long sentence with its pauses is still sent', () => {
  const a = createAmbient({ maxMs: 5000, silenceMs: 900 });
  run(a, 0.001, 800);
  assert.deepEqual(run(a, 0.05, 1500), ['start']);
  assert.deepEqual(run(a, 0.001, 500), []);
  assert.deepEqual(run(a, 0.05, 1500), []);
  assert.deepEqual(run(a, 0.001, 1000), ['end']);
});

test('the microphone watchdog: a lost "stopped speaking" of the floating window cannot mute it for good', () => {
  const src = require('node:fs').readFileSync(require('node:path').join(__dirname, '..', '..', '..', 'src', 'features', 'voice', 'renderer', 'ambient.js'), 'utf8');
  assert.match(src, /if \(P\.otherSpeaking && Date\.now\(\) - otherSince > 90000\) \{ P\.otherSpeaking = false;/);
  assert.match(src, /otherSince = on \? Date\.now\(\) : 0/);
});
