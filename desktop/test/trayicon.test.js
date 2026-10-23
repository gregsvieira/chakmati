const test = require('node:test');
const assert = require('node:assert/strict');
const zlib = require('node:zlib');
const { robotPng } = require('../src/lib/trayicon');

function decode(png) {
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  let off = 8; const chunks = {};
  while (off < png.length) {
    const len = png.readUInt32BE(off); const type = png.toString('ascii', off + 4, off + 8);
    (chunks[type] ||= []).push(png.subarray(off + 8, off + 8 + len)); off += 12 + len;
  }
  const ihdr = chunks.IHDR[0];
  const raw = zlib.inflateSync(Buffer.concat(chunks.IDAT));
  return { width: ihdr.readUInt32BE(0), height: ihdr.readUInt32BE(4), depth: ihdr[8], colorType: ihdr[9], raw };
}

test('robotPng is a valid RGBA PNG of the requested size', () => {
  const { width, height, depth, colorType, raw } = decode(robotPng({ size: 32 }));
  assert.deepEqual([width, height, depth, colorType], [32, 32, 8, 6]);
  assert.equal(raw.length, 32 * (1 + 32 * 4));
});

test('the drawing has opaque pixels (not blank) and transparent corners', () => {
  const { raw } = decode(robotPng({ size: 32 }));
  const px = (x, y) => raw.subarray(y * (1 + 128) + 1 + x * 4, y * (1 + 128) + 1 + x * 4 + 4);
  assert.equal(px(0, 0)[3], 0);
  let opaque = 0;
  for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) if (px(x, y)[3] > 200) opaque++;
  assert.ok(opaque > 300, `only ${opaque} opaque pixels`);
});

test('the template variant is black with alpha only (macOS recolours it for light/dark menu bars)', () => {
  const { raw } = decode(robotPng({ size: 32, template: true }));
  for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) {
    const o = y * 129 + 1 + x * 4;
    if (raw[o + 3] > 0) assert.deepEqual([raw[o], raw[o + 1], raw[o + 2]], [0, 0, 0]);
  }
});
