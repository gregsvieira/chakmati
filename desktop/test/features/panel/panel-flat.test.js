const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');

test('the panel starts flat and still, before any setting arrives', () => {
  assert.match(read('features', 'panel', 'renderer', 'panel.html'), /<body data-flat data-still>/);
});

test('with the glass off the CSS drops every blur, the sheen and the translucency', () => {
  const css = read('features', 'panel', 'renderer', 'glass.css');
  assert.match(css, /body\[data-flat\] \*, body\[data-flat\] \*::before, body\[data-flat\] \*::after \{[^}]*backdrop-filter: none !important/);
  assert.match(css, /body\[data-flat\] #panel::after \{ display: none; \}/);
  assert.match(css, /body\[data-flat\] #panel \{ --g-tint: rgba\(246, 249, 255, 0\.985\)/);
});

test('the macOS native blur is only asked for when the glass is on, and goes away when it is switched off', () => {
  const win = read('features', 'panel', 'window.js');
  assert.match(win, /ctx\.settings\.glass \? \{ vibrancy: 'under-window', visualEffectState: 'active' \} : \{\}/);
  assert.match(win, /setVibrancy\(ctx\.settings\.glass \? 'under-window' : null\)/);
  assert.match(read('features', 'settings', 'service.js'), /key === 'glass' && typeof value === 'boolean'\) \{ ctx\.settings\.glass = value; panelWindow\.applyGlass\(\)/);
});

test('Ajustes has the switch, the page flattens itself from the setting, and the state carries it', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const js = read('features', 'settings', 'renderer', 'settings.js');
  assert.ok(html.includes('id="set-glass"'));
  assert.match(js, /toggleAttribute\('data-flat', !P\.state\.settings\.glass\)/);
  assert.match(js, /\$\('set-glass'\)\.addEventListener\('change', \(e\) => api\.setSetting\('glass', e\.target\.checked\)\)/);
  assert.match(read('features', 'panel', 'window.js'), /glass: ctx\.settings\.glass/);
});
