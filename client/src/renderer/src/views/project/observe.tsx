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
  ProjectOverviewResult,
  RunAttemptResult,
  UsageReport,
} from "../../api/generated/types.gen";
import { paths, type Route } from "../../shell/routing";
import { PageHead } from "../../shell/kit";
import { artifactRefsRow } from "./artifact-ref";
import { failureRows } from "./attempt-failure";
import { attemptsSummary } from "./attempts-summary";
import { Empty, KeyValue, Loading, Section, Table, Tabs, dict, formatNumberOr, list, numberValue, optionalText, pageKey, show, text } from "./common";
import { ATTEMPT_STATUS, DEPARTMENTS, departmentName, formatTime, label } from "./labels";
import { useSnapshot } from "./use-snapshot";
import { reportedCountText, usageText } from "./usage-text";
import { readFailureText } from "../../contract/read-failure";
import { scopeName } from "./scope-name";
import { EMPTY_FILTERS, type Filters, departmentFilterNote, seedFilters } from "./observe-filter";

const PAGE_SIZE = 50;

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

// 部门这一格写回地址（工单 #801）：地址里写的与页面上生效的始终是同一件事，
// 刷新、后退与分享链接都对得上。地址没有变化时不写，地址栏里不多一条历史。
function writeDepartment(projectId: string, workItem: string | null, department: string): void {
  const target = paths.observe(projectId, { workItem, department: department || null });
  if (window.location.hash !== target) {
    window.location.hash = target;
  }
}

// 选择来源的显示（设计说明第 5.3、7.4 节）：提供模型访问定义的那一层。
// 取值由 Provider 模块给出（department_default / project_department_setting），未知值原样显示
function selectionSourceName(value: string | null): string {
  if (value === "department_default") {
    return "部门默认";
  }
  if (value === "project_department_setting") {
    return "项目设置";
  }
  return show(value);
}

// 用量的显示见 usage-text.ts：请求记录表、请求详情与用量统计说的是同一件事，
// 表格列与详情行由同一个函数算出（工单 #301、#744）
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

export function ObservePage(props: { app: ClientApp; route: Route }) {
  const projectId = props.route.projectId ?? "";
  const workItem = props.route.workItemId;
  // 部门这一格筛选条件由地址给出（?dept=，工单 #801）：部门工作间的「本部门的模型请求」
  // 带它进来，观测页自己换条件时地址跟着改；进入页面时的初值就是它
  const department = props.route.departmentFilter;
  const [draft, setDraft] = useState<Filters>(() => seedFilters(department));
  const [applied, setApplied] = useState<Filters>(() => seedFilters(department));
  // 地址里的部门变了（后退、前进、别的页面带进来）：下拉里的初值与已生效的筛选都跟着变
  const lastDepartment = useRef(department);
  if (lastDepartment.current !== department) {
    lastDepartment.current = department;
    const value = department ?? "";
    setDraft((prev) => (prev.department === value ? prev : { ...prev, department: value }));
    setApplied((prev) => (prev.department === value ? prev : { ...prev, department: value }));
  }
  const [tab, setTab] = useState<"records" | "usage">("records");
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
  // 范围里是哪个事项：用事项的名字说明，不显示事项标识（工单 #746）
  const scope = useSnapshot<ProjectOverviewResult>(props.app, "page.observe.scope", "project.overview", {
    project_id: projectId,
  });
  const scopeTitle = scopeName(scope.data?.work_items ?? [], workItem);
  // 游标分页：翻到的页累加起来；第一页的每次新快照（筛选、事项变化或事件到达）都用它替换已有行
  const [rows, setRows] = useState<AttemptView[]>([]);
  const loadedSnapshot = useRef<ProjectAttemptsResult | null>(null);
  if (attempts.data !== null && loadedSnapshot.current !== attempts.data) {
    loadedSnapshot.current = attempts.data;
    setRows(cursor === null ? attempts.data.attempts : [...rows, ...attempts.data.attempts]);
  }

  const filtersChanged = pageKey([draft]) !== pageKey([applied]);
  const inFlight = rows.filter((item) => item.status === "running" || item.status === "requesting").length;
  // 当前筛选的是哪个部门：页面上说明一句（中文名，不出现内部标识）
  const departmentNote = departmentFilterNote(applied.department);

  // 按条件筛选：页面内的一组条件一起生效。部门这一格同时写回地址，
  // 地址里写的与页面上生效的始终是同一件事（工单 #801）
  const applyFilters = () => {
    setApplied(draft);
    setCursor(null);
    writeDepartment(projectId, workItem, draft.department);
  };

  // 清除筛选：条件全部清空，地址里的部门也去掉
  const clearFilters = () => {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setCursor(null);
    writeDepartment(projectId, workItem, "");
  };

  return (
    <div className="page y10-obs">
      <PageHead
        eyebrow={`观测 · ${workItem === null ? "整个项目" : "事项范围"}`}
        title="模型请求"
        subtitle={attemptsSummary({
          inFlight,
          total: usage.data === null ? null : usage.data.totals.attempts,
          totalError: usage.error,
          loaded: rows.length,
          more: attempts.data !== null && attempts.data.cursor !== null,
        })}
      />
      <Section
        id="obs-requests"
        title="请求记录与用量"
        note={`范围：${workItem === null ? "整个项目" : scopeTitle === "" ? "顶栏选中的事项" : scopeTitle}${departmentNote === "" ? "" : `；${departmentNote}`}；按部门、状态、Provider 与模型筛选；两个页签使用同一组筛选。`}
        className="y10-obs"
      >
        <div className="y10-obs-filters filters">
          <label className="y10-obs-filter field">
            <span>部门</span>
            <select className="y10-select" value={draft.department} onChange={(event) => setDraft({ ...draft, department: event.target.value })}>
              <option value="">全部</option>
              {Object.keys(DEPARTMENTS).map((key) => <option key={key} value={key}>{DEPARTMENTS[key].name}</option>)}
            </select>
          </label>
          <label className="y10-obs-filter field">
            <span>状态</span>
            <select className="y10-select" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
              <option value="">全部</option>
              <option value="success">成功</option>
              <option value="running">进行中</option>
              <option value="failed">失败</option>
              <option value="cancelled">已取消</option>
            </select>
          </label>
          <label className="y10-obs-filter is-search field">
            <span>关键词</span>
            <input className="y10-input" type="search" value={draft.q} placeholder="模型、调用目标、事项等" onChange={(event) => setDraft({ ...draft, q: event.target.value })} />
          </label>
          <label className="y10-obs-filter field">
            <span>Provider 配置</span>
            <input className="y10-input" type="text" value={draft.provider} onChange={(event) => setDraft({ ...draft, provider: event.target.value })} />
          </label>
          <label className="y10-obs-filter field">
            <span>请求的模型</span>
            <input className="y10-input" type="text" value={draft.requestedModel} onChange={(event) => setDraft({ ...draft, requestedModel: event.target.value })} />
          </label>
          <label className="y10-obs-filter field">
            <span>实际的模型</span>
            <input className="y10-input" type="text" value={draft.actualModel} onChange={(event) => setDraft({ ...draft, actualModel: event.target.value })} />
          </label>
          <button
            type="button"
            className="y10-btn primary"
            onClick={applyFilters}
          >
            按条件筛选
          </button>
          {pageKey([applied]) !== pageKey([EMPTY_FILTERS]) ? (
            <button
              type="button"
              className="y10-link y10-obs-reset link"
              onClick={clearFilters}
            >
              清除筛选
            </button>
          ) : null}
          {filtersChanged ? <p className="y10-note note">条件已改动，按「按条件筛选」以后生效</p> : null}
        </div>
        <Tabs
          items={[{ id: "records", label: "请求记录" }, { id: "usage", label: "用量统计" }]}
          active={tab}
          onPick={(id) => setTab(id === "usage" ? "usage" : "records")}
        />
        {tab === "records" ? (
          <RecordsPanel
            projectId={projectId}
            rows={rows}
            workItem={workItem}
            department={applied.department}
            loading={attempts.loading}
            cursor={attempts.data?.cursor ?? null}
            onMore={() => setCursor(attempts.data?.cursor ?? null)}
          />
        ) : <UsageSection usage={usage} />}
      </Section>
    </div>
  );
}

// 请求记录面板：列按原型 v10 的「请求记录」页签排布（开始、状态、耗时、部门、请求、返回、请求类型、用量）；
// 请求与返回的模型分开列出，用量的显示与请求详情同一口径（工单 #744：同一页三处说法不同）
function RecordsPanel(props: {
  projectId: string;
  rows: AttemptView[];
  workItem: string | null;
  // 当前生效的部门筛选条件：进请求详情时带着，回来以后还是同一组筛选（工单 #801）
  department: string;
  loading: boolean;
  cursor: string | null;
  onMore: () => void;
}) {
  return (
    <>
      <p className="y10-note note">用量与请求详情同一口径：报了总量写「总 X token」，没报的那几项写「未上报」；一次都没有上报时写「未上报」，不填 0。请求与返回的模型分开列出。</p>
      {props.rows.length === 0 && !props.loading ? <Empty text="这个范围没有请求记录" /> : null}
      {props.rows.length > 0 ? (
        <Table
          head={["开始", "状态", "耗时", "部门", "请求", "返回", "请求类型", "用量", ""]}
          rows={props.rows.map((item) => {
            const usage = dict(item.usage);
            return [
              formatTime(item.started_at ?? item.finished_at),
              label(ATTEMPT_STATUS, item.status),
              item.status === "prepared" || item.status === "requesting" || item.status === "running"
                ? "进行中"
                : formatNumberOr(item.duration_ms, " 毫秒"),
              departmentName(item.department),
              show(item.requested_model, "未知"),
              show(item.actual_model, "未知"),
              item.purpose === "work" ? "工作请求" : item.purpose === "compaction" ? "压缩请求" : show(item.purpose, ""),
              usageText(usage),
              <button
                type="button"
                className="y10-link link"
                key={item.attempt_id}
                onClick={() => { window.location.hash = paths.observeDetail(props.projectId, item.attempt_id, { workItem: props.workItem, runId: item.run_id, department: props.department || null }); }}
              >
                详情
              </button>,
            ];
          })}
        />
      ) : null}
      {props.cursor ? (
        <button type="button" onClick={props.onMore} disabled={props.loading}>
          {props.loading ? "正在加载" : "加载更多"}
        </button>
      ) : null}
      {props.cursor === null && props.rows.length > 0 ? <p className="y10-note note">已到最后一批</p> : null}
    </>
  );
}

function UsageSection(props: { usage: { data: UsageReport | null; loading: boolean; error: string | null } }) {
  const data = props.usage.data;
  if (data === null) {
    return (
      <div className="y10-usage">
        {props.usage.error !== null ? (
          // 用量统计读不出来：说读不出来，不安静地少一句数字（工单 #775）
          <p className="y10-note note" role="status">{readFailureText(props.usage.error)}</p>
        ) : (
          <Loading state={props.usage} />
        )}
      </div>
    );
  }
  const totals = dict(data.totals);

  return (
    <div className="y10-usage">
      <h3>用量统计</h3>
      <p className="y10-usage-note note">「上报用量的请求」按当前筛选范围统计，请求记录一页 50 条、可以加载更多；输入（含缓存）与缓存读取（输入子集）不重复相加；用量只读显示，不是事项的预算</p>
      <KeyValue
        items={[
          ["请求数", formatNumberOr(numberValue(totals.attempts))],
          ["上报用量的请求", reportedCountText(totals.reported)],
          ["输入（含缓存）", formatNumberOr(numberValue(totals.input_tokens), " token")],
          ["输出", formatNumberOr(numberValue(totals.output_tokens), " token")],
          ["缓存读取（输入子集）", formatNumberOr(numberValue(totals.cache_read_tokens), " token")],
          ["总 Token", formatNumberOr(numberValue(totals.total_tokens), " token")],
          ["成本", totals.cost === null || totals.cost === undefined ? "未上报" : String(totals.cost)],
        ]}
      />
      <UsageGroups title="按部门" groups={data.departments} />
      <UsageGroups title="按模型" groups={data.models} />
    </div>
  );
}

function UsageGroups(props: { title: string; groups: UsageReport["departments"] }) {
  if (props.groups.length === 0) {
    return <p className="y10-note note">{props.title}：没有上报的用量</p>;
  }
  return (
    <Table
      head={["名称", "请求数", "上报用量的请求", "输入（含缓存）", "输出", "总 Token", "成本"]}
      rows={props.groups.map((group) => [
        group.label || group.key,
        formatNumberOr(group.attempts),
        reportedCountText(group.reported),
        formatNumberOr(numberValue(group.input_tokens)),
        formatNumberOr(numberValue(group.output_tokens)),
        formatNumberOr(numberValue(group.total_tokens)),
        group.cost === null || group.cost === undefined ? "未上报" : String(group.cost),
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
      <Section title="请求详情" note={`请求标识 ${attemptId}`}>
        <p>
          <button
            type="button"
            className="y10-link link"
            onClick={() => { window.location.hash = paths.observe(projectId, { workItem, department: props.route.departmentFilter }); }}
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
  // 调用目标的公开部分（不含 Key）、选择来源与请求/实际发送的档位（设计说明第 6 节）
  const callTarget = dict(attempt.call_target);
  // 失败类型与结束原因（工单 #305）：取值规则抽在 attempt-failure.ts，便于单元测试核对
  const failure = failureRows(attempt);

  return (
    <>
      <KeyValue
        items={[
          ["状态", `${label(ATTEMPT_STATUS, text(attempt.status))}${attempt.stage ? ` · 阶段 ${text(attempt.stage)}` : ""}`],
          // 调用目标：连接、协议、地址、上游模型、容量、凭据引用与版本、选择来源（第 7.4 节）
          ["调用目标", callTargetText(callTarget)],
          ["选择来源", selectionSourceName(optionalText(callTarget.selection_source))],
          ["模型", `请求 ${show(optionalText(attempt.requested_model))}，实际 ${show(optionalText(attempt.actual_model))}`],
          ["协议与档位", `请求 ${show(optionalText(callTarget.requested_tier))}，实际发送 ${show(optionalText(callTarget.sent_tier))}`],
          ["部门设置版本", attempt.prompt_version === null || attempt.prompt_version === undefined ? "未上报" : `第 ${String(attempt.prompt_version)} 版`],
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
