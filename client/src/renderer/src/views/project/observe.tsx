// 观测页（原型 v8 设计说明第 7.4 节，工单 #80，需求 D21）：请求记录、用量统计与请求详情。
// 请求记录来自 project.attempts（筛选：事项、部门、状态、调用目标、模型、关键词；游标分页）；
// 用量统计来自 project.usage（总量与按部门、按模型的分组，未上报的写成「未上报」，不显示成预算）；
// 详情来自 run.attempt（调用目标与请求档位、按栏目的来源与放入原因、事件、工具、错误）。
// 页面只读这些已登记的查询，不用假数据补位。

import { useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  AttemptView,
  ProjectAttemptsResult,
  RunAttemptResult,
  UsageReport,
} from "../../api/generated/types.gen";
import type { Route } from "../../shell/routing";
import { paths } from "../../shell/routing";
import { Empty, KeyValue, Loading, Section, Table, dict, formatNumberOr, list, numberValue, optionalText, pageKey, show, text } from "./common";
import { ATTEMPT_STATUS, DEPARTMENTS, PHASE_LABELS, departmentName, formatTime, label } from "./labels";
import { useSnapshot } from "./use-snapshot";

const PAGE_SIZE = 50;

export type Filters = {
  department: string;
  status: string;
  provider: string;
  requestedModel: string;
  actualModel: string;
  q: string;
};

const EMPTY_FILTERS: Filters = { department: "", status: "", provider: "", requestedModel: "", actualModel: "", q: "" };

// 筛选条件转成查询参数：空值写成 null，由 useSnapshot 去掉（查询按省略处理）
export function filterParams(projectId: string, workItem: string | null, filters: Filters, limit: number): Record<string, unknown> {
  return {
    project_id: projectId,
    work_item: workItem || null,
    department: filters.department || null,
    status: filters.status || null,
    provider: trimOrNull(filters.provider),
    requested_model: trimOrNull(filters.requestedModel),
    actual_model: trimOrNull(filters.actualModel),
    q: trimOrNull(filters.q),
    limit,
  };
}

function trimOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

export function ObservePage(props: { app: ClientApp; route: Route }) {
  const projectId = props.route.projectId ?? "";
  const workItem = props.route.workItemId;
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [cursor, setCursor] = useState<string | null>(null);
  const params = filterParams(projectId, workItem, applied, PAGE_SIZE);
  const usageParams = { ...params, limit: undefined };
  const usage = useSnapshot<UsageReport>(props.app, "page.usage", "project.usage", usageParams);
  const attempts = useSnapshot<ProjectAttemptsResult>(
    props.app,
    cursor === null ? "page.attempts" : `page.attempts.${cursor}`,
    "project.attempts",
    { ...params, cursor },
  );
  // 游标分页：翻到的页累加起来；第一页的每次新快照（筛选、事项变化或事件到达）都用它替换已有行
  const [rows, setRows] = useState<AttemptView[]>([]);
  const loadedSnapshot = useRef<ProjectAttemptsResult | null>(null);
  if (attempts.data !== null && loadedSnapshot.current !== attempts.data) {
    loadedSnapshot.current = attempts.data;
    setRows(cursor === null ? attempts.data.attempts : [...rows, ...attempts.data.attempts]);
  }

  const filtersChanged = pageKey([draft]) !== pageKey([applied]);

  return (
    <div className="page">
      <Section title="请求记录" note={`范围：${workItem === null ? "整个项目" : `事项 ${workItem}`}；数据来自 project.attempts`}>
        <div className="filters">
          <label className="field">
            <span>部门</span>
            <select value={draft.department} onChange={(event) => setDraft({ ...draft, department: event.target.value })}>
              <option value="">全部</option>
              {Object.keys(DEPARTMENTS).map((key) => <option key={key} value={key}>{DEPARTMENTS[key].name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>状态</span>
            <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
              <option value="">全部</option>
              <option value="success">成功</option>
              <option value="running">进行中</option>
              <option value="failed">失败</option>
              <option value="cancelled">已取消</option>
            </select>
          </label>
          <label className="field">
            <span>关键词</span>
            <input type="search" value={draft.q} placeholder="模型、调用目标、事项等" onChange={(event) => setDraft({ ...draft, q: event.target.value })} />
          </label>
          <label className="field">
            <span>调用目标</span>
            <input type="text" value={draft.provider} onChange={(event) => setDraft({ ...draft, provider: event.target.value })} />
          </label>
          <label className="field">
            <span>请求的模型</span>
            <input type="text" value={draft.requestedModel} onChange={(event) => setDraft({ ...draft, requestedModel: event.target.value })} />
          </label>
          <label className="field">
            <span>实际的模型</span>
            <input type="text" value={draft.actualModel} onChange={(event) => setDraft({ ...draft, actualModel: event.target.value })} />
          </label>
          <button
            type="button"
            className="primary"
            onClick={() => { setApplied(draft); setCursor(null); }}
          >
            按条件筛选
          </button>
          {filtersChanged ? <p className="note">条件已改动，按「按条件筛选」以后生效</p> : null}
        </div>
        <Loading state={attempts} />
        {rows.length === 0 && !attempts.loading ? <Empty text="这个范围没有请求记录" /> : null}
        {rows.length > 0 ? (
          <Table
            head={["时间", "部门", "状态", "请求的模型", "实际的模型", "用时", "用量", ""]}
            rows={rows.map((item) => [
              formatTime(item.started_at ?? item.finished_at),
              departmentName(item.department),
              label(ATTEMPT_STATUS, item.status),
              show(item.requested_model),
              show(item.actual_model),
              formatNumberOr(item.duration_ms, " 毫秒"),
              usageBrief(dict(item.usage)),
              <button
                type="button"
                className="link"
                key={item.attempt_id}
                onClick={() => { window.location.hash = paths.observeDetail(projectId, item.attempt_id, { workItem, runId: item.run_id }); }}
              >
                详情
              </button>,
            ])}
          />
        ) : null}
        {attempts.data?.cursor ? (
          <button type="button" onClick={() => setCursor(attempts.data?.cursor ?? null)} disabled={attempts.loading}>
            {attempts.loading ? "正在加载" : "加载更多"}
          </button>
        ) : null}
        {attempts.data && attempts.data.cursor === null && rows.length > 0 ? <p className="note">已到最后一批</p> : null}
      </Section>
      <UsageSection usage={usage} />
    </div>
  );

  function usageBrief(usage: Record<string, unknown>): string {
    const total = numberValue(usage.total_tokens);
    const reported = usage.reported === true;
    if (!reported && total === null) {
      return "未上报";
    }
    return `${formatNumberOr(total, " token")}，输入 ${formatNumberOr(numberValue(usage.input_tokens))}，输出 ${formatNumberOr(numberValue(usage.output_tokens))}`;
  }
}

function UsageSection(props: { usage: { data: UsageReport | null; loading: boolean } }) {
  const data = props.usage.data;
  if (data === null) {
    return (
      <Section title="用量统计">
        <Loading state={props.usage} />
      </Section>
    );
  }
  const totals = dict(data.totals);

  return (
    <Section title="用量统计" note="只读显示，不显示成预算（第 7.4 节）">
      <KeyValue
        items={[
          ["请求数", `${formatNumberOr(numberValue(totals.attempts))}（上报 ${formatNumberOr(numberValue(totals.reported))}）`],
          ["输入 token", formatNumberOr(numberValue(totals.input_tokens), " token")],
          ["输出 token", formatNumberOr(numberValue(totals.output_tokens), " token")],
          ["缓存读取", formatNumberOr(numberValue(totals.cache_read_tokens), " token")],
          ["缓存写入", formatNumberOr(numberValue(totals.cache_write_tokens), " token")],
          ["合计 token", formatNumberOr(numberValue(totals.total_tokens), " token")],
          ["耗时", formatNumberOr(numberValue(totals.latency_ms), " 毫秒")],
          ["费用", totals.cost === null || totals.cost === undefined ? "未上报" : String(totals.cost)],
        ]}
      />
      <UsageGroups title="按部门" groups={data.departments} />
      <UsageGroups title="按模型" groups={data.models} />
    </Section>
  );
}

function UsageGroups(props: { title: string; groups: UsageReport["departments"] }) {
  if (props.groups.length === 0) {
    return <p className="note">{props.title}：没有上报的用量</p>;
  }
  return (
    <Table
      head={["名称", "请求数", "输入", "输出", "合计", "耗时"]}
      rows={props.groups.map((group) => [
        group.label || group.key,
        formatNumberOr(group.attempts),
        formatNumberOr(numberValue(group.input_tokens)),
        formatNumberOr(numberValue(group.output_tokens)),
        formatNumberOr(numberValue(group.total_tokens)),
        formatNumberOr(numberValue(group.latency_ms), " 毫秒"),
      ])}
      caption={props.title}
    />
  );
}

// 请求详情（run.attempt）：调用目标与档位、按栏目的来源与放入原因、事件、工具、错误
export function ObserveDetailPage(props: { app: ClientApp; route: Route }) {
  const attemptId = props.route.attemptId ?? "";
  const workItem = props.route.workItemId;
  const projectId = props.route.projectId ?? "";
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
      <Section title="请求详情" note={`请求标识 ${attemptId}，数据来自 run.attempt`}>
        <p>
          <button
            type="button"
            className="link"
            onClick={() => { window.location.hash = paths.observe(projectId) + (workItem ? `?w=${workItem}` : ""); }}
          >
            返回请求记录
          </button>
        </p>
        <Loading state={detail} />
        <Loading state={lookup} />
        {runId === null && attemptId !== "" ? <Empty text="这个请求标识在本项目里找不到，请从请求记录点「详情」进入" /> : null}
        {data ? <AttemptDetail data={data} projectId={projectId} attemptId={attemptId} /> : null}
      </Section>
    </div>
  );
}

function AttemptDetail(props: { data: RunAttemptResult; projectId: string; attemptId: string }) {
  const attempt = dict(props.data.attempt);
  const context = props.data.context === null ? null : dict(props.data.context);
  const manifest = context === null ? null : dict(context.manifest);
  const parts = context === null ? [] : list(context.parts);
  const scope = dict(attempt.observed_scope);
  const siblings = list(props.data.siblings);
  const events = list(props.data.events);
  const tools = list(props.data.tools);
  const refs = dict(props.data.artifact_refs);

  return (
    <>
      <KeyValue
        items={[
          ["状态", `${label(ATTEMPT_STATUS, text(attempt.status))}${attempt.stage ? ` · 阶段 ${text(attempt.stage)}` : ""}`],
          ["调用目标", `${show(optionalText(attempt.provider))}（请求 ${show(optionalText(attempt.requested_provider))}，实际 ${show(optionalText(attempt.actual_provider))}）`],
          ["模型", `请求 ${show(optionalText(attempt.requested_model))}，实际 ${show(optionalText(attempt.actual_model))}`],
          ["协议与档位", `请求 ${show(optionalText(attempt.requested_tier))}，实际发送 ${show(optionalText(attempt.sent_tier))}`],
          ["部门 Prompt 版本", attempt.prompt_version === null || attempt.prompt_version === undefined ? "未上报" : `第 ${String(attempt.prompt_version)} 版`],
          ["第几步 / 第几次尝试", `${show(optionalText(attempt.step))} / ${show(optionalText(attempt.attempt))}`],
          ["开始与结束", `${formatTime(optionalText(attempt.started_at))} → ${formatTime(optionalText(attempt.finished_at))}（${formatNumberOr(numberValue(attempt.duration_ms), " 毫秒")}）`],
          ["用量", text(attempt.usage) === "" ? "未上报" : JSON.stringify(attempt.usage)],
          ["运行限制", `收集范围 ${show(optionalText(scope.max_items) ?? optionalText(scope.mode), "未上报")}；输出条目 ${show(optionalText(attempt.output_item_count), "未上报")}`],
          ["错误", show(optionalText(attempt.error), "没有"),],
          ["是否可重试", attempt.retryable === true ? "是" : attempt.retryable === false ? "否" : "未上报"],
          ["引用", `请求 ${show(optionalText(refs.request))}，响应 ${show(optionalText(refs.response))}，原始流 ${show(optionalText(refs.events))}，用量 ${show(optionalText(refs.usage))}`],
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
      ) : <p className="note">这一次请求没有记录上下文的栏目</p>}
      {manifest !== null ? (
        <p className="note">
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
        <pre className="raw">{JSON.stringify(props.data.request, null, 2)}</pre>
      ) : <p className="note">请求内容没有记录</p>}
      {props.data.response !== null && props.data.response !== undefined ? (
        <pre className="raw">{JSON.stringify(props.data.response, null, 2)}</pre>
      ) : <p className="note">响应内容没有记录</p>}
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
      <p className="note">
        阶段名称按 {label(PHASE_LABELS, "PRODUCT_SPEC")} 等取值；详情页的路径是 {paths.observeDetail(props.projectId, props.attemptId)}
      </p>
    </>
  );
}
