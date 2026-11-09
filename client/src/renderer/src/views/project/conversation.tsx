// 对话页（工单 #1638、#1639、#1641、#1643，项目的组织设计说明 4.14「项目页是循环图加对话」、4.15「循环图跟着组织长」）。
//
// 页面上半是循环图：按所选事项冻结的组织画节点、成果箭头与结论。图上方的行选事项（默认最近在跑的），
// 点节点、点箭头打开同一个面板。最上面是时间条（工单 #1653）：所选事项的已用时间与上限，在跑时另有「停止」。
// 图右上角的「看经过」展开时序图（工单 #1641）：按轮折起来的经过，展开在循环图下面，不盖住线程。
// 点时序图上的一行打开同一个面板（工单 #1643）：成果是那一版与差异，问答与你的话是全文。
// 下面是线程与输入框（工单 #1639）：一条线程跨多个事项，已结束的事项默认收起；输入框上方一行收件人。
// 线程的折叠行展开以后末尾有「在时序图里看」：只看这两个职能的时序图（工单 #1643）。
//
// 读的事实：project.loop（冻结的组织、职能状态、轮次与 run）、project.overview（事项标题）、
// project.flow（箭头，以及线程里你的输入、指导、交完成与放行）、work_item.materials（版本与改了的文件）、
// decisions.list（要你决定的气泡）、run.asks（每个展开的事项各读一次，线程与时序图的问答都从它来）、
// system.status（模型可不可用）。页面不另存一份，也不按形态名判断。
// 一切「事实推出图与线程」的判断在 loop-graph-model.ts、sequence-model.ts 与 thread-model.ts 里，三处都有单元测试。

import { useEffect, useMemo, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  DecisionList, DecisionView, ProjectFlowResult, ProjectLoopResult, ProjectOrganizationResult, ProjectOverviewResult,
  RunAsksResult, SystemStatus, WorkItemMaterialsResult,
} from "../../api/generated/types.gen";
import { readFailureText } from "../../contract/read-failure";
import { providerNotice } from "../../shell/provider-status";
import type { Route } from "../../shell/routing";
import { paths } from "../../shell/routing";
import { Empty, Loading } from "./common";
import { Composer } from "./composer";
import { workItemStatusText } from "./labels";
import type { DepartmentView } from "./organization";
import { graphOf, otherCounts, pickItem, type LoopArrow, type LoopItemView } from "./loop-graph-model";
import { LoopGraphView, type LoopPanelPick } from "./loop-graph";
import { LoopPanel, type LoopPanelTarget } from "./loop-panel";
import { ProjectTimeBar } from "./project-head";
import { SequenceView } from "./sequence";
import { hasSequence, sequenceOf, type SequenceRow } from "./sequence-model";
import { ThreadView } from "./thread";
import {
  receiverOf, runningItem, workingRoleOf, type ComposerInput,
} from "./thread-model";
import { useSnapshot } from "./use-snapshot";

/** 面板打开的那一个，连同它在哪件事项上打开：换了事项就收起，不在新图上留着旧的一版。 */
type PanelState = { item: string | null; value: LoopPanelTarget };

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
  // 事项标题（图上方选事项那一行与线程里的事项细线用）
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
  // 流转记录读整个项目（线程跨多个事项），画图与时序图时再按所选事项过滤
  const flow = useSnapshot<ProjectFlowResult>(props.app, "page.conversation.flow", "project.flow", {
    project_id: projectId,
  });
  const records = useMemo(() => flow.data?.records ?? [], [flow.data]);
  const itemFlow = useMemo(() => records.filter((record) => record.work_item_id === itemId), [records, itemId]);
  // 版本与改了的文件按所选事项读（面板里逐版看用）
  const materials = useSnapshot<WorkItemMaterialsResult>(props.app, "page.conversation.materials", "work_item.materials", {
    project_id: projectId,
    work_item: itemId,
  }, item === null);
  // 要你决定的气泡（项目这一层；线程里按事项与项目层面分开摆，时序图只用所选事项的那几条）
  const decisions = useSnapshot<DecisionList>(props.app, "page.conversation.decisions", "decisions.list", {
    project_id: projectId,
  });
  const decisionList = useMemo<DecisionView[]>(() => decisions.data?.decisions ?? [], [decisions.data]);
  const itemDecisions = useMemo(
    () => decisionList.filter((decision) => decision.work_item_id === itemId),
    [decisionList, itemId],
  );
  // 模型可不可用：没有可用的模型时对话里一句话提示并链到模型管理，写明不能开始
  const status = useSnapshot<SystemStatus>(props.app, "page.conversation.status", "system.status", {});
  const provider = providerNotice(status.data?.provider ?? null);
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
  const departmentChoices = useMemo(
    () => props.departments.map((department) => ({ id: department.id, label: department.label })),
    [props.departments],
  );
  const others = useMemo(() => otherCounts(items, itemId === "" ? null : itemId), [items, itemId]);
  const graph = useMemo(() => graphOf({
    item,
    flow: itemFlow,
    materials: materials.data,
    labels,
    current,
    currentRoles,
    others,
  }), [item, itemFlow, materials.data, labels, current, currentRoles, others]);
  // 同一个面板里逐版看：按出现顺序排的箭头
  const arrows = useMemo<LoopArrow[]>(() => [
    ...graph.gaps.flat(), ...graph.skip, ...graph.side.flatMap((part) => part.arrows),
  ], [graph]);
  const [panel, setPanel] = useState<PanelState>({ item: null, value: null });
  const pick: LoopPanelTarget = panel.item === itemId ? panel.value : null;
  // 图上标出选中的节点或箭头：时序图上那一行在图上打开的是箭头，两处标的是同一样
  const graphPick: LoopPanelPick = pick !== null && (pick.kind === "node" || pick.kind === "arrow") ? pick : null;
  const open = (value: LoopPanelTarget): void => setPanel({ item: itemId, value });
  // 时序图（工单 #1641）：图右上角的「看经过」展开它；展开以后才读询问（决定请求线程里一直在读）
  const [sequenceOpen, setSequenceOpen] = useState(false);
  // 展开的是哪几轮：没有点过时按模型给的默认（只展开最新一轮）；挂了哪一件事项一起记，换了事项就不留着旧选择
  const [roundPick, setRoundPick] = useState<{ item: string; rounds: readonly number[] } | null>(null);
  const openRounds = roundPick?.item === itemId ? roundPick.rounds : null;
  // 只看这两个职能（线程折叠行的「在时序图里看」）：挂在哪件事项上一块记，换了事项就不留着
  const [pair, setPair] = useState<{ item: string; roles: readonly string[] } | null>(null);
  // 点的折叠行在别的事项上：切过去以后（数据到了才）展开只看这两个职能的时序图
  const [pendingSequence, setPendingSequence] = useState<{ item: string; roles: readonly string[] } | null>(null);
  // 时序图展开在循环图下面：从线程里点过来时把它带到眼前；面板在时序图下面，点一行时也把它带到眼前
  const sequenceRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const runId = useMemo(
    () => loop.data?.work_items.find((card) => card.work_item_id === itemId)?.run_id ?? "",
    [loop.data, itemId],
  );
  const asks = useSnapshot<RunAsksResult>(props.app, "page.conversation.asks", "run.asks", {
    run_id: runId,
  }, item === null || !sequenceOpen || runId === "");
  // 列是这个事项冻结的组织里的职能和你（显示名用项目现在组织的名字，旧组织里的用冻结的那一份）
  const roles = useMemo(
    () => (item?.organization?.roles ?? []).map((role) => ({ id: role.id, label: labels[role.id] ?? role.label })),
    [item, labels],
  );
  const sequence = useMemo(() => sequenceOf({
    roles,
    flow: itemFlow,
    asks: asks.data?.asks ?? [],
    decisions: itemDecisions,
    materials: materials.data,
    verifiers: item?.organization?.verifiers ?? [],
    pair: pair !== null && pair.item === itemId ? pair.roles : null,
    // 「现在」：还没等到的色条画到这里。按这一份事实算一次，不跟着每次重算而抖
    now: new Date().toISOString(),
    openRounds,
  }), [roles, itemFlow, asks.data, itemDecisions, materials.data, item, pair, itemId, openRounds]);
  const toggleRound = (round: number): void => {
    const shown = openRounds ?? sequence.rounds.filter((entry) => entry.open).map((entry) => entry.round);
    setRoundPick({
      item: itemId,
      rounds: shown.includes(round) ? shown.filter((value) => value !== round) : [...shown, round],
    });
  };
  // 点时序图的一行：成果那一行用图上那条箭头（那一版与差异），其余打开全文
  const openRow = (row: SequenceRow): void => {
    const detail = row.detail;
    const arrow = detail.kind === "outcome"
      ? arrows.find((candidate) => detail.flowIds.includes(candidate.key))
      : undefined;
    open(arrow === undefined ? { kind: "row", row } : { kind: "arrow", arrow });
  };
  // 面板上标出来的那一行：成果那一行按它找到的箭头认
  const pickedKey = pick === null
    ? null
    : pick.kind === "row" ? pick.row.key : pick.kind === "arrow" ? pick.arrow.key : null;
  // 只看这两个职能的时序图（线程折叠行末尾的「在时序图里看」）：折叠行在别的事项上时先切过去
  const showPair = (workItem: string, pairRoles: readonly string[]): void => {
    if (workItem !== itemId) {
      setPendingSequence({ item: workItem, roles: pairRoles });
      props.onNavigate(paths.conversation(projectId, { workItem }));
      return;
    }
    setPair({ item: workItem, roles: pairRoles });
    setSequenceOpen(true);
  };
  useEffect(() => {
    if (pendingSequence === null || pendingSequence.item !== itemId) {
      return;
    }
    setPair(pendingSequence);
    setSequenceOpen(true);
    setPendingSequence(null);
  }, [pendingSequence, itemId]);
  useEffect(() => {
    if (!sequenceOpen) {
      return;
    }
    sequenceRef.current?.scrollIntoView({ block: "nearest" });
  }, [sequenceOpen, pair, itemId]);
  useEffect(() => {
    if (pick === null) {
      return;
    }
    panelRef.current?.scrollIntoView({ block: "nearest" });
  }, [pick]);

  // 线程（工单 #1639）：展开过的结束事项、点过的节点（收件人跟着切到给它的指导）、发送以后滚到最新一条
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const [focus, setFocus] = useState<string | null>(null);
  const [scrollSignal, setScrollSignal] = useState(0);
  // 「看这一版」点的是别的事项：切过去以后在它的图上打开那条箭头（数据到了才打开）
  const [pendingLook, setPendingLook] = useState<{ item: string; flowId: string } | null>(null);
  useEffect(() => {
    if (pendingLook === null || pendingLook.item !== itemId) {
      return;
    }
    const arrow = arrows.find((candidate) => candidate.key === pendingLook.flowId);
    if (arrow === undefined) {
      return;
    }
    setPanel({ item: itemId, value: { kind: "arrow", arrow } });
    setPendingLook(null);
  }, [pendingLook, itemId, arrows]);

  const look = (workItem: string, flowId: string): void => {
    if (workItem !== itemId) {
      setPendingLook({ item: workItem, flowId });
      props.onNavigate(paths.conversation(projectId, { workItem }));
      return;
    }
    const arrow = arrows.find((candidate) => candidate.key === flowId);
    if (arrow !== undefined) {
      open({ kind: "arrow", arrow });
    }
  };

  // 收件人一行读正在做的那件事项冻结的组织（换过形态以后仍按它）；没有在跑事项时用项目现在的组织。
  // 图上选中的那件还在跑时就用它自己的那一份（选中事项冻结的组织），否则用最近在跑的一件。
  const running = useMemo(() => runningItem(items), [items]);
  const composerItem = item !== null && (item.status === "in_progress" || item.status === "awaiting_initial_prd")
    ? item : running;
  const composerFlow = useMemo(
    () => records.filter((record) => record.work_item_id === composerItem?.work_item_id),
    [records, composerItem],
  );
  const composerInput = useMemo<ComposerInput>(() => {
    const organization = composerItem?.organization ?? null;
    const roleChoices = organization === null ? departmentChoices : organization.roles;
    const routing = organization?.routing ?? props.organization?.organization?.routing ?? "direct";
    const receiver = organization === null
      ? props.organization?.organization?.sources?.user_input ?? departmentChoices[0]?.id ?? ""
      : receiverOf(organization, composerFlow, current);
    return {
      frozen: organization, roles: roleChoices, routing, receiver, working: workingRoleOf(composerItem),
      focus, active: composerItem !== null, labels,
    };
  }, [composerItem, composerFlow, departmentChoices, props.organization, current, focus, labels]);

  return (
    <div className="y10-cv-page y10-pp" data-testid="conversation-page">
      <Loading state={loop} />
      {loop.error === null ? null : <Empty text={readFailureText(loop.error)} />}
      {/* 时间条在对话上方，每种组织都有（项目的组织设计说明 4.15）：选中事项的已用时间与上限，
          在跑时旁边一个「停止」。没有事项时没有这一条 */}
      <ProjectTimeBar app={props.app} items={loop.data?.work_items ?? []} selected={itemId} />
      {loop.data === null ? null : (
        <>
          {items.length === 0 ? (
            <Empty text="这个项目还没有事项。在下面写一句，就开始做。" />
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
                              data-testid="show-sequence" onClick={() => {
                                // 「看经过」看整件事：只看过两个职能时点它回到整件事，已经看整件事时收起
                                if (sequenceOpen && (pair === null || pair.item !== itemId)) {
                                  setSequenceOpen(false);
                                } else {
                                  setPair(null);
                                  setSequenceOpen(true);
                                }
                              }}>
                        看经过
                      </button>
                    </div>
                  ) : null}
                  <LoopGraphView
                    graph={graph}
                    pick={graphPick}
                    onPickNode={(id) => {
                      // 点节点：看这个职能，收件人跟着切到给它的指导（项目的组织设计说明 4.14）
                      setFocus(id);
                      open({ kind: "node", id });
                    }}
                    onPickArrow={(arrow) => open({ kind: "arrow", arrow })}
                  />
                  {/* 时序图展开在循环图下面，不是单独的页，也不盖住线程 */}
                  {sequenceOpen && hasSequence(roles) ? (
                    <div ref={sequenceRef}>
                      {asks.error === null ? null : <Empty text={readFailureText(asks.error)} />}
                      <SequenceView
                        view={sequence}
                        pickedKey={pickedKey}
                        onPickRow={openRow}
                        onShowAll={() => setPair(null)}
                        onClose={() => setSequenceOpen(false)}
                        onToggleRound={toggleRound}
                      />
                    </div>
                  ) : null}
                  {/* 面板在图的下面（时序图展开时在它下面）：点节点、点箭头与点时序图的一行都是这一个 */}
                  {pick === null ? null : (
                    <div ref={panelRef}>
                      <LoopPanel
                        graph={graph}
                        arrows={arrows}
                        pick={pick}
                        onPickArrow={(arrow) => open({ kind: "arrow", arrow })}
                        onClose={() => open(null)}
                      />
                    </div>
                  )}
                </>
              )}
              {flow.error === null ? null : <Empty text={readFailureText(flow.error)} />}
              {materials.error === null ? null : <Empty text={readFailureText(materials.error)} />}
            </>
          )}
          {provider === null ? null : (
            <p className="y10-cv-model" role="status">
              {provider.label}{provider.detail === "" ? "" : `：${provider.detail}`}。现在不能开始新事项。
              <button type="button" className="y10-link" onClick={() => props.onNavigate(paths.sys("models"))}>
                去模型管理
              </button>
            </p>
          )}
          {items.length === 0 ? null : (
            <ThreadView
              app={props.app}
              items={items}
              titles={titles}
              flow={records}
              decisions={decisionList}
              labels={labels}
              selected={itemId}
              opened={opened}
              onToggleItem={(workItem) => setOpened((previous) => ({ ...previous, [workItem]: !previous[workItem] }))}
              onSelectItem={(workItem) => props.onNavigate(paths.conversation(projectId, { workItem }))}
              onLook={look}
              onSequence={showPair}
              onNavigate={props.onNavigate}
              scrollSignal={scrollSignal}
            />
          )}
          <Composer
            app={props.app}
            projectId={projectId}
            input={composerInput}
            activeItemId={composerItem?.work_item_id ?? null}
            activeTitle={composerItem === null ? "" : titles[composerItem.work_item_id] ?? "这件事项"}
            dataKey={`${items.length}:${records.length}`}
            onSent={() => setScrollSignal((value) => value + 1)}
          />
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
