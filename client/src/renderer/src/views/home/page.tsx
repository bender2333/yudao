// 系统首页（原型 v8 设计说明第 4 节，工单 #175）：从上到下依次是状态项、楼、待你决定、
// 离开期间的报告、项目列表。数据来自 system.status、decisions.list、home.away_report 与 projects.list。
// 楼由像素画面五（#178）画出（views/home/building-section）。页面上的数据都来自查询与事件流。

import { useEffect, useMemo, useState } from "react";
import type {
  AwayReport,
  DecisionList,
  DecisionView,
  ProjectList,
  ProjectOverviewResult,
} from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { Loading, Section, hasCommand } from "../project/common";
import { formatTime } from "../project/labels";
import { useCommand, useSnapshot } from "../project/use-snapshot";
import { DecisionCardList } from "../decisions/card";
import { sortByRequested } from "../decisions/card-logic";
import { statusItems, type StatusItem } from "./status-items";
import { BuildingSection } from "./building-section";

const RANGE_LABELS: Record<string, string> = { since_seen: "自上次查看", "24h": "最近 24 小时", "7d": "最近 7 天" };

export type AwayRangeId = "since_seen" | "24h" | "7d";

export function HomePage(props: { app: ClientApp; onNavigate: (hash: string) => void }) {
  const [range, setRange] = useState<AwayRangeId>("since_seen");
  const [openItem, setOpenItem] = useState<string | null>(null);

  const changeRange = (next: AwayRangeId) => {
    setRange(next);
    setOpenItem(null);
  };

  const decisions = useSnapshot<DecisionList>(
    props.app,
    "page.home.decisions",
    "decisions.list",
    { status: ["open"] },
  );
  const report = useSnapshot<AwayReport>(props.app, "page.home.report", "home.away_report", { range });
  const projects = useSnapshot<ProjectList>(props.app, "page.home.projects", "projects.list", {});

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

  return (
    <div className="page home">
      <Loading state={decisions} />
      <StatusRow items={items} onNavigate={props.onNavigate} />

      <BuildingSection app={props.app} projects={projects.data} onNavigate={props.onNavigate} />

      <Section title="待你决定" note="跨项目，按发出时间排列">
        <DecisionNames
          app={props.app}
          decisions={waiting}
          now={now}
          projectNames={projectNames}
          onNavigate={props.onNavigate}
        />
      </Section>

      <AwayReportSection
        app={props.app}
        report={report}
        range={range}
        onRange={changeRange}
        openItem={openItem}
        onToggleItem={(id) => setOpenItem(openItem === id ? null : id)}
      />

      <Section title="项目" note="数据来自 projects.list">
        {projects.data === null ? (
          <Loading state={projects} />
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
                {projects.data.projects
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

// 待你决定：跨项目的决定卡片。事项标题由 project.overview 解析（决定请求只带标识），
// 解析不到时回落到标识本身。项目名由 projects.list 给出。
function DecisionNames(props: {
  app: ClientApp;
  decisions: DecisionView[];
  now: number;
  projectNames: Record<string, string>;
  onNavigate: (hash: string) => void;
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
    <div className="status-row" aria-label="状态项">
      {props.items.map((item) => {
        const value = item.lit ? (item.count !== null ? String(item.count) : item.text) : "无";
        return (
          <button
            key={item.id}
            type="button"
            className={`status-item${item.lit ? " lit" : ""}`}
            disabled={!item.lit || item.href === null}
            onClick={() => {
              if (item.href !== null) {
                props.onNavigate(item.href);
              }
            }}
            title={`${item.label}：${value}${item.lit && item.href !== null ? "，点击查看" : ""}`}
          >
            <span className="status-label">{item.label}</span>
            <span className="status-value">{value}</span>
          </button>
        );
      })}
    </div>
  );
}

// 离开期间的报告（第 4.4 节）：上次查看的时间、范围切换、「已看过」（home.mark_seen）；
// 汇总项取自 home.away_report，每项数字可以点击，展开来源事件；没有来源事件的项不显示。
// 时间轴与画面的回放由像素画面六（#180）实现，这里只留出位置。
function AwayReportSection(props: {
  app: ClientApp;
  report: { data: AwayReport | null; loading: boolean };
  range: AwayRangeId;
  onRange: (range: AwayRangeId) => void;
  openItem: string | null;
  onToggleItem: (id: string) => void;
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
          ? "数据来自 home.away_report"
          : `上次查看：${formatTime(data.last_seen.at)}`
      }
    >
      <div className="row-actions">
        {ranges.map((option) => (
          <button
            key={option.id}
            type="button"
            className={option.id === props.range ? "primary" : ""}
            onClick={() => props.onRange(option.id as AwayRangeId)}
          >
            {option.label}
          </button>
        ))}
        {hasCommand(props.app, "home.mark_seen") && data !== null ? (
          <button
            type="button"
            className="primary"
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
        <p className="note">这段时间没有完成、放行或其他需要报告的事（范围：{rangeLabel}）</p>
      ) : (
        <>
          <div className="report-items">
            {data.summary.map((item) => (
              <div key={item.id} className={`report-item${props.openItem === item.id ? " open" : ""}`}>
                <button type="button" className="report-head" onClick={() => props.onToggleItem(item.id)}>
                  <span className="report-label">{item.label}</span>
                  <span className="report-value">
                    {item.value}
                    <small>{item.unit}</small>
                  </span>
                  {item.detail ? <span className="report-detail">{item.detail}</span> : null}
                </button>
                {props.openItem === item.id ? (
                  item.refs.length === 0 ? (
                    <p className="note">{item.detail ?? ""}（来源：范围内的调用尝试记录）</p>
                  ) : (
                    <ul className="source-list">
                      {item.refs.map((position) => {
                        const fact = data.facts.find((row) => row.position === position);
                        return (
                          <li key={position}>
                            <span className="note">{formatTime(fact?.at ?? null)}</span>{" "}
                            {fact?.label ?? "来源事件"}{" "}
                            <code>{fact?.type ?? `事件 ${position}`}</code>
                          </li>
                        );
                      })}
                    </ul>
                  )
                ) : null}
              </div>
            ))}
          </div>
          <p className="note">关键事实 {data.facts.length} 条；时间轴与画面的回放由像素画面六（#180）实现。</p>
        </>
      )}
    </Section>
  );
}
