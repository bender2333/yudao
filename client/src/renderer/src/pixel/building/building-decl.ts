// 楼的声明表（画面与播放设计说明第 5.1 节、原型 v13 js/pixel/building-decl.js，工单 #955）：
// 楼画面认的每种动作的级别（tier）与声明的最短时长（ms）。
//
// 画面层唯一认的动作种类就是这里的键：翻译层（translate/building.ts）只给出这里的 kind，
// 播放时间线按级别与时长排队，驱动（pixel/world/building.ts）按 kind 演。
// 楼里的动作都是闪光与撒彩带，不占用任何小人（时间线里不占参与方，互相不等）。
// 机房（通往机房的管线上的包裹、设备闪光、包裹到设备）不移植：客户端还没有机房，属于 3.2C 的工单。

import type { ActionClass } from "../timeline.ts";

/** 一个动作的级别与声明时长。 */
export type BuildingKind = ActionClass;

const k = (tier: ActionClass["tier"], ms: number): BuildingKind => ({ tier, ms });

/** 楼的动作：种类 → 级别与声明时长（原型 v13 building-decl.js 的 kinds）。 */
export const BUILDING_KINDS: Readonly<Record<string, BuildingKind>> = {
  // 关键事实时这一层闪一下（颜色写在动作里）；采纳时撒彩带（同时闪绿光）
  floor_flash: k("normal", 1200),
  celebrate: k("key", 1200),
};

/** 楼声明表里的动作种类（核对与测试用）。 */
export const BUILDING_KIND_NAMES: readonly string[] = Object.keys(BUILDING_KINDS);

/** 一个动作在这个场景的级别与声明时长；表里没有的种类抛错（楼只演声明表里的动作）。 */
export function buildingKind(kind: string): BuildingKind {
  const hit = BUILDING_KINDS[kind];
  if (!hit) throw new Error("楼的声明表里没有这种动作：" + kind);
  return hit;
}
