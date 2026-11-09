// 项目头部一行与对话上方的时间条（工单 #1653；项目的组织设计说明 4.15「循环图跟着组织长」的「其余规矩」、
// 4.12「形态一键选用」；形态与核验角色设计说明「开环完成」）。
//
// 两件东西读两处事实，都不另存一份：
//   - 头部一行标签（形态名与改过几处、轮转方式、有核验或开环）读项目现在的组织（project.organization），
//     对话页与设置页都在。在跑的事项照它自己冻结的组织跑，这一行不随选中的事项变。
//   - 时间条（已用时间与上限，旁边一个「停止」）在对话上方，读选中事项的 project.loop；停止走现有的
//     取消事项：点下去先确认、写明后果，确认以后才把命令交给服务端（与事项面板的取消事项同一套）。
//
// 一切「事实推出页面写什么」的判断在 project-head-model.ts 里，那里有单元测试；这一份只负责摆位置。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { ProjectOrganizationResult } from "../../api/generated/types.gen";
import { cancelItemCommand, type CancelRequest } from "./cancel-text";
import { CommandFeedback, hasCommand, Modal } from "./common";
import {
  projectHead, STOP_LABEL, stopConfirm, timeBar, type TimeItem,
} from "./project-head-model";
import { useCommand } from "./use-snapshot";

/** 项目头部的一行标签：形态名（改过几处）、轮转方式、有核验或开环。还没有读到组织时没有这一行。 */
export function ProjectHead(props: { organization: ProjectOrganizationResult | null }) {
  const head = projectHead(props.organization);
  if (head === null) {
    return null;
  }
  return (
    <div className="y10-phead" data-testid="project-head" aria-label="项目现在用的组织">
      {head.tags.map((tag, index) => (
        <span
          key={tag}
          className={`y10-phead-tag${index === 0 && head.form !== "" ? " is-form" : ""}`}
        >
          {tag}
        </span>
      ))}
    </div>
  );
}

/**
 * 对话上方的时间条：选中事项的已用时间与上限。
 *
 * 事项在做时旁边多一个「停止」：点下去只换来一次确认（写明后果），确认以后才提交取消事项的命令；
 * 事项结束以后没有「停止」，已用时间与上限照写。
 */
export function ProjectTimeBar(props: {
  app: ClientApp;
  items: readonly TimeItem[];
  selected: string | null;
}) {
  const bar = timeBar(props.items, props.selected);
  // 待确认的那一份：点「停止」只记下它，确认框里点确认才提交
  const [pending, setPending] = useState<CancelRequest | null>(null);
  // 事项停下以后 project.loop 的 status 变了：这一次提交的提示随之收起，改由状态本身说结果
  const command = useCommand(props.app, bar === null || bar.stop === null ? "" : `${bar.stop.work_item_id}:${bar.stop.status}`);
  if (bar === null) {
    return null;
  }
  const confirm = pending === null ? null : stopConfirm(pending);
  return (
    <div className="y10-cv-time" data-testid="project-time-bar">
      <div className="y10-cv-time-row">
        <span className="y10-cv-time-text">{bar.text}</span>
        {bar.stop === null || !hasCommand(props.app, "work_item.cancel") ? null : (
          <button
            type="button"
            className="y10-btn danger"
            data-testid="stop-item"
            disabled={command.busy}
            onClick={() => setPending(bar.stop)}
          >
            {STOP_LABEL}
          </button>
        )}
      </div>
      {bar.ratio === null ? null : (
        <span
          className={`y10-meter${bar.ratio >= 0.8 ? " is-warn" : ""}`}
          role="meter"
          aria-label="已用时间与上限"
          aria-valuemin={0}
          aria-valuemax={bar.limit}
          aria-valuenow={bar.used ?? 0}
        >
          <span style={{ width: `${(bar.ratio * 100).toFixed(1)}%` }} />
        </span>
      )}
      <CommandFeedback submitted={command.submitted} problem={command.problem} />
      {confirm === null || pending === null ? null : (
        <Modal title={confirm.title} onClose={() => setPending(null)}>
          {confirm.lines.map((line) => (
            <p key={line} className="y10-note note">{line}</p>
          ))}
          <p className="y10-row">
            <button
              type="button"
              className="y10-btn danger"
              data-testid="stop-item-confirm"
              disabled={command.busy}
              onClick={() => {
                const body = cancelItemCommand(pending, true);
                setPending(null);
                if (body !== null) {
                  void command.submit("work_item.cancel", body);
                }
              }}
            >
              {confirm.confirm}
            </button>
            <button type="button" className="y10-btn" data-testid="stop-item-dismiss" onClick={() => setPending(null)}>
              {confirm.cancel}
            </button>
          </p>
        </Modal>
      )}
    </div>
  );
}
