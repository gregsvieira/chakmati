'use strict';
// Every threshold of the installer lives here. The RAM limits sit a little under the number on the box because the system
// reports less than what was sold (a "4 GB" computer reports about 3.7 GB, "8 GB" about 7.7, "16 GB" about 15.6).
// The suggestion limits (voice, microphone, WhatsApp) are estimates, not measurements yet.
const { REASONING } = require('./catalog');
const LIMITS = Object.freeze({
  minRamGb: 3.5,
  compactRamGb: 5.5, // a "6 GB" computer reports about 5.7
  standardRamGb: 7.5,
  fullRamGb: 15,
  minFreeDiskGb: Object.freeze({ light: 6, compact: 8, standard: 10, full: 15 }),
  diskMarginGb: 2,
  talkCores: 6,
  whatsappFreeDiskGb: 20,
});

const SUPPORTED_PLATFORMS = ['darwin', 'win32', 'linux'];
const SUPPORTED_ARCH = ['x64', 'arm64'];
const MODEL_BY_LEVEL = Object.freeze({ light: 'qwen3.5:0.8b', compact: 'granite4:3b', standard: 'qwen3.5:4b', full: 'qwen3.5:latest' });
const LEVELS_DOWN = ['full', 'standard', 'compact', 'light'];

const LIGHT_NOTE = 'Com pouca memória o Chakmati usa um modelo leve: conversa e pesquisa funcionam bem, mas pedidos no computador (criar pastas e arquivos) podem falhar mais.';

function ramLevel(ramGb) {
  if (ramGb >= LIMITS.fullRamGb) return 'full';
  if (ramGb >= LIMITS.standardRamGb) return 'standard';
  if (ramGb >= LIMITS.compactRamGb) return 'compact';
  return 'light';
}

function verdict(hw) {
  const reasons = [];
  if (!SUPPORTED_PLATFORMS.includes(hw.platform)) reasons.push('Sistema operacional não suportado (Windows, macOS ou Ubuntu).');
  if (!SUPPORTED_ARCH.includes(hw.arch)) reasons.push('Processador de 32 bits ou de tipo não suportado.');
  if (hw.ramGb < LIMITS.minRamGb) reasons.push(`Memória RAM insuficiente: ${hw.ramGb} GB (mínimo 4 GB).`);
  if (hw.freeDiskGb !== null && hw.freeDiskGb < LIMITS.minFreeDiskGb.light) {
    reasons.push(`Pouco espaço em disco: ${hw.freeDiskGb} GB livres (mínimo 6 GB).`);
  }
  if (reasons.length) return { level: 'unsupported', model: null, reasons, notes: [] };

  const notes = [];
  let level = ramLevel(hw.ramGb);
  if (hw.freeDiskGb === null) {
    notes.push('Não consegui medir o espaço livre em disco; confira que há pelo menos 6 GB livres.');
  } else {
    const wanted = level;
    while (level !== 'light' && hw.freeDiskGb < LIMITS.minFreeDiskGb[level]) level = LEVELS_DOWN[LEVELS_DOWN.indexOf(level) + 1];
    if (level !== wanted) notes.push('O espaço livre em disco só comporta um modelo menor do que a memória permitiria.');
  }
  if (level === 'light') notes.push(LIGHT_NOTE);
  return { level, model: MODEL_BY_LEVEL[level], reasons: [], notes };
}

// The reasoning model this computer can run, or null: the biggest one whose memory and disk needs are met (the chat model is not loaded at the same time).
function reasoningFor(hw) {
  if (!hw || verdict(hw).level === 'unsupported') return null;
  return REASONING.find((m) => hw.ramGb >= m.minRamGb && (hw.freeDiskGb === null || hw.freeDiskGb >= (m.diskMb / 1024) + 8)) || null;
}

// Only labels: nothing is ever pre-selected from this.
function suggestions(hw, level) {
  if (level === 'unsupported') return { reasoning: false, voice: false, talk: false, whatsapp: false, animations: false, glass: false, hideShare: false };
  return {
    reasoning: reasoningFor(hw) !== null,
    voice: hw.ramGb >= LIMITS.standardRamGb,
    talk: hw.ramGb >= LIMITS.fullRamGb && hw.cores >= LIMITS.talkCores,
    whatsapp: hw.ramGb >= LIMITS.fullRamGb && hw.freeDiskGb !== null && hw.freeDiskGb >= LIMITS.whatsappFreeDiskGb,
    animations: level === 'standard' || level === 'full', // they cost memory: only suggested where there is plenty
    glass: level === 'standard' || level === 'full',
    hideShare: true,
  };
}

module.exports = { LIMITS, MODEL_BY_LEVEL, verdict, suggestions, reasoningFor };
