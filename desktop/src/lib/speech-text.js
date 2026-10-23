'use strict';
// What is worth saying aloud: no links, no list of sources, no markdown marks, and not a whole essay.
(function (root) {
  const MAX = 600;

  function speakable(text) {
    let t = String(text || '');
    t = t.replace(/\n+\s*(Fontes?|Sources?)\s*:[\s\S]*$/i, ''); // the list of links that follows an answer
    t = t.replace(/https?:\/\/\S+/g, '');
    t = t.replace(/[*_`#>]+/g, '');
    t = t.replace(/^\s*[-•]\s+/gm, '');
    t = t.replace(/\s+/g, ' ').trim();
    if (t.length > MAX) {
      const cut = t.slice(0, MAX);
      const stop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('! '), cut.lastIndexOf('? '));
      t = (stop > 200 ? cut.slice(0, stop + 1) : cut).trim();
    }
    return t;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { speakable };
  else root.SpeechText = { speakable };
})(typeof window !== 'undefined' ? window : globalThis);
