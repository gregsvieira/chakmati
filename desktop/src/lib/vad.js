'use strict';
// Decides when the person has finished speaking, from the loudness (RMS) of the microphone every ~80 ms.
// It learns the room's noise floor in the first 300 ms, treats anything clearly above it as speech, and stops after a
// stretch of silence that follows speech. A single bump is not speech: it takes a few loud frames in a row.
(function (root) {
  function createDetector({ silenceMs = 1200, maxWaitMs = 8000, maxMs = 30000, calibrateMs = 300, minSpeechFrames = 3 } = {}) {
    let elapsed = 0;
    let floor = 0;
    let floorFrames = 0;
    let loud = 0;
    let silent = 0;
    const d = {
      speaking: false,
      level: 0,
      // 'continue' | 'stop' (finished speaking or too long) | 'no-speech' (never started)
      push(rms, dtMs) {
        elapsed += dtMs;
        d.level = rms;
        if (elapsed <= calibrateMs) { floor = (floor * floorFrames + rms) / (floorFrames + 1); floorFrames += 1; return 'continue'; }
        const bar = Math.max(floor * 2.5, 0.004);
        if (rms > bar) { loud += 1; silent = 0; if (loud >= minSpeechFrames) d.speaking = true; } else { loud = 0; if (d.speaking) silent += dtMs; }
        if (elapsed >= maxMs) return 'stop';
        if (d.speaking && silent >= silenceMs) return 'stop';
        if (!d.speaking && elapsed >= maxWaitMs) return 'no-speech';
        return 'continue';
      },
    };
    return d;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { createDetector };
  else root.Vad = { createDetector };
})(typeof window !== 'undefined' ? window : globalThis);
