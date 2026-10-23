const test = require('node:test');
const assert = require('node:assert/strict');
const { speakable } = require('../src/lib/speech-text');

test('links and the list of sources are not read aloud', () => {
  const text = 'Os últimos filmes de 2026 incluem "Pânico 7" e "Nuremberg".\n\nFontes:\n- https://exemplo.com/filmes\n- https://outro.com';
  assert.equal(speakable(text), 'Os últimos filmes de 2026 incluem "Pânico 7" e "Nuremberg".');
});

test('markdown marks, bullets and extra whitespace are cleaned', () => {
  assert.equal(speakable('**Atenção**:   veja  `isto`\n- item um\n- item dois'), 'Atenção: veja isto item um item dois');
});

test('long answers are cut at a sentence end, short ones are kept', () => {
  const sentence = 'Esta é uma frase de tamanho razoável para o teste. ';
  const long = sentence.repeat(30);
  const out = speakable(long);
  assert.ok(out.length <= 600 && out.endsWith('.'), out.length);
  assert.equal(speakable('Olá!'), 'Olá!');
  assert.equal(speakable(null), '');
});

test('interface markers are never spoken', () => {
  assert.equal(speakable('Aguardando sua aprovação - nada foi enviado ainda.\n[[action:abc123]]'), 'Aguardando sua aprovação - nada foi enviado ainda.');
});
