// 对话页（工单 #1638、#1639、#1641、#1643，项目的组织设计说明 4.14「项目页是循环图加对话」、4.15「循环图跟着组织长」）。
//
// 页面上半是循环图：按所选事项冻结的组织画节点、成果箭头与结论。图上方的行选事项（默认最近在跑的），
// 点节点、点箭头打开同一个面板。最上面是时间条（工单 #1653）：所选事项的已用时间与上限，在跑时另有「停止」。
// 图右上角的「看经过」展开时序图（工单 #1641）：按轮折起来的经过，展开在循环图下面，不盖住线程。
// 同一行还有「累计往来」（工单 #1642）：打开以后图上按两个职能合成一条线，写问了几次（次数含开着的）。
// 点图上的询问线（开着的或累计的）只看这两个职能的时序图，上面一行写「只看 A 与 B · 看全部」。
// 点时序图上的一行打开同一个面板（工单 #1643）：成果是那一版与差异，问答与你的话是全文。
// 下面是线程与输入框（工单 #1639）：一条线程跨多个事项，已结束的事项默认收起；输入框上方一行收件人。
// 线程的折叠行展开以后末尾有「在时序图里看」：只看这两个职能的时序图（工单 #1643）。
//
// 读的事实：project.loop（冻结的组织、职能状态、轮次与 run）、project.overview（事项标题）、
// project.flow（箭头，以及线程里你的输入、指导、交完成与放行）、work_item.materials（版本与改了的文件）、
// decisions.list（要你决定的气泡）、run.asks（所选事项的运行：循环图的开着询问、节点的往来、线程与时序图的
// 问答都从它来）、system.status（模型可不可用）。页面不另存一份，也不按形态名判断。
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
import { AllItems, ALL_ITEMS_PICK, type AllItemsPick } from "./all-items";
import { Empty, Loading } from "./common";
import { Composer } from "./composer";
import { interruptionFactRows } from "./floor-text";
import { ItemPanel, ITEM_PANEL_PICK, type ItemPanelPick } from "./item-panel";
import { ItemPicker } from "./item-picker";
import type { DepartmentView } from "./organization";
import { frozenOrganizationOf } from "./form-cards-model";
import { graphOf, otherCounts, pickItem, type LoopArrow, type LoopItemView } from "./loop-graph-model";
import { LoopGraphView, type LoopPanelPick } from "./loop-graph";
import { LoopPanel, type LoopPanelTarget } from "./loop-panel";
import { ProjectTimeBar } from "./project-head";
import { SequenceView } from "./sequence";
import { hasSequence, sequenceOf, type SequenceRow } from "./sequence-model";
import { ThreadView } from "./thread";
import { organizationChangeAfter, type ThreadOrganizationChange } from "./thread-model";
import {
  receiverOf, runningItem, workingRoleOf, type ComposerInput,
} from "./thread-model";
import { useSnapshot } from "./use-snapshot";

/**
 * 面板打开的那一个，连同它在哪件事项上打开：换了事项就收起，不在新图上留着旧的一版。
 * 同一个位置只开一个面板（工单 #1708）：点选事项一行里选中那件的标题开事项面板，
 * 点节点、点箭头、点时序图的一行换成那个面板。
 * 这里还有全部事项的分组列表（工单 #1709）：点选事项一行末尾的「全部事项」开它，
 * 从列表里点一件时图切过去，面板换成那件事项的事项面板。
 */
type PanelState = { item: string | null; value: LoopPanelTarget | ItemPanelPick | AllItemsPick };

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
  // 事项到运行：循环图的开着询问与时序图都读这个运行的 run.asks（接口设计说明 4.4）
  const runId = useMemo(
    () => loop.data?.work_items.find((card) => card.work_item_id === itemId)?.run_id ?? "",
    [loop.data, itemId],
  );
  // 开着的询问一直读：循环图在收起时序图时也要画虚线；答完的也读，节点面板列它的往来
  const asks = useSnapshot<RunAsksResult>(props.app, "page.conversation.asks", "run.asks", {
    run_id: runId,
  }, item === null || runId === "");
  const askList = useMemo(() => asks.data?.asks ?? [], [asks.data]);
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
  // 累计往来（工单 #1642）：由用户点开，同一对职能的询问合成一条线；关掉回到只画开着的询问
  const [accumulated, setAccumulated] = useState(false);
  const graph = useMemo(() => graphOf({
    item,
    flow: itemFlow,
    materials: materials.data,
    labels,
    current,
    currentRoles,
    others,
    asks: askList,
    accumulated,
  }), [item, itemFlow, materials.data, labels, current, currentRoles, others, askList, accumulated]);
  // 项目现在这份组织改过的历史（设置页加独立核验、换形态，工单 #1649）：线程里一句话，
  // 图下面一行小图（设计说明 4.15 最后一条：在跑的事项还按旧组织时，图仍画在跑的那件）
  const organizationChanges = useMemo<ThreadOrganizationChange[]>(
    () => (props.organization?.history ?? []).map((change) => ({ at: change.at, form: change.form })),
    [props.organization]);
  const organizationChange = useMemo(
    () => (item === null ? null : organizationChangeAfter(item, organizationChanges)),
    [item, organizationChanges]);
  const nextGraph = useMemo(() => {
    const currentOrganization = props.organization?.organization ?? null;
    if (organizationChange === null || currentOrganization === null) {
      return null;
    }
    // 与新建项目的形态卡同一种画法（form-cards-model 的 frozenOrganizationOf 与 loop-graph-model 的 graphOf）
    const frozen = frozenOrganizationOf(currentOrganization);
    return graphOf({
      item: { work_item_id: "", status: "not_started", organization: frozen },
      flow: [],
      materials: null,
      current: { form: frozen.form, sources: currentOrganization.sources },
      currentRoles: frozen.roles.map((role) => role.id),
    });
  }, [organizationChange, props.organization]);
  // 同一个面板里逐版看：按出现顺序排的箭头
  const arrows = useMemo<LoopArrow[]>(() => [
    ...graph.gaps.flat(), ...graph.skip, ...graph.side.flatMap((part) => part.arrows),
  ], [graph]);
  const [panel, setPanel] = useState<PanelState>({ item: null, value: null });
  const pick: LoopPanelTarget | ItemPanelPick | AllItemsPick = panel.item === itemId ? panel.value : null;
  // 图上标出选中的节点或箭头：时序图上那一行在图上打开的是箭头，两处标的是同一样
  const graphPick: LoopPanelPick = pick === null || pick === ITEM_PANEL_PICK || pick === ALL_ITEMS_PICK
    ? null
    : (pick.kind === "node" || pick.kind === "arrow") ? pick : null;
  // 用户收起面板、切换面板或收起来源详情时立即抑制当前路由对象的 at，等待新路由到达（工单 #1745）
  const [clearedForRoute, setClearedForRoute] = useState<Route | null>(null);
  const effectiveAt = clearedForRoute === props.route ? null : props.route.at;
  const openedAtKeyRef = useRef<string | null>(null);
  const clearRoutePosition = (): void => {
    if (props.route.at === null) {
      return;
    }
    openedAtKeyRef.current = null;
    setClearedForRoute(props.route);
    const workItem = itemId !== "" ? itemId : props.route.workItemId;
    props.onNavigate(paths.conversation(projectId, { workItem }));
  };
  const open = (value: LoopPanelTarget): void => {
    setPanel({ item: value === null ? null : itemId, value });
    clearRoutePosition();
  };
  // 事项面板（工单 #1708）：点选事项一行里选中那件的标题，同一个位置换成这一件事项的面板
  const openItem = (): void => setPanel({ item: itemId, value: ITEM_PANEL_PICK });
  // 全部事项（工单 #1709）：同一个位置换成这个项目的分组列表
  const openAllItems = (): void => {
    setPanel({ item: itemId, value: ALL_ITEMS_PICK });
    clearRoutePosition();
  };
  // 回链地址带有 ?at= 时，在选中事项就绪后自动展开事项面板读取对应位置的原始事件（工单 #1745）
  useEffect(() => {
    if (effectiveAt === null) {
      openedAtKeyRef.current = null;
      return;
    }
    if (loop.data === null) {
      return;
    }
    const key = `${projectId}:${props.route.workItemId ?? ""}:${effectiveAt}`;
    if (openedAtKeyRef.current === key) {
      return;
    }
    openedAtKeyRef.current = key;
    setPanel({ item: itemId, value: ITEM_PANEL_PICK });
  }, [loop.data, projectId, props.route.workItemId, effectiveAt, itemId]);
  // 从全部事项里点了一件：已经画着的那件直接换面板，别的那件先切过去（切过去以后才开面板）
  const [pendingItem, setPendingItem] = useState<string | null>(null);
  const pickFromAllItems = (workItem: string): void => {
    if (workItem === itemId) {
      setPanel({ item: itemId, value: ITEM_PANEL_PICK });
      clearRoutePosition();
      return;
    }
    setPendingItem(workItem);
    props.onNavigate(paths.conversation(projectId, { workItem }));
  };
  // 有中断待恢复的事项时，选事项一行下面多一行提示（设计说明「事项面板与全部事项」）
  const interruptions = useMemo(() => interruptionFactRows(loop.data), [loop.data]);
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
  // 列是这个事项冻结的组织里的职能和你（显示名用项目现在组织的名字，旧组织里的用冻结的那一份）
  const roles = useMemo(
    () => (item?.organization?.roles ?? []).map((role) => ({ id: role.id, label: labels[role.id] ?? role.label })),
    [item, labels],
  );
  const sequence = useMemo(() => sequenceOf({
    roles,
    flow: itemFlow,
    asks: askList,
    decisions: itemDecisions,
    materials: materials.data,
    verifiers: item?.organization?.verifiers ?? [],
    pair: pair !== null && pair.item === itemId ? pair.roles : null,
    // 「现在」：还没等到的色条画到这里。按这一份事实算一次，不跟着每次重算而抖
    now: new Date().toISOString(),
    openRounds,
  }), [roles, itemFlow, askList, itemDecisions, materials.data, item, pair, itemId, openRounds]);
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
  // 面板上标出来的那一行：成果那一行按它找到的箭头认（事项面板与全部事项不对应图上的行）
  const pickedKey = pick === null || pick === ITEM_PANEL_PICK || pick === ALL_ITEMS_PICK
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
  // 从全部事项里点了一件：图切到它以后（事项编号换过来才）打开它的事项面板
  useEffect(() => {
    if (pendingItem === null || pendingItem !== itemId) {
      return;
    }
    setPanel({ item: itemId, value: ITEM_PANEL_PICK });
    setPendingItem(null);
  }, [pendingItem, itemId]);
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
            <>
              <Empty text="这个项目还没有事项。在下面写一句，就开始做。" />
              {pick === ITEM_PANEL_PICK ? (
                <div ref={panelRef}>
                  <ItemPanel
                    app={props.app}
                    projectId={projectId}
                    workItemId={itemId}
                    loop={loop}
                    overview={overview}
                    initialPosition={effectiveAt}
                    onClearPosition={clearRoutePosition}
                    onClose={() => open(null)}
                    onNavigate={props.onNavigate}
                  />
                </div>
              ) : null}
            </>
          ) : (
            <>
              <ItemPicker
                items={items}
                titles={titles}
                selected={itemId}
                interruptions={interruptions}
                // 总数取项目概览的事项统计（设计说明「事项面板与全部事项」）：还没读到时入口不出现
                total={overview.data === null ? null : overview.data.stats.total}
                onPick={(workItem) => props.onNavigate(paths.conversation(projectId, { workItem }))}
                onOpen={openItem}
                onOpenAll={openAllItems}
                onOpenRecovery={(workItem) => props.onNavigate(paths.recovery(projectId, workItem))}
              />
              {item === null ? null : item.organization == null ? (
                <Empty text="这件事项冻结的组织不在这一版发布里，图上没有可画的节点。" />
              ) : (
                <>
                  {/* 图右上角的入口（工单 #1641、#1642）：只有一个职能时两个都没有，也没有时序图（设计说明 4.15） */}
                  {hasSequence(roles) ? (
                    <div className="y10-cv-tools">
                      <button type="button" className="y10-btn small y10-cv-accum" aria-pressed={accumulated}
                              data-testid="show-accumulated" onClick={() => setAccumulated((value) => !value)}>
                        累计往来
                      </button>
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
                    // 点询问线（开着的或累计的）只看这两个职能的时序图（设计说明 4.14 第 2 层）
                    onPickAsk={(from, to) => showPair(itemId, [from, to])}
                  />
                  {/* 组织刚改过、在跑的事项还按旧组织：图下面多一行小图，写「之后新建的事项按现在的组织走」 */}
                  {nextGraph === null ? null : (
                    <div className="y10-cv-next" data-testid="next-organization">
                      <p className="y10-cv-next-text">之后新建的事项按现在的组织走</p>
                      <LoopGraphView
                        graph={nextGraph}
                        pick={null}
                        onPickNode={() => undefined}
                        onPickArrow={() => undefined}
                        onPickAsk={() => undefined}
                      />
                    </div>
                  )}
                  {/* 询问读不出来时在图上说一句：不静默少画线（图上的虚线、节点的往来都与时序图读同一份查询） */}
                  {asks.error === null ? null : <Empty text={readFailureText(asks.error)} />}
                  {/* 时序图展开在循环图下面，不是单独的页，也不盖住线程 */}
                  {sequenceOpen && hasSequence(roles) ? (
                    <div ref={sequenceRef}>
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
                </>
              )}
              {/* 面板在图的下面（时序图展开时在它下面）：点节点、点箭头与点时序图的一行都是这一个，
                  点选事项一行里选中那件的标题换成事项面板（工单 #1708），末尾的「全部事项」换成
                  分组列表（工单 #1709）。这个位置在图上有没有画节点之外：事项冻结的组织不在这一版
                  发布里时，事项面板与全部事项照样能开 */}
              {pick === null ? null : (
                <div ref={panelRef}>
                  {pick === ALL_ITEMS_PICK ? (
                    <AllItems
                      state={overview}
                      selected={itemId}
                      onPick={pickFromAllItems}
                      onClose={() => open(null)}
                    />
                  ) : pick === ITEM_PANEL_PICK ? (
                    <ItemPanel
                      app={props.app}
                      projectId={projectId}
                      workItemId={itemId}
                      loop={loop}
                      overview={overview}
                      initialPosition={effectiveAt}
                      onClearPosition={clearRoutePosition}
                      onClose={() => open(null)}
                      onNavigate={props.onNavigate}
                    />
                  ) : (
                    <LoopPanel
                      app={props.app}
                      projectId={projectId}
                      workItemId={itemId}
                      runId={runId}
                      // 询问编号：询问分支的激活带着它，按第几轮找工作过程时排掉那几次（工单 #1658）
                      branchSessions={askList.map((ask) => ask.id)}
                      graph={graph}
                      arrows={arrows}
                      pick={pick}
                      onPickArrow={(arrow) => open({ kind: "arrow", arrow })}
                      onClose={() => open(null)}
                    />
                  )}
                </div>
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
              organizationChanges={organizationChanges}
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

