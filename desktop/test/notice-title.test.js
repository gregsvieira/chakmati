const test = require('node:test');
const assert = require('node:assert/strict');
const { noticeTitle } = require('../src/lib/notice-title');

test('only the first line, without the body', () => {
  assert.equal(noticeTitle({ text: 'Há uma ação aguardando a sua aprovação: Enviar WhatsApp para Maria\nChego em 10 minutos, me espera na portaria.' }),
    'Há uma ação aguardando a sua aprovação: Enviar WhatsApp para Maria');
});
test('a trailing colon and phone number are dropped', () => {
  assert.equal(noticeTitle({ text: 'Enviar WhatsApp para Maria Victoria +55 45 9968-4020:' }), 'Enviar WhatsApp para Maria Victoria');
});
test('long titles are cut with an ellipsis', () => {
  const t = noticeTitle({ text: 'x'.repeat(200) });
  assert.equal(t.length, 70);
  assert.ok(t.endsWith('…'));
});
test('short notices stay as they are, and nothing breaks on empty input', () => {
  assert.equal(noticeTitle({ text: 'O WhatsApp voltou a funcionar.' }), 'O WhatsApp voltou a funcionar.');
  assert.equal(noticeTitle(null), '');
  assert.equal(noticeTitle({}), '');
});
