// 生成托盘图标资源：resources/tray.png（基础图标）与 resources/tray-1.png 至 tray-9.png（带数量角标）。
// 纯 Node 标准库编码 PNG（zlib + CRC32），不引入第三方依赖。运行：node scripts/make-tray-icons.mjs

import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "..", "resources");
mkdirSync(outDir, { recursive: true });

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeAndData = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typeAndData), 0);
  return Buffer.concat([length, typeAndData, crc]);
}

function encodePng(width, height, pixels) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // 位深
  ihdr[9] = 6; // RGBA
  // 每行前面加一个过滤类型字节 0
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * (width * 4 + 1)] = 0;
    pixels.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function blank(size) {
  return Buffer.alloc(size * size * 4);
}

function setPixel(pixels, size, x, y, [r, g, b, a]) {
  if (x < 0 || y < 0 || x >= size || y >= size) return;
  const offset = (y * size + x) * 4;
  pixels[offset] = r;
  pixels[offset + 1] = g;
  pixels[offset + 2] = b;
  pixels[offset + 3] = a;
}

// 基础图标：一个内向的圆环，象征循环
function drawBase(size) {
  const pixels = blank(size);
  const center = (size - 1) / 2;
  const radius = size * 0.36;
  const thickness = size * 0.12;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const distance = Math.hypot(x - center, y - center);
      if (distance <= radius + thickness / 2 && distance >= radius - thickness / 2) {
        setPixel(pixels, size, x, y, [90, 160, 240, 255]);
      }
    }
  }
  return pixels;
}

// 角标：右上角一个红点的方块，数量点亮若干小格
function drawBadge(size, count) {
  const pixels = drawBase(size);
  const box = Math.round(size * 0.5);
  const originX = size - box;
  const originY = 0;
  for (let y = 0; y < box; y += 1) {
    for (let x = 0; x < box; x += 1) {
      setPixel(pixels, size, originX + x, originY + y, [230, 70, 70, 255]);
    }
  }
  const lit = Math.max(1, Math.min(9, count));
  for (let i = 0; i < lit; i += 1) {
    const cx = originX + 1 + (i % 3) * Math.floor((box - 2) / 3);
    const cy = originY + 1 + Math.floor(i / 3) * Math.floor((box - 2) / 3);
    for (let dy = 0; dy < 2; dy += 1) {
      for (let dx = 0; dx < 2; dx += 1) {
        setPixel(pixels, size, cx + dx, cy + dy, [255, 255, 255, 255]);
      }
    }
  }
  return pixels;
}

const size = 32;
writeFileSync(join(outDir, "tray.png"), encodePng(size, size, drawBase(size)));
for (let count = 1; count <= 9; count += 1) {
  writeFileSync(join(outDir, `tray-${count}.png`), encodePng(size, size, drawBadge(size, count)));
}
console.log("托盘图标已生成到 resources/");
