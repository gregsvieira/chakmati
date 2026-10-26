'use strict';
// What the installer needs to know about this computer, and nothing else: no user name, host name, network or files.
const nodeOs = require('node:os');
const nodeFs = require('node:fs');

const GB = 1024 ** 3;
const round1 = (n) => Math.round(n * 10) / 10;

// `os` and `fs` can be replaced, so the tests can describe computers we do not have.
function readHardware({ os = nodeOs, fs = nodeFs, where = nodeOs.homedir() } = {}) {
  let freeDiskGb = null; // null = could not be measured; the verdict says so instead of guessing
  try {
    const st = fs.statfsSync(where);
    freeDiskGb = round1((Number(st.bavail) * Number(st.bsize)) / GB);
  } catch { /* leave null */ }
  return {
    platform: os.platform(),
    arch: os.arch(),
    osRelease: os.release(),
    ramGb: round1(os.totalmem() / GB),
    freeDiskGb,
    cores: os.cpus().length,
  };
}

module.exports = { readHardware };
