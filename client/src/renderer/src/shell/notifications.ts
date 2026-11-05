// 通知文本与浏览器通知入口（网页界面的提供与发布设计说明第 5.3 节，应用层与接口层设计说明第 5.7 节，工单 #375）。
// 页面打开期间保持一条不按项目筛选的事件流连接（contract/client-app.ts）：决定请求与等待模型服务
// 由事件给出，这里把事件翻译成通知的标记、标题、正文与点击去处。
// 通知只用页面上已经查到的名称：项目名来自 projects.list，事项标题来自 project.overview；
// 名称还没有取到时正文写标识（与决定卡片第 5 节的回落相同）。
//
// 浏览器只在 https 页面与本机地址提供 Web Notifications（设计说明第 5.3 节）：局域网的 http 地址上
// window.Notification 不存在，这时不发通知也不报错。权限由浏览器在第一次需要发通知时询问，
// 用户拒绝以后不再发（同一页面上不再问）。

import type { EventObject } from "../api/generated/types.gen";
import { DECISION_KIND, departmentName, label } from "../views/project/labels.ts";

// 一条通知的内容
export type SystemNotice = {
  // 标记：决定请求取它的身份（决定请求的身份就是发出它的事件的编号），其余事件取事件的编号。
  // 浏览器按标记合并：同一件事在几个打开的页面里只显示一条
  tag: string;
  title: string;
  // 正文写明是哪个项目、哪件事
  body: string;
  // 决定请求的通知给出决定的标识：点击以后回到页面并打开这张决定卡片；其余通知没有去处
  decisionId: string | null;
  // 这件事由哪个事件引起：同一事件只发一次（重新同步时重复到达的事件跳过）
  eventId: string;
};

// 通知需要的名称：由页面上的查询给出，缺名称时给标识，正文不猜
export type NoticeNames = {
  projectName: (projectId: string | null) => string;
  workItemTitle: (workItemId: string | null) => string;
};

// 决定请求：run 流与项目流的两条事件（harness/projection.py 的 apply_decision_event：
// 决定请求的身份就是发出它的事件的编号，标记因此可以取事件的编号）
// 等待模型服务：model_retry_scheduled，模型服务不可用时按 payload.delay_sec 重试。
// 等待模型服务的完整实现属于 Stage 4（D17、app-and-interface.md 第 5.4 节）：
// 重试用完以后进入待恢复时由上面的 model_unavailable 决定请求给出通知，这里给的是等待期间的重试
export function noticeForEvent(event: EventObject, names: NoticeNames): SystemNotice | null {
  if (event.type === "decision_requested" || event.type === "project_decision_requested") {
    const kind = event.payload.kind;
    const matter = `${names.projectName(event.project_id)} · ${names.workItemTitle(event.work_item_id)}`;
    return {
      tag: event.event_id,
      title: kind === "model_unavailable" ? "等待模型服务，需要你决定" : "需要你决定",
      body: `${matter}：${label(DECISION_KIND, kind)}`,
      decisionId: event.event_id,
      eventId: event.event_id,
    };
  }
  if (event.type === "model_retry_scheduled") {
    const matter = `${names.projectName(event.project_id)} · ${names.workItemTitle(event.work_item_id)}`;
    return {
      tag: event.event_id,
      title: "等待模型服务",
      body: `${matter}：${departmentName(event.department)}部门的模型 ${event.payload.requested_model} 暂时不可用，${event.payload.delay_sec} 秒后重试`,
      decisionId: null,
      eventId: event.event_id,
    };
  }
  return null;
}

// 页面标题：待决定的数量。没有待决定的事时不显示数字（设计说明第 5.3 节）
export function pageTitle(pending: number, base: string): string {
  return pending > 0 ? `(${pending}) ${base}` : base;
}

// 浏览器通知：权限由浏览器在第一次需要发通知时询问（设计说明第 5.3 节）。
// window.Notification 在发通知时取，不在模块装载时取
export class SystemNotifier {
  private asked = false;
  private readonly sent = new Set<string>();

  // 发出通知；发过的不再发（同一件事只发一次）。返回是否真的发出了通知，
  // 页面用它核对事件流上收到的新决定请求与已发出的通知一一对应
  notify(notice: SystemNotice, open: (decisionId: string) => void): boolean {
    if (this.sent.has(notice.eventId)) {
      return false;
    }
    const ctor = typeof window === "undefined" ? undefined : window.Notification;
    if (ctor === undefined || ctor.permission === "denied" || (ctor.permission === "default" && this.asked)) {
      return false;
    }
    this.sent.add(notice.eventId);
    if (ctor.permission === "granted") {
      return this.show(ctor, notice, open);
    }
    this.asked = true;
    void ctor.requestPermission().then(
      (permission) => permission === "granted" && this.show(ctor, notice, open),
      () => undefined,
    );
    return true;
  }

  private show(ctor: typeof Notification, notice: SystemNotice, open: (decisionId: string) => void): boolean {
    const shown = new ctor(notice.title, { body: notice.body, tag: notice.tag });
    if (notice.decisionId !== null) {
      const decisionId = notice.decisionId;
      shown.onclick = () => {
        shown.close();
        open(decisionId);
      };
    }
    return true;
  }
}
