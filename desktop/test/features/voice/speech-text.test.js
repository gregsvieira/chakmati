const test = require('node:test');
const assert = require('node:assert/strict');
const { speakable } = require('../../../src/features/voice/speech-text');

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

test('emojis are skipped by default and kept when the option asks to describe them', () => {
  const text = 'Claro! São quatro. 😊 Boa sorte 👍🏽 e 🇧🇷 feliz ❤️';
  assert.equal(speakable(text), 'Claro! São quatro. Boa sorte e feliz');
  assert.ok(speakable(text, { emojis: true }).includes('😊'));
  assert.equal(speakable('Preço: 10 e 2 dígitos 1234'), 'Preço: 10 e 2 dígitos 1234'); // digits are not emoji
});

test('the wake greetings (also the feminine one) are spoken exactly as written', () => {
  for (const g of ['Klift, kloft, still, a porta se abriu!', 'Klift, still, kloft! fala fióti.', 'Klift, kloft, stão! fala paizão!', 'Klift, kloft, stôna! Fala mãezôna!']) {
    assert.equal(speakable(g), g);
  }
});

test('text with no letters or digits, like the start-up "(...)", is never spoken', () => {
  assert.equal(speakable('(...)'), '');
  assert.equal(speakable('…'), '');
  assert.equal(speakable('😊'), '');
  assert.ok(speakable('(ok)').includes('ok'));
});

test('citation marks like [2], [1-4] and [1, 3] are not spoken', () => {
  assert.equal(speakable('Não há informação nesses textos [1-4]. Os documentos citam títulos [2][3].'), 'Não há informação nesses textos. Os documentos citam títulos.');
  assert.equal(speakable('Resposta [1, 3] e mais [4–6] fim.'), 'Resposta e mais fim.');
  assert.equal(speakable('lista [a] e [10] ok'), 'lista [a] e ok'); // only numbers in brackets are citations
});

test('a sources block is dropped even when it comes first or after a single line break', () => {
  assert.equal(speakable('Fontes:\n- https://exemplo.com'), '');
  assert.equal(speakable('Resposta curta.\nFontes:\n- https://a.com\n- https://b.com'), 'Resposta curta.');
});

test('the plan shown before a job is not read aloud, only the answer', () => {
  const { speakable } = require('../../../src/features/voice/speech-text');
  const text = 'Plano:\n1. Procurar a pasta «provas» em ~/Documents/Chakmati: achei 20 arquivos.\n2. Verificar como ler cada prova.\n3. Montar a planilha.\n\nLi 20 provas. Acertaram tudo: Ana.';
  assert.equal(speakable(text), 'Li 20 provas. Acertaram tudo: Ana.');
});
