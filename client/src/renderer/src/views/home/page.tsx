// 系统首页（原型 v8 设计说明第 4 节，工单 #175）：从上到下依次是状态项、楼、待你决定、
// 离开期间的报告、项目列表。数据来自 system.status、decisions.list、home.away_report 与 projects.list。
// 楼由像素画面五（#178）画出（views/home/building-section）。页面上的数据都来自查询与事件流。

import { useEffect, useMemo, useState } from "react";
import type {
  AwayReport,
  DecisionList,
  DecisionView,
  ProjectList,
  ProjectRow,
  ProjectOverviewResult,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { Loading, Section, hasCommand } from "../project/common";
import { formatTime } from "../project/labels";
import { useCommand, useSnapshot } from "../project/use-snapshot";
import { projectOnboardingMark } from "../project/onboarding";
import { DecisionCardList } from "../decisions/card";
import { sortByRequested } from "../decisions/card-logic";
import { statusItems, type StatusItem } from "./status-items";
import { BuildingSection } from "./building-section";
import { Timeline } from "../timeline/timeline";
import { ticksInRefs, ticksOf } from "../timeline/logic";
import { paths } from "../../shell/routing";
import { Icon } from "../../shell/kit";

// 状态项的图标（原型 v9 的 ui/shell.js 的 statusItems）：每项一个字形，「待你决定」用 decide，
// 与决定卡片同一个字形；kit.tsx 的 GLYPHS 里有它（不在 StatusMark 的状态名单中）
const STAT_ICONS: Record<string, string> = { decisions: "decide" };

const RANGE_LABELS: Record<string, string> = { since_seen: "自上次查看", "24h": "最近 24 小时", "7d": "最近 7 天" };

export type AwayRangeId = "since_seen" | "24h" | "7d";

export function HomePage(props: {
  app: ClientApp;
  onNavigate: (hash: string) => void;
  at: number | null;
  // 系统通知点击后要打开并标出的决定卡片（工单 #375，设计说明第 5.3 节）
  targetDecision: string | null;
}) {
  const [range, setRange] = useState<AwayRangeId>("since_seen");
  const [openItem, setOpenItem] = useState<string | null>(null);
  // 回放位置（全局位置）写在路径的 ?at= 中（设计说明第 3.3 节）：刷新、后退与分享链接回到同一位置
  const at = props.at;
  // 时间轴上选中的刻度：报告项与刻度互相高亮（设计说明第 5.4 节）
  const [selected, setSelected] = useState<number | null>(null);

  // 换范围以后回到现在：起点状态由新的范围给出，路径上的回放位置也跟着清掉
  const changeRange = (next: AwayRangeId) => {
    setRange(next);
    setOpenItem(null);
    setSelected(null);
    props.onNavigate(paths.home());
  };

  const decisions = useSnapshot<DecisionList>(
    props.app,
    "page.home.decisions",
    "decisions.list",
    { status: ["open"] },
  );
  const report = useSnapshot<AwayReport>(props.app, "page.home.report", "home.away_report", { range });
  const projects = useSnapshot<ProjectList>(props.app, "page.home.projects", "projects.list", {});
  // 回放时的项目列表：带 at 读取，画面与项目列表都按该时刻的状态显示（设计说明第 4.1 节）
  const replayProjects = useSnapshot<ProjectList>(
    props.app,
    "page.home.replay.projects",
    "projects.list",
    { at },
    at === null,
  );

  // 项目标识到名称：来自 projects.list（决定请求只带标识）
  const projectNames = useMemo(() => {
    const names: Record<string, string> = {};
    for (const project of projects.data?.projects ?? []) {
      names[project.project_id] = project.name;
    }
    return names;
  }, [projects.data]);

  // 现在的时间只在读取快照后取一次，等待时长按发出时间到这个时刻算（卡片不自行计时）
  const now = Date.now();
  const waiting = useMemo(() => sortByRequested(decisions.data?.decisions ?? []), [decisions.data]);
  const items = statusItems(waiting.length);

  // 报告项展开时高亮的刻度：报告的来源事件位置与刻度位置相同即高亮
  const highlights = useMemo(() => {
    if (report.data === null || openItem === null) {
      return [];
    }
    const item = report.data.summary.find((row) => row.id === openItem);
    if (!item) {
      return [];
    }
    return ticksInRefs(item.refs, ticksOf(report.data.facts));
  }, [report.data, openItem]);

  const replaying = at !== null;

  return (
    <div className={`y9-home page home${replaying ? " is-replay" : ""}`}>
      <Loading state={decisions} />
      <StatusRow items={items} onNavigate={props.onNavigate} />

      <BuildingSection
        app={props.app}
        projects={replaying ? replayProjects.data : projects.data}
        at={at}
        onNavigate={props.onNavigate}
      />

      {replaying ? (
        <p className="replay-banner" role="status">
          回放中 · {formatTime(report.data?.facts.find((fact) => fact.position === at)?.at ?? null)}
        </p>
      ) : null}

      <Section title="待你决定" note="跨项目，按发出时间排列">
        <DecisionNames
          app={props.app}
          decisions={waiting}
          now={now}
          projectNames={projectNames}
          onNavigate={props.onNavigate}
          targetDecision={props.targetDecision}
        />
      </Section>

      <AwayReportSection
        app={props.app}
        report={report}
        range={range}
        onRange={changeRange}
        openItem={openItem}
        onToggleItem={(id) => setOpenItem(openItem === id ? null : id)}
        at={at}
        onPosition={(next) => props.onNavigate(paths.homeAt(next))}
        selected={selected}
        onSelect={setSelected}
        highlights={highlights}
      />

      <Section title="项目" note="按项目列出长期目标、当前成果与等待数量">
        {(replaying ? replayProjects.data : projects.data) === null ? (
          <Loading state={replaying ? replayProjects : projects} />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">项目</th>
                  <th scope="col">长期目标</th>
                  <th scope="col">当前成果</th>
                  <th scope="col">进行中 · 排队中</th>
                  <th scope="col">待回答的决定</th>
                  <th scope="col">最近活动</th>
                </tr>
              </thead>
              <tbody>
                {(replaying ? replayProjects.data : projects.data)!.projects
                  .filter((project) => !project.archived)
                  .map((project) => (
                    <tr key={project.project_id}>
                      <td>
                        <button
                          type="button"
                          className="link"
                          onClick={() => props.onNavigate(`#/p/${project.project_id}/overview`)}
                        >
                          {project.name}
                        </button>
                        {project.source === "existing" ? <span className="tag">已有项目</span> : null}
                        <OnboardingMark project={project} decisions={waiting} />
                      </td>
                      <td>{project.goal === "" ? "没有填写" : project.goal}</td>
                      <td>{project.current_adoption === null ? "尚未采纳" : project.current_adoption}</td>
                      <td>
                        {project.in_progress_count} · {project.waiting_count}
                      </td>
                      <td>{project.decisions_waiting > 0 ? project.decisions_waiting : "无"}</td>
                      <td>{formatTime(project.last_activity_at)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

// 项目行上的建档状态标记（3.8 第 3.4 节）：来自 projects.list 与等待回答的初始 PRD 决定请求，
// 项目没有建档状态时不显示标记
function OnboardingMark(props: { project: ProjectRow; decisions: DecisionView[] }) {
  const mark = projectOnboardingMark(props.project, props.decisions);
  return mark === null ? null : <span className="tag">{mark}</span>;
}

// 待你决定：跨项目的决定卡片。事项标题由 project.overview 解析（决定请求只带标识），
// 解析不到时回落到标识本身。项目名由 projects.list 给出。
function DecisionNames(props: {
  app: ClientApp;
  decisions: DecisionView[];
  now: number;
  projectNames: Record<string, string>;
  onNavigate: (hash: string) => void;
  // 系统通知点击后要打开并标出的决定卡片（工单 #375，设计说明第 5.3 节）
  targetDecision: string | null;
}) {
  const titles = useWorkItemTitles(props.app, props.decisions);
  return (
    <DecisionCardList
      app={props.app}
      decisions={props.decisions}
      now={props.now}
      names={(decision) => ({
        projectName: props.projectNames[decision.project_id ?? ""] ?? decision.project_id ?? "",
        workItemTitle: titles[decision.work_item_id ?? ""] ?? decision.work_item_id ?? "",
      })}
      onNavigate={props.onNavigate}
      targetDecision={props.targetDecision}
      emptyText="没有等待回答的决定"
    />
  );
}

// 决定请求涉及的项目的事项标识到标题：对这些项目打开 project.overview，汇总出标题表。
// 项目集合变化时重新打开；查询随事件刷新
function useWorkItemTitles(app: ClientApp, decisions: DecisionView[]): Record<string, string> {
  const projectIds = useMemo(
    () => [...new Set(decisions.map((decision) => decision.project_id).filter((id): id is string => id !== null))].sort(),
    [decisions],
  );
  const key = projectIds.join(",");
  const [titles, setTitles] = useState<Record<string, string>>({});
  useEffect(() => {
    const views = app.viewSync;
    if (!views) {
      return;
    }
    const ids = key === "" ? [] : key.split(",");
    for (const projectId of ids) {
      void views.open<ProjectOverviewResult>(`home.titles.${projectId}`, {
        query: "project.overview",
        params: { project_id: projectId },
      }, (data) => {
        setTitles((current) => {
          const next = { ...current };
          for (const item of data.work_items) {
            next[item.work_item_id] = item.title;
          }
          return next;
        });
      });
    }
    return () => {
      for (const projectId of ids) {
        views.close(`home.titles.${projectId}`);
      }
    };
  }, [app, key]);
  return titles;
}

// 状态项的一排：正常时灰色「无」，异常时亮起并显示数量，点击进入对应的页面
function StatusRow(props: { items: StatusItem[]; onNavigate: (hash: string) => void }) {
  return (
    <div className="y9-stats status-row" aria-label="状态项">
      {props.items.map((item) => {
        const value = item.lit ? (item.count !== null ? String(item.count) : item.text) : "无";
        return (
          <button
            key={item.id}
            className={`y9-stat status-item is-${item.id}${item.lit ? " is-lit lit" : ""}${
              item.lit && STAT_ICONS[item.id] === "decide" ? " is-decide" : ""
            }`}
            disabled={!item.lit || item.href === null}
            onClick={() => {
              if (item.href !== null) {
                props.onNavigate(item.href);
              }
            }}
            title={`${item.label}：${value}${item.lit && item.href !== null ? "，点击查看" : ""}`}
          >
            <Icon name={STAT_ICONS[item.id] ?? "unknown"} className="y9-stat-icon" />
            <span className="y9-stat-label status-label">{item.label}</span>
            <span className="y9-stat-value status-value">{value}</span>
          </button>
        );
      })}
    </div>
  );
}

// 离开期间的报告（第 4.4 节）：上次查看的时间、范围切换、「已看过」（home.mark_seen）；
// 汇总项取自 home.away_report，每项数字可以点击，展开来源事件；没有来源事件的项不显示。
// 时间轴放在报告下方（第 5.5 节）：刻度取关键事实，与楼联动回放；报告项与刻度互相高亮。
function AwayReportSection(props: {
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
}) {
  const data = props.report.data;
  const command = useCommand(props.app, JSON.stringify(data?.range ?? null));
  const ranges = data?.ranges ?? [];
  const rangeLabel = RANGE_LABELS[props.range] ?? props.range;

  return (
    <Section
      title="离开期间的报告"
      note={
        data === null
          ? "正在读取这段时间的完成情况"
          : `上次查看：${formatTime(data.last_seen.at)}`
      }
    >
      <div className="y9-row row-actions">
        {/* 范围切换（原型 ui/views/home.js 的 reportBlock）：三个按钮一组，选中的一项高亮 */}
        <span className="y9-seg">
          {ranges.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`y9-seg-btn${option.id === props.range ? " is-on primary" : ""}`}
              onClick={() => props.onRange(option.id as AwayRangeId)}
            >
              {option.label}
            </button>
          ))}
        </span>
        {hasCommand(props.app, "home.mark_seen") && data !== null ? (
          <button
            type="button"
            className="y9-btn small primary"
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
        <p className="y9-note note">这段时间没有完成、放行或其他需要报告的事（范围：{rangeLabel}）</p>
      ) : (
        <>
          <div className="y9-report-items report-items">
            {data.summary.map((item) => {
              // 刻度选中时高亮对应的报告项（点击刻度，报告中的项高亮）
              const lit = props.selected !== null && item.refs.includes(props.selected);
              return (
                <div key={item.id} className={`y9-report-item report-item${props.openItem === item.id ? " is-open open" : ""}${lit ? " is-highlight highlight" : ""}`}>
                  <button type="button" className="y9-report-head report-head" onClick={() => props.onToggleItem(item.id)}>
                    <span className="y9-report-label report-label">{item.label}</span>
                    <span className="y9-report-value report-value">
                      {item.value}
                      <small>{item.unit}</small>
                    </span>
                    {item.detail ? <span className="y9-report-detail report-detail">{item.detail}</span> : null}
                  </button>
                  {props.openItem === item.id ? (
                    item.refs.length === 0 ? (
                      <p className="y9-note note">{item.detail ?? ""}（来源：范围内的调用尝试记录）</p>
                    ) : (
                      <ul className="y9-source-list source-list">
                        {item.refs.map((position) => {
                          const fact = data.facts.find((row) => row.position === position);
                          return (
                            <li key={position}>
                              <span className="y9-note note">{formatTime(fact?.at ?? null)}</span>{" "}
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
