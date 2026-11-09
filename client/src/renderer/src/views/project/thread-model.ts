// 对话线程与输入框的事实推出（工单 #1639，项目的组织设计说明 4.14「项目页是循环图加对话」的交互骨架第 1 至 3 条）。
//
// 这里只取值、排序与判断，不碰界面与网络，单元测试直接调用（thread-model.test.ts）。线程里出现的每一句话都从
// 已经发生过的事实推出，不另存一份：
//   - 你写的与指导取 project.flow（kind 为「你的输入」「指导」；事项创建是第 0 轮的那一句）；
//   - 角色之间的往来取 run.asks 里答完的询问（问与答），以及 project.flow 里角色交给角色的成果
//     （PRD 新版本、版本交付、问题反馈）；进行中的询问画在循环图上，不进线程；
//   - 要你决定的取 decisions.list；
//   - 交完成、放行与事项的结果取事项的状态与流转记录（放行那一条来自 kind 为「放行」的记录）。
//
// 几条固定的读法：
//   - 线程默认只露「你写的」「要你决定的」「交完成或放行」三种话；角色之间的往来折成一行，点开才展开。
//   - 折叠行只合并连续的往来：被你写的、要你决定的、交完成或放行打断以后另起一行；往来发生在别的两个职能之间
//     也另起一行。
//   - 已结束的事项默认收起，只露细线与交完成或放行那一条。
//   - 收件人按在跑事项冻结的组织给出（项目换过形态以后仍按它）；默认值按状态选，点过节点以后切到给那个职能的指导。
//   - 名字从冻结的组织与项目现在的组织里取显示名，页面上不出现内部标识。

import { workItemStatusText } from "./labels.ts";

/** 一个职能（事项冻结的组织里的一项）。 */
export interface ThreadRole {
  id: string;
  label: string;
}

/**
 * 一个事项冻结的组织（project.loop 的 organization）。
 *
 * 与循环图读的是同一份：职能、核验声明、轮转方式与关注关系。收件人的选项按这一份给出，
 * 项目后来换过形态也不拿现在的组织顶替。
 */
export interface ThreadOrganization {
  form: string;
  routing: string;
  roles: readonly ThreadRole[];
  verifiers: readonly { role: string; verifies: readonly { role: string; outcomes: readonly string[] }[] }[];
  completing?: { id: string; label: string } | null;
  watched: readonly { source: string; recipient: string; outcome: string }[];
  asks?: readonly { requester: string; recipient: string }[];
  rejections?: readonly { verifier: string; role: string; outcome: string }[];
}

/** project.loop 的一项：线程读的那几栏。 */
export interface ThreadItemView {
  work_item_id: string;
  kind?: string | null;
  status: string;
  stop_reason?: string | null;
  round?: number;
  started_at?: string | null;
  department?: string | null;
  departments?: Record<string, { state: string; note?: string | null }> | null;
  progress?: { conclusion?: string | null } | null;
  organization?: ThreadOrganization | null;
  run_id?: string | null;
}

/** project.flow 的一条。 */
export interface ThreadFlowRecord {
  flow_id: string;
  kind: string;
  content: string;
  direction_from: string | null;
  direction_to: string | null;
  position: number;
  round?: number | null;
  work_item_id?: string | null;
  created_at?: string | null;
}

/** run.asks 的一项（只列线程用到的字段）。 */
export interface ThreadAsk {
  id: string;
  requester: string;
  recipient: string;
  question: string;
  background?: string | null;
  expected?: string | null;
  status: string;
  answer?: string | null;
  answer_facts?: string | null;
  answer_explanation?: string | null;
  started_at: string;
  ended_at?: string | null;
  start_position: number;
  end_position?: number | null;
}

/** decisions.list 的一项（只列线程用到的字段；请求与回答的载荷按原样带走）。 */
export interface ThreadDecision {
  decision_id: string;
  kind: string;
  status: string;
  work_item_id: string | null;
  requested_at: string;
  version: number;
  request?: { [key: string]: unknown } | null;
  answer?: { option?: string | null; note?: string | null; answered_at?: string } | null;
}

/** 折叠行里的一条话。问答的两条分别是 question 与 answer。 */
export interface ThreadMessage {
  key: string;
  /** 说这句话的职能标识（只用来取显示名与排样式，不写到页面上） */
  who: string;
  whoLabel: string;
  /** 问的那一条：问的是谁（显示名）；其余为空 */
  toLabel: string | null;
  text: string;
  at: string;
  role: "question" | "answer" | "message";
  /** 工程回答质检时分开的两段；其余为空 */
  facts: string | null;
  explanation: string | null;
  /** 解释旁写明核验角色对哪一版下了结论以后才看到；不要解释或不是核验角色问的时为空 */
  explanationNote: string | null;
}

/** 线程里的一项。sep 是事项之间那条细线，其余是线程里的一行或一个气泡。 */
export type ThreadEntry =
  | { kind: "sep"; key: string; item: string; title: string; result: string; ended: boolean; expandable: boolean }
  | { kind: "you"; key: string; item: string; at: string; text: string; tag: string; long: boolean }
  | { kind: "fold"; key: string; item: string; at: string; label: string; roles: string[]; messages: ThreadMessage[] }
  | {
    kind: "done"; key: string; item: string; at: string; who: string; whoLabel: string;
    label: string; text: string; release: boolean; flowId: string | null;
  }
  | { kind: "decision"; key: string; item: string | null; at: string; decision: ThreadDecision }
  | { kind: "notice"; key: string; item: string; at: string; text: string };

/** 一条消息的显示长度上限：超过以后先折起来，点开看全文。 */
export const LONG_TEXT_LIMIT = 140;

/** 这句话太长，线程里先折叠（项目组织设计说明 4.14：你写的话太长时折叠，点开看全文）。 */
export function isLongText(text: string): boolean {
  return text.length > LONG_TEXT_LIMIT;
}

/** 折起来以后显示的那一段：前 LONG_TEXT_LIMIT 个字加省略号；不长时原样。 */
export function shortText(text: string): string {
  return isLongText(text) ? `${text.slice(0, LONG_TEXT_LIMIT)}…` : text;
}

/** 一个职能在页面上的名字：项目现在的组织给了名字先用它，旧组织里的用冻结的那一份，都没有时用标识（不写到页面上）。 */
export function roleLabel(
  id: string,
  organization?: ThreadOrganization | null,
  labels: Record<string, string> = {},
): string {
  return labels[id] ?? organization?.roles.find((role) => role.id === id)?.label ?? id;
}

const DONE_STATUS = new Set(["adopted", "released_unsettled", "stopped"]);
const INPUT_KIND = "你的输入";
const GUIDANCE_KIND = "指导";
const RELEASE_KIND = "放行";
const DELIVERY_KIND = "版本交付";
const ROLE_KINDS = new Set(["PRD 新版本", "版本交付", "问题反馈"]);

/** 事项结束了没有（结束的事项默认收起）。 */
export function isEnded(item: ThreadItemView): boolean {
  return DONE_STATUS.has(item.status);
}

/**
 * 接收你的输入的职能（直做的形态要靠它决定「工程接」）。
 *
 * 冻结的组织没有 sources 一栏，按这个顺序取：项目现在的组织与冻结的是同一份形态时照它的 sources.user_input；
 * 否则看这件事项已经发生的事——交出最后一版交付的职能；再没有时取冻结组织里的第一个职能。
 */
export function receiverOf(
  organization: ThreadOrganization,
  flow: readonly ThreadFlowRecord[],
  current?: { form?: string | null; sources?: Record<string, string> | null } | null,
): string {
  const ids = organization.roles.map((role) => role.id);
  const sameForm = current?.form !== undefined && current?.form !== null && current.form === organization.form;
  const picked = sameForm ? current?.sources?.user_input ?? null : null;
  if (picked !== null && ids.includes(picked)) {
    return picked;
  }
  const records = [...flow].sort((left, right) => left.position - right.position);
  const sender = records.filter((record) => record.kind === DELIVERY_KIND && record.direction_from).at(-1)?.direction_from
    ?? records.find((record) => record.direction_from)?.direction_from
    ?? null;
  if (sender !== null && ids.includes(sender)) {
    return sender;
  }
  return ids[0] ?? "";
}

/** 正在做的那件事项（有事项在做时收件人默认给它的指导）：最晚开始的一件，等待确认初始 PRD 也算在做。 */
export function runningItem(items: readonly ThreadItemView[]): ThreadItemView | null {
  const running = items.filter((item) => item.status === "in_progress" || item.status === "awaiting_initial_prd");
  const sorted = [...running].sort((left, right) => (right.started_at ?? "").localeCompare(left.started_at ?? ""));
  return sorted[0] ?? null;
}

/** 一件在跑的事项里正在工作的那个职能：事项的当前部门，其次状态是 working 的那个，都没有时为空。 */
export function workingRoleOf(item: ThreadItemView | null): string | null {
  if (item === null || item.organization == null) {
    return null;
  }
  const ids = new Set(item.organization.roles.map((role) => role.id));
  if (item.department != null && ids.has(item.department)) {
    return item.department;
  }
  for (const [id, state] of Object.entries(item.departments ?? {})) {
    if (state.state === "working" && ids.has(id)) {
      return id;
    }
  }
  return null;
}

/** 一件事项下面要你决定的那几条（撤销的不算；项目层面的那条不挂在事项下）。 */
export function decisionsForItem(decisions: readonly ThreadDecision[], workItemId: string): ThreadDecision[] {
  return decisions.filter((decision) => decision.work_item_id === workItemId && decision.status !== "withdrawn");
}

/** 不属于任何事项的决定请求（观察者发现的、项目层面的）：另放在线程末尾。 */
export function projectDecisions(decisions: readonly ThreadDecision[]): ThreadDecision[] {
  return decisions.filter((decision) => decision.work_item_id === null && decision.status !== "withdrawn");
}

export interface ItemThreadInput {
  item: ThreadItemView;
  flow: readonly ThreadFlowRecord[];
  asks: readonly ThreadAsk[];
  decisions?: readonly ThreadDecision[];
  /** 事项标题：project.overview 给出的那一份 */
  titles?: Record<string, string>;
  /** 职能显示名：项目现在的组织给出的名字先用 */
  labels?: Record<string, string>;
  /** 这件事项在排队时排在谁后面（有事项在做时新开的那一件）；没有时为空 */
  queuedBehind?: string | null;
  /** 已结束的事项要展开才看完整的；默认收起 */
  expanded?: boolean;
}

/** 一条消息的内部形状：折叠之前先排好先后。 */
type Atom =
  | { kind: "role"; time: number; at: string; order: number; from: string; to: string; messages: ThreadMessage[] }
  | { kind: "entry"; time: number; at: string; order: number; entry: ThreadEntry };

/** 一件事项的结果：交完成或放行那一条，以及它指向的那一版交付。 */
interface Ending {
  done: ThreadFlowRecord;
  delivery: ThreadFlowRecord | null;
  release: boolean;
  openLoop: boolean;
}

/** 引用时刻：有时间的事实按时间排；旧数据没有时间时按它在事件流里的位置排（不编一个时间）。 */
function stamp(iso: string | null | undefined, position: number): { at: string; time: number } {
  const parsed = typeof iso === "string" && iso !== "" ? Date.parse(iso) : Number.NaN;
  if (!Number.isNaN(parsed)) {
    return { at: iso as string, time: parsed };
  }
  return { at: iso ?? "", time: position };
}

/** 这件事项结束时线程里写的那一条：有放行记录时写放行，否则写交完成（开环完成另写一句）。 */
function endingOf(item: ThreadItemView, flow: readonly ThreadFlowRecord[]): Ending | null {
  if (item.status === "stopped" || !isEnded(item)) {
    return null;
  }
  const ordered = [...flow].sort((left, right) => left.position - right.position);
  const release = ordered.filter((record) => record.kind === RELEASE_KIND).at(-1) ?? null;
  const delivery = ordered.filter((record) => record.kind === DELIVERY_KIND).at(-1) ?? null;
  const openLoop = item.status === "released_unsettled" && item.stop_reason === "open_loop";
  if (openLoop) {
    return delivery === null ? null : { done: delivery, delivery, release: false, openLoop: true };
  }
  if (release !== null) {
    return { done: release, delivery, release: true, openLoop: false };
  }
  return delivery === null ? null : { done: delivery, delivery, release: false, openLoop: false };
}

/** 交完成那一条的正文：开环完成写明没有人核验，不写成放行。 */
function doneText(ending: Ending): string {
  if (ending.release) {
    return ending.done.content;
  }
  if (!ending.openLoop) {
    return ending.done.content;
  }
  const summary = ending.done.content.trim();
  const head = summary === "" ? "做完了。" : `做完了：${summary}。`;
  return `${head}开环完成：没有人核验`;
}

/** 核验角色问被核验的一方时，解释旁写明它对哪一版下了结论以后才看到：数它问之前这个职能交给它的交付。 */
function explanationNoteOf(
  ask: ThreadAsk,
  organization: ThreadOrganization | null,
  labels: Record<string, string>,
  flow: readonly ThreadFlowRecord[],
): string | null {
  const explanation = ask.answer_explanation ?? "";
  if (organization === null || explanation.trim() === "") {
    return null;
  }
  const verifies = organization.verifiers.some(
    (verifier) => verifier.role === ask.requester
      && verifier.verifies.some((verified) => verified.role === ask.recipient),
  );
  if (!verifies) {
    return null;
  }
  const before = flow.filter((record) => record.kind === DELIVERY_KIND
    && record.direction_from === ask.recipient
    && record.direction_to === ask.requester
    && record.position < ask.start_position).length;
  const name = roleLabel(ask.requester, organization, labels);
  return before === 0 ? `${name}对交付下结论以后才看到` : `${name}对交付第 ${before} 版下结论以后才看到`;
}

/**
 * 一件事项在线程里的那些行：细线、你写的、要你决定的、折叠行、交完成或放行。
 *
 * 已结束的事项收起时只有细线与交完成或放行那一条；展开以后才看完整的（设计说明 4.14 交互骨架第 1 条）。
 */
export function itemThread(input: ItemThreadInput): ThreadEntry[] {
  const { item } = input;
  const labels = input.labels ?? {};
  const organization = item.organization ?? null;
  const itemId = item.work_item_id;
  const title = input.titles?.[itemId] ?? "这件事项";
  const ended = isEnded(item);
  const roleIds = new Set(organization?.roles.map((role) => role.id) ?? []);
  const atoms: Atom[] = [];
  let order = 0;

  // 结束那一条先从流转记录里挑出来：它不重复出现在折叠行里
  const ending = endingOf(item, input.flow);
  const endingIds = new Set<string>();
  if (ending !== null) {
    endingIds.add(ending.done.flow_id);
    if (ending.delivery !== null) {
      endingIds.add(ending.delivery.flow_id);
    }
  }

  for (const record of input.flow) {
    const { at, time } = stamp(record.created_at, record.position);
    if (record.kind === INPUT_KIND) {
      atoms.push({
        kind: "entry", time, at, order: order++,
        entry: {
          kind: "you", key: record.flow_id, item: itemId, at,
          text: record.content, tag: record.round === 0 ? "开始一个新事项" : "追加输入",
          long: isLongText(record.content),
        },
      });
      continue;
    }
    if (record.kind === GUIDANCE_KIND) {
      atoms.push({
        kind: "entry", time, at, order: order++,
        entry: {
          kind: "you", key: record.flow_id, item: itemId, at,
          text: record.content, tag: `给${roleLabel(record.direction_to ?? "", organization, labels)}的指导`,
          long: isLongText(record.content),
        },
      });
      continue;
    }
    if (!ROLE_KINDS.has(record.kind) || endingIds.has(record.flow_id)) {
      continue;
    }
    const from = record.direction_from;
    const to = record.direction_to;
    // 只看角色交给角色的往来；两端有一端不是这份组织里的职能时（图外的来源、结束）不进折叠行
    if (from === null || to === null || !roleIds.has(from) || !roleIds.has(to)) {
      continue;
    }
    atoms.push({
      kind: "role", time, at, order: order++, from, to,
      messages: [{
        key: record.flow_id, who: from, whoLabel: roleLabel(from, organization, labels), toLabel: null,
        text: record.content, at, role: "message", facts: null, explanation: null, explanationNote: null,
      }],
    });
  }

  for (const ask of input.asks) {
    // 答完的询问才收进来；进行中的那几次画在循环图上（设计说明 4.14：答完的询问收进折叠行）
    if (ask.status === "进行中") {
      continue;
    }
    if (!roleIds.has(ask.requester) || !roleIds.has(ask.recipient)) {
      continue;
    }
    const asked = stamp(ask.started_at, ask.start_position);
    const answered = stamp(ask.ended_at ?? ask.started_at, ask.start_position);
    const question: ThreadMessage = {
      key: `${ask.id}:q`, who: ask.requester, whoLabel: roleLabel(ask.requester, organization, labels),
      toLabel: roleLabel(ask.recipient, organization, labels), text: ask.question, at: asked.at,
      role: "question", facts: null, explanation: null, explanationNote: null,
    };
    const answer: ThreadMessage = {
      key: `${ask.id}:a`, who: ask.recipient, whoLabel: roleLabel(ask.recipient, organization, labels),
      toLabel: null, text: ask.answer ?? "", at: answered.at, role: "answer",
      facts: ask.answer_facts ?? null,
      explanation: ask.answer_explanation ?? null,
      explanationNote: explanationNoteOf(ask, organization, labels, input.flow),
    };
    atoms.push({ kind: "role", time: answered.time, at: answered.at, order: order++, from: ask.requester, to: ask.recipient, messages: [question, answer] });
  }

  for (const decision of input.decisions ?? []) {
    if (decision.work_item_id !== itemId || decision.status === "withdrawn") {
      continue;
    }
    const { at, time } = stamp(decision.requested_at, 0);
    atoms.push({
      kind: "entry", time, at, order: order++,
      entry: { kind: "decision", key: decision.decision_id, item: itemId, at, decision },
    });
  }

  // 新开的事项排在一件在做的事项后面：线程里写与收件人一行同样的一句话
  if (input.queuedBehind != null && input.queuedBehind !== "" && item.status === "not_started") {
    const first = input.flow.find((record) => record.kind === INPUT_KIND);
    const { at, time } = stamp(first?.created_at ?? item.started_at, first?.position ?? 0);
    atoms.push({
      kind: "entry", time, at, order: order++,
      entry: { kind: "notice", key: `queue:${itemId}`, item: itemId, at, text: `排在「${input.queuedBehind}」后面，它做完才开始` },
    });
  }

  if (ending !== null) {
    const { at, time } = stamp(ending.done.created_at, ending.done.position);
    atoms.push({
      kind: "entry", time, at, order: order++,
      entry: {
        kind: "done", key: `done:${itemId}`, item: itemId, at,
        who: ending.done.direction_from ?? "",
        whoLabel: roleLabel(ending.done.direction_from ?? "", organization, labels),
        label: ending.release ? "放行" : "交完成",
        text: doneText(ending), release: ending.release,
        flowId: ending.delivery?.flow_id ?? null,
      },
    });
  }

  atoms.sort((left, right) => (left.time - right.time) || (left.order - right.order));

  // 折叠行只合并连续的往来：中间隔着别的话就另起一行
  const rows: ThreadEntry[] = [];
  let lastFold: { pair: string; entry: Extract<ThreadEntry, { kind: "fold" }> } | null = null;
  for (const atom of atoms) {
    if (atom.kind === "role") {
      const pair = [atom.from, atom.to].sort().join(">");
      if (lastFold !== null && lastFold.pair === pair) {
        lastFold.entry.messages.push(...atom.messages);
        continue;
      }
      const entry: Extract<ThreadEntry, { kind: "fold" }> = {
        kind: "fold", key: `fold:${itemId}:${atom.order}`, item: itemId, at: atom.at,
        label: `${roleLabel(atom.from, organization, labels)}与${roleLabel(atom.to, organization, labels)}往来`,
        roles: [atom.from, atom.to], messages: [...atom.messages],
      };
      rows.push(entry);
      lastFold = { pair, entry };
      continue;
    }
    rows.push(atom.entry);
    lastFold = null;
  }

  const sep: ThreadEntry = {
    kind: "sep", key: `sep:${itemId}`, item: itemId, title, result: workItemStatusText(item),
    ended, expandable: rows.some((entry) => entry.kind !== "done"),
  };
  if (ended && input.expanded !== true) {
    return [sep, ...rows.filter((entry) => entry.kind === "done")];
  }
  return [sep, ...rows];
}

// ---------------------------------------------------------------- 收件人

/** 一个职能的显示名（收件人选项用）：项目现在的名字先用，其次冻结的组织里的。 */
export interface ComposerRole {
  id: string;
  label: string;
}

/**
 * 收件人一行读的事实：
 *   - 在跑事项冻结的组织（frozen）：换过形态以后选项仍按它；没有在跑事项时为空，用项目现在的组织（roles/routing）；
 *   - receiver：接你的输入的职能；
 *   - working：正在工作的职能（默认的指导对象）；
 *   - focus：点过节点的那一个（直做里多出给它的指导一项）；
 *   - active：有事项在做（没有时默认「开始一个新事项」，也没有追加输入）。
 */
export interface ComposerInput {
  frozen: ThreadOrganization | null;
  roles: readonly ComposerRole[];
  routing: string;
  receiver: string;
  working: string | null;
  focus: string | null;
  active: boolean;
  labels?: Record<string, string>;
}

export type RecipientOption = {
  id: string;
  kind: "new" | "append" | "guide";
  department: string | null;
  label: string;
};

/** 收件人连续发送的两种记忆：选过的指导对象（manual）与输入框里有字时冻住的那一个（hold）。 */
export type ComposerState = { manual: string | null; hold: string | null };

function composerFacts(input: ComposerInput): { roles: readonly ComposerRole[]; routing: string } {
  return input.frozen === null
    ? { roles: input.roles, routing: input.routing }
    : { roles: input.frozen.roles, routing: input.frozen.routing };
}

function nameOf(id: string, input: ComposerInput, roles: readonly ComposerRole[]): string {
  return input.labels?.[id] ?? roles.find((role) => role.id === id)?.label ?? id;
}

/**
 * 收件人一行的选项（设计说明 4.14 交互骨架第 2 条）：
 *   直做是「开始一个新事项」「给接输入的职能的指导」，点过别的节点再多出给它的指导一项；
 *   按成果是「开始一个新事项」「追加输入」「每个职能一项指导」。
 */
export function recipientOptions(input: ComposerInput): RecipientOption[] {
  const { roles, routing } = composerFacts(input);
  const ids = roles.map((role) => role.id);
  const receiver = ids.includes(input.receiver) ? input.receiver : ids[0] ?? "";
  const options: RecipientOption[] = [
    { id: "new", kind: "new", department: null, label: "开始一个新事项" },
  ];
  if (routing !== "direct" && input.active) {
    options.push({
      id: "append", kind: "append", department: null,
      label: `追加输入（${nameOf(receiver, input, roles)}接，重新验收）`,
    });
  }
  const guides: string[] = [];
  if (routing === "direct") {
    if (receiver !== "") {
      guides.push(receiver);
    }
    if (input.focus !== null && ids.includes(input.focus) && !guides.includes(input.focus)) {
      guides.push(input.focus);
    }
  } else {
    guides.push(...ids);
  }
  for (const id of guides) {
    options.push({ id: `guide:${id}`, kind: "guide", department: id, label: `给${nameOf(id, input, roles)}的指导` });
  }
  return options;
}

/** 按状态选的默认收件人：没有事项在做时是开始一个新事项，有事项在做时给正在工作的职能（读不到时给接输入的职能）。 */
export function defaultRecipient(input: ComposerInput): string {
  if (!input.active) {
    return "new";
  }
  const guides = recipientOptions(input).filter((option) => option.kind === "guide").map((option) => option.id);
  const working = input.working === null ? "" : `guide:${input.working}`;
  if (guides.includes(working)) {
    return working;
  }
  const receiver = `guide:${input.receiver}`;
  return guides.includes(receiver) ? receiver : guides[0] ?? "new";
}

/** 现在选中的收件人：有字时冻住的那一个先在，其次是选过的指导对象，都没有时按状态选。 */
export function chosenRecipient(input: ComposerInput, state: ComposerState): string {
  const options = recipientOptions(input);
  const valid = (id: string | null): boolean => id !== null && options.some((option) => option.id === id);
  if (valid(state.hold)) {
    return state.hold as string;
  }
  if (valid(state.manual)) {
    return state.manual as string;
  }
  return defaultRecipient(input);
}

/**
 * 输入框里的字变了：从没有字变成有字时把当时的收件人冻住（事项进展不再改它），
 * 清空以后恢复按状态选（设计说明 4.14：输入框里有字以后收件人不再随状态变，发送后恢复按状态选）。
 */
export function draftChanged(state: ComposerState, draft: string, current: string): ComposerState {
  return { manual: state.manual, hold: draft.trim() === "" ? null : state.hold ?? current };
}

/**
 * 发送之后：发的是指导就把它记为选中的对象（连续发送时保持不变）；
 * 发的是新事项或追加输入就回到按状态选的默认。
 */
export function afterSend(state: ComposerState, sent: string): ComposerState {
  void state;
  return sent.startsWith("guide:") ? { manual: sent, hold: null } : { manual: null, hold: null };
}

/** 收件人下面那一行说明（设计说明 4.14：新事项排在谁后面、追加输入要重新验收、指导下一轮读到）。 */
export function recipientHint(input: ComposerInput, recipientId: string, activeTitle: string): string {
  const { roles } = composerFacts(input);
  const ids = roles.map((role) => role.id);
  const receiver = ids.includes(input.receiver) ? input.receiver : ids[0] ?? "";
  const option = recipientOptions(input).find((candidate) => candidate.id === recipientId);
  if (option === undefined) {
    return "";
  }
  const working = input.active && activeTitle !== "";
  if (option.kind === "new") {
    return working ? `排在「${activeTitle}」后面，它做完才开始` : `${nameOf(receiver, input, roles)}接，马上开始`;
  }
  if (option.kind === "append") {
    return `${nameOf(receiver, input, roles)}接，已有的交付要重新验收`;
  }
  const who = option.department === null ? "" : nameOf(option.department, input, roles);
  return working ? `发给${who}：用在「${activeTitle}」上，下一轮读到` : `发给${who}`;
}
