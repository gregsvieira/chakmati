'use strict';
// "agora", "há 3 min", "há 2 h": short relative times in Portuguese. Works in Node (tests) and in the browser (panel).
(function (root) {
  function relativeTime(thenSeconds, nowSeconds) {
    const s = Math.max(0, Math.round(nowSeconds - thenSeconds));
    if (s < 45) return 'agora';
    if (s < 3600) return `há ${Math.max(1, Math.round(s / 60))} min`;
    if (s < 86400) return `há ${Math.round(s / 3600)} h`;
    return `há ${Math.round(s / 86400)} d`;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { relativeTime };
  else root.RelTime = { relativeTime };
})(typeof window !== 'undefined' ? window : globalThis);
