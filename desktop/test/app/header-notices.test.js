const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', 'src', ...p), 'utf8');
const html = read('features', 'panel', 'renderer', 'panel.html');
const layout = read('features', 'panel', 'renderer', 'layout.js');

test('the header has the bell, the three dots and close; size and Ajustes live in the menu', () => {
  const header = html.slice(html.indexOf('<header id="bar">'), html.indexOf('</header>'));
  const buttons = [...header.matchAll(/<button id="([\w-]+)"/g)].map((m) => m[1]).filter((id) => id !== 'retry');
  assert.deepEqual(buttons, ['back', 'open-notices', 'open-menu', 'close']);
  const menu = html.slice(html.indexOf('id="menu-pop"'), html.indexOf('<!-- the only part that scrolls -->'));
  for (const id of ['expand', 'maximize', 'open-settings']) assert.match(menu, new RegExp(`<button id="${id}"`));
});

test('the recent notices are a little window of the bell, no longer a topic of the page', () => {
  const pop = html.slice(html.indexOf('id="notices-pop"'), html.indexOf('id="menu-pop"'));
  assert.match(pop, /id="recent-body"/);
  assert.doesNotMatch(html, /<section id="recent"/);
  assert.doesNotMatch(layout, /'recent'/);
});

test('the conversation has a title and its button stays in its row', () => {
  assert.match(html, /<span class="h-title">Conversa com o Chakmati<\/span>/);
  const css = read('features', 'panel', 'renderer', 'panel.css');
  assert.doesNotMatch(css, /#thread-section > h2 \{ position: absolute/);
  assert.doesNotMatch(css, /:not\(\[data-focus="thread"\]\) \.h-title \{ display: none/);
});

test('every id the header code looks up exists in the page', () => {
  for (const id of ['open-notices', 'open-menu', 'notices-pop', 'menu-pop', 'expand-label', 'maximize-label']) assert.match(html, new RegExp(`id="${id}"`));
});

test('the bell by the character shows only with news or a request; the header bell always shows', () => {
  const css = read('shared', 'ui', 'robot.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.match(css, /#approval-badge\.bell\[data-state="idle"\], #head-approval\.bell\[data-state="idle"\] \{ visibility: hidden; \}/);
  assert.doesNotMatch(css, /#open-notices[^{]*\{[^}]*visibility: hidden/);
});
