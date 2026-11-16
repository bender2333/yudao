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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ClientApp } from "../../contract/client-app";
import type {
  Catalog, DecisionList, DecisionView, DepartmentWorkspaceResult, ProjectAttemptsResult,
  ProjectFlowResult, ProjectLoopResult, ProjectOrganizationResult, ProjectOverviewResult,
  ProjectSettingsResult, RunAsksResult, SystemStatus, WorkItemMaterialsResult,
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
import { LiveWindow } from "./live-window";
import { arrowMatchesQuery, pickLiveDepartment } from "./live-window-model";
import type { DepartmentView } from "./organization";
import { frozenOrganizationOf } from "./form-cards-model";
import {
  BLUEPRINT_THEME_STORAGE_KEY, DEFAULT_BLUEPRINT_THEME, blueprintEndOf, blueprintRailOf,
  blueprintThemeParse, graphOf, nextBlueprintTheme, nodeTelemetryOf, otherCounts, pickItem,
  type BlueprintTheme, type LoopArrow, type LoopItemView, type NodeTelemetry,
} from "./loop-graph-model";
import { LoopGraphView, type LoopPanelPick } from "./loop-graph";
import { LoopPanel, type LoopPanelLiveContext, type LoopPanelTarget } from "./loop-panel";
import { ProjectTimeBar } from "./project-head";
import { SequenceView } from "./sequence";
import { hasSequence, sequenceOf, type SequenceRow } from "./sequence-model";
import { ThreadView } from "./thread";
import { organizationChangeAfter, type ThreadOrganizationChange } from "./thread-model";
import {
  receiverOf, runningItem, workingRoleOf, type ComposerInput,
} from "./thread-model";
import { useSnapshot, type SnapshotState } from "./use-snapshot";

/**
 * 面板打开的那一个，连同它在哪件事项上打开：换了事项就收起，不在新图上留着旧的一版。
 * 同一个位置只开一个面板（工单 #1708）：点选事项一行里选中那件的标题开事项面板，
 * 点节点、点箭头、点时序图的一行换成那个面板。
 * 这里还有全部事项的分组列表（工单 #1709）：点选事项一行末尾的「全部事项」开它，
 * 从列表里点一件时图切过去，面板换成那件事项的事项面板。
 */
type PanelState = { item: string | null; value: LoopPanelTarget | ItemPanelPick | AllItemsPick };

/** 按职能订阅 department.workspace，给蓝图节点遥测与现场窗口提供同一份真实工作间快照。 */
function DepartmentWorkspaceProbe(props: {
  app: ClientApp;
  projectId: string;
  workItemId: string;
  department: string;
  onUpdate: (workItemId: string, department: string, state: SnapshotState<DepartmentWorkspaceResult>) => void;
}): null {
  const state = useSnapshot<DepartmentWorkspaceResult>(
    props.app,
    `page.cv.node.workspace.${props.department}`,
    "department.workspace",
    {
      project_id: props.projectId,
      department: props.department,
      work_item: props.workItemId === "" ? null : props.workItemId,
    },
    props.projectId === "",
  );
  useEffect(() => {
    props.onUpdate(props.workItemId, props.department, state);
  }, [props.workItemId, props.department, props.onUpdate, state.data, state.error, state.loading]);
  return null;
}

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
  // 蓝图节点遥测与现场窗口需要的真实配置与最近尝试（不估算、不伪造）
  const settings = useSnapshot<ProjectSettingsResult>(
    props.app,
    "page.conversation.settings",
    "project.settings",
    { project_id: projectId },
    projectId === "",
  );
  const catalog = useSnapshot<Catalog>(props.app, "page.conversation.catalog", "catalog", {});
  const attemptsQuery = useSnapshot<ProjectAttemptsResult>(
    props.app,
    `page.conversation.attempts.${itemId}`,
    "project.attempts",
    { project_id: projectId, work_item: itemId, limit: 50 },
    projectId === "" || itemId === "",
  );
  const attemptsList = useMemo(() => attemptsQuery.data?.attempts ?? [], [attemptsQuery.data]);
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
  // 用户收起面板、切换面板或收起来源详情时立即抑制当前路由对象的 at / arrow，等待新路由到达（工单 #1745、#1811）
  const [clearedAtForRoute, setClearedAtForRoute] = useState<Route | null>(null);
  const [clearedArrowForRoute, setClearedArrowForRoute] = useState<Route | null>(null);
  const effectiveAt = clearedAtForRoute === props.route ? null : props.route.at;
  const effectiveArrow = clearedArrowForRoute === props.route ? null : props.route.arrowFlowId;
  const openedAtKeyRef = useRef<string | null>(null);
  const openedArrowKeyRef = useRef<string | null>(null);
  const clearRouteParams = (which: "at" | "arrow" | "both"): void => {
    const clearAt = (which === "at" || which === "both") && props.route.at !== null;
    const clearArrow = (which === "arrow" || which === "both") && props.route.arrowFlowId !== null;
    if (!clearAt && !clearArrow) {
      return;
    }
    if (clearAt) {
      openedAtKeyRef.current = null;
      setClearedAtForRoute(props.route);
    }
    if (clearArrow) {
      openedArrowKeyRef.current = null;
      setClearedArrowForRoute(props.route);
    }
    const workItem = itemId !== "" ? itemId : props.route.workItemId;
    props.onNavigate(paths.conversation(projectId, {
      workItem,
      at: which === "arrow" ? effectiveAt : null,
      arrow: which === "at" ? effectiveArrow : null,
    }));
  };
  const open = (value: LoopPanelTarget): void => {
    setPanel({ item: value === null ? null : itemId, value });
    clearRouteParams("both");
  };
  // 事项面板（工单 #1708）：点选事项一行里选中那件的标题，同一个位置换成这一件事项的面板
  const openItem = (): void => {
    setPanel({ item: itemId, value: ITEM_PANEL_PICK });
    clearRouteParams("arrow");
  };
  // 全部事项（工单 #1709）：同一个位置换成这个项目的分组列表
  const openAllItems = (): void => {
    setPanel({ item: itemId, value: ALL_ITEMS_PICK });
    clearRouteParams("both");
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
  // 从成果库带 ?arrow= 跳入时，在图箭头就绪后自动定位对应箭头面板（工单 #1811）
  useEffect(() => {
    if (effectiveArrow === null) {
      openedArrowKeyRef.current = null;
      return;
    }
    if (loop.data === null || flow.data === null) {
      return;
    }
    const hit = arrowMatchesQuery(arrows, effectiveArrow);
    if (hit === null) {
      return;
    }
    const key = `${projectId}:${props.route.workItemId ?? ""}:${effectiveArrow}`;
    if (openedArrowKeyRef.current === key) {
      return;
    }
    openedArrowKeyRef.current = key;
    setPanel({ item: itemId, value: { kind: "arrow", arrow: hit } });
  }, [loop.data, flow.data, arrows, projectId, props.route.workItemId, effectiveArrow, itemId]);
  // 从全部事项里点了一件：已经画着的那件直接换面板，别的那件先切过去（切过去以后才开面板）
  const [pendingItem, setPendingItem] = useState<string | null>(null);
  const pickFromAllItems = (workItem: string): void => {
    if (workItem === itemId) {
      setPanel({ item: itemId, value: ITEM_PANEL_PICK });
      clearRouteParams("both");
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
  // 详情面板紧贴循环图下方、排在时序图上方；点节点、箭头、事项标题或时序图行后滚到眼前
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

  // troupe 蓝图主题（深色 / 纸面，本地持久化）与现场窗口开关（工单 #1811）
  const [bpTheme, setBpTheme] = useState<BlueprintTheme>(() => {
    try {
      return blueprintThemeParse(window.localStorage.getItem(BLUEPRINT_THEME_STORAGE_KEY));
    } catch {
      return DEFAULT_BLUEPRINT_THEME;
    }
  });
  const toggleBpTheme = (): void => {
    const next = nextBlueprintTheme(bpTheme);
    setBpTheme(next);
    try {
      window.localStorage.setItem(BLUEPRINT_THEME_STORAGE_KEY, next);
    } catch {
      // 忽略受限存储环境写入失败
    }
  };

  const [liveOpen, setLiveOpen] = useState(true);
  const [liveDeptPick, setLiveDeptPick] = useState<{ item: string; dept: string } | null>(null);
  const [workspaceFeed, setWorkspaceFeed] = useState<{
    item: string;
    map: Record<string, SnapshotState<DepartmentWorkspaceResult>>;
  }>({ item: "", map: {} });

  const handleWorkspaceUpdate = useCallback((
    workItemKey: string,
    department: string,
    state: SnapshotState<DepartmentWorkspaceResult>,
  ): void => {
    setWorkspaceFeed((previous) => {
      const base = previous.item === workItemKey ? previous.map : {};
      const prevEntry = base[department];
      if (
        prevEntry !== undefined
        && prevEntry.data === state.data
        && prevEntry.error === state.error
        && prevEntry.loading === state.loading
      ) {
        return previous;
      }
      return {
        item: workItemKey,
        map: { ...base, [department]: state },
      };
    });
  }, []);

  const workspaces = useMemo(
    () => (workspaceFeed.item === itemId ? workspaceFeed.map : {}),
    [workspaceFeed, itemId],
  );

  const telemetryById = useMemo<Record<string, NodeTelemetry>>(() => {
    const map: Record<string, NodeTelemetry> = {};
    for (const node of graph.nodes) {
      map[node.id] = nodeTelemetryOf({
        node,
        item,
        workspace: workspaces[node.id]?.data ?? null,
        settings: settings.data,
        catalog: catalog.data,
        attempts: attemptsList,
        decisions: itemDecisions,
      });
    }
    return map;
  }, [graph.nodes, item, workspaces, settings.data, catalog.data, attemptsList, itemDecisions]);

  const rail = useMemo(() => blueprintRailOf({
    item,
    graph,
    flow: itemFlow,
    materials: materials.data,
    telemetryById,
    labels,
  }), [item, graph, itemFlow, materials.data, telemetryById, labels]);

  const endView = useMemo(
    () => blueprintEndOf(item, item?.organization ?? null, labels),
    [item, labels],
  );

  const isNodePick = pick !== null && typeof pick === "object" && pick.kind === "node";
  const showingLive = liveOpen && (pick === null || isNodePick);
  const activeLiveDept = useMemo(() => {
    const explicit = isNodePick
      ? pick.id
      : (liveDeptPick?.item === itemId ? liveDeptPick.dept : null);
    return pickLiveDepartment(item, roles, explicit);
  }, [isNodePick, pick, liveDeptPick, itemId, item, roles]);

  const closeLiveWindow = (): void => {
    setLiveOpen(false);
    if (isNodePick) {
      open(null);
    }
  };

  const toggleLiveWindow = (): void => {
    if (showingLive) {
      closeLiveWindow();
    } else {
      setLiveOpen(true);
      open(null);
    }
  };

  const selectLiveDepartment = (deptId: string): void => {
    setLiveDeptPick({ item: itemId, dept: deptId });
    if (isNodePick) {
      open({ kind: "node", id: deptId });
    }
  };

  const focusGuidance = (deptId: string): void => {
    setFocus(deptId);
    const roleLabel = roles.find((r) => r.id === deptId)?.label ?? labels[deptId] ?? deptId;
    const expectedPill = `给${roleLabel}的指导`;
    const radios = document.querySelectorAll<HTMLButtonElement>(".y10-cv-to button[role='radio']");
    for (const radio of radios) {
      if (radio.textContent?.trim() === expectedPill && radio.getAttribute("aria-checked") !== "true") {
        radio.click();
        break;
      }
    }
    const textarea = document.querySelector<HTMLTextAreaElement>(".y10-cv-composer textarea");
    if (textarea !== null) {
      textarea.scrollIntoView({ behavior: "smooth", block: "nearest" });
      textarea.focus();
    }
  };

  const scrollToDecision = (decisionId: string): void => {
    const bubble = document.querySelector<HTMLElement>(`[data-testid="thread-decision-${decisionId}"]`);
    if (bubble === null) {
      return;
    }
    bubble.scrollIntoView({ behavior: "smooth", block: "center" });
    bubble.classList.add("is-flash");
    window.setTimeout(() => bubble.classList.remove("is-flash"), 1600);
  };

  const liveContext = useMemo<LoopPanelLiveContext>(() => ({
    item,
    flow: itemFlow,
    materials: materials.data,
    decisions: itemDecisions,
    asks: askList,
    roles,
    workspaces,
    settings: settings.data,
    catalog: catalog.data,
    attempts: attemptsList,
    organization: props.organization?.organization ?? null,
    blueprintTheme: bpTheme,
    onSelectDepartment: selectLiveDepartment,
    onFocusGuidance: focusGuidance,
    onScrollToDecision: scrollToDecision,
  }), [
    item, itemFlow, materials.data, itemDecisions, askList, roles, workspaces,
    settings.data, catalog.data, attemptsList, props.organization, bpTheme,
  ]);
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
                    onClearPosition={() => clearRouteParams("at")}
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
                  {roles.map((role) => (
                    <DepartmentWorkspaceProbe
                      key={`${projectId}:${itemId}:${role.id}`}
                      app={props.app}
                      projectId={projectId}
                      workItemId={itemId}
                      department={role.id}
                      onUpdate={handleWorkspaceUpdate}
                    />
                  ))}
                  {/* 图右上角的入口：现场窗口、蓝图主题（所有组织都有）；累计往来与看经过只在多职能时显示（设计说明 4.15） */}
                  <div className="y10-cv-tools">
                    <button
                      type="button"
                      className="y10-btn small"
                      aria-pressed={showingLive}
                      data-testid="toggle-live-window"
                      onClick={toggleLiveWindow}
                    >
                      现场窗口
                    </button>
                    <button
                      type="button"
                      className="y10-btn small"
                      aria-pressed={bpTheme === "paper"}
                      data-testid="toggle-blueprint-theme"
                      onClick={toggleBpTheme}
                    >
                      {bpTheme === "dark" ? "蓝图：深色" : "蓝图：纸面"}
                    </button>
                    {hasSequence(roles) ? (
                      <>
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
                      </>
                    ) : null}
                  </div>
                  <LoopGraphView
                    graph={graph}
                    pick={graphPick}
                    troupe
                    blueprintTheme={bpTheme}
                    rail={rail}
                    telemetry={telemetryById}
                    endView={endView}
                    frozenOrganization={{
                      form: item.organization.form,
                      sameAsProject: item.organization.same_as_project,
                    }}
                    selectedDepartmentId={showingLive ? activeLiveDept : null}
                    onPickNode={(id) => {
                      // 点节点：看这个职能，收件人跟着切到给它的指导（项目的组织设计说明 4.14）
                      setFocus(id);
                      setLiveOpen(true);
                      setLiveDeptPick({ item: itemId, dept: id });
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
                </>
              )}
              {/* 详情面板与内嵌现场窗口紧贴循环图正下方（在时序图上方，工单 #1807、#1811）：
                  点箭头、点时序图行、点事项标题或「全部事项」展开对应面板；点职能节点或处于现场窗口开启状态时呈现 LiveWindow */}
              {pick !== null || (liveOpen && item !== null && item.organization != null && activeLiveDept !== "") ? (
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
                      onClearPosition={() => clearRouteParams("at")}
                      onClose={() => open(null)}
                      onNavigate={props.onNavigate}
                    />
                  ) : pick !== null ? (
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
                      liveContext={liveContext}
                      onPickArrow={(arrow) => open({ kind: "arrow", arrow })}
                      onClose={() => {
                        if (isNodePick) {
                          closeLiveWindow();
                        } else {
                          open(null);
                        }
                      }}
                    />
                  ) : (
                    <LiveWindow
                      app={props.app}
                      projectId={projectId}
                      workItemId={itemId}
                      runId={runId}
                      graph={graph}
                      arrows={arrows}
                      department={activeLiveDept}
                      onPickArrow={(arrow) => open({ kind: "arrow", arrow })}
                      onClose={closeLiveWindow}
                      {...liveContext}
                    />
                  )}
                </div>
              ) : null}
              {/* 时序图排在展开的详情面板下方、对话线程上方 */}
              {item !== null && item.organization != null && sequenceOpen && hasSequence(roles) ? (
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

