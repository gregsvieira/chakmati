'use strict';
// Turns captured microphone samples into a 16 kHz mono 16-bit WAV file: the format the speech recogniser reads without
// any codec, and small enough (about 32 KB per second).
(function (root) {
  const TARGET_RATE = 16000;

  function downsample(samples, fromRate) {
    if (fromRate === TARGET_RATE) return samples;
    const ratio = fromRate / TARGET_RATE;
    const out = new Float32Array(Math.floor(samples.length / ratio));
    for (let i = 0; i < out.length; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.min(Math.floor((i + 1) * ratio), samples.length);
      let sum = 0;
      for (let j = start; j < end; j++) sum += samples[j];
      out[i] = sum / Math.max(1, end - start); // average of the source samples: a cheap low-pass against aliasing
    }
    return out;
  }

  function encodeWav(chunks, sampleRate) {
    let total = 0;
    for (const c of chunks) total += c.length;
    const merged = new Float32Array(total);
    let at = 0;
    for (const c of chunks) { merged.set(c, at); at += c.length; }
    const pcm = downsample(merged, sampleRate);
    const bytes = new Uint8Array(44 + pcm.length * 2);
    const view = new DataView(bytes.buffer);
    const text = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };
    text(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); text(8, 'WAVE');
    text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, TARGET_RATE, true); view.setUint32(28, TARGET_RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, 'data'); view.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) {
      const s = Math.max(-1, Math.min(1, pcm[i]));
      view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return bytes;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { encodeWav, downsample, TARGET_RATE };
  else root.Wav = { encodeWav, downsample, TARGET_RATE };
})(typeof window !== 'undefined' ? window : globalThis);
