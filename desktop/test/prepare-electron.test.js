const test = require('node:test');
const assert = require('node:assert/strict');
const { KEYS, missingKeys } = require('../scripts/prepare-electron');

test('an Info.plist without the sentences is missing all of them', () => {
  assert.deepEqual(missingKeys({}).sort(), Object.keys(KEYS).sort());
});

test('a prepared Info.plist is missing none, and a changed sentence counts as missing', () => {
  assert.deepEqual(missingKeys({ ...KEYS }), []);
  assert.deepEqual(missingKeys({ ...KEYS, NSMicrophoneUsageDescription: 'This app needs access to the microphone' }), ['NSMicrophoneUsageDescription']);
});

test('the calendar is covered for both the old and the new macOS permission keys', () => {
  assert.ok('NSCalendarsUsageDescription' in KEYS && 'NSCalendarsFullAccessUsageDescription' in KEYS);
});
