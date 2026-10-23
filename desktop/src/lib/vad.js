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
  // Always-on version: it never gives up waiting, keeps following the room's noise, and reports each utterance:
  // 'start' when speech begins, 'end' when the person finished (long enough to be words), 'drop' for a blip too short.
  function createAmbient({ silenceMs = 900, minSpeechFrames = 3, minSpeechMs = 400, maxMs = 20000, adapt = 0.03 } = {}) {
    let floor = null;
    let loud = 0;
    let silent = 0;
    let speechMs = 0;
    let utterMs = 0;
    const a = {
      speaking: false,
      get floor() { return floor; },
      push(rms, dtMs) {
        if (floor === null) { floor = rms; return null; }
        const bar = Math.max(floor * 2.5, 0.004);
        const isLoud = rms > bar;
        if (!a.speaking) {
          if (!isLoud) floor = floor * (1 - adapt) + rms * adapt; // follow the noise only while nobody is talking
          loud = isLoud ? loud + 1 : 0;
          if (loud >= minSpeechFrames) { a.speaking = true; silent = 0; speechMs = loud * dtMs; utterMs = loud * dtMs; return 'start'; }
          return null;
        }
        utterMs += dtMs;
        if (isLoud) { silent = 0; speechMs += dtMs; } else silent += dtMs;
        if (silent >= silenceMs || utterMs >= maxMs) {
          const words = speechMs >= minSpeechMs;
          a.speaking = false; loud = 0; silent = 0; speechMs = 0; utterMs = 0;
          return words ? 'end' : 'drop';
        }
        return null;
      },
    };
    return a;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { createDetector, createAmbient };
  else root.Vad = { createDetector, createAmbient };
})(typeof window !== 'undefined' ? window : globalThis);
