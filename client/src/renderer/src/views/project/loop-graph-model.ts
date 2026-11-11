// 循环图的事实推出（工单 #1638、#1640，项目的组织设计说明 4.14「项目页是循环图加对话」、
// 4.15「循环图跟着组织长」）。
//
// 这里只做取值、布局与判断，不碰界面与网络：页面按这里给出的节点、箭头、询问与两端照画，单元测试直接核对。
// 读的四处事实：
//   - project.loop：所选事项冻结的组织（节点、核验关系、关注关系）、每个职能在这件事项上的状态与原因、事项的轮次；
//   - project.flow：箭头（成果与版本），按事项过滤；
//   - work_item.materials：版本号、改了的文件、结论；
//   - run.asks：开着的询问（提问方、被询问的职能、问题、状态、询问链的层数）；答完的只进节点的往来，
//     用户打开「累计往来」时同一对职能的询问合成一条线（工单 #1642，次数含开着的）。
//
// 几条固定的读法（设计说明 4.14、4.15、department-loop「职能的状态」与术语表「循环图」）：
//   - 节点是职能；箭头只放成果与版本（原文、PRD、交付、缺陷记录），询问不是成果，不画成成果箭头。
//   - 一次询问开着时，提问方与被询问的职能之间画一条虚线，写「询问」，不带版本；同时开着几次就有几条，
//     询问链上每一层一条；答完虚线消失，收进线程与节点面板的往来。虚线只给询问，成果箭头都是实线。
//   - 节点上的字、角标与节点详情从同一份状态推出：状态词用「职能的状态」那几个，有具体原因时写在括号里；
//     「在做」角标只挂在一轮工作中的节点（主线在工作，或正在分支里回答询问）。
//   - 放行与打回是对某一版的结论，标在那一版上，不另起一条箭头；打回之后交出的新一版是新的一条箭头。
//   - 来源从图外进来，接它的职能是第一个节点；结束写放行（核验角色的显示名）或开环完成。
//   - 图按所选事项冻结的组织画：换过组织以后，旧事项仍按它那一份画。
//
// 服务端还没有「第几轮」的字段时（app-and-interface 4.4 第 1 条由接口工单补上），箭头上不写轮次，
// 其余照画：这里读的是可选的 round，加上以后不用改页面。

import { DEPARTMENT_STATE } from "./labels.ts";

/** 循环图的箭头两端：图外的来源、结束，或一个职能的标识。 */
export const SOURCE = "src";
export const END = "end";

/** 一个职能（事项冻结的组织里的一项）。 */
export interface LoopRole {
  id: string;
  label: string;
}

/**
 * 一个事项冻结的组织（project.loop 的 organization）。
 *
 * 只列循环图用到的几项：职能、核验关系、关注关系。`watched` 给出「谁接收谁的哪种成果」，
 * 直做的形态里没有成果交接，它是空的。
 */
export interface FrozenOrganization {
  form: string;
  routing: string;
  roles: readonly LoopRole[];
  verifiers: readonly { role: string; verifies: readonly { role: string; outcomes: readonly string[] }[] }[];
  completing?: { id: string; label: string } | null;
  watched: readonly { source: string; recipient: string; outcome: string }[];
  asks?: readonly { requester: string; recipient: string }[];
  rejections?: readonly { verifier: string; role: string; outcome: string }[];
}

/**
 * project.flow 的一条。`round` 是产生这条记录的那次激活的轮次（接口工单加上这个字段以后才有）；
 * 没有时箭头上不写轮次，不拿版本号或猜出来的数字顶替。
 */
export interface FlowRecordLike {
  flow_id: string;
  event_id: string;
  kind: string;
  content: string;
  direction_from: string | null;
  direction_to: string | null;
  position: number;
  round?: number | null;
}

/** work_item.materials 里循环图用到的几项。 */
export interface MaterialsView {
  contracts?: readonly { event_id: string; revision: number | null }[];
  deliveries?: readonly { event_id: string; revision: number | null; summary?: string | null; files?: readonly string[] }[];
  reviews?: readonly { event_id: string; verdict: string; rationale?: string }[];
  inputs?: readonly { version: number; text: string; created_event_id?: string | null }[];
}

/** 一项职能在这件事项上的状态与原因（project.loop 的 departments 的一项）。 */
export interface DepartmentStateLike {
  state: string;
  note?: string | null;
}

/**
 * run.asks 的一次询问（循环图读的那几栏，应用层与接口层设计说明 4.4「项目页四层读哪个查询」）。
 *
 * 状态由查询给出：进行中的画成虚线；已回答与没能回答的虚线消失，只进节点面板的往来。
 * `depth` 是询问链上的层数（最外层为 1），询问里又问时每一层各是一条。
 */
export interface AskViewLike {
  id: string;
  requester: string;
  recipient: string;
  question?: string;
  status: "进行中" | "已回答" | "没能回答";
  depth?: number;
  /** 这次询问开始的那条事实在事件流里的位置：同一个格子里按它排 */
  start_position?: number;
}

/** project.loop 的一项：循环图读的那几栏。 */
export interface LoopItemView {
  work_item_id: string;
  kind?: string | null;
  status: string;
  /**
   * 事项的停止原因（project.loop 给出，线程一侧读的也是它）：`open_loop` 表示以开环完成结束，
   * 采纳以后状态变成 adopted、这一项仍是 open_loop（工单 #1704）。
   */
  stop_reason?: string | null;
  round?: number;
  started_at?: string | null;
  department?: string | null;
  departments?: Record<string, DepartmentStateLike> | null;
  progress?: { conclusion?: string | null } | null;
  organization?: FrozenOrganization | null;
}

/** 项目现在的组织（project.organization）：只用来取「接来源的职能」。 */
export interface CurrentOrganization {
  form?: string | null;
  sources?: Record<string, string> | null;
}

export interface LoopGraphInput {
  item: LoopItemView | null;
  flow: readonly FlowRecordLike[];
  materials: MaterialsView | null;
  /** 职能显示名：项目现在的组织给出的名字先用，旧组织里的职能用冻结的那一份 */
  labels?: Record<string, string>;
  current?: CurrentOrganization | null;
  /** 项目现在的组织里的职能标识：不在其中的旧组织职能标「只在旧组织里」 */
  currentRoles?: readonly string[];
  /** 别的事项在这些职能上的件数 */
  others?: Record<string, number>;
  /** 这个事项所在运行里的询问（run.asks）：开着的画虚线，答完的只进往来 */
  asks?: readonly AskViewLike[];
  /**
   * 用户打开了「累计往来」（工单 #1642）：同一对职能的询问合成一条线，次数含开着的；
   * 不打开时图上仍然只画开着的询问。
   */
  accumulated?: boolean;
}

/** 一条虚线画在哪：主线相邻的一格、跨过中间节点另起一行、或旁边的职能与主线之间的竖线。 */
export type LoopAskPlace = "gap" | "skip" | "side";

/** 一条虚线画在图的哪里：放置、格子与两端在主线上的下标。 */
export interface LoopAskSpot {
  /** 画在哪：主线的一格、跨过中间节点另起一行、或旁边的职能与主线之间的竖线 */
  place: LoopAskPlace;
  /** place 为 gap 时主线的第几格；为 side 时是对接的那个主线职能的下标；skip 时为 -1 */
  gap: number;
  /** 两端在主线上的下标：旁边的职能与图外为 -1 */
  fromIndex: number;
  toIndex: number;
  /** place 为 side 时它对接的主线职能 */
  partner: string;
}

/**
 * 一条询问：提问方与被询问的职能，以及它画在哪。
 *
 * 开着的（open）画成写「询问」的虚线，不带版本；答完的虚线消失，只进节点面板的往来。
 * 放置与成果箭头分开：询问不是成果，不进 gaps 里的箭头，也不参与逐版看。
 */
export interface LoopAsk extends LoopAskSpot {
  kind: "ask";
  key: string;
  /** 提问方 */
  from: string;
  /** 被询问的职能 */
  to: string;
  question: string;
  status: "进行中" | "已回答" | "没能回答";
  /** 走到这里时还开着：画虚线；答完的收进线程与节点的往来（设计说明 4.14） */
  open: boolean;
  /** 询问链上的层数：最外层为 1（询问里又问时每层一条） */
  depth: number;
  /** 这次询问开始的位置：同一个格子里按它排 */
  position: number;
}

/**
 * 两个职能之间的累计往来（工单 #1642，设计说明 4.14「累计往来」）：这件事项的询问按两个职能合成的一条线。
 *
 * 次数含开着的；还有开着的在这条线的字后面写「开着」。来回问的两个方向各写几次，同一行里用逗号分开。
 * 放在原来的询问线那一格：同一对职能在图上只有一个位置。
 */
export interface LoopAskPair extends LoopAskSpot {
  kind: "pair";
  key: string;
  /** 两端：第一次问的那个方向（画线只看两端，不看方向） */
  from: string;
  to: string;
  /** 每个方向问了几次，按第一次问的先后排 */
  directions: { from: string; to: string; count: number }[];
  /** 一共问了几次（含开着的） */
  count: number;
  /** 还有开着的 */
  open: boolean;
  /** 线上写的那句话，例如「工程问产品 2 次」「工程问产品 2 次，产品问工程 1 次 · 开着」 */
  label: string;
}

/** 图上画的一条虚线：打开累计往来时是一对职能的合计，不打开时是一次开着的询问。 */
export type LoopAskLine = LoopAsk | LoopAskPair;

/** 一个节点：一个职能，加上它在这件事项上的状态与标记。 */
export interface LoopNode {
  id: string;
  label: string;
  /** 状态词：职能的状态里的一个；没有状态（事项还没开始或已经结束）时为空串 */
  stateWord: string;
  /** 节点上写的那句话：状态词，有具体原因（具体工作）时写在括号里；没有状态时为空串 */
  state: string;
  /** 「在做」角标：只有一轮工作中的节点挂 */
  working: boolean;
  /** 它在等的回答（「在等待某某的回答」）：窄屏不画线时写在节点名旁 */
  waiting: string[];
  /** 做核验的节点 */
  verifier: boolean;
  /** 只在旧组织里：项目现在的组织里已经没有这个职能 */
  oldOnly: boolean;
  /** 别的事项正在这个职能上的件数 */
  others: number;
}

/** 一条成果箭头：成果、版本、第几轮，以及标在这一版上的结论。 */
export interface LoopArrow {
  key: string;
  /** 成果名：原文（建档事项写建档）、PRD、交付、缺陷记录 */
  outcome: string;
  version: number | null;
  round: number | null;
  /** 发出的一端：图外的来源、结束，或者一个职能 */
  from: string;
  /** 收到的一端 */
  to: string;
  /** 回头画的箭头（缺陷记录：从核验角色回到被核验的那一方） */
  back: boolean;
  /** 这条箭头来自的那条事实在事件流里的位置：逐版看与「当前箭头」都按它排序 */
  position: number;
  /** 对某一版的结论：打回或放行；只标在成果那一版上 */
  verdict: { tone: "reject" | "release"; by: string; text: string } | null;
  /** 那一版的一句话（交付的摘要、PRD 的改动说明、缺陷记录的内容） */
  text: string;
  /** 改了的文件（交付有；别的成果没有） */
  files: string[];
  /**
   * 这一版在 work_item.materials 里的那条事实：箭头面板按它取这一版的文件清单、摘要与单个文件。
   * 缺陷记录与来源箭头也带上自己的事件，图纸上画的时候不用，面板取资料时用。
   */
  eventId?: string | null;
}

/** 主线上一个节点与它旁边那些职能之间的一格：旁边的职能怎么和主线往来。 */
export interface LoopSide {
  node: LoopNode;
  /** 它对接的主线职能 */
  partner: string;
  /** 它与主线之间的箭头（直做的职能没有成果交接，因此通常是空的） */
  arrows: LoopArrow[];
  /** 它与主线之间画的虚线：两节点之间的竖线换成它（「产品 · 工程」）；打开累计往来时是一对职能的合计 */
  lines: LoopAskLine[];
}

export interface LoopGraph {
  /** 主线上从左到右的节点 */
  chain: LoopNode[];
  /** 主线旁边的节点（「产品 · 工程」的产品） */
  side: LoopSide[];
  /**
   * 主线上的空格子，长度是 chain.length + 1：
   * 第 0 格是来源到第一个节点，第 i 格是第 i-1 与第 i 个节点之间，最后一格是到结束。
   * 每一格里两个方向的箭头都在（回头的缺陷记录在同一条缝里，箭头朝左）。
   */
  gaps: LoopArrow[][];
  /** 跨过中间节点的箭头（PRD 给质检），另起一行画，仍是实线 */
  skip: LoopArrow[];
  /** 图外的那一端写什么：你的输入 / 建档 */
  sourceText: string;
  /** 结束写什么：质检放行、开环完成、已停止 */
  endText: string;
  endTone: "ok" | "open" | "plain";
  /** 这件事项第几轮（project.loop 的 round） */
  rounds: number;
  /** 节点逐个取用：图表与面板都按标识找 */
  nodes: LoopNode[];
  /** 这件事项的询问（开着的在前，同一类按发生先后）：节点面板列它的往来时用 */
  asks: LoopAsk[];
  /** 开着的询问：节点上写「在等待某某的回答」用；答完的收进线程与节点的往来 */
  openAsks: LoopAsk[];
  /**
   * 图上画的虚线：打开累计往来时是每对职能合成的一条（次数含开着的），不打开时是开着的询问。
   * 两种线点下去都只看这两个职能的时序图（设计说明 4.14）。
   */
  lines: LoopAskLine[];
}

const PRD_KIND = "PRD 新版本";
const DELIVERY_KIND = "版本交付";
const DEFECT_KIND = "问题反馈";

/** 事项已经结束的三种状态（与页面上别处的说法一致） */
const DONE_STATUS = new Set(["adopted", "released_unsettled", "stopped"]);


/** 一个职能的显示名：项目现在的组织给了名字就先用它，旧组织里的用冻结的那一份。 */
function labelOf(id: string, organization: FrozenOrganization, labels: Record<string, string>): string {
  return labels[id] ?? organization.roles.find((role) => role.id === id)?.label ?? id;
}

/** 一件事项里冻结的组织给出职能标识与显示名：项目现在的组织给了名字就先用它，旧组织里的用冻结的那一份。 */
function rolesOf(organization: FrozenOrganization, labels: Record<string, string>): LoopRole[] {
  return organization.roles.map((role) => ({ id: role.id, label: labels[role.id] ?? role.label }));
}

/** 核验角色（做核验标记的节点与放行时写的那几个名字）. */
function verifierIds(organization: FrozenOrganization): string[] {
  return organization.verifiers.map((verifier) => verifier.role);
}

/** 接收你的输入的职能：直做的形态里它是主线上的那个节点。 */
function receiverOf(organization: FrozenOrganization, roles: readonly LoopRole[], flow: readonly FlowRecordLike[],
                    current: CurrentOrganization | null | undefined): string {
  const ids = roles.map((role) => role.id);
  // 项目现在的组织与事项冻结的是同一份形态时，来源的接收者是同一处定义给出的，可以照它取。
  // 形态换过以后不拿现在的顶替：旧事项按它冻结的那一份画，只是这一个位置没有冻结的事实可读
  const sameForm = current?.form !== undefined && current.form === organization.form;
  const picked = sameForm ? current?.sources?.user_input ?? null : null;
  if (picked !== null && ids.includes(picked)) {
    return picked;
  }
  // 没有来源的接收者时看这件事项已经发生的事：交出最后一版成果的职能在主线
  const records = [...flow].sort((left, right) => left.position - right.position);
  const sender = records.filter((record) => record.kind === DELIVERY_KIND && record.direction_from).at(-1)?.direction_from
    ?? records.find((record) => record.direction_from)?.direction_from
    ?? null;
  if (sender !== null && ids.includes(sender)) {
    return sender;
  }
  return ids[0] ?? "";
}

/**
 * 布局：哪些职能在主线、哪些在旁边。
 *
 * 有成果交接的形态（产品 · 工程 · 质检）沿「交出 → 接收」排：既不是接收方、又交出成果的那个职能是第一个节点，
 * 顺着关注的成果往下走。没有成果交接的形态（直做）是一行：接来源的职能在主线，其余在旁边接询问。
 */
export function layoutOf(organization: FrozenOrganization, flow: readonly FlowRecordLike[],
                         roles: readonly LoopRole[], current: CurrentOrganization | null | undefined): {
  chain: string[];
  side: { id: string; partner: string }[];
} {
  if (roles.length === 0) {
    return { chain: [], side: [] };
  }
  const ids = roles.map((role) => role.id);
  const handoffs = organization.watched.filter(
    (watched) => ids.includes(watched.source) && ids.includes(watched.recipient));
  if (handoffs.length > 0) {
    const senders = new Set(handoffs.map((watched) => watched.source));
    const recipients = new Set(handoffs.map((watched) => watched.recipient));
    const head = ids.find((id) => senders.has(id) && !recipients.has(id)) ?? ids[0];
    const chain = [head];
    for (let index = 0; index < chain.length; index += 1) {
      const from = chain[index];
      for (const handoff of handoffs) {
        if (handoff.source === from && !chain.includes(handoff.recipient)) {
          chain.push(handoff.recipient);
        }
      }
    }
    return {
      chain,
      side: ids.filter((id) => !chain.includes(id)).map((id) => ({ id, partner: head })),
    };
  }
  const main = receiverOf(organization, roles, flow, current);
  return {
    chain: main === "" ? [] : [main],
    side: ids.filter((id) => id !== main).map((id) => ({ id, partner: main })),
  };
}

/**
 * 一条线的两端画在哪：主线相邻的两个职能在那一格；隔着职能的另起一行；旁边的职能与主线之间在竖线那一格。
 *
 * 两端对不上这份组织时返回 null：换过组织以后旧事项按冻结的那一份画，对不上的不画、也不进往来。
 */
function spotOf(layout: ReturnType<typeof layoutOf>, from: string, to: string): LoopAskSpot | null {
  const chain = layout.chain;
  const fromIndex = chain.indexOf(from);
  const toIndex = chain.indexOf(to);
  if (fromIndex >= 0 && toIndex >= 0) {
    const distance = Math.abs(fromIndex - toIndex);
    if (distance === 1) {
      return { place: "gap", gap: Math.max(fromIndex, toIndex), fromIndex, toIndex, partner: "" };
    }
    return distance > 1 ? { place: "skip", gap: -1, fromIndex, toIndex, partner: "" } : null;
  }
  const side = layout.side.find((part) =>
    (part.id === from && part.partner === to) || (part.id === to && part.partner === from));
  if (side === undefined) {
    return null;
  }
  return { place: "side", gap: chain.indexOf(side.partner), fromIndex, toIndex, partner: side.partner };
}

/**
 * 询问画在哪：一条询问一条线，放置由两端决定（spotOf）。
 *
 * 只取这份组织里两端的询问。开着的在前（节点面板先列开着的），同一类按发生先后排；
 * 同时开着几次就有几条，询问链每层一条。
 */
function asksOf(layout: ReturnType<typeof layoutOf>, raw: readonly AskViewLike[],
                organization: FrozenOrganization): LoopAsk[] {
  const ids = new Set(organization.roles.map((role) => role.id));
  const out: LoopAsk[] = [];
  for (const entry of raw) {
    if (!ids.has(entry.requester) || !ids.has(entry.recipient) || entry.requester === entry.recipient) {
      continue;
    }
    const spot = spotOf(layout, entry.requester, entry.recipient);
    if (spot === null) {
      continue;
    }
    out.push({
      kind: "ask",
      key: entry.id,
      from: entry.requester,
      to: entry.recipient,
      question: entry.question ?? "",
      status: entry.status,
      open: entry.status === "进行中",
      depth: entry.depth ?? 1,
      position: entry.start_position ?? 0,
      ...spot,
    });
  }
  return out.sort((left, right) =>
    (left.open === right.open ? left.position - right.position : (left.open ? -1 : 1)));
}

/**
 * 两个职能之间的累计往来（工单 #1642）：这件事项的询问按两个职能合成一条线，次数含开着的。
 *
 * 一对职能只有一个位置（放置取这一对里第一次问的那一条），来回问的两个方向各写几次；
 * 还有开着的，在这条线的字后面写「开着」。已经答完的也数进去，所以已结束的事项也有线。
 */
function pairsOf(asks: readonly LoopAsk[], nameOfId: (id: string) => string): LoopAskPair[] {
  type Group = {
    first: LoopAsk;
    directions: Map<string, { from: string; to: string; count: number }>;
    open: boolean;
  };
  const groups = new Map<string, Group>();
  // 按发生先后数：两个方向的先后与次数都由此定，同一份事实每次画出来一样
  for (const ask of [...asks].sort((left, right) => left.position - right.position)) {
    const key = [ask.from, ask.to].sort().join(">");
    const group = groups.get(key);
    if (group === undefined) {
      groups.set(key, {
        first: ask,
        directions: new Map([[`${ask.from}>${ask.to}`, { from: ask.from, to: ask.to, count: 1 }]]),
        open: ask.open,
      });
      continue;
    }
    const directionKey = `${ask.from}>${ask.to}`;
    const direction = group.directions.get(directionKey);
    if (direction === undefined) {
      group.directions.set(directionKey, { from: ask.from, to: ask.to, count: 1 });
    } else {
      direction.count += 1;
    }
    group.open = group.open || ask.open;
  }
  const out: LoopAskPair[] = [];
  for (const [key, group] of groups) {
    const directions = [...group.directions.values()];
    const label = directions
      .map((direction) => `${nameOfId(direction.from)}问${nameOfId(direction.to)} ${direction.count} 次`)
      .join("，") + (group.open ? " · 开着" : "");
    out.push({
      kind: "pair",
      key: `pair:${key}`,
      from: group.first.from,
      to: group.first.to,
      directions,
      count: directions.reduce((sum, direction) => sum + direction.count, 0),
      open: group.open,
      label,
      place: group.first.place,
      gap: group.first.gap,
      fromIndex: group.first.fromIndex,
      toIndex: group.first.toIndex,
      partner: group.first.partner,
    });
  }
  return out;
}

/** 一条询问在节点往来里写的状态：开着的写「还没回答」，答完的写查询给的状态。 */
export function askStateText(ask: LoopAsk): string {
  return ask.open ? "还没回答" : ask.status;
}

/** 图上这个标识写什么：主线或旁边的职能的显示名，图外写来源与结束。找不到时不写英文标识。 */
export function nameOf(graph: LoopGraph, id: string): string {
  if (id === SOURCE) {
    return graph.sourceText;
  }
  if (id === END) {
    return graph.endText;
  }
  return graph.chain.find((node) => node.id === id)?.label
    ?? graph.side.find((part) => part.node.id === id)?.node.label
    ?? "";
}

/** 一种成果在页面上的名字；不是成果的流转（询问等）返回 null，不画成成果箭头。 */
export function outcomeOf(kind: string): string | null {
  if (kind === PRD_KIND) {
    return "PRD";
  }
  if (kind === DELIVERY_KIND) {
    return "交付";
  }
  if (kind === DEFECT_KIND) {
    return "缺陷记录";
  }
  return null;
}

/** 打回这一版的是哪个核验角色：按核验声明取，没有声明时取第一个核验角色。 */
function verifierOfPair(organization: FrozenOrganization, labels: Record<string, string>,
                        verified: string | null): string {
  const rejection = organization.rejections?.find((item) => item.role === verified);
  const id = rejection?.verifier ?? organization.verifiers[0]?.role;
  return id === undefined ? "" : labelOf(id, organization, labels);
}

/**
 * 箭头：成果与版本、第几轮，结论标在那一版上。
 *
 * 版本号按事件对到 work_item.materials 里的那一版（PRD 与交付）；缺陷记录没有版本号，按同一对职能之间
 * 出现的先后数（第 1 份、第 2 份）。结论：打回跟着它后面那条缺陷记录走，放行取事项的进度里对最新交付的结论。
 */
export function arrowsOf(item: LoopItemView | null, organization: FrozenOrganization,
                         flow: readonly FlowRecordLike[], materials: MaterialsView | null,
                         labels: Record<string, string>, receiver: string): LoopArrow[] {
  const out: LoopArrow[] = [];
  // 来源：原文（建档事项写建档）。一条输入一版，从图外进来，接它的是第一个节点
  const source = item?.kind === "onboarding" ? "建档" : "原文";
  for (const input of materials?.inputs ?? []) {
    out.push({
      key: `src:${input.version}`, outcome: source, version: input.version, round: null,
      from: SOURCE, to: receiver, back: false, position: input.version, verdict: null, text: input.text, files: [],
      eventId: input.created_event_id ?? null,
    });
  }
  const contracts = new Map((materials?.contracts ?? []).map((entry) => [entry.event_id, entry]));
  const deliveries = new Map((materials?.deliveries ?? []).map((entry) => [entry.event_id, entry]));
  const records = [...flow].sort((left, right) => left.position - right.position);
  const defects = new Map<string, number>();
  const lastDelivery = new Map<string, LoopArrow>();
  for (const record of records) {
    const outcome = outcomeOf(record.kind);
    if (outcome === null) {
      continue;
    }
    const from = record.direction_from ?? "";
    const to = record.direction_to ?? (record.kind === DELIVERY_KIND ? END : "");
    if (outcome === "缺陷记录") {
      const pair = `${from}>${to}`;
      const version = (defects.get(pair) ?? 0) + 1;
      defects.set(pair, version);
      const by = verifierOfPair(organization, labels, to);
      const arrow: LoopArrow = {
        key: record.flow_id, outcome, version, round: record.round ?? null, from, to, back: false,
        position: record.position, verdict: null, text: record.content, files: [],
        eventId: record.event_id,
      };
      out.push(arrow);
      // 打回是对那一版的结论：标在它前面那一版交付上；前面还没有交付时留在这条缺陷记录上
      const target = lastDelivery.get(`${to}>${from}`);
      const verdict = { tone: "reject" as const, by, text: `${by}打回` };
      if (target === undefined) {
        arrow.verdict = verdict;
      } else if (target.verdict === null) {
        target.verdict = verdict;
      }
      continue;
    }
    const version = outcome === "PRD"
      ? contracts.get(record.event_id)?.revision ?? null
      : deliveries.get(record.event_id)?.revision ?? null;
    const delivery = outcome === "交付" ? deliveries.get(record.event_id) : undefined;
    const arrow: LoopArrow = {
      key: record.flow_id, outcome, version, round: record.round ?? null, from, to, back: false,
      position: record.position, verdict: null, text: delivery?.summary ?? record.content,
      files: [...(delivery?.files ?? [])],
      eventId: record.event_id,
    };
    out.push(arrow);
    if (outcome === "交付") {
      lastDelivery.set(`${from}>${to}`, arrow);
    }
  }
  // 放行：对最新交付的结论（事项的进度，缺失时取最后一份结论是放行的核验）
  const conclusion = item?.progress?.conclusion ?? null;
  const lastReview = (materials?.reviews ?? []).at(-1)?.verdict ?? null;
  const released = conclusion === "release" || (conclusion === null && lastReview === "release");
  if (released) {
    const target = [...out].reverse().find((arrow) => arrow.outcome === "交付" && arrow.verdict === null);
    const ids = verifierIds(organization);
    const by = ids.map((id) => labelOf(id, organization, labels)).join("、");
    if (target !== undefined) {
      target.verdict = { tone: "release", by, text: `放行 · ${by}` };
    }
  }
  return out;
}

/** 同一种成果、同两端的几版：点箭头时按它逐版看。 */
export function versionsOf(arrows: readonly LoopArrow[], arrow: LoopArrow): LoopArrow[] {
  return arrows
    .filter((item) => item.outcome === arrow.outcome && item.from === arrow.from && item.to === arrow.to)
    .sort((left, right) => left.position - right.position);
}

/**
 * 结束写什么：按事项怎么结束的写，看停止原因（工单 #1704）。
 *
 * 以开环完成结束的事项（停止原因是 open_loop）采纳以前与采纳以后都写「开环完成：没有人核验」；
 * 组织里有核验角色、它只核验了中途成果时也一样，不写成放行。核验角色放行的写放行（放行待采纳与已采纳都写），
 * 停下来的写已停止。与线程一侧同一个口径（thread-model 的 endingOf）。
 */
function endOf(item: LoopItemView | null, organization: FrozenOrganization,
               labels: Record<string, string>): { text: string; tone: "ok" | "open" | "plain" } {
  const names = verifierIds(organization).map((id) => labelOf(id, organization, labels)).join("、");
  const conclusion = item?.progress?.conclusion ?? null;
  if (item !== null && item.status === "stopped") {
    return { text: "已停止", tone: "plain" };
  }
  // 事项结束过的两个状态：放行待采纳与已采纳
  const ended = item !== null && (item.status === "released_unsettled" || item.status === "adopted");
  // 开环完成按停止原因认，不按状态：采纳以后状态是 adopted，停止原因仍是 open_loop。
  // 停止原因还没有写下的旧数据里，没有核验角色的组织只能以开环完成结束，同样按它认
  const openLoop = item !== null
    && (item.stop_reason === "open_loop" || (item.stop_reason == null && names === "" && ended));
  if (openLoop) {
    return { text: "开环完成：没有人核验", tone: "open" };
  }
  // 核验角色放行：放行待采纳与已采纳都写放行
  if (conclusion === "release" || ended) {
    return { text: names === "" ? "完成" : `完成 · ${names}放行`, tone: "ok" };
  }
  if (names === "") {
    return { text: "开环完成", tone: "open" };
  }
  return { text: `${names}放行才结束`, tone: "plain" };
}

/**
 * 画一张循环图：节点、主线与旁边的职能、每一条缝里的箭头、两端写什么。
 *
 * 事项没有冻结的组织（形态不在这一版发布里）时给出空的节点与箭头，由页面说清楚为什么没有。
 */
export function graphOf(input: LoopGraphInput): LoopGraph {
  const labels = input.labels ?? {};
  const organization = input.item?.organization ?? null;
  const others = input.others ?? {};
  if (organization === null) {
    return {
      chain: [], side: [], gaps: [], skip: [], sourceText: "", endText: "", endTone: "plain", rounds: 0, nodes: [],
      asks: [], openAsks: [], lines: [],
    };
  }
  const roles = rolesOf(organization, labels);
  const verifiers = new Set(verifierIds(organization));
  const layout = layoutOf(organization, input.flow, roles, input.current);
  const currentRoles = input.currentRoles;
  // 询问从 run.asks 读：开着的画虚线，答完的只进节点的往来（设计说明 4.14）
  const asks = asksOf(layout, input.asks ?? [], organization);
  const openAsks = asks.filter((ask) => ask.open);
  // 打开累计往来时按两个职能合成一条（次数含开着的），不打开时只画开着的询问（工单 #1642）
  const lines: LoopAskLine[] = input.accumulated === true
    ? pairsOf(asks, (id) => labelOf(id, organization, labels))
    : openAsks;
  const waitingOf = (id: string): string[] => openAsks
    .filter((ask) => ask.from === id)
    .map((ask) => `在等待${labelOf(ask.to, organization, labels)}的回答`);
  const nodeOf = (role: LoopRole): LoopNode => {
    const state = input.item?.departments?.[role.id] ?? null;
    const stateWord = state === null ? "" : DEPARTMENT_STATE[state.state] ?? "";
    const note = state?.note ?? "";
    return {
      id: role.id,
      label: role.label,
      stateWord,
      // 节点上的字、角标与节点详情从同一份状态推出：状态词，有具体原因时写在括号里
      state: stateWord === "" ? "" : (note === "" ? stateWord : `${stateWord}（${note}）`),
      working: state?.state === "working",
      waiting: waitingOf(role.id),
      verifier: verifiers.has(role.id),
      // 项目现在的组织里没有这个职能：它只在旧组织里（现在的组织还没读到时不标）
      oldOnly: currentRoles !== undefined && currentRoles.length > 0 && !currentRoles.includes(role.id),
      others: others[role.id] ?? 0,
    };
  };
  const nodes = roles.map(nodeOf);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const chain = layout.chain.map((id) => byId.get(id)).filter((node): node is LoopNode => node !== undefined);
  const arrows = arrowsOf(input.item, organization, input.flow, input.materials, labels, layout.chain[0] ?? "");
  const at = (id: string): number => {
    if (id === SOURCE) {
      return -1;
    }
    if (id === END) {
      return chain.length;
    }
    return chain.findIndex((node) => node.id === id);
  };
  // 两端在图外（来源、结束）的箭头也在主线的格子里：第 0 格与最后一格
  const onChain = (id: string): boolean => id === SOURCE || id === END || chain.some((node) => node.id === id);
  const gaps: LoopArrow[][] = chain.map(() => []);
  gaps.push([]);
  const skip: LoopArrow[] = [];
  const outside: LoopArrow[] = [];
  for (const arrow of arrows) {
    if (!onChain(arrow.from) || !onChain(arrow.to)) {
      outside.push(arrow);
      continue;
    }
    const from = at(arrow.from);
    const to = at(arrow.to);
    if (from === to) {
      outside.push(arrow);
      continue;
    }
    // 箭头朝右是交给下一个职能，朝左是回头（缺陷记录）
    arrow.back = to < from;
    if (Math.abs(to - from) === 1) {
      gaps[Math.max(from, to)].push(arrow);
      continue;
    }
    // 跨过中间节点的箭头（PRD 同时给质检）另起一行，仍是实线
    skip.push(arrow);
  }
  const end = endOf(input.item, organization, labels);
  return {
    chain,
    side: layout.side.map((part) => {
      const node = byId.get(part.id);
      return node === undefined
        ? null
        : {
          node,
          partner: part.partner,
          arrows: outside.filter((arrow) => arrow.from === part.id || arrow.to === part.id),
          // 它与主线之间的虚线（开着的询问，或累计往来）：竖线换成它（「产品 · 工程」）
          lines: lines.filter((line) => line.place === "side" && line.partner === part.partner
            && (line.from === part.id || line.to === part.id)),
        };
    }).filter((part): part is LoopSide => part !== null),
    gaps,
    skip,
    sourceText: input.item?.kind === "onboarding" ? "建档" : "你的输入",
    endText: end.text,
    endTone: end.tone,
    rounds: input.item?.round ?? 0,
    nodes,
    asks,
    openAsks,
    lines,
  };
}

/**
 * 图上画哪一件事项：默认最近在跑的那一件（在跑的事项里开始得最晚的），没有在跑的时取最后一件；
 * 地址里写了哪一件就画哪一件。
 */
export function pickItem(items: readonly LoopItemView[], requested: string | null | undefined): LoopItemView | null {
  if (requested) {
    const hit = items.find((item) => item.work_item_id === requested);
    if (hit !== undefined) {
      return hit;
    }
  }
  const running = items.filter((item) => !DONE_STATUS.has(item.status));
  const pool = running.length > 0 ? running : items;
  const sorted = [...pool].sort((left, right) => (right.started_at ?? "").localeCompare(left.started_at ?? ""));
  return sorted[0] ?? null;
}

/** 别的事项在对应职能上记的件数：还在做、而且这个职能有一轮在工作（或正在回答询问、核验）。 */
export function otherCounts(items: readonly LoopItemView[], selected: string | null): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    if (item.work_item_id === selected || DONE_STATUS.has(item.status)) {
      continue;
    }
    const ids = new Set<string>();
    if (item.department) {
      ids.add(item.department);
    }
    for (const [id, state] of Object.entries(item.departments ?? {})) {
      if (state.state === "working" || state.state === "asking" || state.state === "verifying") {
        ids.add(id);
      }
    }
    for (const id of ids) {
      counts[id] = (counts[id] ?? 0) + 1;
    }
  }
  return counts;
}
