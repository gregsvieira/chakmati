const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', 'src', ...p), 'utf8');

test('the wizard page keeps the strict CSP and loads only its own files', () => {
  const html = read('renderer', 'installer.html');
  assert.match(html, /Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'self'; script-src 'self'"/);
  assert.equal(/<script(?![^>]*\bsrc=)/.test(html), false, 'no inline script');
  assert.equal(/\bstyle=/.test(html), false, 'no inline style');
  assert.equal(/https?:\/\//.test(html), false, 'no remote address');
});

test('the wizard script never writes data as HTML and nothing starts ticked', () => {
  const js = read('renderer', 'installer.js');
  assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|eval\(|new Function/.test(js), false);
  assert.equal(/\bchecked\s*=\s*true|setAttribute\(\s*['"]checked/.test(js), false);
  assert.equal(/\bchecked\b/.test(read('renderer', 'installer.html')), false);
});

test('the preload exposes exactly the installer calls, each as invoke/send of a fixed channel', () => {
  const src = read('preload.js');
  const block = src.slice(src.indexOf('installer: {'));
  for (const channel of ['installer:scan', 'installer:plan', 'installer:run', 'installer:ollama-page', 'installer:progress', 'installer:finish']) {
    assert.ok(block.includes(`'${channel}'`), channel);
  }
});

test('the download dialog defaults to "Pular" and the only external page is the Ollama download', () => {
  const src = read('installer', 'index.js');
  assert.match(src, /buttons: \['Aprovar', 'Pular'\]/);
  assert.match(src, /defaultId: 1/);
  assert.match(src, /cancelId: 1/);
  assert.equal((src.match(/openExternal\(/g) || []).length, 1);
  assert.match(src, /const OLLAMA_DOWNLOAD = 'https:\/\/ollama\.com\/download'/);
});

test('the app starts the wizard only on --setup, and downloads the chosen voice at the next start', () => {
  const main = read('main.js');
  assert.match(main, /process\.argv\.includes\('--setup'\)/);
  assert.match(main, /settings\.enhancedVoice && state\.voice && !state\.voice\.installed/);
});
