const test = require('node:test');
const assert = require('node:assert/strict');
const { verdict, suggestions, MODEL_BY_LEVEL, LIMITS } = require('../../../src/features/installer/tiers');

const pc = (over = {}) => ({ platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 15.6, freeDiskGb: 50, cores: 8, ...over });

test('the model ladder is the measured one', () => {
  assert.deepEqual(MODEL_BY_LEVEL, { light: 'qwen3.5:0.8b', compact: 'granite4:3b', standard: 'qwen3.5:4b', full: 'qwen3.5:latest' });
});

test('RAM as the system reports it picks the level (a "4 GB" PC reports about 3.7)', () => {
  assert.equal(verdict(pc({ ramGb: 3.7 })).level, 'light');
  assert.equal(verdict(pc({ ramGb: 3.7 })).model, 'qwen3.5:0.8b');
  assert.equal(verdict(pc({ ramGb: 5.7 })).level, 'compact');
  assert.equal(verdict(pc({ ramGb: 5.7 })).model, 'granite4:3b');
  assert.equal(verdict(pc({ ramGb: 5.4 })).level, 'light');
  assert.equal(verdict(pc({ ramGb: 7.7 })).level, 'standard');
  assert.equal(verdict(pc({ ramGb: 7.7 })).model, 'qwen3.5:4b');
  assert.equal(verdict(pc({ ramGb: 15.6 })).level, 'full');
  assert.equal(verdict(pc({ ramGb: 64 })).model, 'qwen3.5:latest');
});

test('the light level warns that computer commands are weak', () => {
  const v = verdict(pc({ ramGb: 3.7 }));
  assert.ok(v.notes.some((n) => /pedidos no computador/.test(n)));
  assert.deepEqual(verdict(pc({ ramGb: 15.6 })).notes, []);
});

test('below the minimum it says what is missing and picks no model', () => {
  const v = verdict(pc({ ramGb: 2 }));
  assert.equal(v.level, 'unsupported');
  assert.equal(v.model, null);
  assert.ok(v.reasons.some((r) => /RAM/.test(r)));
  assert.ok(verdict(pc({ freeDiskGb: 5 })).reasons.some((r) => /espaço/i.test(r)));
  assert.ok(verdict(pc({ arch: 'ia32' })).reasons.some((r) => /32 bits/.test(r)));
  assert.ok(verdict(pc({ platform: 'freebsd' })).reasons.some((r) => /Sistema operacional/.test(r)));
});

test('little free disk steps the model down; it never picks one that does not fit', () => {
  assert.equal(verdict(pc({ ramGb: 15.6, freeDiskGb: 12 })).level, 'standard');
  assert.equal(verdict(pc({ ramGb: 15.6, freeDiskGb: 8 })).level, 'compact');
  assert.equal(verdict(pc({ ramGb: 15.6, freeDiskGb: 7 })).level, 'light');
  assert.ok(verdict(pc({ ramGb: 15.6, freeDiskGb: 12 })).notes.some((n) => /espaço/i.test(n)));
});

test('an unmeasurable disk does not block, but says so', () => {
  const v = verdict(pc({ freeDiskGb: null }));
  assert.equal(v.level, 'full');
  assert.ok(v.notes.some((n) => /não consegui medir/i.test(n)));
});

test('suggestions follow RAM, cores and free disk; nothing is suggested when unsupported', () => {
  const big = suggestions(pc({ cores: 8 }), 'full');
  assert.deepEqual(big, { reasoning: true, voice: true, talk: true, whatsapp: true, animations: true, hideShare: true });
  const mid = suggestions(pc({ ramGb: 7.7, cores: 4, freeDiskGb: 30 }), 'standard');
  assert.deepEqual(mid, { reasoning: false, voice: true, talk: false, whatsapp: false, animations: true, hideShare: true });
  const small = suggestions(pc({ ramGb: 3.7 }), 'light');
  assert.deepEqual(small, { reasoning: false, voice: false, talk: false, whatsapp: false, animations: false, hideShare: true });
  assert.deepEqual(suggestions(pc({ ramGb: 2 }), 'unsupported'), { reasoning: false, voice: false, talk: false, whatsapp: false, animations: false, hideShare: false });
  assert.equal(suggestions(pc({ freeDiskGb: 15 }), 'full').whatsapp, false);
  assert.equal(suggestions(pc({ freeDiskGb: null }), 'full').whatsapp, false);
});

test('limits are frozen', () => {
  assert.throws(() => { 'use strict'; LIMITS.minRamGb = 1; });
});
