// 像素画面的整数倍最近邻缩放：对应原型 engine.js 810-829 的 resize 规则（工单 #176 验收标准 3）。
// 画布按逻辑尺寸 W×H 的整数倍 k 渲染，再用最近邻采样缩放到容器宽度，缩放后像素不模糊。
// 这里的计算是纯函数：在 node --test 下可验证「k 一定是整数且缓冲不小于设备像素」。

export interface PixelViewSize {
  /** 画面的逻辑宽（像素）。 */
  W: number;
  /** 画面的逻辑高（像素）。 */
  H: number;
}

export interface ScaleLayout {
  /** 缩放倍数：正整数，最近邻放大。 */
  k: number;
  /** 渲染缓冲的宽高：逻辑尺寸乘以 k，必为整倍数。 */
  bufferW: number;
  bufferH: number;
  /** 缓冲宽高对应的 CSS 尺寸（按容器宽度等比给出）。 */
  cssW: number;
  cssH: number;
  /** 设备像素比。 */
  dpr: number;
}

/** 取不小于 avail*dpr/W 的最小整数倍，且至少 1。 */
export function integerScale(avail: number, dpr: number, W: number): number {
  return Math.max(1, Math.ceil((avail * dpr) / W - 1e-6));
}

/**
 * 按容器可用尺寸与设备像素比排布画面：渲染缓冲 = 逻辑尺寸 × 整数倍 k，CSS 尺寸铺满容器宽。
 * 视图尺寸改变时重新调用，k 随之改变，像素始终是整数倍。
 */
export function layoutFor(W: number, H: number, containerW: number, _containerH: number, dpr: number): ScaleLayout {
  const avail = Math.max(40, containerW);
  const k = integerScale(avail, dpr, W);
  return {
    k,
    bufferW: W * k,
    bufferH: H * k,
    cssW: avail,
    cssH: Math.round((avail * H) / W),
    dpr,
  };
}
