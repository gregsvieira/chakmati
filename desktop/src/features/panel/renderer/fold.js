'use strict';
// The reduced card shows the newest message in two lines. A longer text is not cut after its second line: it shows its FIRST line and its LAST line, with "…" between,
// so the person sees how it starts and how it ends. Pure (the measuring of a piece of text is given), so it is tested without a window.
(function (root) {
  // Greedy word wrap: the lines the text takes in `width`, `measure(text)` giving the width of a piece of text. Blank lines are dropped.
  function wrap(text, width, measure) {
    const lines = [];
    for (const paragraph of String(text || '').split('\n')) {
      let line = '';
      for (const word of paragraph.split(/\s+/).filter(Boolean)) {
        const next = line ? `${line} ${word}` : word;
        if (line && measure(next) > width) { lines.push(line); line = word; } else line = next;
      }
      if (line) lines.push(line);
    }
    return lines;
  }

  // -> { folded: false, text } when it fits in two lines, else { folded: true, text: "first line\n… last line", lines }
  function fold(text, width, measure, maxLines = 2) {
    const lines = wrap(text, width, measure);
    if (lines.length <= maxLines) return { folded: false, text: String(text || ''), lines: lines.length };
    // the second line is the END of the text: if "… " plus the whole last line does not fit, the beginning of that line is what gives way ("… reserva do restaurante … sábado.")
    const words = lines[lines.length - 1].split(' ');
    while (words.length > 1 && measure(`… ${words.join(' ')}`) > width) words.shift();
    return { folded: true, text: `${lines[0]}\n… ${words.join(' ')}`, lines: lines.length };
  }

  const api = { wrap, fold };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Fold = api;
})(typeof window !== 'undefined' ? window : globalThis);
