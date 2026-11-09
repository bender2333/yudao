// 时序图的事实推出（工单 #1641，项目的组织设计说明 4.14「项目页是循环图加对话」的「时序图（经过）」一节、
// 4.15「循环图跟着组织长」的时序图一行；应用层与接口层设计说明 4.4「项目页四层读哪个查询」）。
//
// 这里只做取值与判断，不碰界面与网络：视图按这里给出的列、行、轮、摘要与色条照画，单元测试直接核对。
// 读的三处事实，与接口设计说明 4.4 的表一致：
//   - project.flow：成果、你的输入、指导、打回与放行（每条带第几轮）；询问不读它，见下一条；
//   - run.asks：询问与回答、缩进（询问链的层数）、提问方的等待；
//   - decisions.list：要你决定、你决定与等你决定。
//
// 几条固定的读法（设计说明 4.14「时序图」）：
//   - 列是这个事项冻结的组织里的职能和你，事项开始以后组织改了也不变；
//   - 一行一条消息，询问与回答是虚线，其余（成果、你的输入、指导、决定）是实线；
//   - 同一版同时给几个职能是一行：流转记录按事件合成一条，去向合起来；
//   - 放行与打回是对某一版的结论，标在那一版那一行上，不单独占一行；没有那条事实就不写结论；
//   - 提问方等待的时段在它那一列上画一段色条，等你决定也一样，还没等到的画到「现在」；
//   - 按轮折叠，只展开最新一轮，折起来的一行写这一轮的摘要。
//
// 版本号（PRD v1、交付 v2）按事件对到 work_item.materials 的那一版：project.flow 的记录里只有文字内容，
// 版本号在成果材料里，循环图的箭头也这样读（loop-graph-model 的 arrowsOf），两处写出的版本因此一致。

/** 「你」在列与行里的标识：不是任何一个职能。 */
export const YOU = "you";

const INPUT_KIND = "你的输入";
const GUIDANCE_KIND = "指导";
const PRD_KIND = "PRD 新版本";
const DELIVERY_KIND = "版本交付";
const DEFECT_KIND = "问题反馈";
const RELEASE_KIND = "放行";
// 流转记录里的询问不读（应用层与接口层设计说明 4.4）：那一条只有一行，回答到达时内容被回答替换，
// 问题与结束时间读不到；询问、回答与等待一律读 run.asks
const ASK_KIND = "询问";

/** 一个职能（事项冻结的组织里的一项，显示名已经换成项目现在组织的名字）。 */
export interface SequenceRole {
  id: string;
  label: string;
}

/** project.flow 的一条：时序图读的那几栏。 */
export interface FlowRowLike {
  flow_id: string;
  event_id: string;
  kind: string;
  content: string;
  direction_from: string | null;
  direction_to: string | null;
  position: number;
  /** 第几轮：产生这条记录的那次激活（事项创建时是第 0 轮） */
  round: number;
  created_at: string;
}

/** run.asks 的一次询问：时序图读的那几栏。 */
export interface AskLike {
  id: string;
  requester: string;
  recipient: string;
  question: string;
  status: "进行中" | "已回答" | "没能回答";
  answer?: string | null;
  answer_facts?: string | null;
  reason?: string | null;
  parent?: string | null;
  /** 询问链：从最外层起经过的职能；最外层只有它自己 */
  chain: readonly string[];
  /** 询问链上的询问数：最外层为 1 */
  depth: number;
  start_position: number;
  ended_at?: string | null;
  started_at: string;
}

/** 决定请求里时序图读的那几栏（decisions.list 的 request）。 */
export interface DecisionRequestLike {
  department?: string | null;
  description?: string | null;
  options?: readonly { id: string; label: string }[] | null;
}

/** 决定的回答（decisions.list 的 answer）。 */
export interface DecisionAnswerLike {
  option: string;
  note?: string | null;
  answered_at: string;
}

/** decisions.list 的一条：要你决定与你决定。 */
export interface DecisionLike {
  decision_id: string;
  work_item_id?: string | null;
  status: "open" | "answered" | "withdrawn";
  requested_at: string;
  request: DecisionRequestLike;
  answer?: DecisionAnswerLike | null;
}

/** work_item.materials 里时序图用到的两栏：成果的版本号按事件对。 */
export interface SequenceMaterials {
  contracts?: readonly { event_id: string; revision: number | null }[];
  deliveries?: readonly { event_id: string; revision: number | null }[];
}

export interface SequenceInput {
  /** 事项冻结的组织里的职能（显示名已经换成项目现在组织的名字） */
  roles: readonly SequenceRole[];
  flow: readonly FlowRowLike[];
  asks?: readonly AskLike[];
  decisions?: readonly DecisionLike[];
  materials?: SequenceMaterials | null;
  /** 「现在」：还没等到的色条画到这里，图上最后多一行「现在」；没有开着的等待时用不到 */
  now?: string | null;
  /** 展开的是哪几轮；不给时只展开最新一轮 */
  openRounds?: readonly number[] | null;
}

/** 一行是哪种消息：成果、你的输入、指导、询问、回答、要你决定、你决定。 */
export type SequenceRowKind = "outcome" | "input" | "guidance" | "ask" | "answer" | "decide" | "decided";

/** 一段等待：画在哪一列上、是哪一种（在等回答、等你决定）。 */
export interface SequenceBar {
  column: string;
  kind: "ask" | "user";
  /** 鼠标停在色条上时说的话 */
  tip: string;
}

/** 时序图的一行。 */
export interface SequenceRow {
  key: string;
  kind: SequenceRowKind;
  /** 询问与回答是虚线，其余是实线 */
  dashed: boolean;
  from: string;
  /** 一行可以同时给几个职能（同一版给工程与质检） */
  to: string[];
  /** 窄屏的列表里写的那一句：谁到谁 */
  who: string;
  at: string;
  /** 这一行的那一句标题 */
  title: string;
  /** 询问里又问的缩进：0 是最外层 */
  depth: number;
  round: number;
  /** 打回或放行：标在这一版这一行上 */
  verdict: { tone: "reject" | "release"; text: string } | null;
  /** 还没有回答的询问、还没有回答的决定 */
  open: boolean;
  /** 这一行上正在等的几段：提问方那一列上的色条 */
  bars: SequenceBar[];
}

/** 一轮：这一轮的行，折起来时写的一句摘要。 */
export interface SequenceRound {
  round: number;
  rows: SequenceRow[];
  summary: string;
  open: boolean;
}

export interface SequenceColumn {
  id: string;
  label: string;
}

export interface SequenceView {
  /** 你与这个事项冻结的组织里的职能，从左到右的顺序就是列的顺序 */
  columns: SequenceColumn[];
  rounds: SequenceRound[];
  /** 还有等待没到时的「现在」；没有开着的等待时为 null */
  now: string | null;
  /** 一行也没有（这个事项还没有经过） */
  empty: boolean;
  latestRound: number;
}

/** 内部的一行：加上排序用的次序、它关掉哪一段等待、以及它是哪一段等待的开始。 */
interface BuiltRow extends SequenceRow {
  order: number;
  closes: string | null;
  wait: SequenceBar | null;
}

/** 只有一个职能时没有时序图，图上也没有「看经过」（设计说明 4.15）。 */
export function hasSequence(roles: readonly { id: string }[]): boolean {
  return roles.length > 1;
}

/** 取一段文字里的第一句：每行只有一句标题，多行的内容在原文面板里看。 */
export function firstLine(value: string | null | undefined): string {
  for (const line of (value ?? "").split("\n")) {
    const text = line.trim();
    if (text !== "") {
      return text;
    }
  }
  return "";
}

function timeOf(at: string): number {
  const value = Date.parse(at);
  return Number.isFinite(value) ? value : 0;
}

/** 一行是哪种消息：你的输入与指导从图外来，其余算成果。 */
function kindOf(kind: string): SequenceRowKind {
  if (kind === INPUT_KIND) {
    return "input";
  }
  if (kind === GUIDANCE_KIND) {
    return "guidance";
  }
  return "outcome";
}

/** 决定请求是哪个职能提的：请求载荷里有它，没有时返回 null（不硬指一个方向）。 */
function departmentOf(request: DecisionRequestLike): string | null {
  const value = request.department;
  return typeof value === "string" && value !== "" ? value : null;
}

/** 折起来那一行的摘要：这一轮的成果与结论，加上问了几次（例如「PRD v1 → 交付 v1 → 质检打回 · 询问 1 次」）。 */
export function summaryOf(rows: readonly SequenceRow[]): string {
  const parts: string[] = [];
  for (const row of rows) {
    if (row.kind !== "outcome") {
      continue;
    }
    parts.push(row.title);
    if (row.verdict !== null) {
      parts.push(row.verdict.text);
    }
  }
  const asks = rows.filter((row) => row.kind === "ask").length;
  const body = parts.join(" → ");
  if (asks === 0) {
    return body;
  }
  return body === "" ? `询问 ${asks} 次` : `${body} · 询问 ${asks} 次`;
}

/**
 * 画一张时序图：列、按轮折起来的行、打回与放行的标记、等待的色条。
 *
 * 事项还没有经过（一条事实也没有）时给出空的轮，由页面说一句还没有往来。
 */
export function sequenceOf(input: SequenceInput): SequenceView {
  const roles = input.roles;
  const columns: SequenceColumn[] = [{ id: YOU, label: "你" }, ...roles.map((role) => ({ id: role.id, label: role.label }))];
  const known = new Set(columns.map((column) => column.id));
  const labelOf = (id: string): string => columns.find((column) => column.id === id)?.label ?? id;
  const materials = input.materials ?? null;
  const records = [...input.flow].sort((left, right) => left.position - right.position);
  const built: BuiltRow[] = [];
  const push = (row: Omit<BuiltRow, "order" | "bars">): BuiltRow => {
    const full: BuiltRow = { ...row, order: built.length, bars: [] };
    built.push(full);
    return full;
  };
  // 一条询问或一个决定归到哪一轮：按发生的时间，取它之前最近的那条流转记录的第几轮（接口 4.4 第 1 条）
  const anchors = records
    .map((record) => ({ at: timeOf(record.created_at), round: Math.max(1, record.round) }))
    .sort((left, right) => left.at - right.at);
  const roundAt = (at: string): number => {
    const value = timeOf(at);
    let round = 1;
    for (const anchor of anchors) {
      if (anchor.at <= value) {
        round = anchor.round;
      } else {
        break;
      }
    }
    return round;
  };
  const revisionOf = (eventId: string, side: "contracts" | "deliveries"): number | null =>
    (materials?.[side] ?? []).find((entry) => entry.event_id === eventId)?.revision ?? null;

  // 一、成果、你的输入与指导：一条事件一行；同一版同时给几个职能（PRD 给工程与质检）合成一行
  const deliveries: { row: BuiltRow; position: number; from: string; to: string[] }[] = [];
  const merged = new Map<string, BuiltRow>();
  for (const record of records) {
    if (record.kind === DEFECT_KIND || record.kind === RELEASE_KIND || record.kind === ASK_KIND
      || record.direction_to === null) {
      continue;
    }
    const key = `flow:${record.event_id}`;
    const existing = merged.get(key);
    if (existing !== undefined) {
      if (!existing.to.includes(record.direction_to)) {
        existing.to.push(record.direction_to);
      }
      continue;
    }
    const from = record.direction_from ?? YOU;
    const revision = record.kind === PRD_KIND ? revisionOf(record.event_id, "contracts")
      : record.kind === DELIVERY_KIND ? revisionOf(record.event_id, "deliveries") : null;
    const name = record.kind === PRD_KIND ? "PRD" : record.kind === DELIVERY_KIND ? "交付" : "";
    const content = firstLine(record.content);
    const title = name !== ""
      ? (revision === null ? name : `${name} v${revision}`)
      : content === "" ? record.kind : `${record.kind}：${content}`;
    const row = push({
      key, kind: kindOf(record.kind), dashed: false, from, to: [record.direction_to], who: "",
      at: record.created_at, title, depth: 0, round: Math.max(1, record.round),
      verdict: null, open: false, closes: null, wait: null,
    });
    merged.set(key, row);
    if (record.kind === DELIVERY_KIND) {
      deliveries.push({ row, position: record.position, from, to: [record.direction_to] });
    }
  }

  // 二、打回与放行：标在它前面交的那一版上，不单独占一行
  for (const record of records) {
    if (record.kind !== DEFECT_KIND && record.kind !== RELEASE_KIND) {
      continue;
    }
    const by = record.direction_from;
    const target = record.direction_to;
    if (by === null || target === null) {
      continue;
    }
    const hit = [...deliveries].reverse().find(
      (item) => item.position < record.position && item.from === target && item.to.includes(by));
    if (hit === undefined) {
      continue;
    }
    // 打回照写；放行只写还没有结论的那一版——打回过的一版不会再放行
    if (record.kind === DEFECT_KIND || hit.row.verdict === null) {
      hit.row.verdict = {
        tone: record.kind === DEFECT_KIND ? "reject" : "release",
        text: `${labelOf(by)}${record.kind === DEFECT_KIND ? "打回" : "放行"}`,
      };
    }
  }

  // 三、询问与回答（run.asks）：回答跟着它那一次询问缩进，等待在提问方那一列上
  for (const ask of input.asks ?? []) {
    const key = `ask:${ask.id}`;
    const depth = Math.max(0, ask.depth - 1);
    // 回答的那一行关掉提问方这一段等待；还没回答的留着，色条画到「现在」
    push({
      key, kind: "ask", dashed: true, from: ask.requester, to: [ask.recipient], who: "",
      at: ask.started_at, title: firstLine(ask.question), depth, round: roundAt(ask.started_at),
      verdict: null, open: ask.status === "进行中", closes: ask.status === "进行中" ? null : `${key}:answer`,
      wait: { column: ask.requester, kind: "ask", tip: `在等待${labelOf(ask.recipient)}的回答` },
    });
    if (ask.status === "进行中") {
      continue;
    }
    const answered = ask.status === "已回答";
    const text = answered
      ? `答：${firstLine(ask.answer ?? ask.answer_facts ?? "")}`
      : `没能回答：${firstLine(ask.reason ?? "")}`;
    const at = ask.ended_at ?? ask.started_at;
    push({
      key: `${key}:answer`, kind: "answer", dashed: true, from: ask.recipient, to: [ask.requester], who: "",
      at, title: text, depth, round: roundAt(at), verdict: null, open: false, closes: null, wait: null,
    });
  }

  // 四、要你决定与你决定（decisions.list）：等你决定的色条在提那个请求的职能那一列上
  for (const decision of input.decisions ?? []) {
    // 撤销了的请求不画：它已经不是等你决定的事，查询里也没有撤销的时间
    if (decision.status === "withdrawn") {
      continue;
    }
    const by = departmentOf(decision.request);
    const column = by !== null && known.has(by) ? by : null;
    const key = `dec:${decision.decision_id}`;
    const answered = decision.status === "answered" && decision.answer !== null && decision.answer !== undefined;
    push({
      key, kind: "decide", dashed: false, from: column ?? YOU, to: column === null ? [] : [YOU], who: "",
      at: decision.requested_at, title: `要你决定：${firstLine(decision.request.description ?? "")}`,
      depth: 0, round: roundAt(decision.requested_at), verdict: null, open: decision.status === "open",
      closes: answered ? `${key}:answer` : null,
      wait: column === null ? null : { column, kind: "user", tip: "等你决定" },
    });
    if (!answered) {
      continue;
    }
    const answer = decision.answer as DecisionAnswerLike;
    const option = (decision.request.options ?? []).find((item) => item.id === answer.option);
    push({
      key: `${key}:answer`, kind: "decided", dashed: false, from: YOU, to: column === null ? [] : [column], who: "",
      at: answer.answered_at, title: `你决定：${option?.label ?? answer.option}`,
      depth: 0, round: roundAt(answer.answered_at), verdict: null, open: false, closes: null, wait: null,
    });
  }

  // 行按时间排；同一时刻的按读到它们的先后（流转记录在前，其次询问，再其次决定）
  built.sort((left, right) => timeOf(left.at) - timeOf(right.at) || left.order - right.order);
  for (const row of built) {
    row.who = row.to.length === 0 ? labelOf(row.from) : `${labelOf(row.from)} → ${row.to.map(labelOf).join("、")}`;
  }

  // 色条：从这一段等待开始的那一行画到关掉它的那一行；还没关掉的画到最后一行（也就是「现在」）
  const at = new Map(built.map((row, index) => [row.key, index]));
  const last = built.length - 1;
  for (const row of built) {
    if (row.wait === null) {
      continue;
    }
    const start = at.get(row.key) ?? 0;
    const end = row.closes === null ? last : at.get(row.closes) ?? last;
    for (let index = start; index <= end && index <= last; index += 1) {
      built[index].bars.push(row.wait);
    }
  }
  const waiting = built.some((row) => row.wait !== null && row.closes === null);

  // 按轮折起来：只展开最新一轮，前面几轮各一行摘要
  const byRound = new Map<number, SequenceRow[]>();
  for (const row of built) {
    byRound.set(row.round, [...(byRound.get(row.round) ?? []), row]);
  }
  const numbers = [...byRound.keys()].sort((left, right) => left - right);
  const latest = numbers.at(-1) ?? 0;
  const openRounds = input.openRounds ?? null;
  const rounds: SequenceRound[] = numbers.map((round) => ({
    round,
    rows: byRound.get(round) ?? [],
    summary: summaryOf(byRound.get(round) ?? []),
    open: openRounds === null ? round === latest : openRounds.includes(round),
  }));
  return {
    columns,
    rounds,
    now: waiting ? (input.now ?? "") : null,
    empty: built.length === 0,
    latestRound: latest,
  };
}
