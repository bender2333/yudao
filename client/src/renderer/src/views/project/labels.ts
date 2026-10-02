// 页面显示用的名称（原型 v8 设计说明第 14 节用词；取值来自应用层的查询结果，未知值原样显示，不做猜测）。
// 单一来源：harness/app/labels.py 里的部门、阶段与状态名称，客户端按生成的合同取值对应显示。

export const DEPARTMENTS: Record<string, { name: string; role: string }> = {
  product: { name: "产品", role: "把用户的要求整理成有效需求" },
  engineering: { name: "工程", role: "按有效需求实现并封存交付" },
  quality: { name: "质检", role: "按验收条件核验并给出放行或返工" },
};

export const WORK_ITEM_STATUS: Record<string, string> = {
  not_started: "未开始",
  in_progress: "进行中",
  adopted: "已采纳",
  released_unsettled: "已放行",
  stopped: "已停止",
  held: "排队中",
};

export const RECOVERY_STATE: Record<string, string> = {
  running: "运行中",
  interrupted: "中断",
  pending_verification: "待核实",
  waiting_resume: "待恢复",
  terminated: "已终止",
};

export const PHASE_LABELS: Record<string, string> = {
  PRODUCT_SPEC: "产品处理中",
  ENGINEERING_PLAN: "工程计划中",
  ENGINEERING: "工程处理中",
  QUALITY: "质检处理中",
  DONE: "已完成",
  FAILED: "执行失败",
  PAUSED: "已暂停",
};

export const ACTION_STATUS: Record<string, string> = {
  not_sent: "未发送",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
  unknown: "结果未知",
};

export const ATTEMPT_STATUS: Record<string, string> = {
  prepared: "准备中",
  requesting: "请求中",
  success: "成功",
  failed: "失败",
  running: "进行中",
  cancelled: "已取消",
};

export const GUIDANCE_STATUS: Record<string, string> = {
  received: "已接收",
  in_input: "已进入模型输入",
  explained: "已解释",
  completed: "动作已核实",
  declined: "已说明边界",
  needs_work: "需要后续处理",
};

export const DECISION_KIND: Record<string, string> = {
  model_unavailable: "模型引用无法使用，等待恢复",
  definitions_changed: "定义版本不同，等待选择",
  unknown_action: "动作结果未知，等待核实",
  initial_prd: "接入已有项目的初始 PRD 等待确认",
};

export const INPUT_PROGRESS: Record<string, string> = {
  received: "已接收",
  assigned: "已交给产品处理",
  accepted: "已由有效需求接纳",
};

export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "未知";
  }
  return map[value] ?? value;
}

export function departmentName(value: string | null | undefined): string {
  if (!value) {
    return "未知部门";
  }
  return DEPARTMENTS[value]?.name ?? value;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) {
    return "未知时间";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "未上报";
  }
  return value.toLocaleString("zh-CN");
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return "未知";
  }
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) {
    return `${total} 秒`;
  }
  if (total < 3600) {
    return `${Math.floor(total / 60)} 分 ${total % 60} 秒`;
  }
  return `${Math.floor(total / 3600)} 小时 ${Math.floor((total % 3600) / 60)} 分`;
}
