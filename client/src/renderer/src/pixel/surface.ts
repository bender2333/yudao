// 整幅画面的画布：按设备分辨率绘制（工单 #365、ADR-0021 第 4 条）。
//
// 楼层、部门房间与首页的楼三张画布原来先在逻辑尺寸（楼层 640×320、房间 480×240）的 1 倍离屏画布上
// 画完图形与文字，再由 PixiJS 的 Sprite 放大 k 倍：文字在 6 到 7 个逻辑像素里光栅化以后又被插值抹糊，
// 1 像素的线条粗细不均。这里改成原型 v9 engine.js 810-829 与 1126-1132 的做法：画布的像素尺寸就是
// 逻辑尺寸乘整数倍 k，每帧先 setTransform(k,0,0,k,0,0) 再按逻辑坐标绘制，图形与文字都按设备分辨率
// 光栅化，贴图用最近邻采样（imageSmoothingEnabled=false，与纹理最近邻一致）。

import { layoutFor, type ScaleLayout } from "./scale.ts";
import { setCurrentScale } from "./shapes.ts";

export interface PixelSurface {
  /** 挂到宿主元素上的画布：像素尺寸为逻辑尺寸乘整数倍 k，CSS 尺寸铺满容器宽度。 */
  readonly canvas: HTMLCanvasElement;
  /** 取 2D 上下文：每次 frame() 之后按逻辑坐标绘制。 */
  readonly ctx: CanvasRenderingContext2D;
  /** 当前排布（整数倍 k、缓冲尺寸、CSS 尺寸与设备像素比）。 */
  layout(): ScaleLayout;
  /** 逻辑尺寸变化时改尺寸（楼的层数变化后逻辑高随之改变）。 */
  resizeTo(W: number, H: number): void;
  /** 按当前尺寸与容器宽度重排画布。 */
  resize(): void;
  /** 一帧的开始：清屏、设 k 倍缩放、关掉插值，返回按逻辑坐标绘制的上下文。 */
  frame(): CanvasRenderingContext2D;
}

export interface PixelSurfaceOptions {
  host: HTMLElement;
  /** 逻辑宽高。 */
  W: number;
  H: number;
}

export function createPixelSurface(opts: PixelSurfaceOptions): PixelSurface {
  const canvas = document.createElement("canvas");
  canvas.style.imageRendering = "pixelated";
  canvas.style.display = "block";
  opts.host.appendChild(canvas);
  const ctx = canvas.getContext("2d")!;
  let logicalW = opts.W;
  let logicalH = opts.H;
  let lay: ScaleLayout = { k: 1, bufferW: 0, bufferH: 0, cssW: 0, cssH: 0, dpr: 1 };
  const surface: PixelSurface = {
    canvas,
    ctx,
    layout: () => lay,
    resizeTo(W, H) {
      logicalW = W;
      logicalH = H;
    },
    resize() {
      const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
      lay = layoutFor(logicalW, logicalH, contentWidth(opts.host, logicalW), opts.host.clientHeight || logicalH, dpr);
      // 像素尺寸就是逻辑尺寸乘整数倍：宽高必为逻辑宽高的整数倍
      canvas.width = lay.bufferW;
      canvas.height = lay.bufferH;
      canvas.style.width = `${lay.cssW}px`;
      canvas.style.height = `${lay.cssH}px`;
    },
    frame() {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(lay.k, 0, 0, lay.k, 0, 0);
      ctx.imageSmoothingEnabled = false;
      // 发光半径按整数倍放大（原型 P.currentScale），整数倍下不糊
      setCurrentScale(lay.k);
      return ctx;
    },
  };
  surface.resize();
  return surface;
}

// 宿主的可用宽度：容器的内容宽减去左右内边距（原型 engine.js 814-815 的 avail）。
// 宿主的盒宽在没有内边距时就是内容宽；画布按 avail 排布，CSS 宽度铺满到 avail。
function contentWidth(host: HTMLElement, fallback: number): number {
  const cs = typeof window === "undefined" || typeof window.getComputedStyle !== "function"
    ? null
    : window.getComputedStyle(host);
  const pad = cs ? parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) : 0;
  return Math.max(40, (host.clientWidth || host.getBoundingClientRect().width || fallback) - (Number.isNaN(pad) ? 0 : pad));
}