// 设置页底部「模型请求与用量」这一节（工单 #1710；项目的组织设计说明「模型请求与用量」）：
// 请求记录与用量统计两块用同一组筛选（事项、职能、状态、模型），平时收着，展开与筛选都写在地址里。
// 观测页用的是同一个部件（RequestsPanel）：两处内容相同，改一处两处都变。
// 这一节里没有循环的层与收敛状态：循环在对话页的循环图与事项面板里。
//
// 数据来自已登记的查询：请求记录读 project.attempts（游标分页），用量统计读 project.usage，
// 事项的清单读 project.overview；请求详情在 attempt-detail.tsx。

import { useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  AttemptView, ProjectAttemptsResult, ProjectOverviewResult, UsageGroup, UsageReport,
} from "../../api/generated/types.gen";
import { REQUESTS_SECTION, paths, type Route } from "../../shell/routing";
import type { DepartmentLabels, DepartmentView } from "./organization";
import { departmentLabel, departmentLabels } from "./organization";
import { readFailureText } from "../../contract/read-failure";
import { Empty, KeyValue, Loading, Section, Table, Tabs, dict, formatNumberOr, numberValue, pageKey, show } from "./common";
import { ATTEMPT_STATUS, formatTime, label } from "./labels";
import { useSnapshot } from "./use-snapshot";
import { reportedCountText, usageText } from "./usage-text";
import {
  departmentFilterNote, departmentOptions, mergeAddressFilters, usageGroupName,
  EMPTY_FILTERS, type Filters,
} from "./observe-filter";
import { scopeName } from "./scope-name";

const PAGE_SIZE = 50;

// 页头的计数说法要的几个数
export type RequestsSummary = {
  inFlight: number;
  total: number | null;
  totalError: string | null;
  loaded: number;
  more: boolean;
};

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

// 请求记录与用量统计（工单 #1710 从观测页搬出，原工单 #80、#801、#744）：
// 观测试与设置页这一节用同一份；页头、卡片的标题与说明由调用处决定要不要。
// 页面内的输入先攒在 draft 里，点「按条件筛选」以后生效；地址带来的筛选变了
// （后退、前进、从请求详情返回、从节点面板带职能进来）就跟着改，只改地址这次变了的那几格。
export function RequestsPanel(props: {
  app: ClientApp;
  projectId: string;
  workItem: string | null;
  departments: DepartmentView[];
  // 地址里读出的筛选条件（工单 #1710）：设置页这一节全组都在地址里，观测页只有职能一格
  addressFilters: Filters;
  // 用户按了「按条件筛选」或「清除筛选」：调用处把筛选写回地址
  onFiltersChange: (filters: Filters) => void;
  // 事项范围（整个项目 / 某个事项）：地址里的 ?w=，调用处换成新范围的地址
  onScopeChange: (workItem: string | null, filters: Filters) => void;
  // 进请求详情的地址：两处来处不同（设置页这一节、观测页），返回的去处也不同
  attemptHash: (item: AttemptView, filters: Filters) => string;
  // 是否给出「事项」这一格（集合里全部事项，可以切到整个项目）：设置页这一节有，
  // 观测页的范围由页面的地址决定、保持原样（工单 #1710：观测页的内容不变）
  scopeSelect?: boolean;
  head?: (summary: RequestsSummary) => React.ReactNode;
  title?: string;
  note?: string;
  sectionId?: string;
  className?: string;
}) {
  const labels = departmentLabels(props.departments);
  const [draft, setDraft] = useState<Filters>(() => props.addressFilters);
  const [applied, setApplied] = useState<Filters>(() => props.addressFilters);
  // 地址里的筛选变了：下拉里的初值与已生效的筛选都跟着变，只改变了的那几格
  const lastAddress = useRef<Filters>(props.addressFilters);
  if (lastAddress.current !== props.addressFilters) {
    const previous = lastAddress.current;
    lastAddress.current = props.addressFilters;
    const nextApplied = mergeAddressFilters(applied, props.addressFilters, previous);
    if (nextApplied !== applied) {
      setApplied(nextApplied);
      setDraft((current) => mergeAddressFilters(current, props.addressFilters, previous));
    }
  }
  const [tab, setTab] = useState<"records" | "usage">("records");
  const [cursor, setCursor] = useState<string | null>(null);
  const params = filterParams(props.projectId, props.workItem, applied, PAGE_SIZE);
  const usageParams = { ...params, limit: undefined };
  const usage = useSnapshot<UsageReport>(props.app, "page.requests.usage", "project.usage", usageParams);
  const attempts = useSnapshot<ProjectAttemptsResult>(
    props.app,
    cursor === null ? "page.requests.attempts" : `page.requests.attempts.${cursor}`,
    "project.attempts",
    { ...params, cursor },
  );
  // 事项的清单：范围里是哪个事项用它说明，事项下拉的选项也来自它
  const scope = useSnapshot<ProjectOverviewResult>(props.app, "page.requests.scope", "project.overview", {
    project_id: props.projectId,
  });
  const scopeTitle = scopeName(scope.data?.work_items ?? [], props.workItem);
  const workItems = scope.data?.work_items ?? [];
  // 游标分页：翻到的页累加起来；第一页的每次新快照（筛选、事项变化或事件到达）都用它替换已有行
  const [rows, setRows] = useState<AttemptView[]>([]);
  const loadedSnapshot = useRef<ProjectAttemptsResult | null>(null);
  if (attempts.data !== null && loadedSnapshot.current !== attempts.data) {
    loadedSnapshot.current = attempts.data;
    setRows(cursor === null ? attempts.data.attempts : [...rows, ...attempts.data.attempts]);
  }

  const filtersChanged = pageKey([draft]) !== pageKey([applied]);
  const inFlight = rows.filter((item) => item.status === "running" || item.status === "requesting").length;
  const departmentNote = departmentFilterNote(applied.department, labels);
  const scopeText = props.workItem === null ? "整个项目" : scopeTitle === "" ? "顶栏选中的事项" : scopeTitle;
  const departmentChoices = choicesOf(props.departments, draft.department, labels);

  // 按条件筛选：页面内的一组条件一起生效，同时写回地址（工单 #1710）
  const applyFilters = () => {
    setApplied(draft);
    setCursor(null);
    props.onFiltersChange(draft);
  };

  // 清除筛选：条件全部清空，地址里的筛选也去掉
  const clearFilters = () => {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setCursor(null);
    props.onFiltersChange(EMPTY_FILTERS);
  };

  const body = (
    <>
      <p className="y10-note note y20-req-scope">
        范围：{scopeText}{departmentNote === "" ? "" : `；${departmentNote}`}；
        {props.scopeSelect === true ? "按事项、职能、状态与模型筛选" : "按职能、状态与模型筛选"}；两个页签使用同一组筛选。
      </p>
      <div className="y10-obs-filters filters">
        {props.scopeSelect === true ? (
          <label className="y10-obs-filter field">
            <span>事项</span>
            <select
              className="y10-select"
              value={props.workItem ?? ""}
              onChange={(event) => props.onScopeChange(event.target.value === "" ? null : event.target.value, applied)}
            >
              <option value="">整个项目</option>
              {workItems.map((item) => <option key={item.work_item_id} value={item.work_item_id}>{item.title}</option>)}
            </select>
          </label>
        ) : null}
        <label className="y10-obs-filter field">
          <span>职能</span>
          <select className="y10-select" value={draft.department} onChange={(event) => setDraft({ ...draft, department: event.target.value })}>
            <option value="">全部职能</option>
            {departmentChoices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
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
        <label className="y10-obs-filter field">
          <span>请求的模型</span>
          <input className="y10-input" type="text" value={draft.requestedModel} onChange={(event) => setDraft({ ...draft, requestedModel: event.target.value })} />
        </label>
        <label className="y10-obs-filter field">
          <span>实际的模型</span>
          <input className="y10-input" type="text" value={draft.actualModel} onChange={(event) => setDraft({ ...draft, actualModel: event.target.value })} />
        </label>
        <label className="y10-obs-filter field">
          <span>Provider 配置</span>
          <input className="y10-input" type="text" value={draft.provider} onChange={(event) => setDraft({ ...draft, provider: event.target.value })} />
        </label>
        <label className="y10-obs-filter is-search field">
          <span>关键词</span>
          <input className="y10-input" type="search" value={draft.q} placeholder="模型、调用目标、事项等" onChange={(event) => setDraft({ ...draft, q: event.target.value })} />
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
          rows={rows}
          labels={labels}
          loading={attempts.loading}
          cursor={attempts.data?.cursor ?? null}
          onMore={() => setCursor(attempts.data?.cursor ?? null)}
          attemptHash={(item) => props.attemptHash(item, applied)}
        />
      ) : <UsageSection usage={usage} labels={labels} />}
    </>
  );

  const head = props.head === undefined ? null : props.head({
    inFlight,
    total: usage.data === null ? null : usage.data.totals.attempts,
    totalError: usage.error,
    loaded: rows.length,
    more: attempts.data !== null && attempts.data.cursor !== null,
  });

  return (
    <>
      {head}
      {props.title === undefined ? body : (
        <Section id={props.sectionId} title={props.title} note={props.note} className={props.className}>
          {body}
        </Section>
      )}
    </>
  );
}

// 职能下拉的选项：项目现在组织里的职能，加上地址里带来的、组织里还没有的那一个
// （地址可以带项目职能清单里有、页面默认没有的职能进来，工单 #1710）
function choicesOf(departments: readonly DepartmentView[], current: string, labels: DepartmentLabels): { value: string; label: string }[] {
  const choices = departmentOptions(departments);
  if (current !== "" && !choices.some((choice) => choice.value === current)) {
    choices.push({ value: current, label: departmentLabel(current, labels) });
  }
  return choices;
}

// 请求记录面板：列按原型 v10 的「请求记录」页签排布（开始、状态、耗时、职能、请求、返回、请求类型、用量）；
// 请求与返回的模型分开列出，用量的显示与请求详情同一口径（工单 #744：同一页三处说法不同）；
// 职能用项目组织给的显示名（工单 #1710），不在组织里的旧数据用页面原有的写法
function RecordsPanel(props: {
  rows: AttemptView[];
  labels: DepartmentLabels;
  loading: boolean;
  cursor: string | null;
  onMore: () => void;
  attemptHash: (item: AttemptView) => string;
}) {
  return (
    <>
      <p className="y10-note note">用量与请求详情同一口径：报了总量写「总 X token」，没报的那几项写「未上报」；一次都没有上报时写「未上报」，不填 0。请求与返回的模型分开列出。</p>
      {props.rows.length === 0 && !props.loading ? <Empty text="这个范围没有请求记录" /> : null}
      {props.rows.length > 0 ? (
        <Table
          head={["开始", "状态", "耗时", "职能", "请求", "返回", "请求类型", "用量", ""]}
          rows={props.rows.map((item) => {
            const usage = dict(item.usage);
            return [
              formatTime(item.started_at ?? item.finished_at),
              label(ATTEMPT_STATUS, item.status),
              item.status === "prepared" || item.status === "requesting" || item.status === "running"
                ? "进行中"
                : formatNumberOr(item.duration_ms, " 毫秒"),
              departmentLabel(item.department, props.labels),
              show(item.requested_model, "未知"),
              show(item.actual_model, "未知"),
              item.purpose === "work" ? "工作请求" : item.purpose === "compaction" ? "压缩请求" : show(item.purpose, ""),
              usageText(usage),
              <button
                type="button"
                className="y10-link link"
                key={item.attempt_id}
                onClick={() => { window.location.hash = props.attemptHash(item); }}
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

function UsageSection(props: { usage: { data: UsageReport | null; loading: boolean; error: string | null }; labels: DepartmentLabels }) {
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
      {/* 按职能分组时后端给的是职能标识，页面换成项目组织里的显示名（工单 #1710） */}
      <UsageGroups title="按职能" groups={data.departments} name={(group) => usageGroupName(group, props.labels)} />
      <UsageGroups title="按模型" groups={data.models} name={(group) => group.label || group.key} />
    </div>
  );
}

function UsageGroups(props: { title: string; groups: UsageGroup[]; name: (group: UsageGroup) => string }) {
  if (props.groups.length === 0) {
    return <p className="y10-note note">{props.title}：没有上报的用量</p>;
  }
  return (
    <Table
      head={["名称", "请求数", "上报用量的请求", "输入（含缓存）", "输出", "总 Token", "成本"]}
      rows={props.groups.map((group) => [
        props.name(group),
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

// 设置页底部这一节（工单 #1710）：平时收着，展开以后是上面那份部件；
// 展开状态写在地址里（section=requests），从请求详情返回时按地址回到展开的样子，筛选也不变
export function RequestsSection(props: { app: ClientApp; route: Route; departments: DepartmentView[] }) {
  const projectId = props.route.projectId ?? "";
  const open = props.route.settingsSection === REQUESTS_SECTION;
  const write = (workItem: string | null, section: string | null, requests: Filters): void => {
    const target = paths.settings(projectId, { workItem, section, requests });
    if (window.location.hash !== target) {
      window.location.hash = target;
    }
  };

  return (
    <section id={REQUESTS_SECTION} className="y10-block card y20-req">
      <details
        className="y20-req-details"
        open={open}
        onToggle={(event) => {
          // 展开与收起写回地址：刷新与从请求详情返回以后还是这个样子
          const next = event.currentTarget.open;
          if (next !== open) {
            write(props.route.workItemId, next ? REQUESTS_SECTION : null, props.route.requestFilters);
          }
        }}
      >
        <summary className="y20-req-summary section-head">
          <span className="y10-block-title y20-req-title">模型请求与用量</span>
          <span className="y10-block-sub note y20-req-sub">请求记录与用量统计用同一组筛选；默认是当前选中的事项，可以切到整个项目；展开状态与筛选条件写在地址里。</span>
        </summary>
        {open ? (
          <div className="y10-block-body">
            <RequestsPanel
              app={props.app}
              projectId={projectId}
              workItem={props.route.workItemId}
              departments={props.departments}
              addressFilters={props.route.requestFilters}
              onFiltersChange={(filters) => write(props.route.workItemId, REQUESTS_SECTION, filters)}
              onScopeChange={(workItem, filters) => write(workItem, REQUESTS_SECTION, filters)}
              attemptHash={(item, filters) => paths.observeDetail(projectId, item.attempt_id, {
                workItem: props.route.workItemId,
                runId: item.run_id,
                department: filters.department || null,
                from: "settings",
                requests: filters,
              })}
              scopeSelect
            />
          </div>
        ) : null}
      </details>
    </section>
  );
}
