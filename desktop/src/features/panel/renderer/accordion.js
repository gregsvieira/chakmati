'use strict';
// Which topics are folded after the person clicks one. In the small card only one topic is open at a time: opening one folds the others (an accordion).
// In the big window there is room, so each topic opens and folds on its own. Pure.
(function (root) {
  // `folded`: the ids folded now; returns the new set of folded ids.
  function toggled(folded, id, topics, accordion) {
    const next = new Set(folded);
    if (next.has(id)) {
      next.delete(id);
      if (accordion) for (const other of topics) if (other !== id) next.add(other);
    } else next.add(id);
    return next;
  }
  const api = { toggled };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Accordion = api;
})(typeof window !== 'undefined' ? window : globalThis);
