// 房间陈设、管道、包裹、设备、屏幕的画法：由原型 v10 engine.js 第 8 节（1465-2213 行的 paint 表）
// 改写为 TypeScript。常量、坐标运算与分支与原型逐行一致，只把画布相关的 P.drawBitmap、P.text、P.pixText、
// P.linePts、P.mix、P.rgba 换成同项目的模块。

import { hash } from "./anims.ts";
import { linePts, mix, rgba } from "./grid.ts";
import { PAL } from "./registry.ts";
import { drawBitmap, drawPixelText, drawText, fillPixel, fillPixelOutlined } from "./shapes.ts";

/** 陈设画法的参数表；各方法按原型保留自己的可选参数。 */
export interface PaintOptions {
  [key: string]: unknown;
}

export type PaintFn = (c: CanvasRenderingContext2D, x: number, y: number, ...args: any[]) => any;

const optBool = (o: PaintOptions | undefined, name: string, fallback: boolean): boolean => {
  const v = o?.[name];
  return v === undefined ? fallback : Boolean(v);
};

const optNum = (o: PaintOptions | undefined, name: string, fallback: number): number => {
  const v = o?.[name];
  return v === undefined ? fallback : Number(v);
};

const optStr = (o: PaintOptions | undefined, name: string, fallback: string): string => {
  const v = o?.[name];
  return v === undefined ? fallback : String(v);
};

// 黄色闪烁的外框：需要提示的物件都用它
function blinkFrame(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number): void {
  fillPixel(c, x - 2, y - 2, w + 4, 1, PAL.yellow2);
  fillPixel(c, x - 2, y + h + 1, w + 4, 1, PAL.yellow2);
  fillPixel(c, x - 2, y - 2, 1, h + 4, PAL.yellow2);
  fillPixel(c, x + w + 1, y - 2, 1, h + 4, PAL.yellow2);
  fillPixel(c, x, y, w, h, "rgba(247,203,70,0.22)");
}

/** 屏幕内容：off 关闭、idle 光标、boot 开机、code 滚动字符、diff 增删的行、term 终端输出、error 红色、ok 绿色、alert 黄色闪烁、snow 雪花、shot 缩略图。 */
function screen(c: CanvasRenderingContext2D, x0: number, y0: number, w0: number, h0: number, mode: string, t: number, o?: PaintOptions): void {
  const seed = optNum(o, "seed", 0);
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = w0;
  const h = h0;
  if (mode === "off") {
    fillPixel(c, x, y, w, h, "#141a20");
    fillPixel(c, x + 1, y + 1, Math.max(1, Math.floor(w / 3)), 1, "#2a333d");
    fillPixel(c, x + 1, y + 2, 1, Math.max(1, Math.floor(h / 3)), "#2a333d");
    return;
  }
  const bg = mode === "error" ? "#3a0d12" : mode === "alert" ? "#2e2508" : PAL.screen0;
  fillPixel(c, x, y, w, h, bg);
  const fg = mode === "error" ? PAL.red1 : mode === "alert" ? PAL.yellow2 : PAL.screen3;
  const dim = mode === "error" ? PAL.red3 : mode === "alert" ? PAL.yellow4 : PAL.screen2;
  const rows = Math.floor((h - 2) / 2);
  if (mode === "boot") {
    const k = Math.min(1, o?.k === undefined ? 1 : Number(o.k));
    const lw = Math.round((w - 2) * k);
    fillPixel(c, x + Math.round((w - lw) / 2), y + Math.floor(h / 2), lw, 1, PAL.screen4);
    return;
  }
  if (mode === "idle") {
    if (Math.floor(t / 500) % 2 === 0) fillPixel(c, x + 2, y + 2, 2, 2, dim);
    fillPixel(c, x + 5, y + 3, Math.min(w - 8, 6), 1, dim);
    return;
  }
  if (mode === "code" || mode === "term" || mode === "alert") {
    const off = mode === "alert" ? 0 : Math.floor(t / (mode === "term" ? 70 : 110));
    for (let r = 0; r < rows; r++) {
      const n = r + off + seed * 31;
      const len = 2 + Math.floor(hash(n) * (w - 6));
      const ind = mode === "code" ? Math.floor(hash(n * 7) * 3) * 2 : 0;
      fillPixel(c, x + 2 + ind, y + 1 + r * 2, Math.min(len, w - 4 - ind), 1, r === rows - 1 && mode !== "alert" ? fg : dim);
    }
    if (mode === "alert" && Math.floor(t / 300) % 2 === 0) fillPixel(c, x, y, w, h, "rgba(247,203,70,0.22)");
    return;
  }
  if (mode === "diff") {
    const off = Math.floor(t / 240);
    for (let r = 0; r < rows; r++) {
      const n = r + off + seed * 17;
      const kind = hash(n * 3) < 0.34 ? "+" : hash(n * 3) < 0.6 ? "-" : " ";
      const col = kind === "+" ? PAL.green2 : kind === "-" ? PAL.red2 : PAL.screen1;
      if (kind !== " ") fillPixel(c, x + 1, y + 1 + r * 2, w - 2, 1, kind === "+" ? "#14391f" : "#3a1418");
      fillPixel(c, x + 1, y + 1 + r * 2, 1, 1, col);
      fillPixel(c, x + 3, y + 1 + r * 2, 2 + Math.floor(hash(n) * (w - 7)), 1, kind === " " ? PAL.screen2 : col);
    }
    return;
  }
  if (mode === "error") {
    const cx = x + Math.floor(w / 2);
    const cy = y + Math.floor(h / 2);
    for (let i = -2; i <= 2; i++) {
      fillPixel(c, cx + i, cy + i, 1, 1, fg);
      fillPixel(c, cx + i, cy - i, 1, 1, fg);
    }
    return;
  }
  if (mode === "ok") {
    const cx = x + Math.floor(w / 2) - 2;
    const cy = y + Math.floor(h / 2);
    [[0, 0], [1, 1], [2, 0], [3, -1], [4, -2]].forEach(([dx, dy]) => fillPixel(c, cx + dx, cy + dy, 1, 1, PAL.green1));
    return;
  }
  if (mode === "snow") {
    const off = Math.floor(t / 90);
    for (let r = 0; r < h; r++) {
      for (let q = 0; q < w; q++) {
        const n = hash((r * 31 + q) * 7 + off + seed * 13);
        if (n < 0.42) fillPixel(c, x + q, y + r, 1, 1, n < 0.12 ? PAL.white : n < 0.26 ? PAL.grey2 : PAL.grey4);
      }
    }
    return;
  }
  if (mode === "shot") {
    fillPixel(c, x, y, w, h, PAL.screen0);
    fillPixelOutlined(c, x + 1, y + 1, w - 2, h - 2, PAL.white, PAL.ink);
    fillPixel(c, x + 2, y + 2, w - 4, 2, PAL.blue1);
    const n = optNum(o, "shot", 0);
    for (let r = 0; r < Math.floor((h - 8) / 3); r++) {
      const len = 3 + Math.floor(hash(r * 11 + n * 5) * (w - 8));
      fillPixel(c, x + 3, y + 6 + r * 3, len, 1, [PAL.grey1, PAL.pline, PAL.yellow2][r % 3]);
    }
    return;
  }
  throw new Error(`未知屏幕模式：${mode}`);
}

/** 扫描线：每隔一行压一条半透明黑线，做出屏幕的质感。 */
function scanlines(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, a?: number): void {
  c.fillStyle = `rgba(0,0,0,${a || 0.22})`;
  for (let r = 1; r < h; r += 2) c.fillRect(Math.round(x), Math.round(y) + r, w, 1);
}

/** 办公桌：x 左边，y 为桌面前沿（坐着的小人的脚在这条线上）。 */
function desk(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions): void {
  const w = optNum(o, "w", 64);
  const wood = (o?.wood as string[] | undefined) || [PAL.wood1, PAL.wood2, PAL.wood3, PAL.wood4];
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixel(c, x - 1, y - 7, w + 2, 20, PAL.ink);
  fillPixel(c, x, y - 6, w, 6, wood[0]);
  fillPixel(c, x, y - 6, w, 1, mix(wood[0], PAL.white, 0.25));
  fillPixel(c, x, y - 1, w, 1, wood[1]);
  fillPixel(c, x, y, w, 12, wood[1]);
  fillPixel(c, x, y, w, 1, wood[2]);
  fillPixel(c, x + 3, y + 3, w - 6, 1, wood[2]);
  fillPixel(c, x + w - 20, y + 4, 16, 6, wood[2]);
  fillPixel(c, x + w - 19, y + 5, 14, 4, wood[1]);
  fillPixel(c, x + w - 14, y + 6, 4, 1, PAL.yellow3);
  fillPixel(c, x + 2, y + 11, 3, 1, wood[3]);
  fillPixel(c, x + w - 5, y + 11, 3, 1, wood[3]);
}

/** 桌上物件：纸堆、文件夹、写字用的纸、键盘、茶杯、显示器、状态灯、名牌。 */
function deskItems(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const w = optNum(o, "w", 64);
  const x = Math.round(x0);
  const y = Math.round(y0);
  const papers = Math.min(optNum(o, "papers", 0), 9);
  for (let i = 0; i < papers; i++) {
    const px = x + 3 + (i % 2 ? 1 : 0);
    const py = y - 3 - i * 1.5;
    fillPixel(c, px - 1, py - 1, 12, 3, PAL.ink);
    fillPixel(c, px, py, 10, 1, i % 2 ? PAL.white2 : PAL.white);
  }
  if (optBool(o, "folder", false)) drawBitmap(c, "folder", x + 4, y - 5 - Math.min(papers, 9) * 1.5);
  if (optBool(o, "docOnDesk", false)) drawBitmap(c, "doc_write", x + Math.round(w / 2) - 12, y - 5);
  if (optBool(o, "keyboard", true)) drawBitmap(c, "keyboard", x + Math.round(w / 2) - 7, y - 4);
  if (optBool(o, "cup", false)) drawBitmap(c, "cup", x + w - 32, y - 5);
  if (optBool(o, "box", false)) drawBitmap(c, "box_open", x + 4, y - 10);
  if (optBool(o, "card", false)) drawBitmap(c, "card", x + Math.round(w / 2) + 6, y - 5);
  if (optBool(o, "cardResult", false)) drawBitmap(c, "card_result", x + Math.round(w / 2) + 6, y - 5);
  if (o?.monitor !== false) {
    const mx = x + w - 22;
    const my = y - 19;
    drawBitmap(c, "deskMonitor", mx, my);
    screen(c, mx + 3, my + 2, 14, 9, (o?.monitor as string) || "off", t, { seed: optNum(o, "seed", 0), k: o?.bootK });
    if (optBool(o, "monitorBlink", false) && Math.floor(t / 300) % 2 === 0) fillPixel(c, mx + 3, my + 2, 14, 9, "rgba(247,203,70,0.55)");
  }
  if (o?.lamp) {
    const lx = x + w - 4;
    const ly = y - 9;
    fillPixel(c, lx - 1, ly - 1, 4, 5, PAL.ink);
    const on = o.lamp === "red" ? Math.floor(t / 350) % 2 === 0 : true;
    fillPixel(c, lx, ly, 2, 2, o.lamp === "red" ? (on ? PAL.red2 : PAL.red4) : PAL.green2);
    fillPixel(c, lx, ly + 2, 2, 1, PAL.grey3);
  }
  if (o?.nameplate) {
    c.font = `600 6px sans-serif`;
    const tw = Math.min(w - 10, c.measureText(String(o.nameplate)).width + 6);
    const nx = Math.round(x + w / 2 - tw / 2);
    fillPixel(c, nx - 1, y + 2, tw + 2, 9, PAL.ink);
    fillPixel(c, nx, y + 3, tw, 7, optStr(o, "plateColor", PAL.paper));
    drawText(c, String(o.nameplate), x + w / 2, y + 6.5, { size: 6, weight: 600, align: "center", max: w - 12, color: PAL.ink });
  }
}

/** 椅子：cx 中心，y 为桌面前沿。 */
function chair(c: CanvasRenderingContext2D, cx0: number, y0: number, o?: PaintOptions): void {
  const cx = Math.round(cx0);
  const y = Math.round(y0);
  const col = optStr(o, "color", PAL.grey3);
  fillPixelOutlined(c, cx - 10, y - 16, 20, 9, col);
  fillPixel(c, cx - 9, y - 16, 18, 1, mix(col, PAL.white, 0.35));
  fillPixel(c, cx - 8, y - 14, 16, 5, mix(col, PAL.white, 0.14));
  fillPixelOutlined(c, cx - 9, y - 7, 18, 2, mix(col, PAL.ink, 0.25));
}

/** 文件柜：open 为中间抽屉拉开程度 0-1。 */
function cabinet(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = 28;
  const h = 40;
  const body = optStr(o, "color", "#8fa3a0");
  const shade = mix(body, PAL.ink, 0.3);
  const hi = mix(body, PAL.white, 0.3);
  fillPixelOutlined(c, x, y - h, w, h, body);
  fillPixel(c, x, y - h, w, 2, hi);
  fillPixel(c, x + w - 2, y - h, 2, h, shade);
  for (let i = 0; i < 3; i++) {
    const dy0 = y - h + 3 + i * 12;
    const openK = i === 1 ? optNum(o, "open", 0) : 0;
    if (openK > 0) {
      fillPixel(c, x + 2, dy0, w - 4, 11, "#2b2f38");
      const tabs = [PAL.yellow2, PAL.blue2, PAL.red2, PAL.green2, PAL.white];
      tabs.forEach((col, j) => fillPixel(c, x + 4 + j * 4, dy0 + 1 + Math.round((1 - openK) * 4), 3, 3, col));
    }
    const off = Math.round(openK * 4);
    const fx = x + 2 - Math.round(openK * 2);
    const fw = w - 4 + Math.round(openK * 4);
    fillPixelOutlined(c, fx, dy0 + off, fw, 10, mix(body, PAL.white, 0.12));
    fillPixel(c, fx, dy0 + off + 9, fw, 1, shade);
    fillPixel(c, fx + Math.round(fw / 2) - 5, dy0 + off + 2, 10, 3, PAL.white);
    fillPixel(c, fx + Math.round(fw / 2) - 4, dy0 + off + 3, 8, 1, PAL.pline);
    fillPixel(c, fx + Math.round(fw / 2) - 4, dy0 + off + 6, 8, 2, PAL.metal4);
    fillPixel(c, fx + Math.round(fw / 2) - 3, dy0 + off + 6, 6, 1, PAL.metal1);
  }
  if (optBool(o, "blink", false) && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x, y - h, w, h);
}

export interface TerminalHandles {
  lampX: number;
  lampY: number;
  knob: [number, number];
  top: [number, number];
}

/** 终端与拉杆：lever 0 抬起、1 拉下；exit 为 null、'green'、'red'。 */
function terminal(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): TerminalHandles {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = 28;
  const h = 34;
  fillPixelOutlined(c, x, y - h, w, h, PAL.grey4);
  fillPixel(c, x, y - h, w, 1, PAL.grey3);
  fillPixel(c, x + w - 2, y - h, 2, h, PAL.grey5);
  const exit = o?.exit;
  const lampCol = exit === "green" ? PAL.green2 : exit === "red" ? PAL.red2 : PAL.grey5;
  fillPixelOutlined(c, x + 10, y - h - 5, 8, 4, lampCol);
  if (exit) fillPixel(c, x + 11, y - h - 5, 3, 1, exit === "green" ? PAL.green1 : PAL.red1);
  fillPixel(c, x + 9, y - h - 1, 10, 1, PAL.grey5);
  fillPixelOutlined(c, x + 3, y - h + 3, 22, 13, PAL.screen0);
  screen(c, x + 3, y - h + 3, 22, 13, optStr(o, "screen", "idle"), t, { seed: 3 });
  scanlines(c, x + 3, y - h + 3, 22, 13, 0.18);
  for (let i = 0; i < 5; i++) fillPixel(c, x + 4 + i * 4, y - h + 19, 3, 2, i === 4 ? PAL.red3 : PAL.grey2);
  for (let i = 0; i < 3; i++) fillPixel(c, x + 5, y - 9 + i * 3, 18, 1, PAL.grey5);
  const k = optNum(o, "lever", 0);
  const px = x - 1;
  const py = y - 11;
  const ang = -2.2 + k * 1.5;
  const kx = Math.round(px + Math.cos(ang) * 8);
  const ky = Math.round(py + Math.sin(ang) * 8);
  fillPixelOutlined(c, px - 1, py - 2, 3, 5, PAL.grey3);
  const pts = linePts(px, py, kx, ky);
  c.fillStyle = PAL.ink;
  pts.forEach((p) => c.fillRect(p[0] - 1, p[1] - 1, 3, 3));
  c.fillStyle = PAL.metal2;
  pts.forEach((p) => c.fillRect(p[0], p[1], 1, 1));
  fillPixelOutlined(c, kx - 1, ky - 1, 3, 3, PAL.red2);
  if (optBool(o, "blink", false) && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x - 8, y - h - 6, w + 8, h + 6);
  return { lampX: x + 14, lampY: y - h - 3, knob: [kx, ky], top: [x + 14, y - h - 6] };
}

export interface DoorHandles {
  nail: [number, number];
  slot: [number, number];
  w: number;
  h: number;
}

/** 门：open 0-1；返回门牌钉子与信箱缝的位置。 */
function door(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions): DoorHandles {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 36);
  const h = optNum(o, "h", 60);
  const wood = optStr(o, "color", PAL.wood2);
  fillPixel(c, x - 3, y - h - 3, w + 6, h + 3, PAL.ink);
  fillPixel(c, x - 2, y - h - 2, w + 4, h + 2, PAL.wood3);
  fillPixel(c, x, y - h, w, h, "#1c1a26");
  const k = optNum(o, "open", 0);
  if (k > 0) {
    c.fillStyle = `rgba(255,236,190,${0.35 * k})`;
    c.fillRect(x, y - h, w, h);
  }
  const pw = Math.max(4, Math.round(w * (1 - 0.8 * k)));
  const px = x + w - pw;
  fillPixel(c, px, y - h, pw, h, wood);
  if (pw > 12) {
    fillPixel(c, px + 4, y - h + 5, pw - 8, 16, mix(wood, PAL.white, 0.15));
    fillPixel(c, px + 4, y - h + 5, pw - 8, 1, mix(wood, PAL.ink, 0.3));
    fillPixel(c, px + 5, y - h + 7, pw - 10, 10, optStr(o, "glass", "#a9d3ef") as string);
    fillPixel(c, px + 5, y - h + 7, 3, 3, PAL.white);
    fillPixel(c, px + 4, y - h + 26, pw - 8, 22, mix(wood, PAL.white, 0.1));
    fillPixel(c, px + 4, y - h + 26, pw - 8, 1, mix(wood, PAL.ink, 0.3));
    fillPixel(c, px + Math.round(pw / 2) - 6, y - 10, 12, 3, PAL.yellow3);
    fillPixel(c, px + Math.round(pw / 2) - 5, y - 9, 10, 1, PAL.ink);
    fillPixel(c, px + 3, y - Math.round(h / 2) + 2, 3, 3, PAL.yellow2);
    fillPixel(c, px + 3, y - Math.round(h / 2) + 2, 1, 1, PAL.yellow1);
  } else {
    fillPixel(c, px + 1, y - h + 2, 1, h - 4, mix(wood, PAL.white, 0.2));
  }
  return { nail: [x + Math.round(w / 2), y - h + 2], slot: [x + Math.round(w / 2), y - 9], w, h };
}

export interface BoardLine {
  text?: string;
  color?: string;
  done?: boolean;
  tag?: string;
  tagColor?: string;
}

/** 可移动白板：floor 为地面；lines 为条目，sheet 为贴上的计划纸，erase 为擦除进度。 */
function whiteboard(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 88);
  const h = optNum(o, "h", 46);
  const fy = Math.round(Number(o?.floor ?? y + h + 20));
  [x + 6, x + w - 8].forEach((lx) => {
    fillPixelOutlined(c, lx, y + h, 2, fy - y - h - 2, PAL.metal3);
    fillPixelOutlined(c, lx - 3, fy - 2, 8, 2, PAL.metal4);
  });
  fillPixelOutlined(c, x - 2, y - 2, w + 4, h + 4, PAL.metal2);
  fillPixel(c, x - 2, y - 2, w + 4, 1, PAL.metal1);
  fillPixel(c, x, y, w, h, "#fbfcff");
  fillPixel(c, x, y, w, 1, "#e8ecf5");
  fillPixelOutlined(c, x + 4, y + h + 2, w - 8, 2, PAL.metal3);
  fillPixel(c, x + 10, y + h + 1, 6, 1, PAL.red2);
  fillPixel(c, x + 18, y + h + 1, 6, 1, PAL.blue2);
  fillPixel(c, x + 26, y + h + 1, 6, 1, PAL.green2);
  const lines = (o?.lines as BoardLine[] | undefined) || [];
  const sheetW = o?.sheet ? 24 : 0;
  if (o?.title) drawText(c, String(o.title), x + 4, y + 6, { size: 6.5, weight: 700, color: PAL.blue3, max: w - 8 - sheetW });
  lines.forEach((ln, i) => {
    const ly = y + 15 + i * 8;
    if (ly > y + h - 4) return;
    const col = ln.color || PAL.ink2;
    fillPixel(c, x + 4, ly - 1, 2, 2, ln.done ? PAL.green2 : col);
    if (ln.text) {
      drawText(c, ln.text, x + 8, ly, { size: 6, color: col, max: w - 12 - sheetW - (ln.tag ? 34 : 0) });
    } else {
      fillPixel(c, x + 8, ly, Math.round((0.4 + hash(i + 3) * 0.5) * (w - 16 - sheetW)), 1, col);
    }
    if (ln.tag) {
      c.font = "700 5px sans-serif";
      const tw = Math.min(34, c.measureText(ln.tag).width + 4);
      const tx = x + w - 3 - sheetW - tw;
      fillPixel(c, tx, ly - 3, tw, 7, ln.tagColor || PAL.yellow2);
      drawText(c, ln.tag, tx + tw / 2, ly + 0.5, { size: 5, weight: 700, align: "center", color: PAL.ink, max: tw - 2 });
    }
    if (ln.done) fillPixel(c, x + 3, ly - 2, 1, 1, PAL.green3);
  });
  if (o?.sheet) {
    const sx = x + w - sheetW - 1;
    const sy = y + 4;
    fillPixelOutlined(c, sx, sy, 22, h - 10, PAL.white);
    fillPixel(c, sx, sy, 22, 3, PAL.blue2);
    for (let i = 0; i < 5; i++) fillPixel(c, sx + 3, sy + 7 + i * 5, 12 + Math.round(hash(i + 9) * 5), 1, PAL.pline);
    fillPixel(c, sx + 3, sy - 1, 3, 3, PAL.red2);
    fillPixel(c, sx + 16, sy - 1, 3, 3, PAL.red2);
  }
  const erase = o?.erase === undefined ? 0 : Number(o.erase);
  if (erase > 0 && erase < 1) {
    const ew = Math.round((w - 2) * erase);
    fillPixel(c, x + 1, y + 11, ew, h - 13, "#fbfcff");
    for (let i = 0; i < 6; i++) fillPixel(c, x + 1 + ew - 3, y + 12 + i * 5, 2, 2, "#dfe5f0");
  }
  if (optBool(o, "blink", false) && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x, y, w, h);
}

/** 软木板（钉指导纸条）：notes 为纸条数量，done 为已回复数量。 */
function corkboard(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 30);
  const h = optNum(o, "h", 30);
  fillPixelOutlined(c, x - 2, y - 2, w + 4, h + 4, PAL.wood3);
  fillPixel(c, x, y, w, h, "#c9955c");
  for (let i = 0; i < 22; i++) fillPixel(c, x + Math.floor(hash(i) * w), y + Math.floor(hash(i + 40) * h), 1, 1, "#a8763f");
  const n = Math.min(optNum(o, "notes", 0), 6);
  for (let i = 0; i < n; i++) {
    const nx = x + 3 + (i % 3) * 9;
    const ny = y + 3 + Math.floor(i / 3) * 13;
    const done = i < optNum(o, "done", 0) || i === optNum(o, "doneIndex", -1);
    drawBitmap(c, done ? "note_done" : "note", nx, ny + 1);
    fillPixel(c, nx + 2, ny, 2, 2, done ? PAL.green2 : PAL.red2);
  }
  if (o?.label) drawText(c, String(o.label), x + w / 2, y + h + 6, { size: 5.5, align: "center", color: PAL.ink2, weight: 600 });
}

export interface CrtLine {
  k?: string;
  v: string;
  color?: string;
}

/** 墙上的大 CRT：lines 为 [{k, v, color}]；power 0 关闭、1 开启；boot 为开机动画进度。 */
function crt(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 128);
  const h = optNum(o, "h", 64);
  const shell = optStr(o, "shell", PAL.beige1);
  const shell2 = PAL.beige2;
  const shell3 = PAL.beige3;
  fillPixel(c, x + 20, y - 8, 3, 8, PAL.grey4);
  fillPixel(c, x + w - 23, y - 8, 3, 8, PAL.grey4);
  fillPixel(c, x + 16, y - 9, 11, 2, PAL.grey5);
  fillPixel(c, x + w - 27, y - 9, 11, 2, PAL.grey5);
  fillPixel(c, x + 2, y - 1, w - 4, h + 2, PAL.ink);
  fillPixel(c, x - 1, y + 2, w + 2, h - 4, PAL.ink);
  fillPixel(c, x + 2, y, w - 4, h, shell);
  fillPixel(c, x, y + 2, w, h - 4, shell);
  fillPixel(c, x + 2, y, w - 4, 1, PAL.white);
  fillPixel(c, x, y + h - 12, w, 10, shell2);
  fillPixel(c, x + 2, y + h - 2, w - 4, 2, shell2);
  fillPixel(c, x + w - 3, y + 2, 2, h - 6, shell2);
  const sx = x + 6;
  const sy = y + 5;
  const sw = w - 12;
  const sh = h - 19;
  fillPixel(c, sx - 1, sy - 1, sw + 2, sh + 2, shell3);
  fillPixel(c, sx, sy, sw, sh, PAL.ink);
  const on = optNum(o, "power", 1) !== 0;
  fillPixel(c, sx + 1, sy + 1, sw - 2, sh - 2, on ? optStr(o, "bg", PAL.screen0) : "#12171c");
  if (!on) {
    fillPixel(c, sx + 4, sy + 3, Math.round(sw / 4), 1, "#2c353f");
    fillPixel(c, sx + 3, sy + 4, 1, Math.round(sh / 3), "#2c353f");
  } else if (o?.boot !== undefined && Number(o.boot) < 1) {
    const k = Number(o.boot);
    const lw = Math.round((sw - 4) * Math.min(1, k * 2));
    const lh = k < 0.5 ? 1 : Math.round((sh - 4) * (k - 0.5) * 2);
    fillPixel(c, sx + Math.round((sw - lw) / 2), sy + Math.round((sh - lh) / 2), lw, Math.max(1, lh), rgba(PAL.screen4, 0.9));
  } else {
    const lines = (o?.lines as CrtLine[] | undefined) || [];
    const lh = Math.min(9, Math.floor((sh - 4) / Math.max(1, lines.length)));
    const size = Math.min(7.5, lh - 1);
    lines.forEach((ln, i) => {
      const ly = sy + 3 + i * lh + lh / 2;
      const col = ln.color || (optBool(o, "dim", false) ? PAL.screen2 : PAL.screen3);
      const glow: string | undefined = optBool(o, "dim", false) ? undefined : rgba(col, 0.8);
      let lx = sx + 4;
      if (ln.k) lx += drawText(c, ln.k, lx, ly, { size, color: optBool(o, "dim", false) ? PAL.screen1 : PAL.screen2, weight: 600 }) + 2;
      drawText(c, ln.v, lx, ly, { size, color: col, glow, weight: 600, max: sx + sw - 4 - lx });
    });
    if (optBool(o, "cursor", false) && Math.floor(t / 450) % 2 === 0) fillPixel(c, sx + sw - 8, sy + sh - 6, 3, 3, PAL.screen3);
    if (optBool(o, "alert", false) && Math.floor(t / 300) % 2 === 0) fillPixel(c, sx + 1, sy + 1, sw - 2, sh - 2, "rgba(247,203,70,0.18)");
    fillPixel(c, sx + 2, sy + 2, 6, 1, "rgba(255,255,255,0.18)");
    fillPixel(c, sx + 2, sy + 2, 1, 4, "rgba(255,255,255,0.18)");
  }
  scanlines(c, sx + 1, sy + 1, sw - 2, sh - 2, 0.16);
  const by = y + h - 9;
  fillPixelOutlined(c, x + 8, by, 5, 5, PAL.grey3);
  fillPixel(c, x + 10, by + 1, 1, 2, PAL.grey1);
  fillPixelOutlined(c, x + 16, by, 5, 5, PAL.grey3);
  fillPixel(c, x + 18, by + 1, 1, 2, PAL.grey1);
  for (let i = 0; i < 8; i++) fillPixel(c, x + w - 40 + i * 3, by + 1, 2, 4, shell3);
  fillPixel(c, x + w - 10, by + 2, 3, 2, on ? PAL.green2 : PAL.red3);
  if (o?.label) drawText(c, String(o.label), x + 26, by + 2.5, { size: 5.5, weight: 700, color: shell3 });
}

/** 窗户：night 为夜景，clouds 随时间移动。 */
function windowPaint(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 46);
  const h = optNum(o, "h", 40);
  fillPixelOutlined(c, x - 2, y - 2, w + 4, h + 4, PAL.white);
  const night = optBool(o, "night", false);
  const skies = night ? ["#1b2350", "#232d62", "#2c3875"] : ["#7fc4f0", "#9dd3f5", "#bfe3f8"];
  const bands = [0, Math.round(h * 0.45), Math.round(h * 0.75)];
  bands.forEach((b, i) => fillPixel(c, x, y + b, w, h - b, skies[i]));
  if (night) {
    [[6, 5], [30, 8], [18, 14], [38, 20], [10, 24]].forEach(([sx, sy]) => fillPixel(c, x + sx, y + sy, 1, 1, PAL.white));
    fillPixel(c, x + w - 12, y + 5, 5, 5, PAL.yellow1);
    fillPixel(c, x + w - 10, y + 5, 3, 3, "#1b2350");
  } else {
    const off = Math.floor(t / 700) % (w + 20);
    [[0, 8], [26, 20]].forEach(([cx0c, cy]) => {
      const cx = x + ((cx0c + off) % (w + 20)) - 14;
      c.save();
      c.beginPath();
      c.rect(x, y, w, h);
      c.clip();
      fillPixel(c, cx, y + cy, 12, 3, PAL.white);
      fillPixel(c, cx + 3, y + cy - 2, 6, 2, PAL.white);
      c.restore();
    });
    fillPixel(c, x + 3, y + h - 6, 8, 6, "#6fae5e");
    fillPixel(c, x + 12, y + h - 9, 10, 9, "#5d9b50");
    fillPixel(c, x + 30, y + h - 7, 12, 7, "#6fae5e");
  }
  fillPixel(c, x + Math.floor(w / 2) - 1, y, 2, h, PAL.white);
  fillPixel(c, x, y + Math.floor(h / 2) - 1, w, 2, PAL.white);
  fillPixelOutlined(c, x - 4, y + h + 2, w + 8, 3, PAL.white2);
}

/** 挂钟：time 为毫秒。 */
function clockPaint(c: CanvasRenderingContext2D, x: number, y: number, time: number, o?: PaintOptions): void {
  drawBitmap(c, "clock", x, y);
  const cx = x + 6;
  const cy = y + 6;
  const min = (time / 60000) % 60;
  const hr = (time / 3600000) % 12 + min / 60;
  const hand = (ang: number, len: number, col: string): void => {
    const ex = Math.round(cx + Math.sin(ang) * len);
    const ey = Math.round(cy - Math.cos(ang) * len);
    c.fillStyle = col;
    linePts(cx, cy, ex, ey).forEach((p) => c.fillRect(p[0], p[1], 1, 1));
  };
  hand((hr / 12) * Math.PI * 2, 3, PAL.ink);
  hand((min / 60) * Math.PI * 2, 5, PAL.ink2);
  if (optBool(o, "seconds", true)) hand((((time / 1000) % 60) / 60) * Math.PI * 2, 5, PAL.red2);
  fillPixel(c, cx, cy, 1, 1, PAL.red3);
  if (optBool(o, "stopped", false)) {
    fillPixel(c, x + 10, y - 3, 7, 7, PAL.ink);
    fillPixel(c, x + 11, y - 2, 5, 5, PAL.red2);
    fillPixel(c, x + 12, y, 3, 1, PAL.white);
  }
}

/** 吊灯：from 为吊线的起点（天花板高度）。 */
function lamp(c: CanvasRenderingContext2D, cx0: number, y0: number, on: boolean, from?: number): void {
  const recolor = on ? null : { y: PAL.grey3 };
  const top = Math.round(from || 0);
  const cx = Math.round(cx0);
  const y = Math.round(y0);
  fillPixel(c, cx, top, 1, Math.round(y) - top, PAL.grey4);
  drawBitmap(c, "lamp", cx - 7, y, { recolor: recolor ?? undefined });
}

/** 吊灯下的光锥。 */
function lightCone(c: CanvasRenderingContext2D, cx: number, y: number, len: number, w: number, color: string, alpha: number): void {
  const g = c.createLinearGradient(0, y, 0, y + len);
  g.addColorStop(0, rgba(color, alpha));
  g.addColorStop(1, rgba(color, 0));
  c.save();
  c.globalCompositeOperation = "lighter";
  c.fillStyle = g;
  c.beginPath();
  c.moveTo(cx - 5, y);
  c.lineTo(cx + 5, y);
  c.lineTo(cx + w / 2, y + len);
  c.lineTo(cx - w / 2, y + len);
  c.closePath();
  c.fill();
  c.restore();
}

/** 圆形发光。 */
function glow(c: CanvasRenderingContext2D, cx: number, cy: number, r: number, color: string, alpha: number): void {
  const g = c.createRadialGradient(cx, cy, 0, cx, cy, r);
  g.addColorStop(0, rgba(color, alpha));
  g.addColorStop(1, rgba(color, 0));
  c.save();
  c.globalCompositeOperation = "lighter";
  c.fillStyle = g;
  c.fillRect(cx - r, cy - r, r * 2, r * 2);
  c.restore();
}

/** 提案托盘（放在小边桌上）。 */
function tray(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixelOutlined(c, x, y - 18, 26, 18, PAL.wood2);
  fillPixel(c, x, y - 18, 26, 2, PAL.wood1);
  fillPixel(c, x + 3, y - 13, 20, 8, PAL.wood3);
  fillPixel(c, x + 4, y - 12, 18, 6, PAL.wood2);
  drawText(c, optStr(o, "label", "提案"), x + 13, y - 9, { size: 5.5, weight: 700, align: "center", color: PAL.paper });
  const n = Math.min(optNum(o, "count", 0), 6);
  for (let i = 0; i < n; i++) {
    fillPixel(c, x + 3, y - 21 - i * 1.5, 20, 2, PAL.ink);
    fillPixel(c, x + 4, y - 21 - i * 1.5, 18, 1, i % 2 ? PAL.white2 : PAL.white);
  }
  fillPixelOutlined(c, x + 2, y - 22, 22, 3, PAL.wood3);
  fillPixel(c, x + 2, y - 22, 22, 1, PAL.wood2);
  if (optBool(o, "blink", false)) blinkFrame(c, x, y - 24, 26, 24);
}

/** 废纸篓。 */
function bin(c: CanvasRenderingContext2D, x: number, y: number, o?: PaintOptions): void {
  drawBitmap(c, "bin", x, y - 8);
  const n = Math.min(optNum(o, "count", 0), 3);
  for (let i = 0; i < n; i++) drawBitmap(c, "paperball", x + 2 + i * 3, y - 10 - (i % 2));
}

/** 摘要档案盒：n 为编号。 */
function archive(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = 30;
  const h = 14;
  fillPixelOutlined(c, x, y - h, w, h, PAL.card2);
  fillPixel(c, x, y - h, w, 3, PAL.card1);
  fillPixel(c, x, y - 1, w, 1, PAL.card3);
  fillPixel(c, x + 2, y - h + 4, 14, 8, PAL.white);
  drawText(c, "摘要", x + 9, y - h + 8, { size: 5.5, weight: 700, align: "center", color: PAL.ink2 });
  const label = `#${optNum(o, "n", 0)}`;
  fillPixel(c, x + 17, y - h + 4, 11, 8, PAL.paper);
  drawText(c, label, x + 22.5, y - h + 8.2, { size: label.length > 2 ? 5 : 6, weight: 800, align: "center", color: PAL.red3 });
  if (optBool(o, "flash", false) && Math.floor(t / 150) % 2 === 0) {
    fillPixel(c, x - 2, y - h - 2, w + 4, 1, PAL.yellow2);
    fillPixel(c, x - 2, y + 1, w + 4, 1, PAL.yellow2);
  }
}

export interface MailboxHandles {
  lamp: [number, number];
}

/** 门缝下的信箱：count 为未读指导数量，灯在有未读时亮。 */
function mailbox(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, _t = 0): MailboxHandles {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const n = optNum(o, "count", 0);
  fillPixelOutlined(c, x, y - 7, 14, 7, PAL.metal3);
  fillPixel(c, x, y - 7, 14, 1, PAL.metal1);
  for (let i = 0; i < Math.min(n, 4); i++) {
    fillPixel(c, x + 2 + i, y - 9 - i, 10, 2, PAL.ink);
    fillPixel(c, x + 3 + i, y - 9 - i, 8, 1, PAL.yellow1);
  }
  fillPixelOutlined(c, x - 4, y - 14, 2, 14, PAL.grey3);
  const lit = n > 0;
  fillPixelOutlined(c, x - 6, y - 19, 6, 5, lit ? PAL.yellow2 : PAL.grey5);
  if (lit) fillPixel(c, x - 5, y - 19, 2, 1, PAL.yellow1);
  if (n > 0) drawPixelText(c, String(n), x + 7, y - 6, PAL.white, "center");
  return { lamp: [x - 3, y - 17] };
}

/** 产品的卷轴架：count 为已接纳的卷轴数量。 */
function scrollRack(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = 60;
  const h = 52;
  fillPixelOutlined(c, x, y - h, w, h, PAL.wood3);
  fillPixel(c, x, y - h, w, 3, PAL.wood2);
  const n = optNum(o, "count", 0);
  for (let r = 0; r < 3; r++) {
    for (let q = 0; q < 4; q++) {
      const cx = x + 3 + q * 14;
      const cy = y - h + 5 + r * 15;
      fillPixel(c, cx, cy, 12, 13, PAL.wood4);
      const idx = r * 4 + q;
      if (idx < n) {
        fillPixel(c, cx + 1, cy + 4, 10, 8, PAL.paper2);
        fillPixel(c, cx + 3, cy + 5, 6, 6, PAL.paper);
        fillPixel(c, cx + 5, cy + 7, 2, 2, PAL.paper3);
        fillPixel(c, cx + 1, cy + 7, 10, 1, idx === n - 1 && optBool(o, "flash", false) && Math.floor(t / 150) % 2 === 0 ? PAL.yellow2 : PAL.red2);
      }
    }
  }
  if (o?.label) drawText(c, String(o.label), x + w / 2, y - h - 5, { size: 6, weight: 700, align: "center", color: PAL.wood4 });
}

/** 通用的地面桌子：x 左边，y 为桌面前沿。 */
function table(c: CanvasRenderingContext2D, x0: number, y0: number, w: number, o?: PaintOptions): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const top = optStr(o, "top", PAL.wood1);
  const face = optStr(o, "face", PAL.wood2);
  const edge = optStr(o, "edge", PAL.wood3);
  fillPixel(c, x - 1, y - 7, w + 2, 20, PAL.ink);
  fillPixel(c, x, y - 6, w, 6, top);
  fillPixel(c, x, y - 6, w, 1, mix(top, PAL.white, 0.25));
  fillPixel(c, x, y, w, 12, face);
  fillPixel(c, x, y, w, 1, edge);
  if (o?.label) {
    c.font = "700 6px sans-serif";
    const tw = c.measureText(String(o.label)).width + 8;
    fillPixel(c, x + w / 2 - tw / 2 - 1, y + 2, tw + 2, 9, PAL.ink);
    fillPixel(c, x + w / 2 - tw / 2, y + 3, tw, 7, optStr(o, "labelBg", PAL.paper));
    drawText(c, String(o.label), x + w / 2, y + 6.5, { size: 6, weight: 700, align: "center", color: PAL.ink });
  }
}

/** 服务器机柜：on 运行，alarm 告警，label 版本。 */
function rack(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = 28;
  const h = optNum(o, "h", 70);
  fillPixelOutlined(c, x, y - h, w, h, PAL.grey5);
  fillPixel(c, x, y - h, w, 2, PAL.grey4);
  const units = Math.floor((h - 8) / 11);
  const on = optBool(o, "on", false);
  const alarm = optBool(o, "alarm", false);
  for (let i = 0; i < units; i++) {
    const uy = y - h + 4 + i * 11;
    fillPixelOutlined(c, x + 2, uy, w - 4, 9, PAL.grey4);
    for (let v = 0; v < 4; v++) fillPixel(c, x + 12 + v * 3, uy + 2, 2, 5, PAL.grey5);
    for (let l = 0; l < 2; l++) {
      const phase = hash(i * 5 + l + optNum(o, "seed", 0) * 13);
      let col = PAL.grey5;
      if (on) {
        const blinkOn = Math.floor((t + phase * 1000) / (180 + phase * 300)) % 3 !== 0;
        col = alarm ? (Math.floor(t / 220) % 2 ? PAL.red2 : PAL.red4) : blinkOn ? (l ? PAL.yellow2 : PAL.green2) : PAL.green4;
      }
      fillPixel(c, x + 4 + l * 3, uy + 3, 2, 2, col);
    }
  }
  if (o?.label) {
    fillPixelOutlined(c, x + 5, y - h - 9, 18, 7, PAL.paper);
    drawText(c, String(o.label), x + 14, y - h - 5.3, { size: 6, weight: 800, align: "center", color: PAL.ink });
  }
  if (optBool(o, "blink", false) && Math.floor(t / 300) % 2 === 0) blinkFrame(c, x, y - h, w, h);
}

/** 墙上的架子：x 左边，y 为架子板面。 */
function shelf(c: CanvasRenderingContext2D, x0: number, y0: number, w: number, o?: PaintOptions): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixelOutlined(c, x, y, w, 3, optStr(o, "color", PAL.wood2));
  fillPixel(c, x, y, w, 1, PAL.wood1);
  fillPixel(c, x + 3, y + 3, 2, 4, PAL.wood4);
  fillPixel(c, x + w - 5, y + 3, 2, 4, PAL.wood4);
}

/** 警示灯：color 为 yellow 或 red，on 时亮着。 */
function beacon(c: CanvasRenderingContext2D, x: number, y: number, o?: PaintOptions, _t = 0): void {
  const on = optBool(o, "on", false);
  drawBitmap(c, o?.color === "red" ? "beacon_red" : "beacon", x, y, { recolor: on ? undefined : { L: PAL.grey3, W: PAL.grey2 } });
}

/** 警示灯的旋转光束。 */
function beaconLight(c: CanvasRenderingContext2D, x: number, y: number, o?: PaintOptions, t = 0): void {
  if (!optBool(o, "on", false)) return;
  const col = o?.color === "red" ? PAL.red2 : PAL.yellow2;
  const cx = x + 3;
  const cy = y + 2;
  if (optBool(o, "reduced", false)) {
    glow(c, cx, cy, 16, col, 0.45);
    return;
  }
  const ang = (t / 380) % (Math.PI * 2);
  c.save();
  c.globalCompositeOperation = "lighter";
  for (let s = 0; s < 2; s++) {
    const a = ang + s * Math.PI;
    const len = optNum(o, "len", 70);
    const g = c.createRadialGradient(cx, cy, 0, cx, cy, len);
    g.addColorStop(0, rgba(col, 0.5));
    g.addColorStop(1, rgba(col, 0));
    c.fillStyle = g;
    c.beginPath();
    c.moveTo(cx, cy);
    c.arc(cx, cy, len, a - 0.35, a + 0.35);
    c.closePath();
    c.fill();
  }
  c.restore();
  glow(c, cx, cy, 8, col, 0.6);
}

/** 语义记录柜：cards 为卡片数量。 */
function cardCabinet(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = 24;
  const h = 28;
  fillPixelOutlined(c, x, y - h, w, h, PAL.wood2);
  fillPixel(c, x, y - h, w, 2, PAL.wood1);
  for (let r = 0; r < 3; r++) {
    for (let q = 0; q < 2; q++) {
      const dx = x + 2 + q * 11;
      const dy = y - h + 4 + r * 8;
      fillPixelOutlined(c, dx, dy, 9, 6, PAL.wood1);
      fillPixel(c, dx + 3, dy + 1, 3, 2, PAL.white);
      fillPixel(c, dx + 4, dy + 4, 1, 1, PAL.yellow3);
    }
  }
  const n = Math.min(optNum(o, "cards", 0), 10);
  for (let i = 0; i < n; i++) {
    const cx = x + 2 + i * 2;
    fillPixel(c, cx, y - h - 5 + (i % 2), 2, 5, PAL.ink);
    fillPixel(c, cx, y - h - 4 + (i % 2), 1, 4, i === n - 1 && optBool(o, "flash", false) && Math.floor(t / 150) % 2 === 0 ? PAL.yellow2 : [PAL.white, PAL.blue1, PAL.yellow1][i % 3]);
  }
  if (o?.label) {
    c.font = "700 5.5px sans-serif";
    const lw = c.measureText(String(o.label)).width + 6;
    fillPixel(c, x + w / 2 - lw / 2, y - h - 14, lw, 8, PAL.paper);
    drawText(c, String(o.label), x + w / 2, y - h - 10, { size: 5.5, weight: 700, align: "center", color: PAL.ink2 });
  }
}

/** 推车：box 为车上的箱子位图。 */
function cart(c: CanvasRenderingContext2D, x: number, y: number, o?: PaintOptions): void {
  if (o?.box) drawBitmap(c, String(o.box), x + 8, y - 19);
  drawBitmap(c, "cart", x, y - 11, { flip: optBool(o, "flip", false) });
}

/** 植物。 */
function plant(c: CanvasRenderingContext2D, x: number, y: number): void {
  drawBitmap(c, "plant", x, y - 18);
}

/** 地毯。 */
function rug(c: CanvasRenderingContext2D, x0: number, y0: number, w: number, h: number, col: string, col2: string): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixel(c, x + 2, y, w - 4, h, col);
  fillPixel(c, x, y + 1, w, h - 2, col);
  fillPixel(c, x + 3, y + 2, w - 6, 1, col2);
  fillPixel(c, x + 3, y + h - 3, w - 6, 1, col2);
  for (let i = 4; i < w - 4; i += 6) fillPixel(c, x + i, y + Math.floor(h / 2), 2, 1, col2);
}

/** 海报：draw 给一个钩子，在边框内画内容。 */
function poster(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, bg: string, draw?: (c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) => void): void {
  fillPixelOutlined(c, x, y, w, h, bg);
  if (draw) draw(c, x, y, w, h);
}

/** 显示器里的一张截图或文字行：像素边框。截图没加载出来时画占位图案。 */
function shot(c: CanvasRenderingContext2D, x0: number, y0: number, w: number, h: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixelOutlined(c, x, y, w, h, PAL.grey5, PAL.ink);
  fillPixel(c, x + 1, y + 1, w - 2, h - 2, "#0e1420");
  const img = shotImage(o?.screenshot === undefined ? null : String(o.screenshot));
  if (img) {
    c.imageSmoothingEnabled = false;
    c.drawImage(img, x + 2, y + 2, w - 4, h - 4);
  } else {
    const lines = (o?.text_lines as string[] | undefined) || [];
    if (lines.length) {
      lines.slice(0, Math.max(1, Math.floor((h - 4) / 6))).forEach((s, i) => {
        drawText(c, s, x + 3, y + 5 + i * 6, { size: 4.5, color: PAL.white, max: w - 6 });
      });
    } else {
      for (let r = 1; r < h - 3; r += 3) {
        for (let q = 2; q < w - 4; q += 2) {
          if (hash(r * 13 + q + Math.floor(t / 400)) > 0.55) fillPixel(c, x + q, y + r, 1, 1, PAL.white3);
        }
      }
    }
  }
  scanlines(c, x + 1, y + 1, w - 2, h - 2, 0.14);
  if (optBool(o, "text_only", false)) {
    fillPixel(c, x + w - 13, y + h - 8, 12, 7, PAL.yellow2);
    drawText(c, "文字", x + w - 7, y + h - 4.5, { size: 4.5, weight: 700, align: "center", color: PAL.ink });
  }
}

/** 交接管道口：包裹进出；out 为 flowing 时口上有流动的光点。 */
function pipe(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixelOutlined(c, x - 2, y - 18, 22, 18, PAL.metal4, PAL.ink);
  fillPixel(c, x, y - 16, 18, 14, "#141a20");
  fillPixel(c, x, y - 16, 18, 2, PAL.metal3);
  if (o?.out === "flowing") {
    const on = Math.floor(t / 160) % 2 === 0;
    fillPixel(c, x + 1, y - 15, 16, 12, on ? "rgba(63,191,102,0.30)" : "rgba(63,191,102,0.12)");
  }
  if (o?.out === "stopped") {
    fillPixel(c, x - 2, y - 20, 22, 2, PAL.red3);
    drawText(c, "停止", x + 9, y - 27, { size: 5, weight: 700, align: "center", color: PAL.red1, max: 34 });
  }
  if (optBool(o, "letters", false)) drawBitmap(c, "letter", x + 5, y - 12);
}

/** 传信管口：细管与塞着的信筒。 */
function tube(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixel(c, x, y - 5, 26, 5, PAL.yellow4);
  fillPixel(c, x, y - 5, 26, 1, PAL.yellow3);
  fillPixelOutlined(c, x - 4, y - 8, 6, 8, PAL.yellow2, PAL.ink);
  if (optBool(o, "letters", false)) drawBitmap(c, "letter", x - 3, y - 12);
}

/** 门口的邮筒。 */
function postbox(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixelOutlined(c, x, y - 18, 12, 18, PAL.red2, PAL.ink);
  fillPixel(c, x + 2, y - 15, 8, 2, PAL.red4);
  fillPixel(c, x + 3, y - 9, 6, 3, PAL.ink);
  if (optBool(o, "flag", false)) {
    fillPixel(c, x + 12, y - 10, 2, 6, PAL.yellow2);
    fillPixel(c, x + 12, y - 10, 5, 3, PAL.yellow1);
  }
}

/** 备份柜：三格，lit 为亮起的格数。 */
function backup(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, _t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  fillPixelOutlined(c, x, y - 34, 22, 34, PAL.grey5, PAL.ink);
  for (let i = 0; i < 3; i++) {
    const lit = i < optNum(o, "lit", 0);
    fillPixel(c, x + 3, y - 31 + i * 10, 16, 8, lit ? PAL.green3 : PAL.grey6);
    fillPixel(c, x + 3, y - 31 + i * 10, 16, 1, lit ? PAL.green2 : PAL.grey5);
  }
  drawText(c, "备份", x + 11, y + 5, { size: 5, align: "center", color: PAL.ink2 });
}

/** 通往机房的门。 */
function machineDoor(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 26);
  const h = optNum(o, "h", 40);
  fillPixelOutlined(c, x, y - h, w, h, PAL.grey5, PAL.ink);
  const open = optBool(o, "glow", false) ? 0.4 + 0.15 * Math.sin(t / 260) : 0;
  fillPixel(c, x + 2, y - h + 2, w - 4, h - 4, open ? mix("#141a20", PAL.yellow1, open) : "#141a20");
  fillPixel(c, x + w - 6, y - Math.round(h / 2), 2, 3, PAL.yellow2);
  drawText(c, "机房", x + w / 2, y - h - 6, { size: 5, weight: 700, align: "center", color: PAL.ink2, max: 30 });
}

/** 运维监控屏：正常为绿色网格，故障时变红。 */
function monitor(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions, t = 0): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 46);
  const h = optNum(o, "h", 30);
  fillPixelOutlined(c, x, y, w, h, PAL.grey5, PAL.ink);
  const alarm = optBool(o, "alarm", false) && Math.floor(t / 300) % 2 === 0;
  const line = alarm ? PAL.red1 : PAL.screen2;
  fillPixel(c, x + 2, y + 2, w - 4, h - 4, alarm ? "#3a0d12" : PAL.screen0);
  for (let r = 1; r < 4; r++) {
    const yy = y + 4 + r * 5;
    let px = x + 3;
    while (px < x + w - 4) {
      const len = 2 + Math.floor(hash(r * 7 + px) * 6);
      fillPixel(c, px, yy, Math.min(len, x + w - 4 - px), 1, line);
      px += len + 3;
    }
  }
  if (optBool(o, "label", true)) {
    drawText(c, alarm ? "故障" : "运行", x + w / 2, y + h + 5, { size: 5, weight: 700, align: "center", color: alarm ? PAL.red1 : PAL.ink2, max: 34 });
  }
}

/** 墙上的 MCP 工具面板：按下的按钮亮灯。 */
function toolPanel(c: CanvasRenderingContext2D, x0: number, y0: number, o?: PaintOptions): void {
  const x = Math.round(x0);
  const y = Math.round(y0);
  const w = optNum(o, "w", 46);
  const h = optNum(o, "h", 26);
  fillPixelOutlined(c, x, y, w, h, PAL.grey4, PAL.ink);
  drawText(c, "MCP", x + w / 2, y + 6, { size: 5, weight: 700, align: "center", color: PAL.white, max: w - 4 });
  const labels = (o?.labels as string[] | undefined) || [];
  const n = Math.max(1, optNum(o, "buttons", labels.length || 3));
  for (let i = 0; i < n; i++) {
    const lit = i === optNum(o, "lit", -1);
    const bw = Math.floor((w - 6) / n) - 2;
    const bx = x + 3 + i * Math.floor((w - 6) / n);
    fillPixel(c, bx, y + h - 13, bw, 9, lit ? PAL.yellow2 : PAL.grey2);
    if (lit) {
      fillPixel(c, bx + bw / 2 - 1, y + h - 14, 3, 1, PAL.yellow1);
      fillPixel(c, bx + bw / 2, y + h - 15, 1, 3, PAL.yellow1);
    }
    if (labels[i]) {
      drawText(c, labels[i], bx + bw / 2, y + h - 9, { size: 4.5, align: "center", color: lit ? PAL.ink : PAL.grey5, max: bw });
    }
  }
}

const shotCache = new Map<string, HTMLImageElement>();

/** 取一张本地截图（assets/ 下的文件）；加载完成前与文件缺失时返回 null，调用方画占位。 */
export function shotImage(file: string | null): HTMLImageElement | null {
  if (!file) return null;
  let img = shotCache.get(file);
  if (!img) {
    img = new Image();
    img.src = `assets/${file}`;
    shotCache.set(file, img);
  }
  return img.complete && img.naturalWidth > 0 ? img : null;
}

/** 预加载截图至 shotCache，确保首帧同步渲染。 */
export function preloadShotImage(file: string | null): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    if (!file) return resolve(null);
    let img = shotCache.get(file);
    if (!img) {
      img = new Image();
      img.src = `assets/${file}`;
      shotCache.set(file, img);
    }
    if (img.complete && img.naturalWidth > 0) return resolve(img);
    img.addEventListener("load", () => resolve(img), { once: true });
    img.addEventListener("error", () => resolve(null), { once: true });
  });
}

/**
 * 陈设画法表：房间陈设、管道、包裹、设备、屏幕、终端、白板、架子、警示灯等。
 * 键与原型 paint 表一致；图鉴页按这个表逐项列出。
 */
export const paint: Record<string, PaintFn> = {
  screen: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [w, h, mode, t, o] = args;
      screen(c, x, y, w as number, h as number, String(mode ?? "idle"), Number(t) || 0, o as PaintOptions);
    } else {
      const [o, t = 0] = args as [PaintOptions | undefined, number | undefined];
      screen(c, x, y, Number(o?.w) || 22, Number(o?.h) || 13, String(o?.mode ?? "idle"), Number(t) || 0, o);
    }
  },
  scanlines: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [w, h, a] = args;
      scanlines(c, x, y, w as number, h as number, a as number | undefined);
    } else {
      const [o] = args as [PaintOptions | undefined];
      scanlines(c, x, y, Number(o?.w ?? 22), Number(o?.h ?? 13), Number(o?.a ?? 0.22));
    }
  },
  desk,
  deskItems,
  chair,
  cabinet,
  blinkFrame: (c, x, y, o) => blinkFrame(c, x, y, optNum(o, "w", 220), optNum(o, "h", 170)),
  terminal: (c, x, y, o, t = 0) => terminal(c, x, y, o, t),
  door: (c, x, y, o) => door(c, x, y, o),
  whiteboard,
  corkboard,
  crt,
  window: windowPaint,
  clock: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      clockPaint(c, x, y, args[0], args[1] as PaintOptions | undefined);
    } else {
      const o = args[0] as PaintOptions | undefined;
      clockPaint(c, x, y, Number(o?.time) || 0, o);
    }
  },
  lamp: (c, cx, y, o) => {
    lamp(c, cx, y, typeof o === "boolean" ? o : optBool(o, "on", false), (o as PaintOptions)?.from === undefined ? undefined : Number((o as PaintOptions).from));
  },
  lightCone: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [len, w, color, alpha] = args;
      lightCone(c, x, y, len as number, w as number, String(color ?? PAL.yellow2), Number(alpha ?? 0.3));
    } else {
      const [o] = args as [PaintOptions | undefined];
      lightCone(c, x, y, optNum(o, "len", 40), optNum(o, "w", 30), optStr(o, "color", PAL.yellow2), optNum(o, "alpha", 0.3));
    }
  },
  glow: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [r, color, alpha] = args;
      glow(c, x, y, r as number, String(color ?? PAL.yellow2), Number(alpha ?? 0.5));
    } else {
      const [o] = args as [PaintOptions | undefined];
      glow(c, x, y, optNum(o, "r", 16), optStr(o, "color", PAL.yellow2), optNum(o, "alpha", 0.5));
    }
  },
  tray,
  bin,
  archive,
  mailbox: (c, x, y, o, t = 0) => mailbox(c, x, y, o, t),
  scrollRack,
  table: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [w, o] = args as [number, PaintOptions | undefined];
      table(c, x, y, w, o);
    } else {
      const [o] = args as [PaintOptions | undefined];
      const w = optNum(o, "w", 64);
      table(c, x, y, w, o);
    }
  },
  rack,
  shelf: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [w, o] = args as [number, PaintOptions | undefined];
      shelf(c, x, y, w, o);
    } else {
      const [o] = args as [PaintOptions | undefined];
      const w = optNum(o, "w", 64);
      shelf(c, x, y, w, o);
    }
  },
  beacon,
  beaconLight,
  cardCabinet,
  cart,
  plant: (c, x, y) => plant(c, x, y),
  rug: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [w, h, col, col2] = args as [number, number, string, string];
      rug(c, x, y, w, h, col, col2);
    } else {
      const [o] = args as [PaintOptions | undefined];
      rug(c, x, y, optNum(o, "w", 32), optNum(o, "h", 12), optStr(o, "col", PAL.rug), optStr(o, "col2", PAL.rug2));
    }
  },
  poster: (c, x, y, ...args: unknown[]) => {
    if (typeof args[0] === "number") {
      const [w, h, bg, draw] = args as [number, number, string, ((cx: CanvasRenderingContext2D, px: number, py: number, pw: number, ph: number) => void) | undefined];
      poster(c, x, y, w, h, bg, draw);
    } else {
      const [o] = args as [PaintOptions | undefined];
      poster(c, x, y, optNum(o, "w", 24), optNum(o, "h", 32), optStr(o, "bg", PAL.paper), o?.draw as ((cx: CanvasRenderingContext2D, px: number, py: number, pw: number, ph: number) => void) | undefined);
    }
  },
  shot: (c, x, y, ...args: unknown[]) => {
    let w = 32;
    let h = 20;
    let o: PaintOptions = {};
    let t = 0;
    if (typeof args[0] === "number" && typeof args[1] === "number") {
      w = args[0];
      h = args[1];
      o = (args[2] as PaintOptions) || {};
      t = typeof args[3] === "number" ? args[3] : 0;
    } else {
      o = (args[0] as PaintOptions) || {};
      t = typeof args[1] === "number" ? args[1] : 0;
      w = optNum(o, "w", 32);
      h = optNum(o, "h", 20);
    }
    shot(c, x, y, w, h, o, t);
  },
  pipe,
  tube,
  postbox,
  backup,
  machineDoor,
  monitor,
  toolPanel,
};

/** 陈设画法的名字，按原型顺序，供图鉴页列举。 */
export const PAINT_NAMES: string[] = Object.keys(paint);
