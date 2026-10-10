// 像素画登记表：由 scripts/generate-pixel-registry.mjs 从冻结的原型 v10 导出生成（工单 #176）。
// 本文件只做类型化再导出与常量，不重复登记数据；改画法请改生成脚本并 `npm run generate:pixel`。

import data from "./generated/registry.json" with { type: "json" };

/** 位图定义：rows 为点阵行（「.」表示透明），map 为字符到颜色，outline 表示是否自动描黑边。 */
export interface BitmapDef {
  name: string;
  rows: string[];
  map: Record<string, string>;
  outline: boolean;
}

/** 摆放好的手持物件（原型 placeItem 的入参形状）。 */
export interface PlacedItem {
  id: string;
  /** 放在哪只手；「at: both」表示两手之间的正前方（原型 carry 动作） */
  hand?: "A" | "B";
  at?: "both";
  dx?: number;
  dy?: number;
  flip?: boolean;
  scale?: number;
  alpha?: number;
}

/** 姿势：小人一帧的骨架参数（视角、腿部、双臂、手持物、起伏与低头）。 */
export interface Pose {
  v: "f" | "s" | "b";
  sit: number;
  bob: number;
  hx: number;
  hy: number;
  face: string | null;
  legs: string;
  A: [number, number] | null;
  B: [number, number] | null;
  item: PlacedItem | null;
  item2: PlacedItem | null;
  headDown: boolean;
  idle: boolean;
}

/** 动作帧序列：frames 为 [姿势名, 时长毫秒] 的数组。 */
export interface Anim {
  frames: [string, number][];
  loop: boolean;
  still: number;
  total: number;
}

/** 事实与动作的对照表（设计说明书第 3.5、3.9 节）。 */
export interface ActionInfo {
  label: string;
  fact: string;
  source: string;
  action: string;
  room?: string;
  level: "ui" | "S4" | "S5";
  anim: string;
}

export interface Dept {
  name: string;
  main: string;
  shade: string;
  light: string;
  wall: string;
  wall2: string;
  wall3: string;
  trim: string;
  floor: string;
  floor2: string;
  floor3: string;
  rug: string;
  rug2: string;
}

export interface RoleKind {
  label: string;
  hair: string;
  hairColor: string;
  skin: number;
  outfit: string;
  acc: string[];
  idleItem: string | null;
  hood?: boolean;
  pack?: boolean;
  armband?: boolean;
}

/** 部件通用形态：{x, y, rows} 的定位点阵。 */
export interface Part {
  x: number;
  y: number;
  rows: string[];
}

/** 三视角部件（正面/侧面/背面），背面可为 null（画在身体之后即被遮住）。 */
export interface ViewedPart {
  f: string[];
  s: string[];
  b: string[] | null;
}

/** 表情：头部框内的像素坐标；E 眼睛，M 嘴，B 腮红，s 眼皮。 */
export type FaceSpec = Record<string, [number, number][]>;

export interface CharData {
  head: { f: string[]; s: string[]; b: string[] };
  faces: Record<"f" | "s", Record<string, FaceSpec>>;
  hair: Record<string, ViewedPart>;
  acc: Record<string, ViewedPart>;
  outfit: Record<string, ViewedPart>;
  legs: Record<string, string[]>;
  hood: Record<"f" | "s" | "b", Part>;
  pack: Record<"s" | "b", Part>;
}

export interface Registries {
  PAL: Record<string, string>;
  CHAR: CharData;
  DEPTS: Record<string, Dept>;
  SKINS: string[][];
  HAIRS: Record<string, string[]>;
  ROLE_KINDS: Record<string, RoleKind>;
  ROLE_NAMES: Record<string, string>;
  ITEM_COLORS: string[];
  ITEM_SHADES: string[];
  SPRITE_LEVELS: Record<string, "ui" | "S4" | "S5">;
  BITMAPS: Record<string, BitmapDef>;
  POSES: Record<string, Pose>;
  ANIMS: Record<string, Anim>;
  ACTIONS: Record<string, ActionInfo>;
  BASE_MOTIONS: Record<string, { label: string; fact: string; anim: string }>;
  STATUS_ACTIONS: Record<string, string>;
  EVENT_ACTIONS: Record<string, string | { by: string; map: Record<string, string> }>;
  /** 循环画面默认用哪个小人：动作名 → 角色标识。 */
  VIGNETTE_SPRITES: Record<string, string>;
  FONT3: Record<string, string[]>;
}

export interface PixelRegistry {
  generatedFrom: string;
  inventory: { functions: string[]; data: string[]; all: string[] };
  levels: string[];
  levelLabels: Record<string, string>;
  levelTags: Record<string, string | null>;
  charW: number;
  charH: number;
  font: string;
  registries: Registries;
}

export const registry = data as unknown as PixelRegistry;

export const PAL = registry.registries.PAL;
export const CHAR = registry.registries.CHAR;
export const DEPTS = registry.registries.DEPTS;
export const SKINS = registry.registries.SKINS;
export const HAIRS = registry.registries.HAIRS;
export const ROLE_KINDS = registry.registries.ROLE_KINDS;
export const ROLE_NAMES = registry.registries.ROLE_NAMES;
export const ITEM_COLORS = registry.registries.ITEM_COLORS;
export const ITEM_SHADES = registry.registries.ITEM_SHADES;
export const SPRITE_LEVELS = registry.registries.SPRITE_LEVELS;
export const BITMAPS = registry.registries.BITMAPS;
export const POSES = registry.registries.POSES;
export const ANIMS = registry.registries.ANIMS;
export const ACTIONS = registry.registries.ACTIONS;
export const BASE_MOTIONS = registry.registries.BASE_MOTIONS;
export const STATUS_ACTIONS = registry.registries.STATUS_ACTIONS;
export const EVENT_ACTIONS = registry.registries.EVENT_ACTIONS;
export const VIGNETTE_SPRITES = registry.registries.VIGNETTE_SPRITES;
export const FONT3 = registry.registries.FONT3;

/** 小人帧缓冲尺寸：宽 32、高 40，脚底在第 37 行（原型 sprites.js 第 162 行的注释）。 */
export const CHAR_W = registry.charW;
export const CHAR_H = registry.charH;

/** 原型正文用的字体栈。 */
export const PROTOTYPE_FONT = registry.font;

/** 画面文字的字体栈（ADR-0021 第 4 条：微软雅黑，与原型 v10 engine.js 的 P.FONT 相同）。 */
export const PIXEL_FONT_FAMILY = '"Microsoft YaHei UI"';
export const PIXEL_FONT_STACK = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Source Han Sans SC", sans-serif';

/** 档位顺序与标签（原型 y10.js）。 */
export const LEVELS = registry.levels;
export const LEVEL_LABELS = registry.levelLabels;
export const LEVEL_TAGS = registry.levelTags;

/** 原型公开的全部画法成员（64 个），图鉴与测试按它核对「一项不少」。 */
export const PUBLIC_MEMBERS = registry.inventory;
