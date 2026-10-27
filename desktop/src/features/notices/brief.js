'use strict';
// What Chakmati says in the bubble when the panel is closed: at most two short lines. It keeps whole sentences while they
// fit and otherwise cuts at a word with an ellipsis, so the bubble never turns into a paragraph.
const MAX = 110;

function brief(text, max = MAX) {
  let t = String(text || '');
  t = t.replace(/\[\[[^\]]*\]\]/g, ' ').replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const sentences = t.match(/[^.!?…]+[.!?…]+(?=\s|$)|[^.!?…]+$/g) || [t];
  let out = '';
  for (const s of sentences.map((x) => x.trim())) {
    if ((out ? `${out} ${s}` : s).length > max) break;
    out = out ? `${out} ${s}` : s;
  }
  if (out) return out;
  const cut = t.slice(0, max - 1);
  const space = cut.lastIndexOf(' ');
  return `${(space > max * 0.5 ? cut.slice(0, space) : cut).replace(/[\s,;:.-]+$/, '')}…`;
}

module.exports = { brief, MAX };
