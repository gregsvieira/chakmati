'use strict';
// Decides when an installed app must run the setup wizard: no finished marker, or the Python environment is gone.
const nodeFs = require('node:fs');
const path = require('node:path');
const { venvPython } = require('../engine/launch');

const markerPath = (dataDir) => path.join(dataDir, 'setup.json');

function needsSetup({ packaged, dataDir, platform = process.platform, fs = nodeFs }) {
  if (!packaged) return false;
  try {
    const marker = JSON.parse(fs.readFileSync(markerPath(dataDir), 'utf8'));
    if (marker && marker.done === true && fs.existsSync(venvPython({ dataDir, platform }))) return false;
  } catch { /* no marker, or unreadable: set up again */ }
  return true;
}

function writeSetupDone({ dataDir, extras, fs = nodeFs }) {
  fs.mkdirSync(dataDir, { recursive: true });
  const file = markerPath(dataDir);
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify({ done: true, extras: [...extras] }, null, 2));
  fs.renameSync(tmp, file); // atomic: a crash never leaves a half-written marker
}

module.exports = { needsSetup, writeSetupDone };
