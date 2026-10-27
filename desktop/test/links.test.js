const test = require('node:test');
const assert = require('node:assert/strict');
const { splitLinks, safeLink } = require('../src/lib/links');

test('an address is cut out of the text, without the punctuation that closes the sentence', () => {
  assert.deepEqual(splitLinks('Fontes: https://www.lojasrenner.com.br/lista/-/N-1gu70u.'), [
    { text: 'Fontes: ' }, { url: 'https://www.lojasrenner.com.br/lista/-/N-1gu70u' }, { text: '.' }]);
  assert.deepEqual(splitLinks('(veja https://a.test/x?y=1)'), [{ text: '(veja ' }, { url: 'https://a.test/x?y=1' }, { text: ')' }]);
});

test('several addresses and plain text', () => {
  assert.deepEqual(splitLinks('sem link'), [{ text: 'sem link' }]);
  const parts = splitLinks('- https://a.test/1\n- http://b.test/2');
  assert.deepEqual(parts.filter((p) => p.url).map((p) => p.url), ['https://a.test/1', 'http://b.test/2']);
});

test('only http and https with a host and no password open', () => {
  assert.equal(safeLink('https://a.test/x'), 'https://a.test/x');
  assert.equal(safeLink('javascript:alert(1)'), null);
  assert.equal(safeLink('file:///etc/passwd'), null);
  assert.equal(safeLink('https://user:pw@a.test/'), null);
  assert.equal(safeLink('nonsense'), null);
  assert.deepEqual(splitLinks('https://user:pw@a.test/ x'), [{ text: 'https://user:pw@a.test/ x' }]);
});
