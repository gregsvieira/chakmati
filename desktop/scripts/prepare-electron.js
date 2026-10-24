'use strict';
// macOS only. The development copy of Electron does not say why it may need the Calendar (or the microphone), and without
// that sentence in its Info.plist macOS refuses the request silently, with no permission window. This adds the sentences
// and signs the app again (an ad-hoc signature, which is what the original has). Safe to run many times.
const { execFileSync } = require('node:child_process');
const path = require('node:path');

const KEYS = {
  NSCalendarsUsageDescription: 'O Chakmati lê e cria compromissos na sua agenda quando você pede.',
  NSCalendarsFullAccessUsageDescription: 'O Chakmati lê e cria compromissos na sua agenda quando você pede.',
  NSMicrophoneUsageDescription: 'O Chakmati usa o microfone para ouvir você quando "Falar com o Chakmati" está ligado.',
};

// which of the wanted sentences are missing or different in this Info.plist (given as a plain object)
function missingKeys(plist) {
  return Object.entries(KEYS).filter(([key, text]) => plist[key] !== text).map(([key]) => key);
}

function appPath() {
  // require('electron') gives .../Electron.app/Contents/MacOS/Electron
  return path.resolve(require('electron'), '..', '..', '..');
}

function prepare(app = appPath()) {
  if (process.platform !== 'darwin') return { changed: false, reason: 'not macOS' };
  const plist = path.join(app, 'Contents', 'Info.plist');
  const current = JSON.parse(execFileSync('plutil', ['-convert', 'json', '-o', '-', plist], { encoding: 'utf8' }));
  const missing = missingKeys(current);
  if (!missing.length) return { changed: false, reason: 'already prepared' };
  for (const key of missing) execFileSync('plutil', ['-replace', key, '-string', KEYS[key], plist]);
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'ignore' });
  return { changed: true, keys: missing };
}

if (require.main === module) {
  try {
    const r = prepare();
    if (r.changed) console.log(`Electron preparado para pedir permissão (${r.keys.join(', ')}).`);
  } catch (e) {
    console.warn(`Não consegui preparar o Electron (${e.message}). O Calendário pode não pedir permissão.`);
  }
}

module.exports = { KEYS, missingKeys, prepare };
