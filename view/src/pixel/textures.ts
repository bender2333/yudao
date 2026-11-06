// 像素画法 → PixiJS 纹理（工单 #176：小人的外形、姿势与配件、房间陈设、管道、包裹、设备、图标、
// 气泡的边框改写为 TypeScript 用来生成 PixiJS 的纹理，画风与原型一致）。
// 每个画法先在点阵上算好颜色，再一次性写成 ImageData 并包成 CanvasSource/Texture；
// 采样一律 nearest，放大到整数倍时不会出现插值模糊。

import { CanvasSource, Texture } from "pixi.js";
import { rgb, type ColorMap, type Grid } from "./grid.ts";
import { CHAR_H, CHAR_W } from "./registry.ts";
import { bitmapGrid, charFrame, flipGrid, type CharFrame } from "./char.ts";

/** 点阵 → ImageData；透明像素写 0。 */
export function gridImageData(grid: Grid, w: number, h: number): ImageData {
  const data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) {
    const col = grid[i];
    if (!col) continue;
    const v = rgb(col);
    data[i * 4] = v[0];
    data[i * 4 + 1] = v[1];
    data[i * 4 + 2] = v[2];
    data[i * 4 + 3] = 255;
  }
  return new ImageData(data, w, h);
}

const canvasBySize = new Map<string, HTMLCanvasElement>();

function canvasFor(w: number, h: number): HTMLCanvasElement {
  const key = `${w}x${h}`;
  const hit = canvasBySize.get(key);
  if (hit) return hit;
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  canvasBySize.set(key, c);
  return c;
}

/** 纹理缓存：同样的画法与参数只生成一次纹理（图鉴与画面反复取同一批纹理）。 */
const textureCache = new Map<string, Texture>();

function cachedTexture(key: string, build: () => Texture): Texture {
  const hit = textureCache.get(key);
  if (hit) return hit;
  const t = build();
  textureCache.set(key, t);
  return t;
}

/** 点阵 → 纹理（最近邻采样）。 */
export function textureFromGrid(grid: Grid, w: number, h: number, key: string): Texture {
  return cachedTexture(key, () => {
    const canvas = canvasFor(w, h);
    canvas.getContext("2d")!.putImageData(gridImageData(grid, w, h), 0, 0);
    return new Texture({ source: new CanvasSource({ resource: canvas, scaleMode: "nearest" }) });
  });
}

/** 位图（手持物件、图标、小物件）→ 纹理。recolor 覆盖部分字符颜色，flip 水平翻转。 */
export function bitmapTexture(name: string, opts?: { recolor?: ColorMap; flip?: boolean }): Texture {
  const key = `bmp|${name}|${JSON.stringify(opts?.recolor ?? null)}|${opts?.flip ? 1 : 0}`;
  return cachedTexture(key, () => {
    const b = bitmapGrid(name, opts?.recolor);
    const grid = opts?.flip ? flipGrid(b.grid, b.w, b.h) : b.grid;
    return textureFromGrid(grid, b.w, b.h, key);
  });
}

/** 小人帧 → 身体层与前景层两张纹理（原型 drawActor 一次画两张）。 */
export function charFrameTextures(key: string, pose: string, face: string | null, hold: string | null, flip = false): { base: Texture; front: Texture } {
  const frame: CharFrame = charFrame(key, pose, face, hold);
  const ck = `char|${key}|${pose}|${face ?? ""}|${hold ?? ""}|${flip ? 1 : 0}`;
  return {
    base: textureFromGrid(flip ? flipGrid(frame.base, CHAR_W, CHAR_H) : frame.base, CHAR_W, CHAR_H, `${ck}|base`),
    front: textureFromGrid(flip ? flipGrid(frame.front, CHAR_W, CHAR_H) : frame.front, CHAR_W, CHAR_H, `${ck}|front`),
  };
}

/** 释放所有缓存的纹理（视图销毁或图鉴刷新时调用）。 */
export function destroyPixelTextures(): void {
  for (const t of textureCache.values()) t.destroy(true);
  textureCache.clear();
  canvasBySize.clear();
}
