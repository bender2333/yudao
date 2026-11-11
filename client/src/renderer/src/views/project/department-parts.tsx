// 部门页与节点面板共用的几段（原型 v12 第 3 节、docs/design/project-organization.md「节点面板与箭头面板接住的内容」，
// 工单 #1712）：它们原来在部门页（原型 v8 第 7.1 节、工单 #80）里，节点面板要按同一段文字画，
// 所以搬到这里由部门页引用；部门页本身的文字与结构不变，节点面板只按同一份事实写同一段。
// 这一文件只放「按事实画一段」的部件，读数据由调用处做。

import { Fragment } from "react";
import type { ReactNode } from "react";
import type { BackgroundCommandView, GuidanceRecord } from "../../api/generated/types.gen";
import { Empty, Section } from "./common";
import { GUIDANCE_STATUS, departmentsLineParts, formatTime, label, type DepartmentStateView } from "./labels";

// 三个部门各自的状态（原型 v12 第 3.1 节、三部门的循环结构 docs/design/department-loop.md「职能的状态」，工单 #905）：
// 标题区另起一行列出这个事项的组织里的部门，本部门加粗；没有部门状态（事项没有进行中）时这一行不出现。
// 部门清单与显示名取自事实（工单 #1457）：事项冻结的组织里的部门，不写死三个。
export function DepartmentsLine(props: {
  departments?: Record<string, DepartmentStateView> | null;
  department: string;
  /** 这个事项的组织里的部门标识与显示名；为空时按数据里的部门逐个显示（旧数据） */
  labels?: Record<string, string>;
  /** 部门清单只保留这些部门；为空时不筛 */
  keep?: string[];
}) {
  const kept = props.keep === undefined
    ? props.departments ?? null
    : Object.fromEntries(Object.entries(props.departments ?? {})
      .filter(([department]) => props.keep?.includes(department)));
  const parts = departmentsLineParts(kept, props.department, props.labels);
  if (parts === null) {
    return null;
  }
  return (
    <p className="y10-ws-item y10-ws-states department-line">
      <span className="y10-muted">{parts.length > 1 ? "各职能" : "职能"}</span>
      {parts.map((part, index) => (
        <Fragment key={part.text}>
          {index === 0 ? "　" : " · "}
          {part.current ? <strong>{part.text}</strong> : <span>{part.text}</span>}
        </Fragment>
      ))}
    </p>
  );
}

// 正在运行的后台命令：命令原文、开始时间与运行中；数据来自 run.steps 的 background_commands
export function RunningBackgroundCommands(props: { commands: BackgroundCommandView[] }) {
  const running = props.commands.filter((cmd) => cmd.status === "running");
  if (running.length === 0) {
    return null;
  }
  return (
    <>
      <h3 className="y10-h3 sub">正在运行的后台命令（{running.length} 条）</h3>
      <ul className="y10-ws-cmds">
        {running.map((cmd, index) => (
          <li key={`${cmd.started_at}-${index}`} className="y10-ws-cmd">
            <code className="y10-code y10-ws-cmd-command">{cmd.command}</code>
            <span className="y10-muted">{formatTime(cmd.started_at)}</span>
            <span className="y10-ws-cmd-state">运行中</span>
          </li>
        ))}
      </ul>
    </>
  );
}

// 指导一节（原型 v12 设计说明第 3.4 节、工单 #906）：说明写「部门正在工作时，指导在它的下一步作为通知加入；
// 部门在等待工作时，以这段指导开始一轮工作」。记录只写状态与原文，没有单独一行写部门的回答：
// 第三种状态「已回答」就是部门的回答，由主机在收到它的那一轮正常结束时写（#1039）。
// 发送框由调用处作为 children 传进来；这一节自己只认指导记录，单元测试按接口夹具直接渲染它。
export function GuidanceSection(props: {
  guidance: GuidanceRecord[];
  onOpenEvent: (eventId: string) => void;
  children?: ReactNode;
}) {
  return (
    <Section
      title="职能指导"
      note="职能正在工作时，指导在它的下一步作为通知加入；职能在等待工作时，以这段指导开始一轮工作"
    >
      {props.children}
      {props.guidance.length === 0 ? <Empty text="这个职能还没有指导记录" /> : (
        <ul className="y10-ws-guidance guidance-list">
          {props.guidance.map((record) => (
            <li key={record.guidance_id}>
              <div className="y10-ws-log-meta input-head">
                <strong>{label(GUIDANCE_STATUS, record.status)}</strong>
                <span className="y10-code byte-range">第 {record.version} 版</span>
                {record.applied_activation_id ? <span className="y10-code byte-range">已用于激活 {record.applied_activation_id}</span> : null}
                <button type="button" className="y10-link link" onClick={() => props.onOpenEvent(record.created_event_id)}>查看原始事件</button>
              </div>
              <p className="y10-ws-guidance p msg-text">{record.text}</p>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
