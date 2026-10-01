// 小人合成：由原型 v9 engine.js 第 3 节（parseSpriteKey、spriteSpec、put/blk/blit、placeItem、
// drawFace、sideLeg、composeChar、charFrame）与 sprites.js 的 rolePalette 改写为 TypeScript。
// 输出是纯点阵（Grid），不依赖浏览器与 PixiJS：同输入必得同输出，工单 #176 的确定时钟与单测依赖这一点。

import {
  BITMAPS,
  CHAR,
  CHAR_H,
  CHAR_W,
  DEPTS,
  HAIRS,
  ITEM_COLORS,
  ITEM_SHADES,
  PAL,
  POSES,
  ROLE_KINDS,
  SKINS,
  type BitmapDef,
  type PlacedItem,
  type Pose,
  type RoleKind,
} from "./registry.ts";
import { blit, blk, countOpaque, type ColorMap, type Grid, linePts, mix, outlineGrid, put } from "./grid.ts";

export interface SpriteKey {
  dept: string;
  kind: string;
  item: number | null;
}

export interface RolePalette {
  map: ColorMap;
  sleeve: { color: string; shade: string };
}

export interface SpriteSpec extends SpriteKey {
  key: string;
  role: RoleKind;
  map: ColorMap;
  sleeve: { color: string; shade: string };
}

export interface CharFrame {
  /** 身体层：腿、躯干、头、发型、配件、表情。 */
  base: Grid;
  /** 前景层：袖臂、手与手持物件（叠在身体之上）。 */
  front: Grid;
  /** 手持物件的落点矩形 [x, y, w, h]，没有物件时为 null。 */
  item: [number, number, number, number] | null;
  pose: Pose;
  /** base 与 front 依次拼成的稳定字符串，供测试比较同输入同输出。 */
  signature: string;
  /** base 与 front 合并后的非透明像素数。 */
  opaque: number;
}

// ---------------------------------------------------------------------------
// 角色配色：逐字对应 sprites.js 的 rolePalette

export function rolePalette(dept: string, kind: string, itemIndex: number | null): RolePalette {
  const d = DEPTS[dept];
  const r = ROLE_KINDS[kind];
  if (!d) throw new Error(`未知部门：${dept}`);
  if (!r) throw new Error(`未知角色种类：${kind}`);
  const skin = SKIN_PALETTE[r.skin];
  const hair = HAIRS[r.hairColor];
  const pack = itemIndex === null || itemIndex === undefined
    ? ["#9a6a3f", "#6f4a2a"]
    : [ITEM_COLORS[itemIndex], ITEM_SHADES[itemIndex]];
  const map: ColorMap = {
    S: skin[0], s: skin[1], H: hair[0], h: hair[1],
    C: d.main, c: d.shade, L: d.light,
    T: PAL.white, t: PAL.white2, K: d.light, k: d.shade,
    P: "#3b4163", p: "#2b3050", F: "#3a2e2a", f: "#5a4a44",
    W: PAL.white, w: PAL.white2,
    X: pack[0], x: pack[1],
    A: PAL.grey4, a: PAL.grey5,
    G: PAL.glass, g: "#3a3350",
    E: PAL.eye, M: PAL.mouth, B: PAL.blush,
    m: PAL.metal3, o: PAL.ink,
  };
  const sleeve = { color: "C", shade: "c" };
  switch (kind) {
    case "manager":
      Object.assign(map, { K: "#c8384a", k: "#8e2233", P: "#2f3242", p: "#22242f" });
      break;
    case "architect":
      Object.assign(map, { P: "#6b5040", p: "#4e3a2e" });
      break;
    case "lead":
      Object.assign(map, { P: "#35558f", p: "#27406d", A: "#e5484d", a: "#2f333d", F: "#e8e4dc", f: "#b7b2a8" });
      break;
    case "explorer":
      Object.assign(map, { T: "#e2cf9a", t: "#c1ab72", A: "#cdb27a", a: "#9e8452", K: d.main, P: "#6d6a3c", p: "#524f2b", F: "#6b4526" });
      sleeve.color = "T";
      sleeve.shade = "t";
      break;
    case "reviewer":
      Object.assign(map, { K: PAL.red2, k: PAL.red3 });
      break;
    case "tester":
      Object.assign(map, { W: "#f7f8fc", w: "#c6cadb", T: d.main, t: d.shade, K: d.main, P: "#555b6e", p: "#3f4453" });
      sleeve.color = "W";
      sleeve.shade = "w";
      break;
    default:
      Object.assign(map, { K: PAL.white, k: d.main });
  }
  return { map, sleeve };
}

// 肤色表（registry.SKINS）与姿势表（registry.POSES）在角色配色与合成里用
const SKIN_PALETTE = SKINS;

// ---------------------------------------------------------------------------
// 小人标识解析

const OPS_DEPT: Record<string, string> = { ops: "operations" };

export function resolveSpriteKey(key: string): SpriteKey {
  const parts = String(key).split(":");
  const base = parts[0];
  const item = parts.length > 1 && parts[1] !== "" ? Number(parts[1]) : null;
  let dept: string | undefined;
  let kind: string;
  if (base.includes(".")) {
    [dept, kind] = base.split(".");
  } else {
    kind = base;
    dept = OPS_DEPT[kind];
  }
  if (!dept || !ROLE_KINDS[kind]) throw new Error(`小人标识无效：${key}`);
  if (item !== null && !(item >= 0 && item < ITEM_COLORS.length)) throw new Error(`事项颜色序号无效：${key}`);
  return { dept, kind, item };
}

const specCache = new Map<string, SpriteSpec>();

export function spriteSpec(key: string): SpriteSpec {
  const cached = specCache.get(key);
  if (cached) return cached;
  const k = resolveSpriteKey(key);
  const pal = rolePalette(k.dept, k.kind, k.item);
  const spec: SpriteSpec = { key, dept: k.dept, kind: k.kind, item: k.item, role: ROLE_KINDS[k.kind], map: pal.map, sleeve: pal.sleeve };
  specCache.set(key, spec);
  return spec;
}

// ---------------------------------------------------------------------------
// 位图定义与别名（对应 engine.js 的 ITEM_ALIAS 与 bitmapDef）

const ITEM_ALIAS: Record<string, [string, ColorMap]> = {
  stamp_valid: ["stamp", { X: "#d4353f" }],
  stamp_green: ["stamp", { X: PAL.green2 }],
  stamp_red: ["stamp", { X: PAL.red2 }],
  stamp_seal: ["stamp", { X: PAL.blue2 }],
  card_task: ["card", { X: PAL.yellow2 }],
};

export function bitmapDef(name: string): BitmapDef {
  const alias = ITEM_ALIAS[name];
  if (alias) {
    const baseDef = BITMAPS[alias[0]];
    return { rows: baseDef.rows, map: Object.assign({}, baseDef.map, alias[1]), outline: baseDef.outline, name };
  }
  const d = BITMAPS[name];
  if (!d) throw new Error(`未知位图：${name}`);
  return d;
}

/** 位图点阵：把 rows 画到网格上并按需描边；recolor 覆盖部分字符的颜色。返回网格与位图自身尺寸。 */
export function bitmapGrid(name: string, recolor?: ColorMap): { grid: Grid; w: number; h: number; pad: number; bw: number; bh: number } {
  const d = bitmapDef(name);
  const map = recolor ? Object.assign({}, d.map, recolor) : d.map;
  const pad = d.outline ? 1 : 0;
  const bw = d.rows[0].length;
  const bh = d.rows.length;
  const w = bw + pad * 2;
  const h = bh + pad * 2;
  let grid: Grid = new Array<string | null>(w * h).fill(null);
  for (let y = 0; y < bh; y++) {
    for (let x = 0; x < bw; x++) {
      const ch = d.rows[y][x];
      if (ch === ".") continue;
      const col = map[ch];
      if (!col) throw new Error(`位图 ${name} 的字符没有颜色：${ch}`);
      grid[(y + pad) * w + x + pad] = col;
    }
  }
  if (pad) grid = outlineGrid(grid, w, h, PAL.ink);
  return { grid, w, h, pad, bw, bh };
}

// ---------------------------------------------------------------------------
// 侧面走路的腿：n 近侧脚踝，f 远侧脚踝（2×2 块左上角），bob 身体起伏

const LEGS_S: Record<string, { n: [number, number]; f: [number, number]; bob: number }> = {
  ss: { n: [15, 34], f: [13, 34], bob: 0 },
  w0: { n: [18, 34], f: [11, 34], bob: 0 },
  w1: { n: [15, 34], f: [13, 32], bob: -1 },
  w2: { n: [11, 34], f: [18, 34], bob: 0 },
  w3: { n: [14, 32], f: [13, 34], bob: -1 },
  r0: { n: [19, 33], f: [10, 34], bob: -1 },
  r1: { n: [15, 34], f: [12, 31], bob: -2 },
  r2: { n: [10, 34], f: [19, 33], bob: -1 },
  r3: { n: [14, 31], f: [15, 34], bob: -2 },
};

/** 待机时手持角色物件的位置（相对 A 手）。 */
const IDLE_ITEM: Record<string, { id: string; f: [number, number]; s: [number, number] }> = {
  clipboard: { id: "clipboard", f: [-4, -5], s: [-3, -5] },
  blueprint: { id: "blueprint_v", f: [-2, -6], s: [-1, -6] },
  magnifier: { id: "magnifier", f: [-4, 1], s: [-3, 1] },
  pen_red: { id: "pen_red", f: [-2, -5], s: [-1, -5] },
};

// ---------------------------------------------------------------------------
// 合成小工具

function placeItem(g: Grid, id: string, it: PlacedItem, handA: [number, number], handB: [number, number]): [number, number, number, number] {
  const d = bitmapDef(id);
  const w = d.rows[0].length;
  const h = d.rows.length;
  let x: number;
  let y: number;
  if (it.at === "both") {
    const cx = (handA[0] + handB[0] + 2) / 2;
    x = Math.round(cx - w / 2) + (it.dx || 0);
    y = Math.max(handA[1], handB[1]) + 2 - h + (it.dy || 0);
  } else if (it.at === "front") {
    x = handA[0] - Math.floor(w / 2) + 1 + (it.dx || 0);
    y = handA[1] + 3 - h + (it.dy || 0);
  } else {
    const hnd = it.hand === "B" ? handB : handA;
    x = hnd[0] + (it.dx || 0);
    y = hnd[1] + (it.dy || 0);
  }
  blit(g, CHAR_W, CHAR_H, d.rows, x, y, d.map, it.flip);
  return [x, y, w, h];
}

function drawFace(g: Grid, view: "f" | "s", face: string, hx: number, hy: number, map: ColorMap, glasses: boolean): void {
  const set = CHAR.faces[view];
  const f = set[face] || set.normal;
  (f.s || []).forEach(([x, y]) => put(g, CHAR_W, CHAR_H, hx + x, hy + y, map.s));
  if (!glasses) (f.B || []).forEach(([x, y]) => put(g, CHAR_W, CHAR_H, hx + x, hy + y, map.B));
  (f.E || []).forEach(([x, y]) => put(g, CHAR_W, CHAR_H, hx + x, hy + y, map.E));
  (f.M || []).forEach(([x, y]) => put(g, CHAR_W, CHAR_H, hx + x, hy + y, map.M));
}

function sideLeg(g: Grid, hip: [number, number], ank: [number, number], pants: string, shoe: string): void {
  linePts(hip[0], hip[1], ank[0], ank[1]).forEach((p) => blk(g, CHAR_W, CHAR_H, p[0], p[1], pants));
  for (let x = 0; x < 3; x++) {
    put(g, CHAR_W, CHAR_H, ank[0] + x, ank[1] + 2, shoe);
    put(g, CHAR_W, CHAR_H, ank[0] + x, ank[1] + 3, shoe);
  }
}

// ---------------------------------------------------------------------------
// composeChar：核心合成（对应 engine.js 555-654）

export function composeChar(args: { key: string; pose: string; face?: string | null; hold?: string | null }): CharFrame {
  const sp = spriteSpec(args.key);
  const pose = POSES[args.pose];
  if (!pose) throw new Error(`未知姿势：${args.pose}`);
  const map = sp.map;
  const role = sp.role;
  const view = pose.v;
  const base: Grid = new Array<string | null>(CHAR_W * CHAR_H).fill(null);
  const front: Grid = new Array<string | null>(CHAR_W * CHAR_H).fill(null);
  const dy = pose.bob + (pose.sit ? 3 : 0) + (pose.legs === "crouch" ? 4 : 0);
  const sleeve = map[sp.sleeve.color];
  const sleeveShade = map[sp.sleeve.shade];
  const skin = map.S;
  const outfit = CHAR.outfit[role.outfit];
  const headView = pose.headDown ? "b" : view;
  const hx = 10 + pose.hx;
  const hy = 16 + dy + pose.hy;
  const shA: [number, number] = view === "s" ? [15, 26 + dy] : [9, 26 + dy];
  const shB: [number, number] = view === "s" ? [13, 26 + dy] : [21, 26 + dy];
  const handA = pose.A ? ([shA[0] + pose.A[0], shA[1] + pose.A[1]] as [number, number]) : null;
  const handB = pose.B ? ([shB[0] + pose.B[0], shB[1] + pose.B[1]] as [number, number]) : null;

  // 后景：侧面的背包、远侧手臂、帽兜
  if (view === "s") {
    if (role.pack) blit(base, CHAR_W, CHAR_H, CHAR.pack.s.rows, CHAR.pack.s.x, CHAR.pack.s.y + dy, map);
    if (handB) {
      linePts(shB[0], shB[1], handB[0], handB[1]).forEach((p) => blk(base, CHAR_W, CHAR_H, p[0], p[1], sleeveShade));
      blk(base, CHAR_W, CHAR_H, handB[0], handB[1], map.s);
    }
  }
  // 腿
  if (view === "s") {
    const L = LEGS_S[pose.legs];
    if (!L) throw new Error(`侧面腿部帧未定义：${pose.legs}`);
    const pantsN = role.outfit === "jumpsuit" ? map.C : map.P;
    const pantsF = role.outfit === "jumpsuit" ? map.c : map.p;
    sideLeg(base, [13, 32 + pose.bob], L.f, pantsF, map.f);
    sideLeg(base, [15, 32 + pose.bob], L.n, pantsN, map.F);
  } else {
    const legs = CHAR.legs[pose.legs];
    if (!legs) throw new Error(`腿部帧未定义：${pose.legs}`);
    const lx = pose.legs === "crouch" ? 10 : 11;
    const ly = pose.legs === "sit" ? 35 : pose.legs === "crouch" ? 35 : 32 + pose.bob;
    blit(base, CHAR_W, CHAR_H, legs, lx, ly, map);
  }
  // 躯干
  blit(base, CHAR_W, CHAR_H, outfit[view], view === "s" ? 12 : 11, 26 + dy, map);
  if (view === "b" && role.pack) blit(base, CHAR_W, CHAR_H, CHAR.pack.b.rows, CHAR.pack.b.x, CHAR.pack.b.y + dy, map);
  if (role.hood && view !== "b") {
    const hd = CHAR.hood[view];
    blit(base, CHAR_W, CHAR_H, hd.rows, hd.x, hd.y + dy, map);
  }
  // 头、发型、眼镜、表情、头部配件
  blit(base, CHAR_W, CHAR_H, CHAR.head[headView], hx, hy, map);
  blit(base, CHAR_W, CHAR_H, CHAR.hair[role.hair][headView], hx - 1, hy - 2, map);
  const glasses = role.acc.includes("glasses") && headView !== "b";
  if (glasses) blit(base, CHAR_W, CHAR_H, CHAR.acc.glasses[headView], hx - 1, hy - 2, map);
  if (headView !== "b") drawFace(base, headView, args.face || pose.face || "normal", hx, hy, map, glasses);
  role.acc.forEach((a) => {
    if (a === "glasses") return;
    const accPart = CHAR.acc[a][headView];
    if (accPart) blit(base, CHAR_W, CHAR_H, accPart, hx - 1, hy - 2, map);
  });
  if (role.hood && view === "b") {
    const hd = CHAR.hood.b;
    blit(base, CHAR_W, CHAR_H, hd.rows, hd.x, hd.y + dy, map);
  }
  // 前景：袖子、手持物件、手
  const arms: [([number, number] | null), ([number, number] | null)][] =
    view === "s" ? [[shA, handA]] : [[shA, handA], [shB, handB]];
  arms.forEach(([s, h]) => {
    if (!s || !h) return;
    linePts(s[0], s[1], h[0], h[1]).forEach((p) => blk(front, CHAR_W, CHAR_H, p[0], p[1], sleeve));
  });
  // 审查者的袖标画在手臂中段
  if (role.armband && handA) {
    const bx = Math.round(shA[0] + (handA[0] - shA[0]) * 0.6);
    const by = Math.round(shA[1] + (handA[1] - shA[1]) * 0.6);
    blk(front, CHAR_W, CHAR_H, bx, by, map.K);
  }
  let itemRect: [number, number, number, number] | null = null;
  [pose.item, pose.item2].forEach((it) => {
    if (!it) return;
    const id = it.id === "$hold" ? args.hold : it.id;
    if (!id) return;
    const r = placeItem(front, id, it, handA || shA, handB || shB);
    if (!itemRect) itemRect = r;
  });
  if (pose.idle && role.idleItem && !pose.item && handA) {
    const ii = IDLE_ITEM[role.idleItem];
    const off = ii[view === "s" ? "s" : "f"];
    if (view !== "b") placeItem(front, ii.id, { id: ii.id, hand: "A", dx: off[0], dy: off[1] }, handA, handB || handA);
  }
  arms.forEach(([, h]) => {
    if (h) blk(front, CHAR_W, CHAR_H, h[0], h[1], skin);
  });

  // 描边：身体外轮廓用墨色；前景在身体上的边缘用下层颜色的暗色
  const baseOut = outlineGrid(base, CHAR_W, CHAR_H, PAL.ink);
  const frontOut = front.slice();
  for (let y = 0; y < CHAR_H; y++) {
    for (let x = 0; x < CHAR_W; x++) {
      const i = y * CHAR_W + x;
      if (front[i]) continue;
      if (
        (x > 0 && front[i - 1]) ||
        (x < CHAR_W - 1 && front[i + 1]) ||
        (y > 0 && front[i - CHAR_W]) ||
        (y < CHAR_H - 1 && front[i + CHAR_W])
      ) {
        frontOut[i] = baseOut[i] ? mix(baseOut[i], PAL.ink, 0.62) : PAL.ink;
      }
    }
  }
  const merged: Grid = baseOut.map((c, i) => frontOut[i] ?? c);
  const signature = baseOut.map((c, i) => `${c ?? "."}${frontOut[i] ?? "."}`).join("");
  return { base: baseOut, front: frontOut, item: itemRect, pose, signature, opaque: countOpaque(merged) };
}

// 帧缓存（对应 engine.js 的 frameCache）
const frameCache = new Map<string, CharFrame>();

export function charFrame(key: string, poseName: string, face?: string | null, hold?: string | null): CharFrame {
  const ck = `${key}|${poseName}|${face || ""}|${hold || ""}`;
  const cached = frameCache.get(ck);
  if (cached) return cached;
  const f = composeChar({ key, pose: poseName, face, hold });
  frameCache.set(ck, f);
  return f;
}

/** 水平翻转点阵（朝右与朝左）：对应原型 flipCanvas，在点阵空间完成，不依赖画布。 */
export function flipGrid(g: Grid, w: number, h: number): Grid {
  const out: Grid = new Array<string | null>(w * h).fill(null);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      out[y * w + x] = g[y * w + (w - 1 - x)];
    }
  }
  return out;
}

/** 头部像素（原型 headTop）：用于对齐名牌、图标与气泡锚点。 */
export function headTop(pose: Pose): [number, number] {
  return [10 + pose.hx, 16 + pose.bob + (pose.sit ? 3 : 0) + pose.hy];
}
