'use strict';
// The bell behind the character's head. Three states, and the face that goes with each:
//   request: something waits for the person (an action to approve, a question like the user name or the password)  -> yellow bell, alert face
//   notice:  something happened that the person has not seen yet (a message, a reminder, an answer)                  -> red bell, happy face
//   idle:    nothing                                                                                                 -> plain outline
// A request wins over a notice. The face only follows the bell when the mood is on "automático" in Ajustes (a pinned mood stays pinned).
(function (root) {
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function bellState({ pending = 0, asking = false, unread = 0 } = {}) {
    if (asking) return { state: 'request', mood: 'alert', label: pending > 0 ? `O Chakmati precisa de uma resposta sua e há ${plural(pending, 'aprovação pendente', 'aprovações pendentes')}` : 'O Chakmati precisa de uma resposta sua' };
    if (pending > 0) return { state: 'request', mood: 'alert', label: plural(pending, 'aprovação pendente', 'aprovações pendentes') };
    if (unread > 0) return { state: 'notice', mood: 'happy', label: plural(unread, 'novidade', 'novidades') };
    return { state: 'idle', mood: null, label: 'Nenhuma novidade' };
  }

  // The face to show: the bell's mood, unless the person pinned one (`pinned` = anything other than "auto"), the engine is down, or a
  // request is not involved and the character is busy thinking.
  function moodWithBell(base, bell, { pinned = false } = {}) {
    if (pinned || base === 'offline' || !bell.mood) return base;
    if (bell.state === 'request') return bell.mood;
    return base === 'thinking' ? base : bell.mood;
  }

  // What counts as news: not the startup hello, not the "starting up" dots, and not the approval notices (those are requests, counted apart).
  const IGNORED_KEYS = new Set(['startup', 'booting']);
  const countsAsNotice = (notice) => !!notice && notice.kind !== 'approval' && !IGNORED_KEYS.has(notice.key);

  if (typeof module !== 'undefined' && module.exports) module.exports = { bellState, moodWithBell, countsAsNotice };
  else root.Bell = { bellState, moodWithBell, countsAsNotice };
})(typeof window !== 'undefined' ? window : globalThis);
