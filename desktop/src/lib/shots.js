'use strict';
// The pieces of the expanded panel that are plain logic: which layout fits a window, and the pictures of the browser that the right-hand
// screen shows. Works in Node (tests) and in the browser (panel).
(function (root) {
  const WIDE_MIN = 1000;       // a window at least this wide gets three columns: topics, conversation, screen
  const KEEP_IMAGES = 12;      // only the latest pictures keep their image in memory; older steps keep their caption
  const MAX_STEPS = 60;

  const layoutFor = (width) => (width >= WIDE_MIN ? 'wide' : 'compact');

  // Adds a "screenshot" event to the turn's history. The picture of an older step is dropped once there are more than KEEP_IMAGES.
  function addShot(turn, event) {
    const shots = turn.shots || (turn.shots = []);
    const step = { step: event.step, note: event.note || '', url: event.url || '', title: event.title || '', image: event.image || '' };
    const at = shots.findIndex((s) => s.step === step.step);
    if (at >= 0) shots[at] = step; else shots.push(step);
    shots.sort((a, b) => a.step - b.step);
    while (shots.length > MAX_STEPS) shots.shift();
    for (let i = 0; i < shots.length - KEEP_IMAGES; i += 1) shots[i].image = '';
    turn.shot = shots[shots.length - 1];
    return turn;
  }

  // What the right-hand screen shows: the latest turn that used the browser (or the step the person clicked in the strip).
  function screenView(turns, picked = null) {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const shots = turns[i].shots;
      if (!shots || !shots.length) continue;
      const chosen = picked != null && shots.find((s) => s.step === picked) ? shots.find((s) => s.step === picked) : shots[shots.length - 1];
      return { turnId: turns[i].id, shots, current: chosen, live: turns[i].status === 'pending', total: shots.length };
    }
    return null;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { WIDE_MIN, KEEP_IMAGES, MAX_STEPS, layoutFor, addShot, screenView };
  else root.Shots = { layoutFor, addShot, screenView };
})(typeof window !== 'undefined' ? window : globalThis);
