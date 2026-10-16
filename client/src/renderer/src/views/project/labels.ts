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
  awaiting_initial_prd: "等待确认初始 PRD",
  stopped: "已停止",
  held: "排队中",
};
// 事项状态对应的原型标记（原型 v10 handlers/project.js 的 displayOf）：
// held 与 stopped 在原型图标里没有对应（held 无图标），这两项保留纯文字，界面不猜
export const WORK_ITEM_STATUS_KIND: Record<string, string> = {
  not_started: "idle",
  in_progress: "running",
  adopted: "adopted",
  released_unsettled: "released",
  awaiting_initial_prd: "asking",
};

export const RECOVERY_STATE: Record<string, string> = {
  running: "运行中",
  interrupted: "中断",
  pending_verification: "待核实",
  waiting_resume: "待恢复",
  terminated: "已终止",
};

export const PHASE_LABELS: Record<string, string> = {
  CREATED: "等待开始",
  PRODUCT_SPEC: "产品处理中",
  ENGINEERING: "工程处理中",
  DELIVERY: "交付核验中",
  QUALITY: "质检处理中",
  REWORK_PRODUCT: "产品返工中",
  REWORK_ENGINEERING: "工程返工中",
  DONE: "已完成",
  FAILED: "执行失败",
  PAUSED: "已暂停",
};

// 停止原因的中文名（harness/definitions/stop_reasons.json 的取值与 done 的两种一致）
export const STOP_REASON: Record<string, string> = {
  released: "已完成并放行",
  baseline_verified: "已完成基线核验",
  max_cycles: "循环次数已达上限",
  model_steps_exhausted: "部门步数已达上限",
  no_tool_call: "部门连续多次没有调用工具",
  workspace_unrepresentable: "工作区有无法表示的条目",
  time_limit: "运行时间已达上限",
  cancelled: "运行已被取消",
  provider_error: "模型服务失败",
  provider_timeout: "模型服务请求超时",
  provider_protocol: "模型服务协议不符",
  unsupported_protocol: "不支持的协议",
  retry_after_too_long: "要求等待的时间过长",
  context_overflow: "上下文超过窗口",
  compaction_failed: "上下文压缩失败",
  host_commit_error: "主机保存失败",
  run_event_version_changed: "因 Yudao 升级停止",
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
  no_tool_call: "已暂停（模型没有调用工具），等待继续",
  workspace_unrepresentable: "已暂停（工作区无法表示），等待继续",
  definitions_changed: "定义版本不同，等待选择",
  unknown_action: "动作结果未知，等待核实",
  initial_prd: "接入已有项目的初始需求文档等待确认",
  kernel_modification: "交付改动了内核路径，等待批准",
};

// 决定请求的阻塞范围（DecisionView 的 blocks 取值）：卡片头的标记按中文写，不出现内部词 run
export const DECISION_BLOCKS: Record<string, string> = {
  run: "整次运行",
  action: "单个动作",
};

export const INPUT_PROGRESS: Record<string, string> = {
  received: "已接收",
  assigned: "已交给产品处理",
  accepted: "已由有效需求接纳",
};

// 部门设置的来源（DepartmentSettingView 的 source 取值）：本项目写入的设置或跟随部门默认
export const SETTING_SOURCE: Record<string, string> = {
  configured: "本项目写入",
  default: "跟随部门默认",
};

// 输入种类的中文名（work_item.inputs 的 kind 取值：文字，或用户在输入框里发出的命令）
export const INPUT_KIND: Record<string, string> = {
  text: "文字",
  command: "命令",
};

export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "未知";
  }
  return map[value] ?? value;
}

export function departmentName(value: string | null | undefined): string {
  if (!value) {
    // 事项停止后没有在处理的部门；调用处按位置决定写「没有」还是省略这一格
    return "";
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
