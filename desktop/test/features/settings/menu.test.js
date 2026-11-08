const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');
const menu = read('features', 'settings', 'renderer', 'menu.js');
const html = read('features', 'panel', 'renderer', 'panel.html');
const core = read('features', 'panel', 'renderer', 'core.js');
const css = read('features', 'panel', 'renderer', 'panel.css');

test('every section of Ajustes has an entry in the list, with an icon and a name', () => {
  const headings = [...html.slice(html.indexOf('id="settings-view"'), html.indexOf('id="chats-view"')).matchAll(/<h3>([^<]+)<\/h3>/g)].map((m) => m[1]);
  assert.ok(headings.length >= 8, 'the sections are there');
  for (const h of headings) assert.ok(menu.includes(`'${h}': { name:`), `no entry for "${h}"`);
  assert.equal((menu.match(/icon: '/g) || []).length, headings.length);
  assert.match(menu, /name: 'Casa e Alexa'/);   // the long heading has a short name in the list
});

test('the list is the first thing in Ajustes, and the page code finds every element it needs', () => {
  assert.ok(html.indexOf('id="settings-menu"') > html.indexOf('id="settings-view"') && html.indexOf('id="settings-menu"') < html.indexOf('<section class="cat">'));
  const wanted = [...new Set([...menu.matchAll(/\$\('([\w-]+)'\)/g)].map((m) => m[1]))];
  assert.deepEqual(wanted.filter((id) => !html.includes(`id="${id}"`)), []);
  assert.ok(html.includes('settings/renderer/menu.js'));
});

test('an item opens alone, its title goes to the header, and nothing else shows', () => {
  assert.match(menu, /for \(const s of sections\(\)\) \{ s\.hidden = s !== section;/);
  assert.match(menu, /\$\('settings-menu'\)\.hidden = true;/);
  assert.match(menu, /\$\('title'\)\.textContent = item \? item\.name : titleOf\(section\)/);
  assert.match(css, /\.cat\[hidden\] \{ display: none; \}/);                              // a section is "display: grid", which would beat the hidden attribute
  assert.match(css, /\.cat\[data-current\] > h3 \{ display: none; \}/);                    // the header already says which item this is
});

test('Ajustes always opens on the list, and the arrow (and Esc) goes item -> list -> main page', () => {
  assert.match(core, /if \(name === 'settings' && P\.showSettingsMenu\) P\.showSettingsMenu\(\);/);
  assert.match(core, /const goBack = \(\) => \{ if \(screen === 'settings' && P\.settingsBack && P\.settingsBack\(\)\) return; showView\(screen === 'chat' \? P\.backTo : 'main'\); \};/);
  assert.match(core, /if \(screen !== 'main'\) goBack\(\);/);                              // Esc goes through the same function
  assert.match(menu, /P\.settingsBack = \(\) => \{ if \(!current\) return false; showMenu\(\); return true; \}/);
});

test('no innerHTML: the icons are built as SVG elements', () => {
  assert.equal(/innerHTML|outerHTML|insertAdjacentHTML/.test(menu), false);
  assert.match(menu, /document\.createElementNS\(SVG, 'svg'\)/);
});
