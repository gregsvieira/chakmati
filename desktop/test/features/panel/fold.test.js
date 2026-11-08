const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { wrap, fold } = require('../../../src/features/panel/renderer/fold');

const measure = (t) => t.length * 10;   // every character is 10 px wide
const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');

test('wrap breaks at words, keeps explicit line breaks and drops blank lines', () => {
  assert.deepEqual(wrap('aaa bbb ccc ddd', 80, measure), ['aaa bbb', 'ccc ddd']);
  assert.deepEqual(wrap('um\n\ndois', 200, measure), ['um', 'dois']);
  assert.deepEqual(wrap('', 100, measure), []);
  assert.deepEqual(wrap('supercalifragilistico', 50, measure), ['supercalifragilistico']);   // a word longer than the width stays whole
});

test('a text of two lines or less is left alone', () => {
  assert.deepEqual(fold('Oi, tudo bem?', 300, measure), { folded: false, text: 'Oi, tudo bem?', lines: 1 });
  assert.equal(fold('aaa bbb ccc ddd', 80, measure).folded, false);
});

test('a longer text shows its first line and its last, with an ellipsis between', () => {
  const text = 'primeira linha aqui\nmeio do texto que some\noutro trecho do meio\núltima linha final';
  const out = fold(text, 300, measure);
  assert.equal(out.folded, true);
  assert.equal(out.text, 'primeira linha aqui\n… última linha final');
  assert.equal(out.lines, 4);
});

test('when the last line is too long for "… " plus itself, the END of the text is kept and its beginning gives way', () => {
  const text = 'inicio do texto\nmeio\numa ultima linha bem comprida que termina aqui';
  const out = fold(text, 250, measure);
  const second = out.text.split('\n')[1];
  assert.ok(second.startsWith('… ') && second.endsWith('termina aqui') && measure(second) <= 250, second);
});

test('the reduced card folds, and the enlarged conversation hides every topic above it', () => {
  const thread = read('features', 'panel', 'renderer', 'thread.js');
  const css = read('features', 'panel', 'renderer', 'panel.css');
  const html = read('features', 'panel', 'renderer', 'panel.html');
  assert.match(thread, /const reducedNow = \(\) => \{ const p = \$\('panel'\); return p\.dataset\.layout === 'compact' && p\.dataset\.focus !== 'thread'; \}/);
  assert.match(thread, /if \(!reducedNow\(\)\) \{ if \(folded\) renderThread\(false\); return; \}/);   // enlarged or wide: the whole text comes back
  assert.match(thread, /foldReduced\(\);\s*\}\s*\n\s*async function submit/);                          // after every render
  assert.match(read('features', 'panel', 'renderer', 'layout.js'), /if \(P\.foldReduced\) P\.foldReduced\(\);/);
  assert.match(css, /#panel\[data-focus="thread"\]\[data-layout="compact"\] #topics \{ display: none; \}/);
  assert.ok(html.indexOf('fold.js') > 0 && html.indexOf('fold.js') < html.indexOf('<script src="thread.js"></script>'));
});
