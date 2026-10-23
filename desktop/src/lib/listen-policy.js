'use strict';
// What the always-on microphone does with something it heard. Ordinary talk in the room is ignored; it acts on a wake
// phrase, while the assistant is waiting for a command, and for a while after an answer to something said aloud, so a
// conversation can go back and forth without repeating the wake phrase every time.
(function (root) {
  const FOLLOW_UP_MS = 45000;

  function shouldAct({ text, wake, awake, now, conversationUntil }) {
    const t = String(text || '').trim();
    if (!t) return false;
    if (/^(obrigad[oa]\.?|tchau\.?|legendas.*|\.+|…)$/i.test(t) && !wake) return false; // what a recogniser invents from noise
    return !!wake || !!awake || now < (conversationUntil || 0);
  }

  const followUpUntil = (now) => now + FOLLOW_UP_MS;

  if (typeof module !== 'undefined' && module.exports) module.exports = { shouldAct, followUpUntil, FOLLOW_UP_MS };
  else root.ListenPolicy = { shouldAct, followUpUntil, FOLLOW_UP_MS };
})(typeof window !== 'undefined' ? window : globalThis);
