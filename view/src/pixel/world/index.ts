// 世界与系统（任务目录、角色、包裹、管道、场景与楼层驱动）的入口（工单 #82）。
// 画面、部门房间与首页都从这里取同一份实现；这里不依赖渲染与 PixiJS，可以直接在 node --test 下驱动。
//
// 说话的内容由翻译层写在动作的 say 与 sayTo 上（translate/say.ts），画面层只说动作带来的那句话：
// 原来这里的说话目录（world/say.ts）已经没有使用方，画面 9 删掉了（工单 #959）。

export * from "./types.ts";
export * as declar from "./declare.ts";
export * as system from "./characters.ts";
export * as signals from "./signals.ts";
export * as scene from "./scene.ts";
export * as floor from "./floor.ts";
export { buildCatalog, TASKS, IDLE, KINDS, EFFECTS, ROOMS, LINKS, deptRest, roleRest, sayCatalogTypes, eventActionTypes } from "./floor-decl.ts";
