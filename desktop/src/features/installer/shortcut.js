'use strict';
// The "Atalho na área de trabalho" option: puts a way to open the Chakmati (the installed app, not the installer file) on the person's desktop.
// Pure over injected pieces (`fs`, `writeShortcutLink`), so it is tested without touching a real desktop.
const path = require('node:path');

const NAME = 'Chakmati';

// /Applications/Chakmati.app/Contents/MacOS/Chakmati -> /Applications/Chakmati.app
function appBundle(execPath) {
  const i = execPath.indexOf('.app/');
  return i < 0 ? null : execPath.slice(0, i + 4);
}

const quote = (s) => `"${String(s).replace(/(["\\$`])/g, '\\$1')}"`;

function createDesktopShortcut({ platform, execPath, desktopDir, fs, writeShortcutLink }) {
  if (!desktopDir) throw new Error('Não encontrei a área de trabalho deste computador.');
  fs.mkdirSync(desktopDir, { recursive: true });

  if (platform === 'darwin') {
    const bundle = appBundle(execPath);
    if (!bundle) throw new Error('O atalho só pode ser criado a partir do aplicativo instalado.');
    const link = path.join(desktopDir, NAME);
    try { fs.unlinkSync(link); } catch { /* there was none */ }
    fs.symlinkSync(bundle, link);   // a link to the app in Applications: it shows with the app's icon and opens it
    return { path: link };
  }
  if (platform === 'win32') {
    const link = path.join(desktopDir, `${NAME}.lnk`);
    const ok = writeShortcutLink(link, 'create', { target: execPath, cwd: path.dirname(execPath), icon: execPath, iconIndex: 0, description: 'Abrir o Chakmati' });
    if (!ok) throw new Error('O Windows não deixou criar o atalho.');
    return { path: link };
  }
  if (platform === 'linux') {
    const file = path.join(desktopDir, `${NAME.toLowerCase()}.desktop`);
    fs.writeFileSync(file, ['[Desktop Entry]', 'Type=Application', `Name=${NAME}`, 'Comment=Abrir o Chakmati', `Exec=${quote(execPath)}`, 'Icon=chakmati', 'Terminal=false', 'Categories=Utility;', ''].join('\n'));
    fs.chmodSync(file, 0o755);   // the desktop only runs a launcher that is executable
    return { path: file };
  }
  throw new Error('Sistema sem suporte para o atalho.');
}

module.exports = { createDesktopShortcut, appBundle };
