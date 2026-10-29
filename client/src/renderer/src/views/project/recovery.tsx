// 恢复与动作核实页（原型 v13 `js/ui/views/recovery.js` 第 7.2 节，工单 #380、#181）：只读显示一个事项的
// 恢复观察状态、最后已确认位置与自动继续的时间、待恢复原因与修复入口、等待回答的决定请求、
// 结果未知的动作与它的处理方式、各会话的用量与限额、执行所有权与迟到结果。
// 数据只来自 run.recovery、decisions.list、project.loop 与 project.overview 四个已登记的查询；
// 状态迁移由控制层决定，页面不做任何推进，也不显示按钮声称能继续。
// 恢复观察状态按结束的方式区分（工单 #747）：正常完成是「已完成」，被取消是「已取消」，
// 状态的说法与标记一致，页面上不出现停止原因与阶段的机器标识。
// 因升级停止没有单独的一块（原型 rc-upgrade），停止原因里写着「因 Yudao 升级停止」。
// 文字与状态映射在 recovery-text.ts 里（工单 #181），页面只按它的结果显示。

import type {
  DecisionList,
  ProjectLoopResult,
  ProjectOverviewResult,
  RecoveryOwner,
  RecoverySession,
  RunRecoveryResult,
  UnfinishedAction,
  UnknownAction,
  VerificationRecord,
  WorkItemCard,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import type { Route } from "../../shell/routing";
import { StatusMark } from "../../shell/kit";
import { DecisionCardList } from "../decisions/card";
import { artifactRefText } from "./artifact-ref";
import { Empty, KeyValue, Loading, Section, StopNote, Tag, show } from "./common";
import { ACTION_STATUS, RECOVERY_STATE, RECOVERY_STATE_KIND, STOP_REASON, departmentName, formatDuration, formatTime, label } from "./labels";
import {
  PENDING_NOTE,
  TERMINAL_NOTE,
  UNFINISHED_CLASS,
  UNFINISHED_KIND,
  actionSessionText,
  autoResumeText,
  handlingKind,
  handlingNote,
  handlingText,
  interruptedAtText,
  lastConfirmedText,
  purposeText,
  sessionUsageRows,
  showsInterruptionRecord,
} from "./recovery-text";
import { RestartOnboarding } from "./restart-onboarding";
import { useSnapshot } from "./use-snapshot";
import { readFailureText } from "../../contract/read-failure";

export function RecoveryPage(props: { app: ClientApp; route: Route; onNavigate: (hash: string) => void }) {
  const projectId = props.route.projectId ?? "";
  const workItemId = props.route.workItemId ?? "";
  const loop = useSnapshot<ProjectLoopResult>(props.app, "page.recovery.loop", "project.loop", {
    project_id: projectId,
    work_item: workItemId,
  }, workItemId === "");
  // run 标识由 project.loop 解析：路径上只有事项标识，界面不猜 run。
  // 已用时间与时间上限来自 project.loop 的事项运行限制，run.recovery 只给限额计数。
  // 停止原因来自 project.overview 的事项卡片，界面只读到自己的事项，避免整层不断重画
  const item = (loop.data?.work_items ?? []).find((entry) => entry.work_item_id === workItemId) ?? null;
  const overview = useSnapshot<ProjectOverviewResult>(props.app, "page.recovery.pick", "project.overview", {
    project_id: projectId,
    work_item: workItemId,
  }, workItemId === "");
  const settled = overview.data?.work_items.find((entry) => entry.work_item_id === workItemId) ?? null;
  const title = settled?.title ?? workItemId;
  // 决定卡片写事项标题；取不到时不写事项标识（工单 #802）。
  // 卡片头写项目名：项目名取自己读的概览，不把项目标识写进页面（设计说明第 4.1 节）
  const cardTitle = settled?.title ?? "";
  const projectName = overview.data?.name ?? "";
  const runId = item?.run_id ?? null;
  const elapsed = item?.elapsed_sec ?? null;
  const limit = item?.time_limit_sec ?? null;
  const recovery = useSnapshot<RunRecoveryResult>(props.app, "page.recovery", "run.recovery", {
    run_id: runId ?? "",
  }, runId === null);
  const decisions = useSnapshot<DecisionList>(props.app, "page.recovery.decisions", "decisions.list", {
    work_item_id: workItemId,
    status: ["open"],
  }, workItemId === "");
  const data = recovery.data;
  const now = Date.now();

  return (
    <div className="page y10-rc">
      <Loading state={loop} />
      <Loading state={overview} />
      <Loading state={recovery} />
      {workItemId === "" ? <Empty text="这个页面按事项查看：路径里没有事项标识" /> : null}
      {loop.error !== null ? (
        // 事项列表读不出来：事项明明在，是读不出来，不写「这个项目里没有这个事项」（工单 #775）
        <p className="y10-note note" role="status">{readFailureText(loop.error)}</p>
      ) : null}
      {recovery.error !== null ? (
        // 恢复观察读不出来：这一块本来有内容（工单 #775）
        <p className="y10-note note" role="status">{readFailureText(recovery.error)}</p>
      ) : null}
      {item === null && !loop.loading && loop.error === null && workItemId !== "" ? <Empty text="这个项目里没有这个事项" /> : null}
      {item !== null && runId === null ? <Empty text="这个事项还没有运行记录，没有恢复观察" /> : null}
      {data ? (
        <>
          <StateBlock title={title} data={data} startedAt={item?.started_at ?? null} />
          <ReasonBlock data={data} item={settled} />
          <Section
            id="rc-decide"
            title="决定请求"
            note="需要你修复入口、选择版本或决定是否继续等待时，由这里的卡片交给你；结果未知的动作不在这里"
            className="y10-rc-decide-block"
          >
            <Loading state={decisions} />
            <DecisionCardList
              app={props.app}
              decisions={decisions.data?.decisions ?? []}
              now={now}
              names={() => ({ projectName, workItemTitle: cardTitle })}
              onNavigate={props.onNavigate}
              viewId="recovery.decisions"
              emptyText="没有等待你回答的决定"
            />
          </Section>
          <ActionBlock data={data} />
          <LimitsBlock data={data} elapsed={elapsed} limit={limit} />
          <OwnerBlock data={data} />
          {item?.kind === "onboarding"
            ? <RestartOnboarding app={props.app} projectId={projectId} />
            : null}
        </>
      ) : null}
    </div>
  );
}

// 恢复观察状态（原型 rc-state）：七种状态按原型排成一排，当前一项用原型标记显示
function StateBlock(props: { title: string; data: RunRecoveryResult; startedAt: string | null }) {
  const current = props.data.state;
  return (
    <Section
      id="rc-state"
      title="恢复观察状态"
      note={`事项：${props.title} · ${props.startedAt === null ? "尚未开始" : formatTime(props.startedAt)}`}
      className={`y10-rc-state-block is-${current}`}
    >
      <ul className="y10-rc-states">
        {Object.keys(RECOVERY_STATE).map((state) => (
          <li key={state} className={`y10-rc-state${state === current ? ` is-on is-${state}` : ""}`}>
            {state === current
              ? <StatusMark kind={RECOVERY_STATE_KIND[state]} text={label(RECOVERY_STATE, state)} />
              : label(RECOVERY_STATE, state)}
          </li>
        ))}
      </ul>
      {props.data.reason && props.data.state !== "waiting_resume" && props.data.state !== "interrupted"
        ? <p className="y10-rc-reason">{props.data.reason}</p>
        : null}
      <ul className="y10-rc-rules">
        <li>Yudao 启动时自动继续中断的执行；最后已确认的位置与自动继续的时间在下方列出。</li>
        <li>重新连接事件流只补齐观察，不新建执行，也不重发模型请求或工具调用。</li>
        <li>恢复不清零已用限额。</li>
      </ul>
    </Section>
  );
}

// 待恢复原因、中断位置与四种结束方式（原型 rc-reason）：按状态给出不同内容。
// 已结束的 run 不再继续，未完成动作不由恢复处理，只显示结束原因与最后已确认的位置
function ReasonBlock(props: { data: RunRecoveryResult; item: WorkItemCard | null }) {
  const data = props.data;
  if (data.state === "waiting_resume") {
    const unusable = data.unusable;
    if (unusable === null) {
      // 模型引用无法使用时给出部门、模型与问题；其余的待恢复由决定请求结束（例如定义版本不同，
      // 工单 #181）：原因由决定请求写，页面照实显示，不在这里抛错
      return (
        <Section id="rc-reason" title="待恢复原因" className="y10-rc-reason-block">
          <p className="y10-rc-reason">{show(data.reason, "还没有写明原因")}</p>
          <p className="y10-note note">修复或选择以后由控制主机重新判断能否继续；回答使用下方决定卡片。</p>
        </Section>
      );
    }
    return (
      <Section id="rc-reason" title="待恢复原因" className="y10-rc-reason-block">
        <div className="y10-rc-unusable">
          <StatusMark kind="unusable" text="待恢复" />
          <strong>{departmentName(unusable.department)}部门的模型无法使用</strong>
        </div>
        <KeyValue
          items={[
            ["部门", departmentName(unusable.department)],
            ["模型", <code className="y10-code" key="model">{show(unusable.model, "未设置")}</code>],
            ["问题", show(unusable.problem)],
          ]}
        />
        <p className="y10-note note">
          修复以后控制主机在合适的位置重新判断能否继续；在本项目的部门设置里另选模型只影响本项目，
          从这个部门下一次模型请求起生效。回答使用下方决定卡片。
        </p>
      </Section>
    );
  }
  if (data.state === "interrupted") {
    return (
      <Section id="rc-reason" title="中断位置" className="y10-rc-reason-block">
        <p className="y10-rc-reason">{show(data.reason, "服务进程停止")}</p>
        <KeyValue
          items={[
            ["最后已确认", lastConfirmedText(data)],
            ["自动继续时间", autoResumeText(data.owner)],
          ]}
        />
        <p className="y10-note note">按持久事实核对：没有未完成动作时自动继续。</p>
      </Section>
    );
  }
  // 继续以后（运行中）仍显示这次中断的记录（工单 #181）：中断位置来自取得执行权时记下的依据
  if (showsInterruptionRecord(data)) {
    return (
      <Section id="rc-reason" title="这次中断" className="y10-rc-reason-block">
        <KeyValue
          items={[
            ["中断位置", interruptedAtText(data.owner)],
            ["自动继续时间", autoResumeText(data.owner)],
            ["最后已确认", lastConfirmedText(data)],
          ]}
        />
        <p className="y10-note note">这次中断的记录保留在下方；继续以后的事项是同一个，已用限额不清零。</p>
      </Section>
    );
  }
  // 四种结束方式：标题与状态一致，停止原因与所在部门照旧列出（工单 #747），最后已确认位置也写出来
  const note = TERMINAL_NOTE[data.state];
  if (note !== undefined) {
    const item = props.item;
    return (
      <Section id="rc-reason" title={label(RECOVERY_STATE, data.state)} className="y10-rc-reason-block">
        <KeyValue
          items={[
            ["停止原因", item?.stop_reason ? label(STOP_REASON, item.stop_reason) : "未上报"],
            // 停止说明（工单 #1162）：让事项停下的那条错误的原文，写在停止原因下面；用户自己停下时没有。
            // 已收下的交付（工单 #1239）写在它下面一行，取自同一份事项卡片
            ["停止说明", <StopNote key="stop-note" note={item?.stop_note ?? null} kept={item?.kept_delivery}
              empty="没有" />],
            ["所在部门", item?.department ? departmentName(item.department) : "没有在部门里执行"],
            ["最后已确认", lastConfirmedText(data)],
          ]}
        />
        <p className="y10-note note">{note}</p>
      </Section>
    );
  }
  return null;
}

// 未完成动作与结果未知的动作（原型 rc-verify）：还没有处置的写它的状态与输入依据；
// 已经处置的写处理方式与交还给模型的内容。核实是追加的记录，原始观察不改写
function ActionBlock(props: { data: RunRecoveryResult }) {
  const pending = props.data.unfinished_actions;
  const handled = props.data.unknown_actions;
  const records = props.data.verifications;
  const sessions = props.data.sessions;
  return (
    <Section
      id="rc-verify"
      title="未完成动作"
      note="重新启动时结果未知的动作：有核实方法的先自动核实（核实确认），其余作为工具结果交还发出它的会话（交还会话）；核实产生新的记录，不改写原始观察"
    >
      {pending.length === 0 && handled.length === 0
        ? <Empty text="没有未完成的动作：所有动作都有回执" />
        : null}
      {pending.length > 0 ? (
        <>
          <h3 className="y10-h3 sub">还没有处置</h3>
          <div className="y10-rc-actions">
            {pending.map((entry) => (
              <PendingActionCard key={entry.started_event_id} entry={entry} />
            ))}
          </div>
        </>
      ) : null}
      {handled.length > 0 ? (
        <>
          <h3 className="y10-h3 sub">已经处置</h3>
          <div className="y10-rc-actions">
            {handled.map((entry) => (
              <HandledActionCard
                key={`${entry.action_id}-${entry.at}`}
                entry={entry}
                sessions={sessions}
                checks={records.filter((record) => record.action_id === entry.action_id)}
              />
            ))}
          </div>
        </>
      ) : null}
    </Section>
  );
}

// 还没有处置的动作（原型 rc-verify 的 verifyCard）：状态、所属部门、输入依据与执行前快照
function PendingActionCard(props: { entry: UnfinishedAction }) {
  const entry = props.entry;
  return (
    <article className={`y10-rc-action ${UNFINISHED_CLASS[entry.status] ?? ""} is-pending`}>
      <header className="y10-rc-action-head">
        <StatusMark kind={UNFINISHED_KIND[entry.status] ?? "waiting"} text={label(ACTION_STATUS, entry.status)} />
        <Tag>未完成</Tag>
        <small className="y10-muted">{formatTime(entry.created_at)}</small>
      </header>
      <p className="y10-rc-action-sum">{purposeText(entry.purpose)}</p>
      <KeyValue
        items={[
          ["部门", departmentName(entry.department) || "没有在部门里执行"],
          ["工具", entry.tool],
          ["输入依据", entry.input_version === null ? "未上报" : `第 ${entry.input_version} 版`],
          ["执行前", artifactRefText(entry.before_snapshot_ref)],
          ["所在步骤", entry.step_id === null ? "未上报" : `第 ${entry.step_id} 步`],
        ]}
      />
      <p className="y10-note note">{PENDING_NOTE}</p>
    </article>
  );
}

// 已经处置的结果未知动作（原型 unknownCard）：处理方式、所在会话、执行前快照、交还给模型的内容，
// 以及这次处置的核实依据与结果
function HandledActionCard(props: {
  entry: UnknownAction;
  sessions: RecoverySession[];
  checks: VerificationRecord[];
}) {
  const entry = props.entry;
  const returned = entry.returned ?? "";
  return (
    <article className={`y10-rc-action is-unknown is-${entry.handling}`}>
      <header className="y10-rc-action-head">
        <StatusMark kind={handlingKind(entry.handling)} text={handlingText(entry.handling)} />
        <Tag>结果未知</Tag>
        <small className="y10-muted">{formatTime(entry.at)}</small>
      </header>
      <p className="y10-rc-action-sum">{purposeText(entry.purpose)}</p>
      <KeyValue
        items={[
          ["部门", departmentName(entry.department) || "没有在部门里执行"],
          ["会话", actionSessionText(props.sessions, entry.session_id)],
          ["工具", entry.tool],
          ["输入依据", entry.input_version === null ? "未上报" : `第 ${entry.input_version} 版`],
          ["执行前", artifactRefText(entry.before)],
        ]}
      />
      <p className="y10-note note">{handlingNote(entry.handling)}</p>
      {props.checks.length > 0 ? (
        <ul className="y10-rc-checks">
          {props.checks.map((check) => (
            <li key={check.event_id} className={check.decided_by === "user" ? "is-user" : ""}>
              <div><b>核实依据</b>{show(check.basis)}</div>
              <div><b>核实结果</b>{show(check.result)}</div>
              <small className="y10-muted">
                {formatTime(check.at)}{check.decided_by === "user" ? " · 用户决定" : ""}
              </small>
            </li>
          ))}
        </ul>
      ) : null}
      {returned !== "" ? (
        <>
          <h4 className="y10-h3 sub">交还给模型的内容</h4>
          <pre className="y10-pre raw">{returned}</pre>
        </>
      ) : null}
    </article>
  );
}

// 限额与会话的用量（原型 rc-limits 与 sessionsTable）：已用时间与时间上限来自事项的运行限制；
// 恢复不清零，用量未上报时显示未知。各会话的用量各自累计，部门主线与询问分支各一行
function LimitsBlock(props: { data: RunRecoveryResult; elapsed: number | null; limit: number | null }) {
  const limits = props.data.limits;
  const sessions = sessionUsageRows(props.data.sessions);
  return (
    <Section id="rc-limits" title="限额与会话的用量" note="恢复不清零；发送状态未知的尝试仍然占用；用量未上报时显示未知，不填零">
      <div className="y10-rc-limits">
        <div className="y10-rc-limit is-wide">
          <span>已用时间与时间上限</span>
          <strong>{formatDuration(props.elapsed)} / {formatDuration(props.limit)}</strong>
          {props.elapsed === null || props.limit === null || props.limit === 0 ? null : (
            <span
              className={`y10-meter${props.elapsed / props.limit >= 0.8 ? " is-warn" : ""}`}
              role="meter"
              aria-valuemin={0}
              aria-valuemax={props.limit}
              aria-valuenow={props.elapsed}
            >
              <span style={{ width: `${(Math.min(1, Math.max(0, props.elapsed / props.limit)) * 100).toFixed(1)}%` }} />
            </span>
          )}
        </div>
        <div className="y10-rc-limit">
          <span>已用的工作轮数</span>
          <strong>{limits.activations}</strong>
        </div>
        <div className="y10-rc-limit">
          <span>模型步骤</span>
          <strong>{limits.model_steps}</strong>
        </div>
        <div className="y10-rc-limit">
          <span>重试尝试</span>
          <strong>{limits.retries}</strong>
        </div>
        <div className="y10-rc-limit">
          <span>循环次数</span>
          <strong>{limits.cycle_count}</strong>
        </div>
      </div>
      {sessions.length > 0 ? (
        <>
          <h3 className="y10-h3 sub">各会话的用量</h3>
          <table className="y10-table rc-sessions">
            <thead>
              <tr>
                <th>会话</th>
                <th>已用时间</th>
                <th>工作轮数</th>
                <th>模型步骤</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((row) => (
                <tr key={row.key}>
                  <td>{row.label}</td>
                  <td>{formatDuration(row.elapsedSec)}</td>
                  <td>{row.activations}</td>
                  <td>{row.modelSteps}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
    </Section>
  );
}

// 执行所有权（原型 rc-owner）：当前执行者与取得时间；旧执行者的迟到回执作为历史事实列出，不推进状态
function OwnerBlock(props: { data: RunRecoveryResult }) {
  const owner = props.data.owner;
  const late = props.data.late_results;
  return (
    <Section id="rc-owner" title="执行所有权" note="同一时刻只有一个执行者；旧执行者的迟到回执不推进状态">
      <KeyValue
        items={owner === null
          ? [
            ["当前执行者", <span className="y10-muted" key="none">没有有效执行者</span>],
            ["执行槽位", <span className="y10-muted" key="slot">没有占用执行槽位</span>],
          ]
          : ownerRows(owner)}
      />
      {late.length > 0 ? (
        <>
          <h3 className="y10-h3 sub">迟到结果</h3>
          <p className="y10-note note">旧执行者的迟到回执作为历史事实列出，不推进状态。</p>
          <ul className="y10-rc-late">
            {late.map((entry) => (
              <li key={entry.event_id}>
                <span className="y10-muted">{formatTime(entry.at)}</span>
                <span>{entry.text}</span>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="y10-note note">没有迟到结果。</p>}
    </Section>
  );
}

function ownerRows(owner: RecoveryOwner): [string, React.ReactNode][] {
  return [
    ["当前执行者", `第 ${owner.epoch} 任执行者`],
    ["取得时间", formatTime(owner.since)],
    ["中断位置", interruptedAtText(owner)],
    ["执行槽位", owner.holds_slot ? "占用一个执行槽位" : "没有占用执行槽位"],
  ];
}
