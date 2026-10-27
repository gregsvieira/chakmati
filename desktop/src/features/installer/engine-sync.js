'use strict';
// Runs `uv sync` for the installed app. No shell: a fixed argument list built by engine-launch, with extras checked against the list.
const { spawn } = require('node:child_process');
const { syncCommand } = require('../engine/launch');

function makeSync({ spawnFn = spawn, resourcesPath, dataDir, platform = process.platform, env = process.env }) {
  return (extras, onProgress = () => {}) => new Promise((resolve, reject) => {
    let cmd;
    try { cmd = syncCommand({ resourcesPath, dataDir, platform, extras }); } catch (e) { reject(e); return; }
    const child = spawnFn(cmd.command, cmd.args, { env: { ...env, ...cmd.env }, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    let tail = '';
    const onData = (chunk) => {
      const text = String(chunk);
      tail = (tail + text).slice(-600);
      const line = text.trim().split(/\r?\n/).pop();
      if (line) onProgress({ status: line.slice(0, 120), completed: 0, total: 0 });
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('error', (e) => reject(new Error(`Não consegui iniciar o uv: ${e.message}`)));
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`O uv terminou com erro (${code}). ${tail.trim().split(/\r?\n/).slice(-2).join(' ')}`));
    });
  });
}

module.exports = { makeSync };
