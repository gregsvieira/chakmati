const test = require('node:test');
const assert = require('node:assert/strict');
const { brief } = require('../src/lib/brief');

test('short text is kept, with markdown marks and interface markers removed', () => {
  assert.equal(brief('A resposta é **4**.'), 'A resposta é 4.');
  assert.equal(brief('Aguardando sua aprovação - nada foi enviado ainda.\n[[action:abc]]'), 'Aguardando sua aprovação - nada foi enviado ainda.');
});

test('a long answer keeps only the whole sentences that fit', () => {
  const text = 'Oé! Se eu somasse 5 e dissesse oé, você ia rir. Mas a resposta correta é 4. Sem truques, só matemática pura. Tamo aqui pra te ajudar com mais esse desafio.';
  const out = brief(text);
  assert.ok(out.length <= 110, out.length);
  assert.ok(out.startsWith('Oé! Se eu somasse'));
  assert.ok(/[.!?]$/.test(out), out);
  assert.ok(!out.includes('Tamo aqui'));
});

test('one very long sentence is cut at a word with an ellipsis', () => {
  const out = brief('palavra '.repeat(40));
  assert.ok(out.length <= 110 && out.endsWith('…') && !out.endsWith(' …'), out);
});

test('a first sentence longer than the limit is cut, not dropped', () => {
  const out = brief(`${'muito '.repeat(30)}longa. Curta.`);
  assert.ok(out.endsWith('…') && out.length <= 110);
});

test('empty input gives empty text', () => {
  assert.equal(brief(null), '');
  assert.equal(brief('   '), '');
});
