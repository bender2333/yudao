// 世界与系统（任务目录、角色、包裹、管道、说话目录与楼层驱动）的入口（工单 #82）。
// 画面、部门房间与首页都从这里取同一份实现；这里不依赖渲染与 PixiJS，可以直接在 node --test 下驱动。

export * from "./types.ts";
export * as declar from "./declare.ts";
export * as system from "./characters.ts";
export * as signals from "./signals.ts";
export * as say from "./say.ts";
export * as scene from "./scene.ts";
export * as floor from "./floor.ts";
export { buildCatalog, TASKS, IDLE, ROOMS, LINKS, deptRest, roleRest, keyOf, sayCatalogTypes, eventActionTypes } from "./floor-decl.ts";
