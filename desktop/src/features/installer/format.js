'use strict';
function formatSize(mb) {
  if (mb >= 1000) return `${(mb / 1000).toFixed(1).replace('.', ',')} GB`;
  return `${mb} MB`;
}

const LEVEL_TEXT = {
  unsupported: 'Este computador não atende o mínimo',
  light: 'Atende o mínimo (modelo leve)',
  compact: 'Atende (modelo compacto)',
  standard: 'Atende (modelo intermediário)',
  full: 'Atende com folga (modelo completo)',
};
const levelText = (level) => LEVEL_TEXT[level] || LEVEL_TEXT.unsupported;

module.exports = { formatSize, levelText };
