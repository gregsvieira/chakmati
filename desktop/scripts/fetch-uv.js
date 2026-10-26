'use strict';
// Downloads the pinned uv for one system, checks its SHA-256 BEFORE touching the disk with it, and puts the binary in
// desktop/build/bin/ (ignored by git). A hash that does not match stops the build.
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

const BASE = 'https://github.com/astral-sh/uv/releases/download';

function verifySha256(buffer, expected) {
  const actual = crypto.createHash('sha256').update(buffer).digest('hex');
  if (!expected || actual !== expected) throw new Error(`SHA-256 do uv não confere (esperado ${expected || 'nenhum'}, obtido ${actual})`);
}

function pickTarget(pins, platform, arch) {
  const target = pins.targets[`${platform}-${arch}`];
  if (!target) throw new Error(`não há uv fixado para ${platform}-${arch}`);
  return target;
}

// `tar` reads both .tar.gz and .zip (bsdtar ships with macOS, Windows 10+ and most Linux systems)
async function tarExtract(archive, dest) {
  await promisify(execFile)('tar', ['-xf', archive, '-C', dest]);
}

function findFile(dir, name) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { const hit = findFile(full, name); if (hit) return hit; } else if (entry.name === name) return full;
  }
  return null;
}

async function fetchUv({ platform, arch, outDir, pins, fetchFn = fetch, extract = tarExtract }) {
  const target = pickTarget(pins, platform, arch);
  const response = await fetchFn(`${BASE}/${pins.version}/${target.asset}`);
  if (!response.ok) throw new Error(`download do uv falhou (${response.status})`);
  const data = Buffer.from(await response.arrayBuffer());
  verifySha256(data, target.sha256); // nothing is written or extracted before this passes

  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'chakmati-uv-'));
  try {
    const archive = path.join(work, target.asset);
    fs.writeFileSync(archive, data);
    const unpacked = path.join(work, 'x');
    fs.mkdirSync(unpacked);
    await extract(archive, unpacked);
    const name = platform === 'win32' ? 'uv.exe' : 'uv';
    const found = findFile(unpacked, name);
    if (!found) throw new Error(`${name} não está no arquivo baixado`);
    fs.mkdirSync(outDir, { recursive: true });
    const out = path.join(outDir, name);
    fs.copyFileSync(found, out);
    fs.chmodSync(out, 0o755);
    return out;
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const flag = (name, fallback) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : fallback; };
  const outDir = path.join(__dirname, '..', 'build', 'bin');
  fetchUv({ platform: flag('platform', process.platform), arch: flag('arch', process.arch), outDir, pins: require('../build/uv-pins.json') })
    .then((out) => console.log(`uv pronto em ${out}`))
    .catch((e) => { console.error(e.message); process.exit(1); });
}

module.exports = { verifySha256, pickTarget, fetchUv };
