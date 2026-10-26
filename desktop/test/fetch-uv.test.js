const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { verifySha256, pickTarget, fetchUv } = require('../scripts/fetch-uv');
const pins = require('../build/uv-pins.json');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'chakmati-uv-'));
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

test('the pins cover the four targets, with a real version, a hash and an official asset name', () => {
  assert.match(pins.version, /^\d+\.\d+\.\d+$/);
  assert.deepEqual(Object.keys(pins.targets).sort(), ['darwin-arm64', 'darwin-x64', 'linux-x64', 'win32-x64']);
  for (const t of Object.values(pins.targets)) {
    assert.match(t.sha256, /^[0-9a-f]{64}$/);
    assert.match(t.asset, /^uv-[a-z0-9_-]+\.(tar\.gz|zip)$/);
  }
});

test('a hash that does not match is refused', () => {
  const data = Buffer.from('uv');
  assert.doesNotThrow(() => verifySha256(data, sha(data)));
  assert.throws(() => verifySha256(data, '0'.repeat(64)), /SHA-256/);
  assert.throws(() => verifySha256(data, ''), /SHA-256/);
});

test('an unsupported system or architecture is an error, not a guess', () => {
  assert.equal(pickTarget(pins, 'darwin', 'arm64').asset, 'uv-aarch64-apple-darwin.tar.gz');
  assert.throws(() => pickTarget(pins, 'freebsd', 'x64'), /freebsd-x64/);
});

test('a wrong download is refused before anything is extracted or written', async () => {
  const outDir = tmp();
  let extracted = false;
  const fakePins = { version: '1.0.0', targets: { 'linux-x64': { asset: 'uv-x86_64-unknown-linux-gnu.tar.gz', sha256: sha(Buffer.from('the real one')) } } };
  await assert.rejects(
    fetchUv({ platform: 'linux', arch: 'x64', outDir, pins: fakePins, fetchFn: async () => new Response(Buffer.from('tampered')), extract: async () => { extracted = true; } }),
    /SHA-256/,
  );
  assert.equal(extracted, false);
  assert.deepEqual(fs.readdirSync(outDir), []);
});

test('a good download is extracted and the binary lands in the output folder, executable', async () => {
  const outDir = tmp();
  const payload = Buffer.from('archive bytes');
  const fakePins = { version: '1.0.0', targets: { 'linux-x64': { asset: 'uv-x86_64-unknown-linux-gnu.tar.gz', sha256: sha(payload) } } };
  const urls = [];
  const out = await fetchUv({
    platform: 'linux', arch: 'x64', outDir, pins: fakePins,
    fetchFn: async (url) => { urls.push(url); return new Response(payload); },
    extract: async (archive, dest) => { fs.mkdirSync(path.join(dest, 'uv-x86_64-unknown-linux-gnu'), { recursive: true }); fs.writeFileSync(path.join(dest, 'uv-x86_64-unknown-linux-gnu', 'uv'), '#!binary'); },
  });
  assert.deepEqual(urls, ['https://github.com/astral-sh/uv/releases/download/1.0.0/uv-x86_64-unknown-linux-gnu.tar.gz']);
  assert.equal(out, path.join(outDir, 'uv'));
  assert.equal(fs.readFileSync(out, 'utf8'), '#!binary');
  assert.ok((fs.statSync(out).mode & 0o111) !== 0, 'executable');
  assert.deepEqual(fs.readdirSync(outDir), ['uv']); // no temporary leftovers
});

test('on Windows the binary is called uv.exe and is found even at the top of the archive', async () => {
  const outDir = tmp();
  const payload = Buffer.from('zip bytes');
  const fakePins = { version: '1.0.0', targets: { 'win32-x64': { asset: 'uv-x86_64-pc-windows-msvc.zip', sha256: sha(payload) } } };
  const out = await fetchUv({
    platform: 'win32', arch: 'x64', outDir, pins: fakePins, fetchFn: async () => new Response(payload),
    extract: async (archive, dest) => { fs.writeFileSync(path.join(dest, 'uv.exe'), 'exe'); fs.writeFileSync(path.join(dest, 'uvx.exe'), 'other'); },
  });
  assert.equal(path.basename(out), 'uv.exe');
  assert.deepEqual(fs.readdirSync(outDir), ['uv.exe']);
});
