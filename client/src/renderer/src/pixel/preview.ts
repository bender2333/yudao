// 图鉴与联系表的取样：色板色块、画法点阵的缩略图。
// 联系表（工单 #176 验收标准 1「每一项与原型中对应画法的截图拼成联系表」）由 renderContactSheet 生成。

import { GALLERY_MEMBERS, type GallerySample } from "./gallery-data";
import { PAL } from "./registry";

export interface Swatch {
  name: string;
  color: string;
}

/** 色板色块：图鉴页顶部列出一遍，便于对照像素配色的整体观感。 */
export function paletteSwatch(): Swatch[] {
  return Object.entries(PAL)
    .filter(([, v]) => /^#[0-9a-f]{6}$/i.test(v))
    .map(([name, color]) => ({ name, color }));
}

export interface ContactSheetEntry {
  name: string;
  note: string;
  sample: GallerySample;
}

/** 联系表的条目：就是图鉴的全部画法，按原型成员顺序给出。 */
export function contactSheetEntries(): ContactSheetEntry[] {
  return GALLERY_MEMBERS.map((m) => ({ name: m.name, note: m.note, sample: m.sample }));
}

export interface SheetCell {
  x: number;
  y: number;
  w: number;
  h: number;
  name: string;
}

/**
 * 把联系表的排布算出来：每张缩略图占一格，点阵按整数倍放大后居中放进去。
 * 返回画布尺寸与每一格的矩形，调用方按它逐格绘制（画布绘制在浏览器里做，便于导出图片）。
 */
export function sheetLayout(columns: number, cellW: number, cellH: number): { width: number; height: number; cells: SheetCell[] } {
  const rows = Math.ceil(GALLERY_MEMBERS.length / columns);
  const cells: SheetCell[] = GALLERY_MEMBERS.map((m, i) => ({
    x: (i % columns) * cellW,
    y: Math.floor(i / columns) * cellH,
    w: cellW,
    h: cellH,
    name: m.name,
  }));
  return { width: columns * cellW, height: rows * cellH, cells };
}

/** 取一个点阵在给定字号下的整数倍放大倍数，保证缩略图不模糊。 */
export function sheetZoom(w: number, h: number, box: number): number {
  return Math.max(1, Math.floor(Math.min(box / w, box / h)));
}
