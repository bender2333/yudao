// 楼层的状态词与配色（原型 building.js 的 STATUS，颜色取 PAL 的子集）。
// 单独成模块是为了单元测试能直接核对这几句话（渲染器那一层用了类型擦除不支持的写法）。

import { PAL } from "../registry.ts";

export const BUILDING_STATUS: Record<string, { text: string; color: string }> = {
  running: { text: "运行中", color: PAL.green2 },
  queued: { text: "排队中", color: PAL.grey2 },
  waiting_slot: { text: "等待执行槽位", color: PAL.orange2 },
  // held 是「上一个采纳成果被挂起」，与排队等槽位是两件事（工单 #733）
  held: { text: "成果已挂起", color: PAL.yellow2 },
  waiting_provider: { text: "等待模型服务", color: PAL.grey3 },
  waiting_resume: { text: "待恢复", color: PAL.yellow2 },
  waiting_decision: { text: "等待你的决定", color: PAL.yellow2 },
  interrupted: { text: "中断", color: PAL.grey4 },
  stopped: { text: "已停止", color: PAL.grey4 },
  idle: { text: "空闲", color: PAL.grey2 },
};
