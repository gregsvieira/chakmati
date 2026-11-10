const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { toggled } = require('../../src/features/panel/renderer/accordion');

const TOPICS = ['messages', 'agenda', 'house', 'automations'];

test('small card: opening a topic folds the others', () => {
  const folded = new Set(['agenda', 'house']);   // messages and automations are open
  const next = toggled(folded, 'house', TOPICS, true);
  assert.deepEqual([...next].sort(), ['agenda', 'automations', 'messages']);   // only house is open
});

test('small card: folding the open topic leaves all folded; opening another one from there opens just that one', () => {
  const messagesOpen = new Set(['agenda', 'house', 'automations']);
  const allFolded = toggled(messagesOpen, 'messages', TOPICS, true);   // click on the open one: it folds
  assert.deepEqual([...allFolded].sort(), ['agenda', 'automations', 'house', 'messages']);
  assert.deepEqual([...toggled(allFolded, 'agenda', TOPICS, true)].sort(), ['automations', 'house', 'messages']);   // only agenda open
  assert.deepEqual([...toggled(messagesOpen, 'agenda', TOPICS, true)].sort(), ['automations', 'house', 'messages']);   // messages was open: it folds
});

test('big window: each topic opens and folds on its own', () => {
  const next = toggled(new Set(['agenda']), 'house', TOPICS, false);
  assert.deepEqual([...next], ['agenda', 'house']);   // house folded, agenda unchanged: nothing else touched
  assert.deepEqual([...toggled(new Set(['agenda', 'house']), 'house', TOPICS, false)], ['agenda']);   // opened: the rest keeps its state
});

test('the input is not changed, and the page loads the helper before the layout', () => {
  const folded = new Set(['a']);
  toggled(folded, 'b', ['a', 'b'], true);
  assert.deepEqual([...folded], ['a']);
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'features', 'panel', 'renderer', 'panel.html'), 'utf8');
  assert.ok(html.indexOf('accordion.js') > 0 && html.indexOf('accordion.js') < html.indexOf('layout.js'));
  const layout = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'features', 'panel', 'renderer', 'layout.js'), 'utf8');
  assert.match(layout, /const ACCORDION = TOPICS\.filter\(\(t\) => t !== 'decisions'\)/);
});
