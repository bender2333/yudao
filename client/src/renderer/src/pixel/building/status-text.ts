// 楼层的状态词与配色（原型 v13 building.js 的 STATUS，颜色取 PAL 的子集，工单 #955）。
// 状态灯的取值就是画面合同 FLOOR_SIGNS 的八个（pixel/contract.ts）：服务端的说法只出现在翻译层，
// 这里只认画面的说法，合同加了取值而这里没有对应的词时类型检查就报错。
// 单独成模块是为了单元测试能直接核对这几句话（渲染器那一层用了类型擦除不支持的写法）。

import type { FloorSign } from "../contract.ts";
import { PAL } from "../registry.ts";

export const BUILDING_STATUS: Record<FloorSign, { text: string; color: string }> = {
  working: { text: "运行中", color: PAL.green2 },
  queued: { text: "排队中", color: PAL.grey2 },
  waiting_slot: { text: "等待执行槽位", color: PAL.orange2 },
  waiting_model: { text: "等待模型服务", color: PAL.grey3 },
  waiting_resume: { text: "待恢复", color: PAL.yellow2 },
  waiting_user: { text: "等待你的决定", color: PAL.yellow2 },
  interrupted: { text: "中断", color: PAL.grey4 },
  idle: { text: "空闲", color: PAL.grey2 },
};
