// 运行与执行槽位页（原型 v10 的 ui/views/sys-runtime.js，原型 v8 设计说明第 9.3 节，工单 #378）：
// 执行槽位、排空与磁盘可用空间。数据都来自已经在用的查询：占用与排队数来自 system.status，
// 磁盘可用空间是 home.disk_free_bytes。
// 原型里「正在执行的事项」与「等待队列」的明细来自 runtime.slots，后端还没有这一条查询，
// 因此只写 system.status 给出的数量，不画一张取不到数据的表。

import { useState } from "react";
import type { SystemStatus } from "../../api/generated/types.gen";
import { newCommandId } from "../../contract/command-id.ts";
import type { ClientApp } from "../../contract/client-app";
import { Block } from "../../shell/kit";
import { KeyValue, Loading, Modal, hasCommand, show } from "../project/common";
import { formatTime } from "../project/labels";
import { useCommand } from "../project/use-snapshot";
import {
  DRAIN_CONFIRM_CANCEL, DRAIN_CONFIRM_CONFIRM, DRAIN_CONFIRM_LINES, DRAIN_CONFIRM_TITLE,
  DRAIN_STATE_TEXT,
  FORCE_UPGRADE_CONFIRM_CANCEL, FORCE_UPGRADE_CONFIRM_CONFIRM, FORCE_UPGRADE_CONFIRM_LINES,
  FORCE_UPGRADE_CONFIRM_TITLE,
} from "./drain-text";
import { slotView } from "./slot-view";

export function RuntimePage(props: { app: ClientApp; systemStatus: SystemStatus | null }) {
  if (props.systemStatus === null) {
    return <Loading state={{ loading: true, data: null }} />;
  }
  const status = props.systemStatus;
  return (
    <div className="y10-sys-runtime">
      <SlotBlock status={status} />
      <DrainBlock app={props.app} status={status} />
      <RetentionBlock status={status} />
    </div>
  );
}

// 执行槽位：现在一次只执行一个事项（并行要等 #19），总数是 1，盏只有一盏，
// 占用的那盏按 system.status 的 running_runs 点亮。
function SlotBlock(props: { status: SystemStatus }) {
  const view = slotView({ running_runs: props.status.running_runs, slot_parameter: null });
  return (
    <Block title="执行槽位" subtitle={view.subtitle}>
      <div className="y10-slot-row">
        <div className="y10-lamps">
          {view.lamps.map((lamp, index) => (
            <span
              key={index}
              className={`y10-lamp${lamp.on ? " is-on" : ""}`}
              title={lamp.title}
            />
          ))}
        </div>
        <div className="y10-slot-count">
          <strong>
            {view.used} / {view.total}
          </strong>
          <span className="y10-muted">已占用 / 总数</span>
        </div>
      </div>
      <KeyValue
        items={[
          ["正在执行的事项", <span key="running">{props.status.running_runs} 个</span>],
          ["排队中的事项", <span key="queued">{props.status.drain.queued_work_items} 个</span>],
        ]}
      />
      <p className="y10-note note">正在执行的事项与等待队列的明细由所属工作包登记查询以后显示。</p>
    </Block>
  );
}

// 排空（3.1）：排空期间停止开始新事项，等正在执行的事项结束，排空在服务下一次启动时结束（#731）；
// 强制升级时正在执行的事项记为因升级停止，对应事项用项目的起点重新开始并排在队列最前面（#908）。
// 两个命令按排空状态出现：未排空时可以开始排空，排空中可以强制升级；两个命令点下去以前都要确认
// （工单 #663、#1187）。页面显示这次排空的开始时间与进行中的 run（工单 #1187）
function DrainBlock(props: { app: ClientApp; status: SystemStatus }) {
  const { drain } = props.status;
  const command = useCommand(props.app, `${drain.state}/${drain.version}`);
  const canStart = drain.state === "idle" && hasCommand(props.app, "runtime.start_drain");
  const canForce = drain.state === "draining" && hasCommand(props.app, "runtime.force_upgrade");
  // 「开始排空」不可逆：点下去以前先确认，把后果与剩下的那条路说清楚（工单 #663）
  const [confirming, setConfirming] = useState(false);
  // 强制升级与开始排空一样先确认：说明会让正在进行的 run 记为因升级停止（工单 #1187）
  const [confirmingForce, setConfirmingForce] = useState(false);

  const submit = (name: string) => {
    void props.app.command(name, { command_id: newCommandId(), base_version: drain.version });
  };

  return (
    <Block
      title="排空"
      subtitle="排空期间停止开始新事项，等正在执行的事项结束；排空在服务下一次启动时结束；强制升级时正在执行的事项记为因升级停止，用项目的起点重新开始"
    >
      <KeyValue
        items={[
          ["状态", DRAIN_STATE_TEXT[drain.state] ?? drain.state],
          ["开始时间", drain.since === null ? "—" : formatTime(drain.since)],
          ["正在执行的 run", <span key="running">{drain.running_runs} 个</span>],
          ["排队中的事项", <span key="queued">{drain.queued_work_items} 个</span>],
        ]}
      />
      {drain.running.length > 0 ? (
        <>
          <h3 className="y10-h3 sub">进行中的 run</h3>
          <ul className="y10-list">
            {drain.running.map((entry) => (
              <li key={entry.run_id}>
                <span>{show(entry.title, "未上报")}</span>
                <span className="y10-muted">进行中</span>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="y10-note note">没有正在进行的 run</p>}
      {canStart ? (
        <p className="y10-row">
          <button type="button" className="y10-btn danger" disabled={command.busy} onClick={() => setConfirming(true)}>
            开始排空
          </button>
        </p>
      ) : null}
      {confirming ? (
        <Modal title={DRAIN_CONFIRM_TITLE} onClose={() => setConfirming(false)}>
          {DRAIN_CONFIRM_LINES.map((line) => <p key={line} className="y10-note note">{line}</p>)}
          <p className="y10-row">
            <button
              type="button"
              className="y10-btn danger"
              disabled={command.busy}
              onClick={() => {
                setConfirming(false);
                submit("runtime.start_drain");
              }}
            >
              {DRAIN_CONFIRM_CONFIRM}
            </button>
            <button type="button" className="y10-btn" onClick={() => setConfirming(false)}>
              {DRAIN_CONFIRM_CANCEL}
            </button>
          </p>
        </Modal>
      ) : null}
      {canForce ? (
        <p className="y10-row">
          <button type="button" className="y10-btn primary danger" disabled={command.busy} onClick={() => setConfirmingForce(true)}>
            强制升级
          </button>
        </p>
      ) : null}
      {confirmingForce ? (
        <Modal title={FORCE_UPGRADE_CONFIRM_TITLE} onClose={() => setConfirmingForce(false)}>
          {FORCE_UPGRADE_CONFIRM_LINES.map((line) => <p key={line} className="y10-note note">{line}</p>)}
          <p className="y10-row">
            <button
              type="button"
              className="y10-btn primary danger"
              disabled={command.busy}
              onClick={() => {
                setConfirmingForce(false);
                submit("runtime.force_upgrade");
              }}
            >
              {FORCE_UPGRADE_CONFIRM_CONFIRM}
            </button>
            <button type="button" className="y10-btn" onClick={() => setConfirmingForce(false)}>
              {FORCE_UPGRADE_CONFIRM_CANCEL}
            </button>
          </p>
        </Modal>
      ) : null}
    </Block>
  );
}

// 磁盘可用空间（Stage 4）：home.disk_free_bytes，控制主机没有上报时写明未上报。
// 原型里的提示阈值、交付快照与工作区占用还没有查询来源，有来源以后加在这里
function RetentionBlock(props: { status: SystemStatus }) {
  const free = props.status.home.disk_free_bytes;
  return (
    <Block id="runtime-retention" title="数据保留" subtitle="数据目录所在卷的可用空间">
      <KeyValue
        items={[
          [
            "磁盘可用空间",
            free === null ? <span key="free">未上报</span> : <span key="free">{formatGigaBytes(free)}</span>,
          ],
        ]}
      />
    </Block>
  );
}

function formatGigaBytes(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}
