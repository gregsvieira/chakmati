'use strict';
// What the always-on microphone does with something it heard, like a smart speaker: ordinary talk in the room is ignored;
// it acts on a wake phrase, and on the one command that follows it while the assistant is waiting (a few seconds). After
// the answer it goes back to waiting for the wake phrase.
(function (root) {
  function shouldAct({ text, wake, awake }) {
    const t = String(text || '').trim();
    if (!t) return false;
    if (/^(obrigad[oa]\.?|tchau\.?|legendas.*|thank you\.?|thanks\.?|you\.?|bye\.?|\.+|…)$/i.test(t) && !wake) return false; // what a recogniser invents from noise
    return !!wake || !!awake;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { shouldAct };
  else root.ListenPolicy = { shouldAct };
})(typeof window !== 'undefined' ? window : globalThis);
