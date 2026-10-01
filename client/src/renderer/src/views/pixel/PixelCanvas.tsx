// 像素画面的 React 挂载点（工单 #176）：React 只负责挂载与传入数据，
// 画布与渲染循环全部在 PixiJS 的 createPixelView 里；组件把画面对象的五个方法暴露给调用方。
// 卸载时释放画面与时钟，避免离开页面后还在跑渲染循环。

import { useEffect, useRef, useState } from "react";
import { createPixelView, type PixelEvent, type PixelModel, type PixelView } from "../../pixel/view";
import { createRafClock, type Clock } from "../../pixel/clock";
import { PIXEL_FONT_STACK } from "../../pixel/registry";

export interface PixelCanvasProps {
  /** 画面逻辑尺寸（像素），缩放按它的整数倍放大。 */
  W: number;
  H: number;
  model: PixelModel | null;
  /** 到达的像素事件；每次变化都会转给 playEvent。 */
  event?: PixelEvent | null;
  /** 希望聚焦的小人。 */
  focusId?: string | null;
  /** 画面就绪后回调一次，调用方可直接使用画面的方法。 */
  onReady?: (view: PixelView, clock: Clock) => void;
}

/** 挂载一块 PixiJS 像素画布；数据变化时调用 setModel、playEvent 与 focus。 */
export function PixelCanvas(props: PixelCanvasProps): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<PixelView | null>(null);
  const clockRef = useRef<Clock | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    const clock = createRafClock(
      (cb: (t: number) => void) => requestAnimationFrame(cb),
      () => performance.now(),
      (h: number) => cancelAnimationFrame(h),
    );
    clockRef.current = clock;
    void (async () => {
      try {
        const view = await createPixelView({ host, clock, W: props.W, H: props.H });
        if (cancelled) {
          view.destroy();
          return;
        }
        viewRef.current = view;
        props.onReady?.(view, clock);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      viewRef.current?.destroy();
      viewRef.current = null;
      clock.destroy();
      clockRef.current = null;
    };
    // W、H 变化时重建画面；其它属性走下面的更新路径
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.W, props.H]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || !props.model) return;
    view.setModel(props.model);
  }, [props.model]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || !props.event) return;
    view.playEvent(props.event);
  }, [props.event]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || !props.focusId) return;
    view.focus(props.focusId);
  }, [props.focusId]);

  useEffect(() => {
    const onResize = (): void => viewRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return (
    <div className="pixel-canvas" ref={hostRef} style={{ fontFamily: PIXEL_FONT_STACK, width: "100%" }}>
      {error !== null ? <p className="pixel-canvas-error">像素画面加载失败：{error}</p> : null}
    </div>
  );
}
