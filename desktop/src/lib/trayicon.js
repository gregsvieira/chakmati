'use strict';
// Draws the little robot as a PNG with no image files and no dependencies (used for the menu bar / tray icon).
const zlib = require('node:zlib');

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
const crc32 = (buf) => { let c = 0xffffffff; for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function encodePng(width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 6; // 8-bit RGBA
  const rows = Buffer.alloc(height * (1 + width * 4));
  for (let y = 0; y < height; y++) {
    rows[y * (1 + width * 4)] = 0; // filter: none
    rgba.copy(rows, y * (1 + width * 4) + 1, y * width * 4, (y + 1) * width * 4);
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]);
}

const inRoundRect = (x, y, x0, y0, x1, y1, r) => {
  if (x < x0 || x > x1 || y < y0 || y > y1) return false;
  const cx = Math.min(Math.max(x, x0 + r), x1 - r);
  const cy = Math.min(Math.max(y, y0 + r), y1 - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
};
const inCircle = (x, y, cx, cy, r) => (x - cx) ** 2 + (y - cy) ** 2 <= r * r;

// Layers drawn in order, in unit coordinates.
function shapes(template) {
  const head = (x, y) => inRoundRect(x, y, 0.1, 0.22, 0.9, 0.92, 0.22);
  const face = (x, y) => inRoundRect(x, y, 0.21, 0.34, 0.79, 0.8, 0.13);
  const ears = (x, y) => inRoundRect(x, y, 0.02, 0.46, 0.1, 0.7, 0.03) || inRoundRect(x, y, 0.9, 0.46, 0.98, 0.7, 0.03);
  const mast = (x, y) => inRoundRect(x, y, 0.465, 0.07, 0.535, 0.23, 0.03) || inCircle(x, y, 0.5, 0.075, 0.075);
  const eyes = (x, y) => inRoundRect(x, y, 0.31, 0.46, 0.42, 0.68, 0.045) || inRoundRect(x, y, 0.58, 0.46, 0.69, 0.68, 0.045);
  if (template) {
    // monochrome: macOS recolours "template" images for light and dark menu bars
    return [
      { hit: (x, y) => head(x, y) || ears(x, y) || mast(x, y), color: [0, 0, 0, 255] },
      { hit: face, color: [0, 0, 0, 0], erase: true },
      { hit: eyes, color: [0, 0, 0, 255] },
    ];
  }
  return [
    { hit: (x, y) => head(x, y) || ears(x, y) || mast(x, y), color: [86, 98, 120, 255] },          // slate outline
    { hit: (x, y) => inRoundRect(x, y, 0.14, 0.26, 0.86, 0.88, 0.2), color: [238, 241, 245, 255] }, // porcelain head
    { hit: face, color: [20, 33, 61, 255] },                                                         // ink screen
    { hit: (x, y) => eyes(x, y) || inCircle(x, y, 0.5, 0.075, 0.05), color: [242, 169, 0, 255] },   // amber eyes and lamp
  ];
}

function robotPng({ size = 32, template = false } = {}) {
  const layers = shapes(template);
  const SS = 4; // 4x4 supersampling for smooth edges
  const rgba = Buffer.alloc(size * size * 4);
  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const x = (px + (sx + 0.5) / SS) / size;
          const y = (py + (sy + 0.5) / SS) / size;
          let col = null;
          for (const layer of layers) if (layer.hit(x, y)) col = layer.erase ? null : layer.color;
          if (col) { r += col[0] * col[3]; g += col[1] * col[3]; b += col[2] * col[3]; a += col[3]; }
        }
      }
      const n = SS * SS;
      const o = (py * size + px) * 4;
      if (a > 0) { rgba[o] = Math.round(r / a); rgba[o + 1] = Math.round(g / a); rgba[o + 2] = Math.round(b / a); }
      rgba[o + 3] = Math.round(a / n);
    }
  }
  return encodePng(size, size, rgba);
}

module.exports = { robotPng };
