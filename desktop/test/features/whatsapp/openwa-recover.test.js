const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const src = fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', 'features', 'whatsapp', 'openwa.js'), 'utf8');
const pattern = new RegExp(src.match(/const STUCK = \/(.+)\/i;/)[1], 'i');

test('the stuck-session pattern matches puppeteer page loss and nothing else', () => {
  const err = "OpenWA returned 500: [puppeteer:evaluate] Attempted to use detached Frame 'ABC'. | scriptPreview=() => WAPI.getAllChats()";
  assert.ok(pattern.test(err));
  assert.ok(pattern.test('Protocol error: Target closed'));
  assert.ok(!pattern.test('OpenWA returned 401: unauthorized'));
  assert.ok(!pattern.test('connection refused'));
});

test('recovery is guarded: one at a time, cooldown, never during a QR link', () => {
  assert.match(src, /if \(recovering \|\| setupRunning \|\| owaWatch \|\| ctx\.quitting\) return false;/);
  assert.match(src, /if \(now - lastRecoverAt < RECOVER_COOLDOWN_MS\) return false;/);
  assert.match(src, /Object\.assign\(module\.exports, \{ openWaSetup, recoverStuckSession, isStuckError \}\)/);
});
