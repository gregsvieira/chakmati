const test = require('node:test');
const assert = require('node:assert/strict');
const { encodeWav, downsample } = require('../src/lib/wav');

test('a valid 16 kHz mono 16-bit WAV header and size', () => {
  const one = new Float32Array(48000).fill(0.5); // one second at 48 kHz
  const wav = encodeWav([one], 48000);
  const view = new DataView(wav.buffer);
  const tag = (o) => String.fromCharCode(...wav.slice(o, o + 4));
  assert.equal(tag(0), 'RIFF'); assert.equal(tag(8), 'WAVE'); assert.equal(tag(12), 'fmt '); assert.equal(tag(36), 'data');
  assert.equal(view.getUint16(20, true), 1);        // PCM
  assert.equal(view.getUint16(22, true), 1);        // mono
  assert.equal(view.getUint32(24, true), 16000);    // sample rate
  assert.equal(view.getUint16(34, true), 16);       // bits
  assert.equal(view.getUint32(40, true), 16000 * 2);
  assert.equal(wav.length, 44 + 16000 * 2);
  assert.equal(view.getUint32(4, true), wav.length - 8);
  assert.ok(Math.abs(view.getInt16(44, true) - 0.5 * 0x7fff) < 2);
});

test('several chunks are joined in order', () => {
  const wav = encodeWav([new Float32Array(160).fill(0.25), new Float32Array(160).fill(-0.25)], 16000);
  const view = new DataView(wav.buffer);
  assert.ok(view.getInt16(44, true) > 0 && view.getInt16(44 + 319 * 2 - 2 * 160 + 2 * 160 - 2, true) < 0);
  assert.equal(wav.length, 44 + 320 * 2);
});

test('samples outside [-1, 1] are clipped, not wrapped', () => {
  const view = new DataView(encodeWav([new Float32Array([2, -2])], 16000).buffer);
  assert.equal(view.getInt16(44, true), 0x7fff);
  assert.equal(view.getInt16(46, true), -0x8000);
});

test('downsampling keeps the duration and averages neighbours', () => {
  const out = downsample(new Float32Array([1, 1, 1, 0, 0, 0]), 48000);
  assert.equal(out.length, 2);
  assert.deepEqual([...out], [1, 0]);
});
