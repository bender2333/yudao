// 小人绘制、头顶图标、气泡、牌子、印章、箭头、沙漏、像素圆角框与像素文字：
// 由原型 v9 engine.js 第 7 节（1159-1464 行）改写为 TypeScript。画法与原型逐行一致。
// 文字按屏幕的实际分辨率绘制（画布先乘整数倍并设缩放），字体为微软雅黑（ADR-0021 第 4 条）。

import { animFrameAt } from "./anims.ts";
import { bitmapDef, charFrame, flipGrid, type CharFrame } from "./char.ts";
import { linePts, mix, rgba, type ColorMap, type Grid } from "./grid.ts";
import { CHAR_H, CHAR_W, FONT3, PAL, POSES, PIXEL_FONT_STACK, type Pose } from "./registry.ts";

/** 实心矩形，坐标取整到像素（原型 R）。 */
export function fillPixel(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string): void {
  c.fillStyle = col;
  c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}

/** 带墨色外框的实心矩形（原型 RB）。 */
export function fillPixelOutlined(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, col: string, ink?: string): void {
  fillPixel(c, x - 1, y - 1, w + 2, h + 2, ink || PAL.ink);
  fillPixel(c, x, y, w, h, col);
}

/** 位图绘制（原型 drawBitmap）：(x, y) 是位图自身第一个像素的位置，不含描边。 */
export function drawBitmap(c: CanvasRenderingContext2D, name: string, x: number, y: number, opts?: { recolor?: ColorMap; flip?: boolean; alpha?: number }): void {
  const d = bitmapDef(name);
  const map = opts?.recolor ? Object.assign({}, d.map, opts.recolor) : d.map;
  const pad = d.outline ? 1 : 0;
  const grid = blitToGrid(d.rows, map, opts?.flip);
  if (opts?.alpha !== undefined) c.globalAlpha = opts.alpha;
  for (let r = 0; r < d.rows.length; r++) {
    for (let q = 0; q < d.rows[0].length; q++) {
      const col = grid[(r * d.rows[0].length + q) as number];
      if (!col) continue;
      c.fillStyle = col;
      c.fillRect(Math.round(x) - pad + q, Math.round(y) - pad + r, 1, 1);
    }
  }
  if (opts?.alpha !== undefined) c.globalAlpha = 1;
}

/** 位图行 → 点阵（不描边；描边由 char.ts 的 bitmapGrid 处理，这里只取本体颜色）。 */
function blitToGrid(rows: string[], map: ColorMap, flip?: boolean): Grid {
  const w = rows[0].length;
  const grid: Grid = new Array<string | null>(w * rows.length).fill(null);
  for (let r = 0; r < rows.length; r++) {
    for (let q = 0; q < w; q++) {
      const ch = flip ? rows[r][w - 1 - q] : rows[r][q];
      if (ch === ".") continue;
      const col = map[ch];
      if (!col) throw new Error(`位图字符没有颜色：${ch}`);
      grid[r * w + q] = col;
    }
  }
  return grid;
}

// ---------------------------------------------------------------------------
// 小人绘制

export interface ActorLike {
  id?: string;
  sprite: string;
  x: number;
  y: number;
  anim: string;
  animStart: number;
  clock: number;
  face?: string | null;
  hold?: string | null;
  /** 朝向：<0 为朝左（帧水平翻转）。 */
  facing: number;
  visible?: boolean;
  alpha?: number;
  dim?: number;
  shadow?: boolean;
  seed?: number;
  icon?: HeadIcon | null;
}

export interface SceneLike {
  reduced: boolean;
  frozen?: boolean;
  /** 动画时间（毫秒），图标与沙漏按它变化。 */
  animT: number;
  realT: number;
  /** 画面的整数倍缩放；原型用它在整数倍下画发光。 */
  scale?: number;
}

export interface HeadIcon {
  kind: "think" | "stream" | "bulb" | "hourglass" | "question" | "exclaim" | "check" | "cross" | "zzz" | "heart" | "text";
  text?: string;
  /** 图标出现的时刻（毫秒）。 */
  t0?: number;
}

/** 小人脚下的椭圆阴影（原型 drawShadow）。 */
export function drawShadow(c: CanvasRenderingContext2D, x: number, y: number, w?: number): void {
  const hw = Math.round((w || 12) / 2);
  c.fillStyle = PAL.shadow;
  c.fillRect(Math.round(x) - hw, Math.round(y) - 1, hw * 2, 2);
  c.fillRect(Math.round(x) - hw + 2, Math.round(y) + 1, hw * 2 - 4, 1);
}

/** 小人在此刻的姿势、表情与帧。 */
export interface ActorInfo {
  poseName: string;
  pose: Pose;
  frame: CharFrame;
  face: string | null;
}

/** 小人在此刻的姿势、表情与帧（原型 actorFrame）：待机时按固定间隔眨眼。 */
export function actorFrame(scene: SceneLike, a: ActorLike): ActorInfo {
  const poseName = animFrameAt(a.anim, a.clock - a.animStart, scene.reduced);
  const pose = POSES[poseName];
  let face = a.face ?? null;
  if (!face && !scene.reduced && !scene.frozen && (!pose.face || pose.face === "normal") && ((a.clock + (a.seed ?? 0)) % 3600) < 140) face = "blink";
  return { poseName, pose, frame: charFrame(a.sprite, poseName, face, a.hold ?? null), face };
}

/** 翻转后的帧（对应原型的 baseF/frontF 惰性缓存）。 */
const flippedFrames = new Map<string, { base: Grid; front: Grid }>();

function frameForFlip(frame: CharFrame, key: string): { base: Grid; front: Grid } {
  const hit = flippedFrames.get(key);
  if (hit) return hit;
  const flipped = { base: flipGrid(frame.base, CHAR_W, CHAR_H), front: flipGrid(frame.front, CHAR_W, CHAR_H) };
  flippedFrames.set(key, flipped);
  return flipped;
}

function blitGridToCanvas(c: CanvasRenderingContext2D, grid: Grid, x: number, y: number): void {
  for (let r = 0; r < CHAR_H; r++) {
    for (let q = 0; q < CHAR_W; q++) {
      const col = grid[r * CHAR_W + q];
      if (!col) continue;
      c.fillStyle = col;
      c.fillRect(x + q, y + r, 1, 1);
    }
  }
}

/** 画一个小人（原型 drawActor）：part 为 base / front / base-noshadow。 */
export function drawActor(c: CanvasRenderingContext2D, scene: SceneLike, a: ActorLike, part?: "base" | "front" | "base-noshadow"): ActorInfo | null {
  if (a.visible === false || (a.alpha ?? 1) <= 0.01) return null;
  const info = actorFrame(scene, a);
  const fr = info.frame;
  const x = Math.round(a.x) - 16;
  const y = Math.round(a.y) - 38;
  const flip = a.facing < 0;
  const layers = flip ? frameForFlip(fr, `${a.sprite}|${info.poseName}|${info.face ?? ""}|${a.hold ?? ""}`) : { base: fr.base, front: fr.front };
  const alpha = (a.alpha ?? 1) * (a.dim ?? 1);
  if (alpha < 1) c.globalAlpha = alpha;
  if (part !== "front") {
    if (a.shadow && !info.pose.sit && part !== "base-noshadow") drawShadow(c, a.x, a.y, 12);
    blitGridToCanvas(c, layers.base, x, y);
  }
  if (part !== "base" && part !== "base-noshadow") blitGridToCanvas(c, layers.front, x, y);
  if (alpha < 1) c.globalAlpha = 1;
  return info;
}

/** 小人头顶的坐标：头发最高处上方（原型 headTop）。 */
export function headTop(scene: SceneLike, a: ActorLike): [number, number] {
  const info = actorFrame(scene, a);
  const p = info.pose;
  const dy = p.bob + (p.sit ? 3 : 0) + (p.legs === "crouch" ? 4 : 0) + p.hy;
  return [Math.round(a.x), Math.round(a.y) - 38 + 14 + dy];
}

/** 手持物件在画面上的矩形（原型 itemRect）；没有物件时为 null。 */
export function itemRect(scene: SceneLike, a: ActorLike): [number, number, number, number] | null {
  const info = actorFrame(scene, a);
  const r = info.frame.item;
  if (!r) return null;
  const flip = a.facing < 0;
  const x = flip ? CHAR_W - r[0] - r[2] : r[0];
  return [Math.round(a.x) - 16 + x, Math.round(a.y) - 38 + r[1], r[2], r[3]];
}

// ---------------------------------------------------------------------------
// 文字：微软雅黑，量宽、收缩、描边与发光

function textFont(size: number, weight?: number): string {
  return `${weight || 500} ${size}px ${PIXEL_FONT_STACK}`;
}

/** 量一段文字的像素宽（原型 measure）。 */
export function measure(c: CanvasRenderingContext2D, str: string, size?: number, weight?: number): number {
  c.font = textFont(size || 8, weight);
  return c.measureText(String(str)).width;
}

/** 把文字收缩到给定的像素宽内，超出部分用省略号（原型 fitText 内部函数）。 */
export function shrinkToWidth(c: CanvasRenderingContext2D, s: string, max: number): string {
  if (c.measureText(s).width <= max) return s;
  let t = s;
  while (t.length > 1 && c.measureText(`${t}…`).width > max) t = t.slice(0, -1);
  return `${t}…`;
}

/** 量宽并收缩到给定的像素宽（原型 fitText）。 */
export function fitText(c: CanvasRenderingContext2D, s: string, max: number, size?: number, weight?: number): string {
  c.font = textFont(size || 8, weight);
  return shrinkToWidth(c, String(s), max);
}

export interface TextOptions {
  size?: number;
  weight?: number;
  align?: "left" | "center" | "right";
  base?: "top" | "middle" | "bottom" | "alphabetic";
  /** 超出这个像素宽就收缩。 */
  max?: number;
  /** 描边颜色。 */
  outline?: string;
  outlineW?: number;
  /** 发光颜色。 */
  glow?: string;
  glowR?: number;
  color?: string;
}

/** 画一段文字（原型 text），返回它的像素宽。 */
export function drawText(c: CanvasRenderingContext2D, str: string, x: number, y: number, o?: TextOptions): number {
  const opt = o ?? {};
  c.font = textFont(opt.size || 8, opt.weight);
  c.textAlign = opt.align || "left";
  c.textBaseline = opt.base || "middle";
  let s = String(str);
  if (opt.max) s = shrinkToWidth(c, s, opt.max);
  if (opt.outline) {
    c.lineJoin = "round";
    c.lineWidth = opt.outlineW || 2;
    c.strokeStyle = opt.outline;
    c.strokeText(s, x, y);
  }
  if (opt.glow) {
    c.shadowColor = opt.glow;
    c.shadowBlur = (opt.glowR || 3) * (currentScale || 1);
  }
  c.fillStyle = opt.color || PAL.ink;
  c.fillText(s, x, y);
  if (opt.glow) {
    c.shadowBlur = 0;
    c.shadowColor = "transparent";
  }
  return c.measureText(s).width;
}

/** 画面当前的整数倍缩放（原型 currentScale）；发光半径按它放大，保证整数倍下不糊。 */
let currentScale = 1;

export function setCurrentScale(k: number): void {
  currentScale = k;
}

export function getCurrentScale(): number {
  return currentScale;
}

/** 3×5 像素数字与符号（原型 pixText）：逐像素填一个 1×1 的方块，返回总宽。 */
export function drawPixelText(c: CanvasRenderingContext2D, str: string, x: number, y: number, color: string, align?: "left" | "center" | "right"): number {
  const s = String(str);
  let w = 0;
  for (const ch of s) w += FONT3[ch] ? 4 : 0;
  w = Math.max(0, w - 1);
  let cx = Math.round(align === "center" ? x - w / 2 : align === "right" ? x - w : x);
  c.fillStyle = color;
  for (const ch of s) {
    const g = FONT3[ch];
    if (!g) continue;
    for (let r = 0; r < 5; r++) for (let q = 0; q < 3; q++) if (g[r][q] === "1") c.fillRect(cx + q, Math.round(y) + r, 1, 1);
    cx += 4;
  }
  return w;
}

// ---------------------------------------------------------------------------
// 边框、气泡、牌子、印章、箭头、沙漏

export interface BoxOptions {
  ink?: string;
  hi?: string;
  lo?: string;
}

/** 像素圆角框：外边墨色、内部填色、上沿高光（原型 box）。 */
export function drawBox(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, fill: string, o?: BoxOptions): void {
  const opt = o ?? {};
  x = Math.round(x);
  y = Math.round(y);
  w = Math.round(w);
  h = Math.round(h);
  c.fillStyle = opt.ink || PAL.ink;
  c.fillRect(x + 1, y, w - 2, h);
  c.fillRect(x, y + 1, w, h - 2);
  c.fillStyle = fill;
  c.fillRect(x + 1, y + 1, w - 2, h - 2);
  if (opt.hi) {
    c.fillStyle = opt.hi;
    c.fillRect(x + 2, y + 1, w - 4, 1);
  }
  if (opt.lo) {
    c.fillStyle = opt.lo;
    c.fillRect(x + 2, y + h - 2, w - 4, 1);
  }
}

export interface BubbleOptions {
  /** say 为说话气泡（三角尾巴），think 为思考气泡（小圆点尾巴）。 */
  kind?: "say" | "think";
  fill?: string;
  /** 尾巴的水平位置。 */
  tx?: number;
}

/** 对话气泡（原型 bubble）。 */
export function drawBubble(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, o?: BubbleOptions): void {
  const opt = o ?? {};
  const fill = opt.fill || PAL.white;
  drawBox(c, x, y, w, h, fill, { lo: PAL.white2 });
  const tx = Math.round(opt.tx !== undefined ? opt.tx : x + w / 2);
  if (opt.kind === "think") {
    c.fillStyle = PAL.ink;
    c.fillRect(tx - 2, y + h + 1, 4, 3);
    c.fillRect(tx - 1, y + h, 2, 5);
    c.fillStyle = fill;
    c.fillRect(tx - 1, y + h + 1, 2, 3);
    c.fillStyle = PAL.ink;
    c.fillRect(tx - 4, y + h + 5, 3, 3);
    c.fillStyle = fill;
    c.fillRect(tx - 3, y + h + 6, 1, 1);
  } else {
    c.fillStyle = PAL.ink;
    c.fillRect(tx - 3, y + h - 1, 7, 1);
    c.fillRect(tx - 2, y + h, 5, 1);
    c.fillRect(tx - 1, y + h + 1, 3, 1);
    c.fillRect(tx, y + h + 2, 1, 1);
    c.fillStyle = fill;
    c.fillRect(tx - 2, y + h - 1, 5, 1);
    c.fillRect(tx - 1, y + h, 3, 1);
    c.fillRect(tx, y + h + 1, 1, 1);
  }
}

export interface SignOptions {
  size?: number;
  maxW?: number;
  minW?: number;
  bg?: string;
  fg?: string;
  hi?: string;
  lo?: string;
  stripe?: string;
  string?: string;
  /** 挂绳钉子的高度。 */
  nail?: number;
  /** 下方手柄的长度。 */
  pole?: number;
}

/** 牌子：cx 为中心，bottom 为牌子下沿（原型 sign），返回牌子在画面上的矩形。 */
export function drawSign(c: CanvasRenderingContext2D, cx: number, bottom: number, str: string, o?: SignOptions): { x: number; y: number; w: number; h: number } {
  const opt = o ?? {};
  const size = opt.size || 7;
  const lines = String(str).split("\n");
  c.font = textFont(size, 600);
  const maxW = opt.maxW || 200;
  const texts = lines.map((s) => shrinkToWidth(c, s, maxW - 8));
  const tw = Math.max(...texts.map((s) => c.measureText(s).width));
  const w = Math.round(Math.max(opt.minW || 18, tw + 8));
  const lh = size + 2;
  const h = Math.round(lines.length * lh + 5);
  const x = Math.round(cx - w / 2);
  const y = Math.round(bottom - h);
  if (opt.nail !== undefined) {
    c.fillStyle = opt.string || PAL.wood4;
    linePts(x + 3, y, Math.round(cx), Math.round(opt.nail)).forEach((p) => c.fillRect(p[0], p[1], 1, 1));
    linePts(x + w - 4, y, Math.round(cx), Math.round(opt.nail)).forEach((p) => c.fillRect(p[0], p[1], 1, 1));
    c.fillStyle = PAL.metal3;
    c.fillRect(Math.round(cx) - 1, Math.round(opt.nail) - 1, 2, 2);
  }
  if (opt.pole) {
    c.fillStyle = PAL.ink;
    c.fillRect(Math.round(cx) - 2, bottom - 1, 4, opt.pole + 1);
    c.fillStyle = PAL.wood2;
    c.fillRect(Math.round(cx) - 1, bottom - 1, 2, opt.pole);
  }
  const bg = opt.bg || PAL.paper;
  drawBox(c, x, y, w, h, bg, { hi: opt.hi || PAL.white, lo: opt.lo || mix(bg, PAL.ink, 0.18) });
  if (opt.stripe) {
    c.fillStyle = opt.stripe;
    c.fillRect(x + 1, y + 1, 2, h - 2);
  }
  texts.forEach((s, i) => drawText(c, s, cx + (opt.stripe ? 1 : 0), y + 3 + i * lh + size / 2, { size, weight: 600, align: "center", color: opt.fg || PAL.ink }));
  return { x, y, w, h };
}

export interface SignStyle {
  bg: string;
  fg: string;
  stripe: string;
}

/** 门牌与举牌的配色：按牌上的文字决定（原型 signStyle）。 */
export function signStyle(text: string): SignStyle {
  const s = String(text || "");
  if (/中断/.test(s)) return { bg: "#3d4250", fg: PAL.white, stripe: PAL.grey2 };
  if (/待恢复/.test(s)) return { bg: PAL.yellow2, fg: PAL.ink, stripe: PAL.orange2 };
  if (/待核实/.test(s)) return { bg: PAL.yellow1, fg: PAL.ink, stripe: PAL.yellow3 };
  if (/暂停/.test(s)) return { bg: PAL.blue1, fg: PAL.ink, stripe: PAL.blue2 };
  if (/失败|不通过/.test(s)) return { bg: PAL.red2, fg: PAL.white, stripe: PAL.red3 };
  if (/完成|通过|放行/.test(s)) return { bg: PAL.green2, fg: PAL.white, stripe: PAL.green3 };
  if (/取消/.test(s)) return { bg: PAL.grey1, fg: PAL.ink, stripe: PAL.grey3 };
  if (/不确定/.test(s)) return { bg: PAL.yellow1, fg: PAL.ink, stripe: PAL.yellow3 };
  return { bg: PAL.paper, fg: PAL.ink, stripe: PAL.paper3 };
}

/** 印章印记（原型 stampMark）。 */
export function drawStampMark(c: CanvasRenderingContext2D, cx: number, cy: number, str: string, color: string, o?: { size?: number; rot?: number; alpha?: number }): void {
  const opt = o ?? {};
  const size = opt.size || 7;
  c.save();
  c.translate(Math.round(cx), Math.round(cy));
  c.rotate(opt.rot === undefined ? -0.14 : opt.rot);
  c.globalAlpha = opt.alpha === undefined ? 1 : opt.alpha;
  c.font = textFont(size, 800);
  const w = Math.round(c.measureText(str).width + 6);
  const h = size + 5;
  c.fillStyle = color;
  c.fillRect(-w / 2, -h / 2, w, 1);
  c.fillRect(-w / 2, h / 2 - 1, w, 1);
  c.fillRect(-w / 2, -h / 2, 1, h);
  c.fillRect(w / 2 - 1, -h / 2, 1, h);
  c.fillRect(-w / 2 + 2, -h / 2 + 2, w - 4, 1);
  c.fillRect(-w / 2 + 2, h / 2 - 3, w - 4, 1);
  c.textAlign = "center";
  c.textBaseline = "middle";
  c.fillText(str, 0, 0.5);
  c.restore();
}

/** 箭头：折线加箭头（原型 arrow），减少动画时用它表示交接。 */
export function drawArrow(c: CanvasRenderingContext2D, pts: [number, number][], color: string, o?: { dash?: boolean }): void {
  const opt = o ?? {};
  c.fillStyle = PAL.ink;
  const all: [number, number][] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const seg = linePts(Math.round(pts[i][0]), Math.round(pts[i][1]), Math.round(pts[i + 1][0]), Math.round(pts[i + 1][1]));
    seg.forEach((p) => all.push(p));
  }
  all.forEach((p, j) => {
    if (!opt.dash || j % 6 < 4) c.fillRect(p[0] - 1, p[1] - 1, 3, 3);
  });
  c.fillStyle = color;
  all.forEach((p, j) => {
    if (!opt.dash || j % 6 < 4) c.fillRect(p[0], p[1], 1, 1);
  });
  const a = pts[pts.length - 2];
  const b = pts[pts.length - 1];
  const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
  const tip: [number, number] = [Math.round(b[0]), Math.round(b[1])];
  for (let s = -1; s <= 1; s += 2) {
    const ex = Math.round(b[0] - Math.cos(ang + s * 0.6) * 6);
    const ey = Math.round(b[1] - Math.sin(ang + s * 0.6) * 6);
    const seg = linePts(tip[0], tip[1], ex, ey);
    c.fillStyle = PAL.ink;
    seg.forEach((p) => c.fillRect(p[0] - 1, p[1] - 1, 3, 3));
    c.fillStyle = color;
    seg.forEach((p) => c.fillRect(p[0], p[1], 1, 1));
  }
}

/** 沙漏（原型 hourglass）：t 为动画时间，沙子按 t 下落。 */
export function drawHourglass(c: CanvasRenderingContext2D, x: number, y: number, t: number): void {
  const phase = (t % 2400) / 2400;
  x = Math.round(x);
  y = Math.round(y);
  c.fillStyle = PAL.ink;
  c.fillRect(x - 1, y - 1, 9, 13);
  c.fillStyle = PAL.wood2;
  c.fillRect(x - 1, y - 1, 9, 2);
  c.fillRect(x - 1, y + 10, 9, 2);
  const glass = PAL.glass;
  const rows: [number, number][] = [[1, 5], [1, 5], [2, 3], [3, 1], [3, 1], [2, 3], [1, 5], [1, 5]];
  rows.forEach(([ox, w], i) => {
    c.fillStyle = glass;
    c.fillRect(x + ox, y + 1 + i, w, 1);
  });
  c.fillStyle = PAL.yellow2;
  const top = Math.round((1 - phase) * 3);
  const bot = Math.round(phase * 3);
  for (let r = 3 - top; r < 3; r++) c.fillRect(x + rows[r][0], y + 1 + r, rows[r][1], 1);
  for (let i = 0; i < bot; i++) {
    const r = 7 - i;
    c.fillRect(x + rows[r][0], y + 1 + r, rows[r][1], 1);
  }
  if (phase < 0.95) c.fillRect(x + 3, y + 4 + (Math.floor(t / 120) % 2), 1, 2);
}

/** 头顶图标（原型 drawIcon）：思考、逐字、灯泡、沙漏、问号、叹号、对勾、叉、zzz、爱心、文字。 */
export function drawIcon(c: CanvasRenderingContext2D, scene: SceneLike, a: ActorLike): void {
  const ic = a.icon;
  if (!ic || a.visible === false) return;
  const [hx, hy] = headTop(scene, a);
  const t = scene.reduced ? 0 : scene.animT;
  const bob = scene.reduced ? 0 : Math.round(Math.sin(t / 260));
  const el = scene.realT - (ic.t0 || 0);
  switch (ic.kind) {
    case "think": {
      const w = 22;
      const h = 11;
      const x = hx + 2;
      const y = hy - 22 + bob;
      drawBubble(c, x, y, w, h, { kind: "think", tx: hx + 3 });
      const n = scene.reduced ? 3 : 1 + (Math.floor(t / 280) % 3);
      c.fillStyle = PAL.ink2;
      for (let i = 0; i < n; i++) c.fillRect(x + 5 + i * 5, y + 5, 2, 2);
      break;
    }
    case "stream": {
      const full = String(ic.text || "");
      const count = scene.reduced ? full.length : Math.min(full.length, 1 + Math.floor(el / 110));
      const shown = full.slice(0, count);
      c.font = textFont(7, 500);
      const tw = Math.min(110, Math.max(20, c.measureText(full).width));
      const w = Math.round(tw + 8);
      const h = 12;
      const x = Math.round(hx - w / 2 + 6);
      const y = hy - 22 + bob;
      drawBubble(c, x, y, w, h, { kind: "think", tx: hx + 3 });
      drawText(c, shown + (count < full.length && Math.floor(t / 200) % 2 ? "▌" : ""), x + 4, y + h / 2 + 0.5, { size: 7, max: tw, color: PAL.ink2 });
      break;
    }
    case "bulb": {
      const x = hx - 4;
      const y = hy - 16 + bob;
      if (!scene.reduced) {
        c.fillStyle = rgba(PAL.yellow1, 0.35 + 0.2 * Math.sin(t / 150));
        c.fillRect(x - 3, y - 2, 15, 14);
      }
      c.fillStyle = PAL.yellow2;
      const rays: [number, number][] = [[-5, 3], [13, 3], [4, -5], [-3, -3], [11, -3]];
      rays.forEach(([rx, ry]) => c.fillRect(x + rx, y + ry, 2, 1));
      drawBitmap(c, "bulb", x, y);
      break;
    }
    case "hourglass": {
      const x = hx - 4;
      const y = hy - 17 + bob;
      drawHourglass(c, x, y, t);
      if (ic.text) drawSign(c, hx + 18, y + 10, ic.text, { size: 6, bg: PAL.white, minW: 10 });
      break;
    }
    case "question":
      drawBitmap(c, "question", hx - 2, hy - 12 + bob);
      break;
    case "exclaim":
      drawBitmap(c, "exclaim", hx - 1, hy - 11 + bob);
      break;
    case "check":
      drawBitmap(c, "check", hx - 3, hy - 9 + bob);
      break;
    case "cross":
      drawBitmap(c, "cross", hx - 3, hy - 8 + bob);
      break;
    case "heart":
      drawBitmap(c, "heart", hx - 3, hy - 9 + bob);
      break;
    case "zzz": {
      const k = scene.reduced ? 0 : (t % 1800) / 1800;
      drawBitmap(c, "zzz", hx + 4 + Math.round(k * 4), hy - 8 - Math.round(k * 6), { alpha: 1 - k * 0.6 });
      break;
    }
    case "text": {
      drawSign(c, hx, hy - 2 + bob, ic.text ?? "", { size: 6, bg: PAL.white, minW: 10 });
      break;
    }
    default:
      throw new Error(`未知头顶图标：${(ic as HeadIcon).kind}`);
  }
}
