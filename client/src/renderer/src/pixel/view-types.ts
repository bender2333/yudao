// 像素画面的数据形状：画面对象、小人、覆盖层与事件。
// 单独成文件是为了让 view.ts（PixiJS 渲染层）与 view-state.ts（状态机）共用同一套类型，
// 状态机不必依赖 PixiJS，从而能在 node --test 下验证。

export interface ActorModel {
  id: string;
  /** 小人标识，如 engineering.lead。 */
  sprite: string;
  x: number;
  y: number;
  /** 动作名（ANIMS 里的键）；不给时用 idle。 */
  action?: string;
  /** 手持物件（BITMAPS 里的键）。 */
  hold?: string | null;
  /** 朝向：true 为朝左（水平翻转帧）。 */
  flip?: boolean;
}

export interface OverlayModel {
  id: string;
  kind: "name" | "sign" | "notice";
  x: number;
  y: number;
  text: string;
}

export interface PixelModel {
  items: ActorModel[];
  overlays?: OverlayModel[];
}

export interface PixelEvent {
  type: string;
  actorId?: string;
  action?: string;
  hold?: string | null;
  /** 事件在动作开始后的毫秒数（原型 playEvent 的 at）。 */
  at?: number;
  text?: string;
}

export interface PixelViewSize {
  /** 画面的逻辑宽（像素）。 */
  W: number;
  /** 画面的逻辑高（像素）。 */
  H: number;
}
