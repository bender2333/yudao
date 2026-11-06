// 系统首页（原型 v8 设计说明第 4 节，工单 #175）：从上到下依次是状态项、项目一览、楼、待你决定、
// 离开期间的报告、项目列表。数据来自 system.status、decisions.list、home.away_report 与 projects.list。
// 楼由像素画面五（#178）画出（views/home/building-section）。页面上的数据都来自查询与事件流。
//
// 工单 #1416：原来只在楼的画布上看到的三样事实（此刻在做什么、事项在哪个部门、有没有事项在等执行槽位）
// 补进「项目」一节的每一行；它们与楼一样由每个项目的 project.loop 推出（useProjectLoops 在这里取一次，
// 楼只拿结果画）。画布照旧挂着，由后面的工单搬走。

import { useEffect, useMemo, useState } from "react";
import type {
  AwayReport,
  DecisionList,
  DecisionView,
  ProjectList,
  ProjectLoopResult,
  ProjectRow,
  ProjectOverviewResult,
  SystemStatus,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { Loading, Section } from "../project/common";
import { readFailureText } from "../../contract/read-failure";
import { formatTime } from "../project/labels";
import { projectDoingText, projectItemsByDepartmentText, projectSlotText } from "../project/floor-text";
import { useSnapshot } from "../project/use-snapshot";
import { projectOnboardingMark } from "../project/onboarding";
import { DecisionCardList } from "../decisions/card";
import { sortByRequested } from "../decisions/card-logic";
import { statusItems, type StatusItem } from "./status-items";
import { BuildingSection, type ProjectLoops } from "./building-section";
import { AwayReportSection, type AwayRangeId } from "./away-report";
import { ticksInRefs, ticksOf } from "../timeline/logic";
import { paths } from "../../shell/routing";
import { Block, Icon } from "../../shell/kit";

export type { AwayRangeId } from "./away-report";

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

  const status = useSnapshot<SystemStatus>(props.app, "page.home.status", "system.status", {});
  // 现在的时间只在读取快照后取一次，等待时长按发出时间到这个时刻算（卡片不自行计时）
  const now = Date.now();
  const waiting = useMemo(() => sortByRequested(decisions.data?.decisions ?? []), [decisions.data]);
  const items = statusItems(status.data, waiting);

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
  // 项目列表读取失败时的原因：有它时这一节说「读不出来」，不说「没有项目」（工单 #728）
  const projectError = replaying ? replayProjects.error : projects.error;
  // 每个项目的 project.loop：项目一览的三样事实与楼共用这一份（回放时按位置读）
  const loops = useProjectLoops(props.app, replaying ? replayProjects.data : projects.data, at);

  return (
    <div className={`y10-home page home${replaying ? " is-replay" : ""}`}>
      <Loading state={decisions} />
      <StatusBlock items={items} onNavigate={props.onNavigate} />

      <BuildingSection
        app={props.app}
        projects={replaying ? replayProjects.data : projects.data}
        error={replaying ? replayProjects.error : projects.error}
        at={at}
        loops={loops}
        onNavigate={props.onNavigate}
      />

      {replaying ? (
        <p className="replay-banner" role="status">
          回放中 · {formatTime(report.data?.facts.find((fact) => fact.position === at)?.at ?? null)}
        </p>
      ) : null}

      <Section id="home-decisions" title="待你决定" note="跨项目，按发出时间排列">
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
        id="home-report"
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
        projectNames={projectNames}
        onNavigate={props.onNavigate}
      />

      <Section id="home-projects" title="项目" note="每个项目一行：此刻在做什么、事项在哪个部门、有没有事项在等执行槽位、待你回答的决定">
        {projectError !== null ? (
          <p className="y10-note note" role="status">{readFailureText(projectError)}</p>
        ) : (replaying ? replayProjects.data : projects.data) === null ? (
          <Loading state={replaying ? replayProjects : projects} />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">项目</th>
                  <th scope="col">长期目标</th>
                  <th scope="col">当前成果</th>
                  <th scope="col">此刻在做什么</th>
                  <th scope="col">事项在哪个部门</th>
                  <th scope="col">执行槽位</th>
                  <th scope="col">待回答的决定</th>
                  <th scope="col">最近活动</th>
                </tr>
              </thead>
              <tbody>
                {(replaying ? replayProjects.data : projects.data)!.projects
                  .filter((project) => !project.archived)
                  .map((project) => {
                    // 三样事实来自这个项目的 project.loop：读到之前写「正在读取」，读不出来写「读不出来」
                    const loop = loops.byProject[project.project_id] ?? null;
                    const loopState = loops.failed[project.project_id] === true
                      ? "读不出来"
                      : loop === null ? "正在读取" : null;
                    return (
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
                        <td className="cell-stack">{loopState ?? projectDoingText(loop)}</td>
                        <td className="cell-stack">{loopState ?? projectItemsByDepartmentText(loop)}</td>
                        <td>{loopState ?? projectSlotText(loop)}</td>
                        <td>{project.decisions_waiting > 0 ? project.decisions_waiting : "无"}</td>
                        <td>{formatTime(project.last_activity_at)}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 每个项目的事项：为每行项目打开一次 project.loop，连同查询快照的位置一起记下。
// 项目集合变化时重新打开；查询随事件刷新。位置只增不减：跳到最新以后晚回来的旧结果不再上画面。
// 首页项目一览的三样事实与楼共用这一份结果（工单 #1416）：打开一次，两处都按同一份快照写。

export function useProjectLoops(app: ClientApp, projects: ProjectList | null, at: number | null): ProjectLoops {
  const ids = useMemo(
    () => [...new Set((projects?.projects ?? []).map((p) => p.project_id))].sort(),
    [projects],
  );
  const key = ids.join(",");
  const [loops, setLoops] = useState<ProjectLoops>({ byProject: {}, failed: {}, position: 0 });
  useEffect(() => {
    const views = app.viewSync;
    if (!views || key === "") {
      // 没有项目：楼层清空，位置保留（时间线按位置决定状态上不上画面，位置回到 0 会让空状态上不去）
      setLoops((current) => ({ byProject: {}, failed: {}, position: current.position }));
      return;
    }
    const open = key.split(",");
    for (const projectId of open) {
      const params: Record<string, unknown> = { project_id: projectId };
      if (at !== null) params.at = at;
      void views.open<ProjectLoopResult>(`home.building.${projectId}`, {
        query: "project.loop",
        params,
      }, (data, position) => {
        setLoops((current) => ({
          byProject: { ...current.byProject, [projectId]: data },
          failed: Object.fromEntries(Object.entries(current.failed).filter(([id]) => id !== projectId)),
          position: Math.max(current.position, position),
        }));
      }, () => {
        // 读不出来：这一行的三样事实写「读不出来」，不说「没有在做的事」
        setLoops((current) => ({
          ...current,
          failed: { ...current.failed, [projectId]: true },
        }));
      });
    }
    return () => {
      for (const projectId of open) {
        views.close(`home.building.${projectId}`);
      }
    };
  }, [app, key, at]);
  return loops;
}

// 项目行上的建档状态标记（3.8 第 3.4 节）：来自 projects.list 与等待回答的初始 PRD 决定请求，
// 项目没有建档状态时不显示标记
function OnboardingMark(props: { project: ProjectRow; decisions: DecisionView[] }) {
  const mark = projectOnboardingMark(props.project, props.decisions);
  return mark === null ? null : <span className="tag">{mark}</span>;
}

// 待你决定：跨项目的决定卡片。事项标题由 project.overview 解析（决定请求只带标识），
// 解析不到时是空串，卡片不写事项标识（工单 #802）。项目名由 projects.list 给出。
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
        workItemTitle: titles[decision.work_item_id ?? ""] ?? "",
      })}
      onNavigate={props.onNavigate}
      targetDecision={props.targetDecision}
      viewId="home.decisions"
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

// 状态项的区块（原型 ui/views/home.js 的 statusRow）：一个没有标题的区块里放一排状态项，
// 正常时灰色「无」，异常时亮起并显示数量；点击跳到对应的页面，同页的区块滚到该区块
function StatusBlock(props: { items: StatusItem[]; onNavigate: (hash: string) => void }) {
  return (
    <Block className="y10-home-status card">
      <div className="y10-stats status-row" aria-label="状态项">
        {props.items.map((item) => {
          const value = item.lit ? (item.count !== null ? String(item.count) : item.text) : "无";
          return (
            <button
              key={item.id}
              className={`y10-stat status-item is-${item.id}${item.lit ? " is-lit lit" : ""}${
                item.lit && item.icon === "decide" ? " is-decide" : ""
              }`}
              disabled={!item.lit || item.href === null}
              onClick={() => {
                if (item.href !== null) {
                  props.onNavigate(item.href);
                }
                if (item.anchor !== null) {
                  document.getElementById(item.anchor)?.scrollIntoView({ block: "start" });
                }
              }}
              title={`${item.label}：${value}${item.lit && item.href !== null ? "，点击查看" : ""}`}
            >
              <Icon name={item.icon} className="y10-stat-icon" />
              <span className="y10-stat-label status-label">{item.label}</span>
              <span className="y10-stat-value status-value">{value}</span>
            </button>
          );
        })}
      </div>
    </Block>
  );
}
