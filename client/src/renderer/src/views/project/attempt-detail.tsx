// 请求详情（原型 v8 设计说明第 7.4 节；工单 #1710 从观测页搬出，原工单 #80、#744、#814）：一次模型请求的调用目标与档位、
// 按栏目的来源与放入原因、事件、工具与错误，以及「导出这次运行」。
// 从设置页「模型请求与用量」的请求记录、对话页工作过程的某一步点进来；
// 返回的去处由调用处给出（shell/routing.ts 的 attemptBackPath）：
// 回到进来时的那一节或那一页，设置页那一节回来时仍展开、筛选不变。

import { useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type { ProjectAttemptsResult, ProjectOverviewResult, RunAttemptResult } from "../../api/generated/types.gen";
import type { Route } from "../../shell/routing";
import { artifactRefsRow } from "./artifact-ref";
import { failureRows } from "./attempt-failure";
import {
  Empty, KeyValue, Loading, Section, Table, dict, formatNumberOr, list, numberValue, optionalText, show, text,
} from "./common";
import { ATTEMPT_STATUS, formatTime, label } from "./labels";
import { useSnapshot } from "./use-snapshot";
import { usageText } from "./usage-text";
import { downloadRunExport } from "./run-export";
import { scopeName } from "./scope-name";

const PAGE_SIZE = 50;

// 用量的显示见 usage-text.ts：请求记录表、请求详情与用量统计说的是同一件事，
// 表格列与详情行由同一个函数算出（工单 #301、#744）
// 选择来源的显示（设计说明第 5.3、7.4 节）：提供模型访问定义的那一层。
// 取值由 Provider 模块给出（department_default / project_department_setting），未知值原样显示
function selectionSourceName(value: string | null): string {
  if (value === "department_default") {
    return "职能默认";
  }
  if (value === "project_department_setting") {
    return "项目设置";
  }
  return show(value);
}

// 调用目标的显示（设计说明第 7.4 节）：连接、协议、地址、上游模型、容量、凭据引用与版本。
// 字段取自请求事件的调用目标公开部分（不含 Key）；解析尚未确定的项写成「未上报」
function callTargetText(target: Record<string, unknown>): string {
  const parts = [
    `连接 ${show(optionalText(target.provider_name))}`,
    `协议 ${show(optionalText(target.protocol))}`,
    `地址 ${show(optionalText(target.base_url))}`,
    `上游模型 ${show(optionalText(target.requested_model))}`,
    `窗口 ${formatNumberOr(numberValue(target.context_window), " token")}`,
    `凭据引用 ${show(optionalText(target.credential_ref))}`,
  ];
  return parts.join("，");
}

// 请求详情页：请求标识来自地址，run 标识写在 ?r= 里（刷新、后退以后仍能直接读取）；
// back 是返回的去处与文案，由进来时的地址决定
export function AttemptDetailPage(props: { app: ClientApp; route: Route; back: { label: string; hash: string } }) {
  const attemptId = props.route.attemptId ?? "";
  const workItem = props.route.workItemId;
  const projectId = props.route.projectId ?? "";
  // 范围里是哪个事项：导出的文件名用它（工单 #814），与页面其余地方同一份数据
  const scope = useSnapshot<ProjectOverviewResult>(props.app, "page.observe.scope", "project.overview", {
    project_id: projectId,
  });
  const scopeTitle = scopeName(scope.data?.work_items ?? [], workItem);
  // 路径里带了 run 标识时直接读取；只输入请求标识时用列表按 attempt_id 找回所属的 run
  const lookup = useSnapshot<ProjectAttemptsResult>(
    props.app, `page.attempt.run.${attemptId}`, "project.attempts",
    { project_id: projectId, work_item: workItem, limit: PAGE_SIZE },
    props.route.runId !== null || attemptId === "",
  );
  const runId = props.route.runId ?? (lookup.data?.attempts.find((item) => item.attempt_id === attemptId)?.run_id ?? null);
  const detail = useSnapshot<RunAttemptResult>(
    props.app, `page.attempt.${attemptId}`, "run.attempt",
    { run_id: runId ?? "", attempt_id: attemptId },
    runId === null,
  );
  const data = detail.data;

  return (
    <div className="page">
      <Section title="请求详情" note={`请求标识 ${attemptId}`}>
        <p>
          <button
            type="button"
            className="y10-link link"
            onClick={() => { window.location.hash = props.back.hash; }}
          >
            {props.back.label}
          </button>
        </p>
        <Loading state={detail} />
        <Loading state={lookup} />
        {runId === null && attemptId !== "" ? <Empty text="这个请求标识在本项目里找不到，请从请求记录点「详情」进入" /> : null}
        {data ? <AttemptDetail app={props.app} data={data} projectId={projectId} attemptId={attemptId} workItemTitle={scopeTitle === "" ? null : scopeTitle} /> : null}
      </Section>
    </div>
  );
}

// 观测详情里的「导出这次运行」（工单 #814）：按需读取 run.export，整包下载为 JSON 文件。
// 状态只管两件事：导出进行中禁用按钮，失败把原因写出来；成功不再显示提示，
// 文件本身就是导出的结果（浏览器自己的下载提示在那里）。
function useRunExport(app: ClientApp, runId: string | null, workItemTitle: string | null) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const exportRun = async () => {
    if (runId === null || busy) {
      return;
    }
    setBusy(true);
    setFailure(null);
    const outcome = await downloadRunExport(app, runId, workItemTitle);
    setBusy(false);
    if (!outcome.ok) {
      setFailure(outcome.reason);
    }
  };
  return { busy, failure, exportRun };
}

function AttemptDetail(props: { app: ClientApp; data: RunAttemptResult; projectId: string; attemptId: string; workItemTitle: string | null }) {
  const attempt = dict(props.data.attempt);
  const context = props.data.context === null ? null : dict(props.data.context);
  const manifest = context === null ? null : dict(context.manifest);
  const parts = context === null ? [] : list(context.parts);
  const scope = dict(attempt.observed_scope);
  const siblings = list(props.data.siblings);
  const events = list(props.data.events);
  const tools = list(props.data.tools);
  const refs = dict(props.data.artifact_refs);
  // 调用目标的公开部分（不含 Key）、选择来源与请求/实际发送的档位（设计说明第 6 节）
  const callTarget = dict(attempt.call_target);
  // 失败类型与结束原因（工单 #305）：取值规则抽在 attempt-failure.ts，便于单元测试核对
  const failure = failureRows(attempt);
  // 导出这次运行的证据（工单 #814）：整包是 run.export 给出的那一份
  const runId = text(attempt.run_id) || null;
  const runExport = useRunExport(props.app, runId, props.workItemTitle);

  return (
    <>
      <p>
        {runId !== null ? (
          <button
            type="button"
            className="y10-btn"
            disabled={runExport.busy}
            onClick={() => { void runExport.exportRun(); }}
          >
            {runExport.busy ? "正在导出" : "导出这次运行"}
          </button>
        ) : null}
        {runExport.failure !== null ? <span className="y10-note note"> 导出失败：{runExport.failure}</span> : null}
      </p>
      <KeyValue
        items={[
          ["状态", `${label(ATTEMPT_STATUS, text(attempt.status))}${attempt.stage ? ` · 阶段 ${text(attempt.stage)}` : ""}`],
          // 调用目标：连接、协议、地址、上游模型、容量、凭据引用与版本、选择来源（第 7.4 节）
          ["调用目标", callTargetText(callTarget)],
          ["选择来源", selectionSourceName(optionalText(callTarget.selection_source))],
          ["模型", `请求 ${show(optionalText(attempt.requested_model))}，实际 ${show(optionalText(attempt.actual_model))}`],
          ["协议与档位", `请求 ${show(optionalText(callTarget.requested_tier))}，实际发送 ${show(optionalText(callTarget.sent_tier))}`],
          ["职能设置版本", attempt.prompt_version === null || attempt.prompt_version === undefined ? "未上报" : `第 ${String(attempt.prompt_version)} 版`],
          ["第几步 / 第几次尝试", `${show(optionalText(attempt.step))} / ${show(optionalText(attempt.attempt))}`],
          ["开始与结束", `${formatTime(optionalText(attempt.started_at))} → ${formatTime(optionalText(attempt.finished_at))}（${formatNumberOr(numberValue(attempt.duration_ms), " 毫秒")}）`],
          ["用量", usageText(dict(attempt.usage))],
          ["运行限制", `收集范围 ${show(optionalText(scope.max_items) ?? optionalText(scope.mode), "未上报")}；输出条目 ${show(optionalText(attempt.output_item_count), "未上报")}`],
          ...failure,
          ["错误", show(optionalText(attempt.error), "没有"),],
          ["是否可重试", attempt.retryable === true ? "是" : attempt.retryable === false ? "否" : "未上报"],
          // 工件引用是对象，页面按实际情况给出可核对的标识（工单 #745）
          artifactRefsRow(refs),
        ]}
      />
      {parts.length > 0 ? (
        <Table
          head={["栏目", "版本", "放入原因"]}
          rows={parts.map((part) => [
            text(part.source) || "未命名",
            show(optionalText(part.version)),
            show(optionalText(part.reason), "未写明"),
          ])}
          caption="按栏目的上下文"
        />
      ) : <p className="y10-note note">这一次请求没有记录上下文的栏目</p>}
      {manifest !== null ? (
        <p className="y10-note note">
          清单：估算 {formatNumberOr(numberValue(manifest.token_estimate), " token")} / 上限 {formatNumberOr(numberValue(manifest.budget), " token")}，
          排除 {list(manifest.excluded).length} 项，压缩 {show(optionalText(manifest.compaction_event_id), "无")}
        </p>
      ) : null}
      {siblings.length > 0 ? (
        <Table
          head={["第几次尝试", "状态", "开始", "结束", "错误"]}
          rows={siblings.map((sibling) => [
            show(optionalText(sibling.attempt)),
            label(ATTEMPT_STATUS, text(sibling.status)),
            formatTime(optionalText(sibling.started_at)),
            formatTime(optionalText(sibling.finished_at)),
            show(optionalText(sibling.error), "无"),
          ])}
          caption="同一次逻辑调用的其他尝试"
        />
      ) : null}
      {props.data.request !== null && props.data.request !== undefined ? (
        <pre className="y10-pre raw">{JSON.stringify(props.data.request, null, 2)}</pre>
      ) : <p className="y10-note note">请求内容没有记录</p>}
      {props.data.response !== null && props.data.response !== undefined ? (
        <pre className="y10-pre raw">{JSON.stringify(props.data.response, null, 2)}</pre>
      ) : <p className="y10-note note">响应内容没有记录</p>}
      {events.length > 0 ? (
        <Table
          head={["种类", "时间", "说明"]}
          rows={events.map((event) => [
            text(event.type) || "未写明",
            formatTime(optionalText(event.created_at)),
            show(optionalText(event.label) ?? optionalText(event.summary), "无"),
          ])}
          caption="事件"
        />
      ) : null}
      {tools.length > 0 ? (
        <Table
          head={["工具", "成功", "错误"]}
          rows={tools.map((entry) => [
            text(entry.name) || "未写明",
            entry.ok === true ? "是" : entry.ok === false ? "否" : "未上报",
            show(optionalText(entry.error), "无"),
          ])}
          caption="工具调用"
        />
      ) : null}
    </>
  );
}
