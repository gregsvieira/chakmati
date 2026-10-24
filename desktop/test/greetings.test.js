const test = require('node:test');
const assert = require('node:assert/strict');
const { STARTUP_GREETINGS, pickGreeting } = require('../src/lib/greetings');

test('the start-up greetings are exactly the three requested ones', () => {
  assert.deepEqual(STARTUP_GREETINGS, ['Klift, kloft, still, a porta se abriu!', 'Klift, still, kloft! fala fióti.', 'Klift, kloft, stão! fala paizão!']);
});

test('one of them is picked, including at both ends of the random range', () => {
  assert.equal(pickGreeting(() => 0), STARTUP_GREETINGS[0]);
  assert.equal(pickGreeting(() => 0.5), STARTUP_GREETINGS[1]);
  assert.equal(pickGreeting(() => 0.999999), STARTUP_GREETINGS[2]);
  assert.equal(pickGreeting(() => 1), STARTUP_GREETINGS[2]);
  assert.ok(STARTUP_GREETINGS.includes(pickGreeting()));
});
