'use strict';
// A bit of humour about the computer, under the real figures in the wizard. It is a joke in reverse: a weak computer is treated like
// a prize (absurd praise), a very strong one like a relic (mock disdain). A computer in between gets nothing, and so does one that
// cannot run the app (no joking at the verdict). The line alternates between the computers' remarks from one opening of the wizard to the next, but within one opening it is always the same, so "check again" does not change it.

const PRAISE = Object.freeze([
  'Nossa, é uma honra ser convidado para essa máquina da NASA!',
  'Então esse é o computador de lançamento da SpaceX?',
  'Um computador desses merecia tapete vermelho. Vou entrar de gravata.',
  'Uau, o supercomputador que calculou o caminho até a Lua? Estou emocionado.',
]);

const TEASE = Object.freeze([
  'É a primeira vez que tentam me rodar no laptop da xuxa.',
  'Esse é o computador do show do milhão?',
  'Ual. Esse pc so nao eh mais potente que minha torradeira jorges formgrill',
]);

const STRONG = Object.freeze({ ramGb: 15, cores: 8 }); // "well above what is asked": 16 GB and 8 cores (the same line the wizard uses for the full model)

const SESSION = Math.floor(Math.random() * 1000);   // chosen once per run: another opening of the wizard may say another line

function pick(list, hw) {
  let n = SESSION + Math.round((hw.ramGb || 0) * 10) + (hw.cores || 0) * 7;
  for (const ch of String(hw.platform || '')) n += ch.charCodeAt(0);
  return list[n % list.length];
}

// -> { tone: 'praise' | 'tease', text } | null
function quip(hw, verdict) {
  if (!hw || !verdict || verdict.level === 'unsupported') return null;
  if (verdict.level === 'light' || verdict.level === 'compact') return { tone: 'praise', text: pick(PRAISE, hw) }; // under about 7.5 GB: the weak computers
  if (hw.ramGb >= STRONG.ramGb && hw.cores >= STRONG.cores) return { tone: 'tease', text: pick(TEASE, hw) };
  return null;
}

module.exports = { quip, PRAISE, TEASE, STRONG };
