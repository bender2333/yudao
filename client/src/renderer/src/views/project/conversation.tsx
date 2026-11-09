// 对话页（工单 #1638，项目的组织设计说明 4.14「项目页是循环图加对话」、4.15「循环图跟着组织长」）。
//
// 页面上半是循环图：按所选事项冻结的组织画节点、成果箭头与结论。图上方的行选事项（默认最近在跑的），
// 点节点、点箭头打开同一个面板。最上面是时间条（工单 #1653）：所选事项的已用时间与上限，在跑时另有「停止」。
// 图右上角的「看经过」展开时序图（工单 #1641）：按轮折起来的经过，展开在循环图下面，不盖住线程；
// 只有一个职能时没有这个按钮，也没有时序图。线程的位置这一页只留出来，由后面的工单接上。
//
// 读的事实：project.loop（冻结的组织、职能状态、轮次、运行）、project.overview（事项标题）、
// project.flow（箭头、你的输入、指导、打回与放行）、work_item.materials（版本与改了的文件）；
// 打开时序图以后另读 run.asks（询问与回答、等待）与 decisions.list（要你决定、你决定）。
// 页面不另存一份，也不按形态名判断。
// 一切「事实推出图」的判断在 loop-graph-model.ts 与 sequence-model.ts 里，那里有单元测试。

import { useMemo, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  DecisionList, ProjectFlowResult, ProjectLoopResult, ProjectOrganizationResult, ProjectOverviewResult,
  RunAsksResult, WorkItemMaterialsResult,
} from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import type { Route } from "../../shell/routing";
import { paths } from "../../shell/routing";
import { Empty, Loading } from "./common";
import { workItemStatusText } from "./labels";
import type { DepartmentView } from "./organization";
import { graphOf, otherCounts, pickItem, type LoopArrow, type LoopItemView } from "./loop-graph-model";
import { LoopGraphView, type LoopPanelPick } from "./loop-graph";
import { LoopPanel } from "./loop-panel";
import { ProjectTimeBar } from "./project-head";
import { SequenceView } from "./sequence";
import { hasSequence, sequenceOf } from "./sequence-model";
import { useSnapshot } from "./use-snapshot";

/** 面板打开的那一个，连同它在哪件事项上打开：换了事项就收起，不在新图上留着旧的一版。 */
type PanelState = { item: string | null; value: LoopPanelPick };

export function ConversationPage(props: {
  app: ClientApp;
  route: Route;
  departments: DepartmentView[];
  organization: ProjectOrganizationResult | null;
  onNavigate: (hash: string) => void;
}) {
  const projectId = props.route.projectId ?? "";
  // 每个事项冻结的组织与它在这件事项上的状态（project.loop）
  const loop = useSnapshot<ProjectLoopResult>(props.app, "page.conversation.loop", "project.loop", {
    project_id: projectId,
  });
  // 事项标题（图上方选事项那一行用）
  const overview = useSnapshot<ProjectOverviewResult>(props.app, "page.conversation.overview", "project.overview", {
    project_id: projectId,
  });
  const items = useMemo<LoopItemView[]>(() => loop.data?.work_items ?? [], [loop.data]);
  const titles = useMemo(() => {
    const map: Record<string, string> = {};
    for (const card of overview.data?.work_items ?? []) {
      map[card.work_item_id] = card.title;
    }
    return map;
  }, [overview.data]);
  // 图上画哪件事项：地址里写了就画它，没有时画最近在跑的那一件
  const item = useMemo(() => pickItem(items, props.route.workItemId), [items, props.route.workItemId]);
  const itemId = item?.work_item_id ?? "";
  // 箭头读 project.flow，版本与改了的文件读 work_item.materials；两处都按所选事项过滤
  const flow = useSnapshot<ProjectFlowResult>(props.app, "page.conversation.flow", "project.flow", {
    project_id: projectId,
    work_item: itemId,
  }, item === null);
  const materials = useSnapshot<WorkItemMaterialsResult>(props.app, "page.conversation.materials", "work_item.materials", {
    project_id: projectId,
    work_item: itemId,
  }, item === null);
  const labels = useMemo(() => {
    const merged: Record<string, string> = {};
    for (const department of props.departments) {
      merged[department.id] = department.label;
    }
    return merged;
  }, [props.departments]);
  // 接来源的职能取项目现在组织的来源，只在形态与事项冻结的一致时用（见 loop-graph-model 的 receiverOf）
  const current = useMemo(() => ({
    form: props.organization?.form ?? null,
    sources: props.organization?.organization?.sources ?? null,
  }), [props.organization]);
  const currentRoles = useMemo(() => props.departments.map((department) => department.id), [props.departments]);
  const others = useMemo(() => otherCounts(items, itemId === "" ? null : itemId), [items, itemId]);
  const graph = useMemo(() => graphOf({
    item,
    flow: flow.data?.records ?? [],
    materials: materials.data,
    labels,
    current,
    currentRoles,
    others,
  }), [item, flow.data, materials.data, labels, current, currentRoles, others]);
  // 同一个面板里逐版看：按出现顺序排的箭头
  const arrows = useMemo<LoopArrow[]>(() => [
    ...graph.gaps.flat(), ...graph.skip, ...graph.side.flatMap((part) => part.arrows),
  ], [graph]);
  const [panel, setPanel] = useState<PanelState>({ item: null, value: null });
  const pick: LoopPanelPick = panel.item === itemId ? panel.value : null;
  const open = (value: LoopPanelPick): void => setPanel({ item: itemId, value });
  // 时序图（工单 #1641）：图右上角的「看经过」展开它；展开以后才读询问与决定，收起来就不再读
  const [sequenceOpen, setSequenceOpen] = useState(false);
  // 展开的是哪几轮：没有点过时按模型给的默认（只展开最新一轮）；挂了哪一件事项一起记，换了事项就不留着旧选择
  const [roundPick, setRoundPick] = useState<{ item: string; rounds: readonly number[] } | null>(null);
  const openRounds = roundPick?.item === itemId ? roundPick.rounds : null;
  const runId = useMemo(
    () => loop.data?.work_items.find((card) => card.work_item_id === itemId)?.run_id ?? "",
    [loop.data, itemId],
  );
  const asks = useSnapshot<RunAsksResult>(props.app, "page.conversation.asks", "run.asks", {
    run_id: runId,
  }, item === null || !sequenceOpen || runId === "");
  const decisions = useSnapshot<DecisionList>(props.app, "page.conversation.decisions", "decisions.list", {
    project_id: projectId,
    work_item_id: itemId,
  }, item === null || !sequenceOpen);
  // 列是这个事项冻结的组织里的职能和你（显示名用项目现在组织的名字，旧组织里的用冻结的那一份）
  const roles = useMemo(
    () => (item?.organization?.roles ?? []).map((role) => ({ id: role.id, label: labels[role.id] ?? role.label })),
    [item, labels],
  );
  const sequence = useMemo(() => sequenceOf({
    roles,
    flow: flow.data?.records ?? [],
    asks: asks.data?.asks ?? [],
    decisions: decisions.data?.decisions ?? [],
    materials: materials.data,
    // 「现在」：还没等到的色条画到这里。按这一份事实算一次，不跟着每次重算而抖
    now: new Date().toISOString(),
    openRounds,
  }), [roles, flow.data, asks.data, decisions.data, materials.data, openRounds]);
  const toggleRound = (round: number): void => {
    const shown = openRounds ?? sequence.rounds.filter((entry) => entry.open).map((entry) => entry.round);
    setRoundPick({
      item: itemId,
      rounds: shown.includes(round) ? shown.filter((value) => value !== round) : [...shown, round],
    });
  };

  return (
    <div className="y10-cv-page y10-pp" data-testid="conversation-page">
      <Loading state={loop} />
      {loop.error === null ? null : <Empty text={readFailureText(loop.error)} />}
      {/* 时间条在对话上方，每种组织都有（项目的组织设计说明 4.15）：选中事项的已用时间与上限，
          在跑时旁边一个「停止」。没有事项时没有这一条 */}
      <ProjectTimeBar app={props.app} items={loop.data?.work_items ?? []} selected={itemId} />
      {loop.data === null ? null : items.length === 0 ? (
        <Empty text="这个项目还没有事项。提出问题以后，循环图按那件事项冻结的组织长出来。" />
      ) : (
        <>
          <ItemPicker
            items={items}
            titles={titles}
            selected={itemId}
            onPick={(workItem) => props.onNavigate(paths.conversation(projectId, { workItem }))}
          />
          {item === null ? null : item.organization == null ? (
            <Empty text="这件事项冻结的组织不在这一版发布里，图上没有可画的节点。" />
          ) : (
            <>
              {/* 图右上角的入口（工单 #1641）：只有一个职能时没有「看经过」，也没有时序图（设计说明 4.15） */}
              {hasSequence(roles) ? (
                <div className="y10-cv-tools">
                  <button type="button" className="y10-btn small" aria-pressed={sequenceOpen}
                          data-testid="show-sequence" onClick={() => setSequenceOpen(!sequenceOpen)}>
                    看经过
                  </button>
                </div>
              ) : null}
              <LoopGraphView
                graph={graph}
                pick={pick}
                onPickNode={(id) => open({ kind: "node", id })}
                onPickArrow={(arrow) => open({ kind: "arrow", arrow })}
              />
              <LoopPanel
                graph={graph}
                arrows={arrows}
                pick={pick}
                onPickArrow={(arrow) => open({ kind: "arrow", arrow })}
                onClose={() => open(null)}
              />
              {/* 时序图展开在循环图下面，不是单独的页，也不盖住线程 */}
              {sequenceOpen && hasSequence(roles) ? (
                <>
                  {asks.error === null ? null : <Empty text={readFailureText(asks.error)} />}
                  {decisions.error === null ? null : <Empty text={readFailureText(decisions.error)} />}
                  <SequenceView view={sequence} onClose={() => setSequenceOpen(false)} onToggleRound={toggleRound} />
                </>
              ) : null}
            </>
          )}
          {flow.error === null ? null : <Empty text={readFailureText(flow.error)} />}
          {materials.error === null ? null : <Empty text={readFailureText(materials.error)} />}
          {/* 线程的位置：这一页只留出位置，线程与时序图由后面的工单接上（窄屏时也不被图挤掉） */}
          <section className="y10-cv-thread" aria-label="对话线程">
            <p className="y10-note">
              线程留在这里：你的输入、要你决定的话、交完成与放行，以及职能之间的往来折成的行，由后面的工单接上。
            </p>
          </section>
        </>
      )}
    </div>
  );
}

/** 图上方一行选事项：默认最近在跑的那一件，点别的切过去；只有一件事项时不出现这一行。 */
function ItemPicker(props: {
  items: LoopItemView[];
  titles: Record<string, string>;
  selected: string;
  onPick: (workItem: string) => void;
}) {
  const only = props.items[0];
  if (only === undefined) {
    return null;
  }
  if (props.items.length < 2) {
    return (
      <p className="y10-cv-only" data-testid="item-picker">
        图上画「{props.titles[only.work_item_id] ?? only.work_item_id}」
        {only.round === 0 ? null : <span className="y10-muted"> · 第 {only.round} 轮</span>}
      </p>
    );
  }
  return (
    <div className="y10-cv-pick" role="tablist" aria-label="选事项" data-testid="item-picker">
      <span className="y10-muted">图上画</span>
      {props.items.map((item) => (
        <button
          key={item.work_item_id}
          type="button"
          role="tab"
          aria-selected={item.work_item_id === props.selected}
          className={`y10-cv-pick-btn${item.work_item_id === props.selected ? " is-on" : ""}`}
          onClick={() => props.onPick(item.work_item_id)}
        >
          {props.titles[item.work_item_id] ?? item.work_item_id}
          <small> {workItemStatusText(item)}</small>
        </button>
      ))}
    </div>
  );
}
