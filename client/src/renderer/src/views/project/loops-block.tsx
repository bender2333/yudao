// 观测页「循环」区块（工单 #400，原型 v10 设计说明第 4 节）：按事项一棵循环树的投影，
// 每行一个循环实例：层、实例、轮次、已用量与上限、收敛状态、停止原因；「不判定」的行写明缺少的事实。
// 数据只来自 run.loops（工单 #397），判定在投影里做——页面只照查询结果写，不搬判定，也不用假数据补位。

import type { ClientApp } from "../../contract/client-app";
import type { ProjectOverviewResult, RunLoopsResult } from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import { loopRows, loopRuleText, type LoopRow } from "../../translate/floor";
import { Empty, Section, Table, Tag } from "./common";
import { useSnapshot } from "./use-snapshot";

/** 观测页要显示循环树的事项：事项、标题与它的运行实例（project.overview 里的当前运行）。 */
export interface LoopItemRef {
  workItemId: string;
  title: string;
  runId: string;
}

export function loopItems(overview: ProjectOverviewResult | null, workItem: string | null): LoopItemRef[] {
  // 按观测页当前选中的事项过滤；没有选定时列出全部事项
  return (overview?.work_items ?? [])
    .filter((item) => (workItem ? item.work_item_id === workItem : true))
    .map((item) => ({ workItemId: item.work_item_id, title: item.title, runId: item.run_id }));
}

const STATE_TONE: Readonly<Record<string, "ok" | "warn" | "danger" | "muted">> = Object.freeze({
  converging: "ok",
  stalled: "warn",
  oscillating: "warn",
  drifting: "warn",
  boundary: "danger",
  undetermined: "muted",
});

/** 「循环」区块：每个事项一棵树。没有事项时不出现这一块（观测页没有可看的东西，不写空位）。 */
export function LoopsBlock(props: { app: ClientApp; items: LoopItemRef[] }): React.JSX.Element | null {
  if (props.items.length === 0) return null;
  return (
    <Section id="observe-loops" title="循环"
             note="循环实例的层、已用边界与收敛状态；判定依据有缺少的事实时写「不判定」与缺少的事实">
      {props.items.map((item) => (
        <LoopsTree key={item.runId} app={props.app} item={item} />
      ))}
    </Section>
  );
}

function LoopsTree(props: { app: ClientApp; item: LoopItemRef }): React.JSX.Element {
  const loops = useSnapshot<RunLoopsResult>(props.app, `page.observe.loops.${props.item.runId}`, "run.loops", {
    run_id: props.item.runId,
  });
  const rows = loopRows(loops.data);
  return (
    <div className="y10-block-sub">
      <h3 className="y10-sub-title">{props.item.title}</h3>
      {loops.loading && loops.data === null ? <Empty text="正在读取循环状态…" /> : null}
      {loops.error !== null ? <Empty text={readFailureText(loops.error)} /> : null}
      {loops.data !== null ? (
        <>
          <Table head={["层", "实例", "轮次", "已用量与上限", "收敛状态", "停止原因"]}
                 rows={rows.map((row) => loopCells(row))} />
          <details className="y10-details" open>
            <summary>判定依据</summary>
            <p className="y10-note note">{loopRuleText(loops.data)}</p>
            <ul className="y10-list">
              {rows.filter((row) => row.missing !== "").map((row) => (
                <li key={row.key}>{row.layerLabel} · {row.instance}：{row.missing}</li>
              ))}
            </ul>
          </details>
        </>
      ) : null}
    </div>
  );
}

function loopCells(row: LoopRow): React.ReactNode[] {
  return [
    row.layerLabel,
    row.instance,
    row.rounds === null ? "—" : String(row.rounds),
    row.used,
    <Tag key={`state-${row.key}`} tone={STATE_TONE[row.state] ?? "muted"}>{row.stateLabel}</Tag>,
    row.stopReason === "" ? "—" : row.stopReason,
  ];
}
