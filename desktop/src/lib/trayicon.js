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

// Layers drawn in order, in unit coordinates: hat, tin-can head, two round eyes, nose, chin flap.
function shapes(template) {
  const head = (x, y) => inRoundRect(x, y, 0.28, 0.22, 0.72, 0.9, 0.2);
  const hat = (x, y) => inRoundRect(x, y, 0.27, 0.04, 0.73, 0.26, 0.05) || inRoundRect(x, y, 0.1, 0.22, 0.9, 0.3, 0.04);
  const eyes = (x, y) => inCircle(x, y, 0.4, 0.42, 0.1) || inCircle(x, y, 0.6, 0.42, 0.1);
  const nose = (x, y) => inCircle(x, y, 0.5, 0.57, 0.07);
  const chin = (x, y) => inRoundRect(x, y, 0.32, 0.67, 0.68, 0.86, 0.08);
  if (template) { // monochrome: macOS recolours "template" images for light and dark menu bars
    return [
      { hit: (x, y) => head(x, y) || hat(x, y), color: [0, 0, 0, 255] },
      { hit: eyes, color: [0, 0, 0, 0], erase: true },
      { hit: chin, color: [0, 0, 0, 0], erase: true },
      { hit: nose, color: [0, 0, 0, 255] },
    ];
  }
  return [
    { hit: head, color: [120, 182, 218, 255] },
    { hit: hat, color: [246, 210, 26, 255] },
    { hit: (x, y) => inRoundRect(x, y, 0.27, 0.15, 0.73, 0.19, 0.0), color: [229, 67, 45, 255] },
    { hit: eyes, color: [244, 240, 223, 255] },
    { hit: (x, y) => inCircle(x, y, 0.4, 0.43, 0.045) || inCircle(x, y, 0.6, 0.43, 0.045), color: [16, 24, 32, 255] },
    { hit: nose, color: [226, 69, 42, 255] },
    { hit: chin, color: [47, 154, 67, 255] },
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
