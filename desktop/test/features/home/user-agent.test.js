const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { cleanUserAgent } = require('../../../src/features/home/user-agent');

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) chakmati-desktop/0.1.0 Chrome/140.0.7339.133 Electron/38.2.1 Safari/537.36';

test('the window introduces itself as the plain Chrome it is built on: no Electron token and no app name', () => {
  assert.equal(cleanUserAgent(UA, 'chakmati-desktop'), 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.7339.133 Safari/537.36');
  assert.equal(cleanUserAgent(UA).includes('Electron'), false);
  assert.ok(cleanUserAgent(UA).includes('Chrome/140.0.7339.133'));   // the rest is untouched
});

test('odd input never throws, and an app name with special characters is taken literally', () => {
  assert.equal(cleanUserAgent(undefined), '');
  assert.equal(cleanUserAgent('Mozilla/5.0 x.y/1 Chrome/1', 'x.y'), 'Mozilla/5.0 Chrome/1');
  assert.equal(cleanUserAgent('Mozilla/5.0 xzy/1 Chrome/1', 'x.y'), 'Mozilla/5.0 xzy/1 Chrome/1');
});

test('the login window uses it, and the browser button has its channel and its button', () => {
  const win = fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', 'features', 'home', 'alexa-window.js'), 'utf8');
  assert.match(win, /setUserAgent\(cleanUserAgent\(win\.webContents\.getUserAgent\(\), require\('electron'\)\.app\.getName\(\)\)\)/);
  const src = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');
  assert.match(src('features', 'home', 'ipc.js'), /ipcMain\.handle\('panel:home-alexa-browser', \(\) => service\.alexaOpenBrowser\(\)\)/);
  assert.match(src('features', 'home', 'renderer', 'flow.js'), /text: 'Abrir no meu navegador'/);
  assert.match(src('features', 'home', 'renderer', 'flow.js'), /page === 'alexa-wait' \? api\.homeAlexaBrowser\(\) : api\.homeOpenHa\(\)/);
  assert.equal((src('preload.js').match(/homeAlexaBrowser: \(\) => ipcRenderer\.invoke\('panel:home-alexa-browser'\)/g) || []).length, 2);   // the panel and the wizard
});
