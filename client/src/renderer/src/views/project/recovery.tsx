// 恢复与动作核实页（原型 v10 设计说明第 7.2 节，工单 #380）：只读显示一个事项的恢复观察状态、
// 待恢复原因与修复入口、等待回答的决定请求、未完成动作与核实记录、限额、执行所有权与迟到结果。
// 数据只来自 run.recovery、decisions.list、project.loop 与 project.overview 四个已登记的查询；
// 状态迁移由控制层决定，页面不做任何推进，也不显示按钮声称能继续。
// 因升级停止（原型 rc-upgrade）在 run.recovery 里没有对应的取值，本页不显示这一块。

import type {
  DecisionList,
  ProjectLoopResult,
  ProjectOverviewResult,
  RunRecoveryResult,
  UnfinishedAction,
  VerificationRecord,
  WorkItemCard,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import type { Route } from "../../shell/routing";
import { StatusMark } from "../../shell/kit";
import { DecisionCardList } from "../decisions/card";
import { Empty, KeyValue, Loading, Section, Tag, show } from "./common";
import { ACTION_STATUS, RECOVERY_STATE, STOP_REASON, departmentName, formatDuration, formatTime, label } from "./labels";
import { RestartOnboarding } from "./restart-onboarding";
import { useSnapshot } from "./use-snapshot";
import { readFailureText } from "../../contract/read-failure";

// 恢复观察状态对应的原型标记（原型 v10 views/recovery.js 的 STATE_KIND）
const STATE_KIND: Record<string, string> = {
  running: "running",
  interrupted: "interrupted",
  waiting_resume: "waiting",
  terminated: "cancelled",
};

// 动作状态对应的原型标记（原型 v10 views/recovery.js 的 ACTION_KIND）；
// 已完成不是未完成动作的状态，界面按核实结果给出，不在这一张表里
const ACTION_KIND: Record<string, string> = {
  not_sent: "pending",
  unknown: "unknown",
};

// 动作状态对应的样式（原型 v10 views/recovery.js 的 ACTION_CLASS）
const ACTION_CLASS: Record<string, string> = {
  not_sent: "is-not_sent",
  unknown: "is-unknown",
};

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
            note="主机无法确定结果或需要修复入口时，由这里的卡片交给你"
            className="y10-rc-decide-block"
          >
            <Loading state={decisions} />
            <DecisionCardList
              app={props.app}
              decisions={decisions.data?.decisions ?? []}
              now={now}
              names={() => ({ projectName: projectId, workItemTitle: title })}
              onNavigate={props.onNavigate}
              viewId="recovery.decisions"
              emptyText="没有等待你回答的决定"
            />
          </Section>
          <VerifyBlock data={data} />
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

// 恢复观察状态（原型 rc-state）：五种状态按原型排成一排，当前一项用原型标记显示
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
              ? <StatusMark kind={STATE_KIND[state]} text={label(RECOVERY_STATE, state)} />
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

// 待恢复原因、中断位置与已终止（原型 rc-reason）：按状态给出不同内容。
// 已终止的 run 不再继续，未完成动作不由恢复处理，只显示终止原因与所在部门
function ReasonBlock(props: { data: RunRecoveryResult; item: WorkItemCard | null }) {
  const data = props.data;
  if (data.state === "waiting_resume") {
    const unusable = data.unusable;
    if (unusable === null) {
      throw new Error("待恢复状态没有给出待恢复原因");
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
            ["最后已确认", data.last_confirmed_event_id ?? `第 ${data.last_confirmed_position} 条事件`],
            ["自动继续时间", <span className="y10-muted" key="at">还没有自动继续</span>],
          ]}
        />
        <p className="y10-note note">按持久事实核对：没有未完成动作时自动继续。</p>
      </Section>
    );
  }
  if (data.state === "terminated") {
    const item = props.item;
    return (
      <Section id="rc-reason" title="已终止" className="y10-rc-reason-block">
        <KeyValue
          items={[
            ["停止原因", item?.stop_reason ? label(STOP_REASON, item.stop_reason) : "未上报"],
            ["所在部门", item?.department ? departmentName(item.department) : "没有在部门里执行"],
          ]}
        />
        <p className="y10-note note">已终止的执行不再继续；未完成动作不由恢复处理。</p>
      </Section>
    );
  }
  return null;
}

// 动作核实（原型 rc-verify）：未完成动作与核实记录；核实结果追加到记录，原始观察不改写
function VerifyBlock(props: { data: RunRecoveryResult }) {
  const actions = props.data.unfinished_actions;
  const records = props.data.verifications;
  return (
    <Section
      id="rc-verify"
      title="动作核实"
      note="未完成动作与核实记录；核实结果追加到记录，原始观察不改写"
    >
      {actions.length === 0
        ? <Empty text="没有未完成的动作：所有动作都有回执" />
        : (
          <div className="y10-rc-actions">
            {actions.map((entry) => (
              <ActionCard
                key={entry.action_id}
                entry={entry}
                checks={records.filter((record) => record.action_id === entry.action_id)}
              />
            ))}
          </div>
        )}
      {records.length > 0 ? (
        <>
          <h3 className="y10-h3 sub">核实记录</h3>
          <ul className="y10-rc-checks">
            {records.map((record) => (
              <li key={record.event_id} className={record.decided_by === "user" ? "is-user" : ""}>
                <div><b>动作</b><code className="y10-code">{record.action_id}</code></div>
                <div><b>核实依据</b>{show(record.basis)}</div>
                <div><b>核实结果</b>{show(record.result)}</div>
                <small className="y10-muted">
                  {formatTime(record.at)}{record.decided_by === "user" ? " · 用户决定" : ""}
                </small>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Section>
  );
}

// 一个未完成动作（原型 rc-verify 的 verifyCard）：状态、动作身份、所属部门、输入依据与所在步骤
function ActionCard(props: { entry: UnfinishedAction; checks: VerificationRecord[] }) {
  const entry = props.entry;
  return (
    <article className={`y10-rc-action ${ACTION_CLASS[entry.status]} is-pending`}>
      <header className="y10-rc-action-head">
        <StatusMark kind={ACTION_KIND[entry.status]} text={label(ACTION_STATUS, entry.status)} />
        <code className="y10-code">{entry.action_id}</code>
        <Tag>未完成</Tag>
      </header>
      <p className="y10-rc-action-sum">{show(entry.purpose, `${entry.tool} 动作`)}</p>
      <KeyValue
        items={[
          ["部门", departmentName(entry.department)],
          ["工具", entry.tool],
          ["输入依据", entry.input_version === null ? "未上报" : `第 ${entry.input_version} 版`],
          ["所在步骤", entry.step_id === null ? "未上报" : `第 ${entry.step_id} 步`],
        ]}
      />
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
    </article>
  );
}

// 限额（原型 rc-limits）：已用时间与时间上限来自事项的运行限制；恢复不清零，用量未上报时显示未知
function LimitsBlock(props: { data: RunRecoveryResult; elapsed: number | null; limit: number | null }) {
  const limits = props.data.limits;
  return (
    <Section id="rc-limits" title="限额" note="恢复不清零；发送状态未知的尝试仍然占用；用量未上报时显示未知，不填零">
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
          <span>已用激活次数</span>
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
          : [
            ["当前执行者", `第 ${owner.epoch} 任执行者`],
            ["取得时间", formatTime(owner.since)],
            ["执行槽位", owner.holds_slot
              ? "占用一个执行槽位"
              : <span className="y10-muted" key="slot">没有占用执行槽位</span>],
          ]}
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
