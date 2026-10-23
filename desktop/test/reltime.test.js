const test = require('node:test');
const assert = require('node:assert/strict');
const { relativeTime } = require('../src/lib/reltime');

test('relative times in Portuguese', () => {
  const now = 10000;
  assert.equal(relativeTime(now - 5, now), 'agora');
  assert.equal(relativeTime(now - 60, now), 'há 1 min');
  assert.equal(relativeTime(now - 600, now), 'há 10 min');
  assert.equal(relativeTime(now - 7300, now), 'há 2 h');
  assert.equal(relativeTime(now - 90000, now), 'há 1 d');
  assert.equal(relativeTime(now + 50, now), 'agora'); // clock skew never prints a negative time
});
