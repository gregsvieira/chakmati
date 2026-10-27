const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', '..', 'src');
const pages = [];
(function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p); else if (p.endsWith('.html')) pages.push(p);
  }
})(SRC);

test('there are three pages: the widget, the panel and the wizard', () => {
  assert.deepEqual(pages.map((p) => path.basename(p)).sort(), ['installer.html', 'panel.html', 'widget.html']);
});

test('every script and stylesheet a page names exists', () => {
  for (const page of pages) {
    const html = fs.readFileSync(page, 'utf8');
    for (const m of html.matchAll(/\b(?:src|href)="([^"]+)"/g)) {
      const ref = m[1];
      if (/^(?:https?:|data:|#)/.test(ref)) continue;
      assert.ok(fs.existsSync(path.resolve(path.dirname(page), ref)), `${path.relative(SRC, page)} names ${ref}, which is not there`);
    }
  }
});
