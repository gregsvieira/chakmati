'use strict';
// How the engine is started and prepared. Pure: it only builds commands; main.js and the setup wizard run them.
// Installed app: the engine's code travels in resources/engine (read-only), the Python environment lives in the app's data
// folder and is created by the wizard with the uv that ships in resources/bin. Development: unchanged (uv run in the checkout).
const path = require('node:path');

const EXTRA_NAMES = Object.freeze(['voice', 'listen', 'laya', 'documents']);

const isWin = (platform) => platform === 'win32';
const pathOf = (platform) => (isWin(platform) ? path.win32 : path.posix);

function extrasFromSettings(settings) {
  const extras = [];
  if (settings.enhancedVoice) extras.push('voice');
  if (settings.talk) extras.push('listen');
  if (settings.laya) extras.push('laya');
  if (settings.documents) extras.push('documents');
  return extras;
}

function venvPython({ dataDir, platform = process.platform }) {
  const p = pathOf(platform);
  return isWin(platform) ? p.join(dataDir, 'engine-venv', 'Scripts', 'python.exe') : p.join(dataDir, 'engine-venv', 'bin', 'python');
}

function uvPath({ resourcesPath, platform = process.platform }) {
  return pathOf(platform).join(resourcesPath, 'bin', isWin(platform) ? 'uv.exe' : 'uv');
}

// An app opened from the Finder or with `open` gets a minimal PATH, without the folders where uv and Homebrew live.
function toolPath({ platform = process.platform, base = '', home = '' }) {
  const p = pathOf(platform);
  const dirs = isWin(platform)
    ? []
    : [p.join(home, '.local', 'bin'), ...(platform === 'darwin' ? ['/opt/homebrew/bin'] : []), '/usr/local/bin', '/usr/bin', '/bin'];
  return [base, ...dirs].filter(Boolean).join(isWin(platform) ? ';' : ':');
}

function dataEnv({ dataDir, platform }) {
  const p = pathOf(platform);
  return { UV_PROJECT_ENVIRONMENT: p.join(dataDir, 'engine-venv'), UV_PYTHON_INSTALL_DIR: p.join(dataDir, 'python') };
}

function engineLaunch({ packaged, dataDir, repoRoot, platform = process.platform }) {
  if (!packaged) {
    if (!repoRoot) return null;
    return { command: 'uv', args: ['run', 'python', '-m', 'chakmati.main'], cwd: repoRoot, env: {} };
  }
  const p = pathOf(platform);
  const cwd = p.join(dataDir, 'engine-data'); // writable: the engine keeps its database and calendar file relative to it
  return {
    command: venvPython({ dataDir, platform }),
    args: ['-m', 'chakmati.main'],
    cwd,
    env: { CHAKMATI_DB_PATH: p.join(cwd, 'liteagent.db'), CHAKMATI_CALENDAR_ICS_PATH: p.join(cwd, 'agenda.ics') },
  };
}

// Installs the engine as a copy (--no-editable) into the data folder with uv's own Python, so nothing depends on the app folder.
function syncCommand({ resourcesPath, dataDir, platform = process.platform, extras = [] }) {
  for (const extra of extras) if (!EXTRA_NAMES.includes(extra)) throw new Error(`extra desconhecido: ${extra}`);
  const p = pathOf(platform);
  return {
    command: uvPath({ resourcesPath, platform }),
    args: [
      'sync', '--frozen', '--no-dev', '--no-editable', '--managed-python', '--python', '3.13',
      '--project', p.join(resourcesPath, 'engine'), ...extras.flatMap((e) => ['--extra', e]),
    ],
    env: dataEnv({ dataDir, platform }),
  };
}

module.exports = { EXTRA_NAMES, extrasFromSettings, venvPython, uvPath, toolPath, engineLaunch, syncCommand };
