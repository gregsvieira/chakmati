const test = require('node:test');
const assert = require('node:assert/strict');
const { parse, verdict } = require('../../../src/features/settings/intent');

const cases = [
  ['liga a voz melhorada', 'enhancedVoice', true, false],
  ['Desliga a voz melhorada', 'enhancedVoice', false, false],
  ['ative o ouvir o Chakmati', 'hear', true, false],
  ['liga o falar com o chakmati', 'talk', true, false],
  ['desativa as animações', 'still', true, false],   // animations off = still on
  ['liga as animações', 'still', false, false],
  ['liga os emojis', 'speakEmojis', true, false],
  ['desliga a pesquisa na internet', 'research', false, false],
  ['liga o whatsapp', 'whatsapp', true, false],
  ['desliga a agenda', 'calendar', false, false],
  ['liga o modo discreto', 'masked', true, true],
  ['desativa o modo discreto', 'masked', false, true],
  ['ativa o envio sem pedir aprovação', 'autoSend', true, true],
  ['desliga a proteção de tela', 'protect', false, true],
  ['mostra o balão embaixo', 'bubbleSide', 'bottom', false],
  ['balão em cima', 'bubbleSide', 'top', false],
  ['coloca o humor feliz', 'mood', 'happy', false],
  ['voz mais rápida', 'voiceSpeed', 'fast', false],
  ['Aumenta a velocidade da voz melhorada', 'voiceSpeed', 'fast', false],
  ['Chakmati, aumenta a velocidade da voz', 'voiceSpeed', 'fast', false],
  ['acelera a voz', 'voiceSpeed', 'fast', false],
  ['coloca a velocidade da voz maior', 'voiceSpeed', 'fast', false],
  ['diminui a velocidade da voz', 'voiceSpeed', 'normal', false],
  ['reduz a velocidade da voz melhorada', 'voiceSpeed', 'normal', false],
  ['fala mais devagar', 'voiceSpeed', 'normal', false],
  ['deixa a velocidade da voz normal', 'voiceSpeed', 'normal', false],
  ['usa o microfone do computador', 'micSource', 'computer', false],
  ['muda a personalidade para gaúcho', 'personality', 'gaucho', false],
  ['coloca a personalidade carioca', 'personality', 'carioca', false],
  ['quero o sotaque nordestino', 'personality', 'nordestino', false],
  ['personalidade paulista', 'personality', 'paulista', false],
  ['muda o jeito de falar para mineiro', 'personality', 'mineiro', false],
  ['volta a personalidade para o padrão', 'personality', 'padrao', false],
  ['liga o efeito de vidro', 'glass', true, false],
  ['desliga o vidro', 'glass', false, false],
  ['meus pronomes são ela/dela', 'pronouns', 'ela', false],
  ['usa os pronomes ele/dele', 'pronouns', 'ele', false],
  ['coloca o pronome elu', 'pronouns', 'elu', false],
  ['prefiro não informar os pronomes', 'pronouns', 'none', false],
];
for (const [text, key, value, sensitive] of cases) {
  test(`"${text}"`, () => {
    const r = parse(text);
    assert.ok(r, 'recognised');
    assert.equal(r.key, key);
    assert.equal(r.value, value);
    assert.equal(r.sensitive, sensitive);
    assert.equal(!!r.ask, sensitive);
    assert.match(r.done, /^Pronto: /);
  });
}

test('ordinary requests and questions are not settings', () => {
  for (const t of ['aumenta o volume da voz', 'diminui o volume da voz do Chakmati', 'oi tudo bem', 'liga pra Maria', 'manda no whatsapp pra Maria: oi', 'como faço para ligar a voz melhorada?',
    'o que tenho na agenda hoje?', 'tenho mensagens novas no whatsapp?', 'resuma a conversa com o João', 'qual o humor do dia',
    'ative a lanterna do celular da Maria e depois explique para mim com calma como funciona cada coisa na prática hoje']) {
    assert.equal(parse(t), null, t);
  }
});

test('answers', () => {
  for (const [t, v] of [['sim', 'yes'], ['Pode sim', 'yes'], ['não', 'no'], ['não, cancela', 'no'], ['cancela', 'no'], ['talvez', null], ['liga a voz', null]]) assert.equal(verdict(t), v, t);
});

test('keeping safe commands approved is a sensitive setting', () => {
  const r = parse('liga manter comandos seguros aprovados');
  assert.equal(r.key, 'autoRunSafe');
  assert.equal(r.value, true);
  assert.equal(r.sensitive, true);
  assert.equal(parse('desliga os comandos seguros').value, false);
});

test('the voice itself still turns on and off, and "chakmati, troca para a personalidade Gaúcha!" is understood with its greeting and exclamation', () => {
  assert.deepEqual([parse('liga a voz melhorada').key, parse('liga a voz melhorada').value], ['enhancedVoice', true]);
  assert.deepEqual([parse('desliga a voz melhorada').key, parse('desliga a voz melhorada').value], ['enhancedVoice', false]);
  const r = parse('Chakmati, troca para a personalidade Gaúcha!');
  assert.deepEqual([r.key, r.value, r.done], ['personality', 'gaucho', 'Pronto: a personalidade gaúcha.']);
});
