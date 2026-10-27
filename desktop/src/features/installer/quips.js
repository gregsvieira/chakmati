'use strict';
// A bit of humour about the computer, under the real figures in the wizard. It is a joke in reverse: a weak computer is treated like
// a prize (absurd praise), a very strong one like a relic (mock disdain). A computer in between gets nothing, and so does one that
// cannot run the app (no joking at the verdict). The same computer always gets the same line, so "check again" does not change it.

const PRAISE = Object.freeze([
  'Nossa, é uma honra ser convidado para essa máquina da NASA!',
  'Então esse é o computador de lançamento da SpaceX?',
  'Um computador desses merecia tapete vermelho. Vou entrar de gravata.',
  'Uau, o supercomputador que calculou o caminho até a Lua? Estou emocionado.',
]);

const TEASE = Object.freeze([
  'Primeira vez que vou tentar rodar no laptop da Xuxa.',
  'Ainda fabricam o computador Show do Milhão?! Bom, vamos tentar...',
  'Isso aqui é um computador ou uma torradeira com Wi-Fi? Vamos ver.',
  'Esse computador já viu o Windows 95 nascer, né? Vamos tentar mesmo assim.',
]);

const STRONG = Object.freeze({ ramGb: 15, cores: 8 }); // "well above what is asked": 16 GB and 8 cores (the same line the wizard uses for the full model)

function pick(list, hw) {
  let n = Math.round((hw.ramGb || 0) * 10) + (hw.cores || 0) * 7;
  for (const ch of String(hw.platform || '')) n += ch.charCodeAt(0);
  return list[n % list.length];
}

// -> { tone: 'praise' | 'tease', text } | null
function quip(hw, verdict) {
  if (!hw || !verdict || verdict.level === 'unsupported') return null;
  if (verdict.level === 'light') return { tone: 'praise', text: pick(PRAISE, hw) };
  if (hw.ramGb >= STRONG.ramGb && hw.cores >= STRONG.cores) return { tone: 'tease', text: pick(TEASE, hw) };
  return null;
}

module.exports = { quip, PRAISE, TEASE, STRONG };
