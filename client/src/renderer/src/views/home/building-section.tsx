// 首页的项目一览（原型 v13 设计说明第 3 至 5 节、原型 js/ui/scenes.js 的 mountBuilding，工单 #178、#955）：
// 每个项目一行，写它此刻在做什么、执行槽位与待你回答的决定。
//
// 画面搬出（画面与播放 docs/design/visualization.md「搬出：画面成为单独的应用」，工单 #1418）：
// 楼的画布与回放随画面搬进 view/，这一节只留页面文字，行由首页取好的 project.loop 推出（工单 #1416）。
// 页面不导入画面与翻译层；原来画在楼上的状态灯与亮灯部门在这里按页面自己的说法写——「此刻在做什么」
// 与「执行槽位」是同一批事实的页面文字。
//
// 这一节与首页「项目」一节的表同源（同一份 project.loop），一行一个项目，放在页面上方作概览。

import { useMemo } from "react";
import type { ProjectList, ProjectLoopResult } from "../../api/generated/types.gen";
import { emptyOrFailureText } from "../../contract/read-failure";
import { projectDoingText, projectSlotText } from "../project/floor-text";
import { Section } from "../project/common";

/** 每个项目的事项查询结果（首页取一次，这一节与「项目」一节共用）。 */
export interface ProjectLoops {
  byProject: Record<string, ProjectLoopResult>;
  /** 读取失败的项目：首页项目一览的三样事实写「读不出来」。 */
  failed: Record<string, boolean>;
  /** 这些查询里最新的位置（画面合同的状态要带位置）。 */
  position: number;
}

export interface BuildingSectionProps {
  projects: ProjectList | null;
  /** 项目列表读取失败时的原因：有它时不说「还没有项目」，说「读不出来」（工单 #728）。 */
  error: string | null;
  /** 回放位置（全局位置）：不为 null 时提示这是回放的位置。 */
  at?: number | null;
  /** 每个项目的 project.loop：此刻在做什么与执行槽位都由它推出。 */
  loops: ProjectLoops;
  onNavigate: (hash: string) => void;
}

/** 一行：一个项目的名称、此刻在做什么、执行槽位与待答的决定。 */
interface FloorRow {
  project_id: string;
  name: string;
  /** project.loop 没读到时的说法：读不出来或正在读取。 */
  loopState: string | null;
  doing: string;
  slot: string;
  decisions: number;
}

/** 每个项目一行：三样事实与项目列表里已有的决定数。 */
export function floorRows(projects: ProjectList | null, loops: ProjectLoops): FloorRow[] {
  return (projects?.projects ?? [])
    .filter((project) => !project.archived)
    .map((project) => {
      const loop = loops.byProject[project.project_id] ?? null;
      const loopState = loops.failed[project.project_id] === true
        ? "读不出来"
        : loop === null ? "正在读取" : null;
      return {
        project_id: project.project_id,
        name: project.name,
        loopState,
        doing: loopState ?? projectDoingText(loop),
        slot: loopState === null ? projectSlotText(loop) : "",
        decisions: project.decisions_waiting,
      };
    });
}

/** 首页的项目一览：每个项目一行的文字，不挂画布。 */
export function BuildingSection(props: BuildingSectionProps): React.JSX.Element {
  const at = props.at ?? null;
  const rows = useMemo(() => floorRows(props.projects, props.loops), [props.projects, props.loops]);

  return (
    <Section className="y10-home-building" title="全部项目与机器" note={at !== null ? "回放中：每个项目一行，按所选位置的快照显示" : "每个项目一行；点击项目名进入项目概览"}>
      {rows.length === 0 ? (
        <p className="y10-note note">{emptyOrFailureText(props.error, "还没有项目")}</p>
      ) : (
        <ul className="building-list">
          {rows.map((row) => (
            <li key={row.project_id}>
              <button type="button" className="link" onClick={() => props.onNavigate(`#/p/${row.project_id}/overview`)}>
                {row.name}
              </button>
              <span>{row.doing}</span>
              {row.slot === "" ? null : <span className="y10-note note">{row.slot}</span>}
              {row.decisions > 0 ? <span className="count">待你决定 {row.decisions}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
