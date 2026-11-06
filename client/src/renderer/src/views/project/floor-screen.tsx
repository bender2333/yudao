// 概览页的循环：事项的文字列表与等待回答的决定请求（工单 #82、#953）。
//
// 画面搬出（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」，工单 #1418）：
// 楼层画布、覆盖层与回放随画面搬进 view/；这一节只留页面文字，数据仍取 project.loop 与 decisions.list，
// 与画布同一份查询结果。页面不导入画面与翻译层。
//
// 工单 #1416：原来只在画布上看得到的部门、轮次与中断状态已在页面的「部门」「中断与待恢复」两节；
// 这里留的是每个事项一行的列表与可以同样回答的决定卡片。

import { useMemo } from "react";
import type { DecisionList, DecisionView, ProjectLoopResult } from "../../api/generated/types.gen";
import type { ClientApp } from "../../contract/client-app";
import { DecisionCardList } from "../decisions/card.tsx";
import { sortByRequested } from "../decisions/card-logic";
import { itemColor } from "./floor-text";
import { WORK_ITEM_STATUS, departmentName, label } from "./labels";
import { useSnapshot } from "./use-snapshot";

/** 文字列表里的一行：按查询结果原样写（页面文字不属于画面）。 */
export interface FloorTextRow {
  work_item_id: string;
  sign: string;
  kind: string;
  color_index: number;
  department: string | null;
  round: number;
  status: string;
}

export interface FloorScreenProps {
  app: ClientApp;
  projectId: string;
  workItemId: string | null;
  /** 回放位置（全局位置）：不为 null 时 project.loop 按位置带 at 读取；回放期间不显示决定请求。 */
  at?: number | null;
}

/** 文字列表里的行：事项本身的状态，不是画面的状态名（工单 #900）。 */
export function floorTextRows(loop: ProjectLoopResult | null): FloorTextRow[] {
  return (loop?.work_items ?? []).map((row, index) => ({
    work_item_id: row.work_item_id,
    sign: row.sign,
    kind: row.kind,
    color_index: row.color_index ?? index + 1,
    department: row.department,
    round: row.round,
    status: row.status,
  }));
}

/** 循环：事项的文字列表与等待回答的决定请求。 */
export function FloorScreen(props: FloorScreenProps): React.JSX.Element {
  const at = props.at ?? null;
  const replaying = at !== null;
  const loop = useSnapshot<ProjectLoopResult>(props.app, "page.loop", "project.loop", {
    project_id: props.projectId,
    work_item: props.workItemId,
    ...(at === null ? {} : { at }),
  });
  // 回放到过去的时间点时不显示决定请求（设计说明第 5.5 节、原型 v13 第 1 节）
  const decisions = useSnapshot<DecisionList>(props.app, "page.decisions", "decisions.list", {
    project_id: props.projectId, status: ["open"],
  }, replaying);
  // 文字列表里的决定请求：与页面卡片同源的查询结果，按发出时间排列
  const openDecisions = useMemo(
    () => sortByRequested((decisions.data?.decisions ?? []).filter((d) => d.status === "open")),
    [decisions.data],
  );
  const rows = useMemo(() => floorTextRows(loop.data), [loop.data]);

  return (
    <div className="floor-screen">
      <FloorTextList rows={rows} decisions={openDecisions} app={props.app} />
    </div>
  );
}

/** 画面下方的文字列表：默认折叠（原型 v13 ui/scenes.js 的 floorList），每一行是事项的色点、
 *  标题、中文部门名、轮次与中文状态；等待回答的决定请求在列表里用页面卡片回答。 */
function FloorTextList(props: {
  rows: FloorTextRow[];
  decisions: DecisionView[];
  app: ClientApp;
}): React.JSX.Element {
  const now = Date.now();
  const titleOfItem = (workItemId: string | null): string =>
    workItemId ? props.rows.find((it) => it.work_item_id === workItemId)?.sign ?? "" : "";
  return (
    <>
      <details className="y10-scene-list floor-text-list">
        <summary>文字列表</summary>
        {props.rows.length === 0 ? <p className="y10-note note">项目还没有事项</p> : (
          <ul>
            {props.rows.map((item) => (
              <li key={item.work_item_id}>
                <span className="y10-dot-color" style={{ "--c": itemColor(item) } as React.CSSProperties} />
                <strong>{item.sign}</strong>
                <span>{item.department === null || item.department === "" ? "大厅" : departmentName(item.department)}</span>
                <span>第 {item.round} 轮</span>
                <span>{label(WORK_ITEM_STATUS, item.status)}</span>
                {item.kind === "onboarding" ? <span className="y10-tag tag">建档</span> : null}
              </li>
            ))}
          </ul>
        )}
        {/* 等待回答的决定请求：与大厅的板同源，用页面卡片，可以同样回答 */}
        <DecisionCardList
          app={props.app}
          decisions={props.decisions}
          now={now}
          names={(decision) => ({ projectName: decision.project_id ?? "", workItemTitle: titleOfItem(decision.work_item_id) })}
          onNavigate={(hash) => {
            window.location.hash = hash.startsWith("#") ? hash.slice(1) : hash;
          }}
          viewId="floor.decisions"
          emptyText="没有等待回答的决定请求"
        />
      </details>
    </>
  );
}
