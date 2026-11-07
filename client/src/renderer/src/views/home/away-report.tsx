// 离开期间的报告（原型 v8 设计说明第 4.4 节，工单 #175；开环明细见工单 #401）。
//
// 上次查看的时间、范围切换、「已看过」（home.mark_seen）；汇总项取自 home.away_report，每项数字可以点击，
// 展开来源事件；没有来源事件的项不显示。时间轴放在报告下方（第 5.5 节）：刻度取关键事实，与楼联动回放；
// 报告项与刻度互相高亮。
//
// 带开环条件的放行（工单 #401；验证的独立性 docs/design/independent-verification.md「检验覆盖与开环」、「口径」）：报告的这一项逐条列出每个放行带开环
// 条件的验收条件，条数取自 `acceptance.coverage`——放行记录里一次算好，页面读这个数，不重新计算。
// 事项的名称取自 project.overview（报告项给出事项标识与所在项目，页面用结构化字段拼文字），检验覆盖按事项所属的 run 读。
// 「开环」在这里是验收条件一级的；事项一级的开环完成是另一种记号，本页不写那个词。
//
// 收敛状态的变化（工单 #1583）：明细同样按事项标题写；层名与前后两种状态取自报告项的结构化字段，
// 页面用字段拼文字，不显示 detail 里的标识（docs/design/app-and-interface.md「页面上不出现内部标识」）。
// 事项标识与项目标识在字段里，标题取不到时写「未命名事项」，两者都用于回到事项的页面。

import { useEffect, useMemo, useState } from "react";
import type {
  AcceptanceCoverageResult,
  AwayReport,
  ProjectOverviewResult,
  ReportEntry,
  ReportFact,
  ReportItem,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { paths } from "../../shell/routing";
import { Loading, Section, hasCommand } from "../project/common";
import {
  CRITERIA_TABLE_LINK,
  CRITERIA_TABLE_READY,
  OPEN_CRITERIA_READING,
  OPEN_CRITERIA_UNREADABLE,
  WORK_ITEM_UNNAMED,
  formatTime,
  openCriteriaText,
} from "../project/labels";
import { useCommand } from "../project/use-snapshot";
import { Timeline } from "../timeline/timeline";

const RANGE_LABELS: Record<string, string> = { since_seen: "自上次查看", "24h": "最近 24 小时", "7d": "最近 7 天" };

export type AwayRangeId = "since_seen" | "24h" | "7d";

// 离开期间的报告：时间、范围切换、已看过、汇总项与时间轴
export function AwayReportSection(props: {
  id: string;
  app: ClientApp;
  report: { data: AwayReport | null; loading: boolean };
  range: AwayRangeId;
  onRange: (range: AwayRangeId) => void;
  openItem: string | null;
  onToggleItem: (id: string) => void;
  at: number | null;
  onPosition: (position: number | null) => void;
  selected: number | null;
  onSelect: (position: number) => void;
  highlights: number[];
  // 项目标识到名称（projects.list）：开环明细写在项目名下面
  projectNames: Record<string, string>;
  onNavigate: (hash: string) => void;
}) {
  const data = props.report.data;
  const command = useCommand(props.app, JSON.stringify(data?.range ?? null));
  const ranges = data?.ranges ?? [];
  const rangeLabel = RANGE_LABELS[props.range] ?? props.range;

  return (
    <Section
      id={props.id}
      title="离开期间的报告"
      note={
        data === null
          ? "正在读取这段时间的完成情况"
          : `上次查看：${formatTime(data.last_seen.at)}`
      }
    >
      <div className="y10-row row-actions">
        {/* 范围切换（原型 ui/views/home.js 的 reportBlock）：三个按钮一组，选中的一项高亮 */}
        <span className="y10-seg">
          {ranges.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`y10-seg-btn${option.id === props.range ? " is-on primary" : ""}`}
              onClick={() => props.onRange(option.id as AwayRangeId)}
            >
              {option.label}
            </button>
          ))}
        </span>
        {hasCommand(props.app, "home.mark_seen") && data !== null ? (
          <button
            type="button"
            className="y10-btn small primary"
            disabled={command.busy}
            onClick={() => void command.submit("home.mark_seen", { position: data.range.to_position })}
          >
            已看过
          </button>
        ) : null}
      </div>
      {data === null ? (
        <Loading state={props.report} />
      ) : data.summary.length === 0 ? (
        <p className="y10-note note">这段时间没有完成、放行或其他需要报告的事（范围：{rangeLabel}）</p>
      ) : (
        <>
          <div className="y10-report-items report-items">
            {data.summary.map((item) => {
              // 刻度选中时高亮对应的报告项（点击刻度，报告中的项高亮）
              const lit = props.selected !== null && item.refs.includes(props.selected);
              const openRelease = item.id === OPEN_RELEASE_ITEM_ID;
              const convergence = item.id === CONVERGENCE_ITEM_ID;
              // 这两项的明细由下面按结构化字段逐条列出，不把服务端的 detail 原样写进页面
              const structured = openRelease || convergence;
              return (
                <div key={item.id} className={`y10-report-item report-item${props.openItem === item.id ? " is-open open" : ""}${lit ? " is-highlight highlight" : ""}`}>
                  <button type="button" className="y10-report-head report-head" onClick={() => props.onToggleItem(item.id)}>
                    <span className="y10-report-label report-label">{item.label}</span>
                    <span className="y10-report-value report-value">
                      {item.value}
                      <small>{item.unit}</small>
                    </span>
                    {/* 开环与收敛的明细逐条列在下面（一行一个放行或一处变化），不挤在这一行里 */}
                    {item.detail && !structured ? <span className="y10-report-detail report-detail">{item.detail}</span> : null}
                  </button>
                  {openRelease ? (
                    <OpenReleaseList
                      app={props.app}
                      item={item}
                      facts={data.facts}
                      projectNames={props.projectNames}
                      onNavigate={props.onNavigate}
                    />
                  ) : null}
                  {convergence ? (
                    <ConvergenceList
                      app={props.app}
                      item={item}
                      projectNames={props.projectNames}
                      onNavigate={props.onNavigate}
                    />
                  ) : null}
                  {props.openItem === item.id ? (
                    item.refs.length === 0 ? (
                      <p className="y10-note note">{item.detail ?? ""}（来源：范围内的调用尝试记录）</p>
                    ) : (
                      <ul className="y10-source-list source-list">
                        {item.refs.map((position) => {
                          const fact = data.facts.find((row) => row.position === position);
                          return (
                            <li key={position}>
                              <span className="y10-note note">{formatTime(fact?.at ?? null)}</span>{" "}
                              {fact?.label ?? "来源事件"}{" "}
                              <code>{fact?.type ?? `事件 ${position}`}</code>
                            </li>
                          );
                        })}
                      </ul>
                    )
                  ) : null}
                </div>
              );
            })}
          </div>
        </>
      )}
      {data !== null ? (
        <Timeline
          facts={data.facts}
          fromPosition={data.range.from_position}
          fromAt={data.range.from_at}
          project={null}
          at={props.at}
          onPosition={props.onPosition}
          onSelect={props.onSelect}
          highlight={props.highlights}
          liveNote={`实时画面 · ${data.facts.length} 条关键事实`}
        />
      ) : null}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// 带开环条件的放行的明细（工单 #401）与收敛状态的变化（工单 #1583）

/** 报告里「带开环条件的放行」一项的标识（home.away_report 的 ReportItem.id）。 */
export const OPEN_RELEASE_ITEM_ID = "open_release";

/** 报告里「收敛状态的变化」一项的标识（home.away_report 的 ReportItem.id）。 */
export const CONVERGENCE_ITEM_ID = "convergence";

/** 一个放行：事件位置、所属的项目与事项、放行的时间。 */
export interface OpenReleaseTarget {
  position: number;
  projectId: string;
  workItemId: string;
  at: string | null;
}

/**
 * 报告项指向的放行：事项标识与所在项目取报告项的结构化字段（与 refs 中的事件位置按行对应，
 * 服务端在同一次循环里生成两者），时间取同一份报告的关键事实。缺少事项或项目的行不列。
 */
export function openReleaseTargets(
  item: ReportItem | null | undefined,
  facts: readonly ReportFact[],
): OpenReleaseTarget[] {
  if (!item || item.id !== OPEN_RELEASE_ITEM_ID) {
    return [];
  }
  const byPosition = new Map(facts.map((fact) => [fact.position, fact]));
  const targets: OpenReleaseTarget[] = [];
  (item.entries ?? []).forEach((entry, index) => {
    const position = item.refs[index];
    if (entry.work_item_id == null || entry.project_id == null || position === undefined) {
      return;
    }
    targets.push({
      position,
      projectId: entry.project_id,
      workItemId: entry.work_item_id,
      at: byPosition.get(position)?.at ?? null,
    });
  });
  return targets;
}

/** 开环明细一行在页面上的状态：读到了、还在读、读不出来。 */
export type OpenReleaseState = "ready" | "reading" | "unreadable";

/** 开环明细的一行：一个放行的事项、条数与条件，以及逐条结论表的链接。 */
export interface OpenReleaseRow {
  position: number;
  at: string | null;
  /** 项目名与事项标题；标题取不到时写「未命名事项」，不写事项标识 */
  where: string;
  text: string;
  state: OpenReleaseState;
  /** 「跳到逐条结论表」的链接；逐条结论表读不出来时为空 */
  href: string | null;
}

export interface OpenReleaseLookup {
  targets: readonly OpenReleaseTarget[];
  /** 事项标识到标题（project.overview 的结果） */
  titles: Readonly<Record<string, string>>;
  /** 事项标识到检验覆盖（acceptance.coverage 的结果）；读不出来时那一条是 null，还没有读到时没有这一条 */
  coverage: Readonly<Record<string, AcceptanceCoverageResult | null | undefined>>;
  /** 项目标识到名称（projects.list 的结果） */
  projectNames: Readonly<Record<string, string>>;
  /** 逐条结论表是否已经交付（#154）；省略时按页面上的那一行常量（已经交付） */
  criteriaTableReady?: boolean;
}

/**
 * 开环明细的行：逐个放行写出它的事项与开环条件。
 * 条数与条件取自 `acceptance.coverage`（放行记录里一次算好的数与明细），页面不重新计算。
 */
export function openReleaseRows(lookup: OpenReleaseLookup): OpenReleaseRow[] {
  const ready = lookup.criteriaTableReady ?? CRITERIA_TABLE_READY;
  return lookup.targets.map((target) => {
    const coverage = lookup.coverage[target.workItemId];
    const title = lookup.titles[target.workItemId] ?? "";
    const projectName = lookup.projectNames[target.projectId] ?? "";
    const where = [projectName, title === "" ? WORK_ITEM_UNNAMED : title].filter((part) => part !== "").join(" / ");
    const state: OpenReleaseState = coverage === undefined ? "reading" : coverage === null ? "unreadable" : "ready";
    const text = coverage === undefined
      ? OPEN_CRITERIA_READING
      : coverage === null
        ? OPEN_CRITERIA_UNREADABLE
        : openCriteriaText(coverage.numbers.open, coverage.open_criteria);
    // 逐条结论表在资料页（#154）；读不出检验覆盖的那一行没有条数可对照，不给链接
    const href = ready && coverage !== null && coverage !== undefined
      ? paths.materials(target.projectId, { workItem: target.workItemId })
      : null;
    return { position: target.position, at: target.at, where, text, state, href };
  });
}

/** 收敛状态的变化的一行：事项标题（项目名 / 标题）、层与前后状态，以及回到事项的链接。 */
export interface ConvergenceRowView {
  key: string;
  /** 项目名 / 事项标题；标题取不到时写「未命名事项」，不写事项标识 */
  where: string;
  /** 层名与前后两种状态，例如「部门之间的循环：无法判定 → 收敛中」 */
  change: string;
  /** 回到事项概览的链接；缺项目或事项标识时为空 */
  href: string | null;
}

/**
 * 收敛明细的行：逐个变化写出事项标题、中文层名与前后两种状态。
 * 字段取自报告项的结构化字段（工单 #1583），标题取自 project.overview，页面不解析 detail。
 */
export function convergenceRows(
  item: ReportItem | null | undefined,
  titles: Readonly<Record<string, string>>,
  projectNames: Readonly<Record<string, string>>,
): ConvergenceRowView[] {
  if (!item || item.id !== CONVERGENCE_ITEM_ID) {
    return [];
  }
  return (item.entries ?? []).flatMap((entry, index) => {
    if (entry.layer == null || entry.state_from == null || entry.state_to == null) {
      return [];
    }
    const projectName = entry.project_id == null ? "" : projectNames[entry.project_id] ?? "";
    const title = entry.work_item_id == null ? "" : titles[entry.work_item_id] ?? "";
    const where = [projectName, title === "" ? WORK_ITEM_UNNAMED : title].filter((part) => part !== "").join(" / ");
    const href = entry.project_id != null && entry.work_item_id != null
      ? paths.overview(entry.project_id, { workItem: entry.work_item_id })
      : null;
    return [{
      key: `${item.id}.${index}`,
      where,
      change: `${entry.layer}：${entry.state_from} → ${entry.state_to}`,
      href,
    }];
  });
}

// 收敛明细：标题先经 project.overview 读，读到之前按「未命名事项」写；读不到标题的事项也这样写
function ConvergenceList(props: {
  app: ClientApp;
  item: ReportItem;
  projectNames: Record<string, string>;
  onNavigate: (hash: string) => void;
}) {
  const titles = useConvergenceTitles(props.app, props.item.entries ?? []);
  const rows = convergenceRows(props.item, titles, props.projectNames);
  if (rows.length === 0) {
    return <p className="y10-note note">这一项没有可以列出的明细</p>;
  }
  return (
    <ul className="y10-source-list source-list convergence-list">
      {rows.map((row) => (
        <li key={row.key} className="convergence-row">
          {row.href === null ? (
            <span className="y10-note note">{`${row.where} · ${row.change}`}</span>
          ) : (
            <button type="button" className="link convergence-link" onClick={() => props.onNavigate(row.href!)}>
              {`${row.where} · ${row.change}`}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

// 收敛明细里的事项标题：按结构化字段的（项目, 事项）逐个打开 project.overview，汇总出标题表。
// 同一个事项只读一次；读不到标题的事项不在表里，调用处写「未命名事项」
function useConvergenceTitles(app: ClientApp, entries: readonly ReportEntry[]): Record<string, string> {
  const pairs = useMemo(() => {
    const seen = new Set<string>();
    const list: { projectId: string; workItemId: string }[] = [];
    for (const entry of entries) {
      if (entry.project_id == null || entry.work_item_id == null) {
        continue;
      }
      const key = `${entry.project_id}/${entry.work_item_id}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      list.push({ projectId: entry.project_id, workItemId: entry.work_item_id });
    }
    return list;
  }, [entries]);
  const key = pairs.map((pair) => `${pair.projectId}/${pair.workItemId}`).join(",");
  const [titles, setTitles] = useState<Record<string, string>>({});
  useEffect(() => {
    const views = app.viewSync;
    if (!views) {
      return;
    }
    const list = key === "" ? [] : key.split(",");
    for (const pair of list) {
      const [projectId, workItemId] = pair.split("/");
      void views.open<ProjectOverviewResult>(
        `home.convergence.item.${projectId}.${workItemId}`,
        { query: "project.overview", params: { project_id: projectId, work_item: workItemId } },
        (data) => {
          const card = data.work_items.find((item) => item.work_item_id === workItemId);
          if (card === undefined) {
            return;
          }
          setTitles((current) => ({ ...current, [workItemId]: card.title }));
        },
      );
    }
    return () => {
      for (const pair of list) {
        const [projectId, workItemId] = pair.split("/");
        views.close(`home.convergence.item.${projectId}.${workItemId}`);
      }
    };
  }, [app, key]);
  return titles;
}

// 一个放行的开环明细：先按报告项的位置取放行的事实，再按事项取它的名称与 run，最后读这个 run 的检验覆盖。
// 两次读取分开：project.overview 先给出 run，acceptance.coverage 才有 run 可读
function OpenReleaseList(props: {
  app: ClientApp;
  item: ReportItem;
  facts: ReportFact[];
  projectNames: Record<string, string>;
  onNavigate: (hash: string) => void;
}) {
  const targets = useMemo(() => openReleaseTargets(props.item, props.facts), [props.item, props.facts]);
  const lookup = useReleaseCoverage(props.app, targets);
  const rows = openReleaseRows({ targets, ...lookup, projectNames: props.projectNames });
  if (rows.length === 0) {
    return <p className="y10-note note">这一项没有可以列出的开环明细</p>;
  }
  return (
    <ul className="y10-source-list source-list open-release-list">
      {rows.map((row) => (
        <li key={row.position} className={`open-release-row is-${row.state}`} data-open-release={row.position}>
          <span className="y10-note note">{formatTime(row.at)}</span>{" "}
          <span className="open-release-where">{row.where}</span>
          {row.text === "" ? null : <span className="open-release-criteria"> · {row.text}</span>}
          {row.href === null ? null : (
            <button type="button" className="link open-release-link" onClick={() => props.onNavigate(row.href!)}>
              {CRITERIA_TABLE_LINK}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

// 放行所在事项的名称与检验覆盖：先经 project.overview 把事项换成它的 run（查询只给事项标识），
// 再按 run 读 acceptance.coverage。视图标识带上事件位置，同一页上几个放行各自读各自的
function useReleaseCoverage(app: ClientApp, targets: readonly OpenReleaseTarget[]): {
  titles: Record<string, string>;
  coverage: Record<string, AcceptanceCoverageResult | null>;
} {
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [runs, setRuns] = useState<Record<string, string>>({});
  const [coverage, setCoverage] = useState<Record<string, AcceptanceCoverageResult | null>>({});
  const targetsKey = targets.map((target) => `${target.position}/${target.projectId}/${target.workItemId}`).join(",");

  // 一、事项的名称与 run（project.overview 按事项筛选，只读这一件事）
  useEffect(() => {
    const views = app.viewSync;
    if (!views) {
      return;
    }
    const list = targets;
    for (const target of list) {
      void views.open<ProjectOverviewResult>(
        `home.open-release.item.${target.position}`,
        { query: "project.overview", params: { project_id: target.projectId, work_item: target.workItemId } },
        (data) => {
          const card = data.work_items.find((item) => item.work_item_id === target.workItemId);
          if (card === undefined) {
            return;
          }
          setTitles((current) => ({ ...current, [target.workItemId]: card.title }));
          setRuns((current) => ({ ...current, [target.workItemId]: card.run_id }));
        },
      );
    }
    return () => {
      for (const target of list) {
        views.close(`home.open-release.item.${target.position}`);
      }
    };
  }, [app, targetsKey]);

  // 二、这个 run 的检验覆盖：条数与开环明细从这一份里读，页面不重新计算
  const runsKey = Object.entries(runs)
    .map(([workItemId, runId]) => `${workItemId}:${runId}`)
    .sort()
    .join(",");
  useEffect(() => {
    const views = app.viewSync;
    if (!views) {
      return;
    }
    const opened: string[] = [];
    for (const target of targets) {
      const runId = runs[target.workItemId];
      if (runId === undefined) {
        continue;
      }
      const viewId = `home.open-release.coverage.${target.position}`;
      opened.push(viewId);
      void views.open<AcceptanceCoverageResult>(
        viewId,
        { query: "acceptance.coverage", params: { run_id: runId } },
        (data) => {
          setCoverage((current) => ({ ...current, [target.workItemId]: data }));
        },
        () => {
          setCoverage((current) => ({ ...current, [target.workItemId]: null }));
        },
      );
    }
    return () => {
      for (const viewId of opened) {
        views.close(viewId);
      }
    };
  }, [app, runsKey, targetsKey]);

  return { titles, coverage };
}
