// 像素网格与颜色工具：由原型 v10 engine.js 第 2、3 节的纯数据部分改写为 TypeScript。
// 这里只处理「点阵 → 点阵」的确定性运算，不依赖浏览器与 PixiJS，因此可以在 node --test 下运行，
// 也保证同输入同输出（工单 #176：画风与原型一致、确定的时钟与可重复的位置）。
// 网格是一维数组，长度为 w*h，每个元素是颜色字符串（#rrggbb）或 null（透明）。「.」在位图行里表示透明。

/** 一个 w×h 的像素网格；索引 i = y*w + x。 */
export type Grid = (string | null)[];

export function emptyGrid(w: number, h: number): Grid {
  return new Array<string | null>(w * h).fill(null);
}

const rgbCache = new Map<string, [number, number, number]>();

export function rgb(hex: string): [number, number, number] {
  const cached = rgbCache.get(hex);
  if (cached) return cached;
  if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new Error(`颜色格式无效：${hex}`);
  const v: [number, number, number] = [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
  rgbCache.set(hex, v);
  return v;
}

function hex2(n: number): string {
  return Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
}

export function mix(a: string, b: string, t: number): string {
  const x = rgb(a);
  const y = rgb(b);
  return `#${hex2(x[0] + (y[0] - x[0]) * t)}${hex2(x[1] + (y[1] - x[1]) * t)}${hex2(x[2] + (y[2] - x[2]) * t)}`;
}

export function rgba(hex: string, a: number): string {
  const c = rgb(hex);
  return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}

/** 在 (x, y) 处写一个像素；越界静默忽略（与原型 put 相同）。 */
export function put(g: Grid, w: number, h: number, x: number, y: number, c: string): void {
  if (x < 0 || y < 0 || x >= w || y >= h) return;
  g[y * w + x] = c;
}

/** 在 (x, y) 处写一个 2×2 的块（与原型 blk 相同）。 */
export function blk(g: Grid, w: number, h: number, x: number, y: number, c: string): void {
  put(g, w, h, x, y, c);
  put(g, w, h, x + 1, y, c);
  put(g, w, h, x, y + 1, c);
  put(g, w, h, x + 1, y + 1, c);
}

/** 位图行：字符串数组，每行等长；字符为「.」表示透明，其余查 map 取颜色。 */
export type BitmapRows = string[];
export type ColorMap = Record<string, string>;

/** 把位图行 blit 到网格 (x, y)；flip 为真时水平翻转（与原型 blit 相同）。 */
export function blit(
  g: Grid,
  w: number,
  h: number,
  rows: BitmapRows | null | undefined,
  x: number,
  y: number,
  map: ColorMap,
  flip = false,
): void {
  if (!rows) return;
  const bw = rows[0].length;
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r];
    for (let c = 0; c < bw; c++) {
      const ch = flip ? row[bw - 1 - c] : row[c];
      if (ch === ".") continue;
      const col = map[ch];
      if (!col) throw new Error(`小人部件字符没有颜色：${ch}`);
      put(g, w, h, x + c, y + r, col);
    }
  }
}

/** Bresenham 直线上的点（与原型 linePts 逐字相同，用于腿与手臂）。 */
export function linePts(x0: number, y0: number, x1: number, y1: number): [number, number][] {
  const pts: [number, number][] = [];
  const dx = Math.abs(x1 - x0);
  const dy = -Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1;
  const sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  let x = x0;
  let y = y0;
  for (let guard = 0; guard < 200; guard++) {
    pts.push([x, y]);
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) {
      err += dy;
      x += sx;
    }
    if (e2 <= dx) {
      err += dx;
      y += sy;
    }
  }
  return pts;
}

/** 给网格加一圈描边：原来透明、四邻有颜色的像素涂成 color（与原型 outlineGrid 相同）。 */
export function outlineGrid(grid: Grid, w: number, h: number, color: string): Grid {
  const out = grid.slice();
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (grid[i]) continue;
      if (
        (x > 0 && grid[i - 1]) ||
        (x < w - 1 && grid[i + 1]) ||
        (y > 0 && grid[i - w]) ||
        (y < h - 1 && grid[i + w])
      ) {
        out[i] = color;
      }
    }
  }
  return out;
}

/** 统计非透明像素数（用于测试「画法确实产出像素」）。 */
export function countOpaque(grid: Grid): number {
  let n = 0;
  for (let i = 0; i < grid.length; i++) if (grid[i]) n++;
  return n;
}

/** 把网格序列化为稳定字符串（用于测试与快照比较：同输入必得同输出）。 */
export function gridSignature(grid: Grid): string {
  let s = "";
  for (let i = 0; i < grid.length; i++) s += grid[i] ?? ".";
  return s;
}
