// 形态卡与小循环图的模型（工单 #1648，docs/design/project-organization.md「形态一键选用」「新建的入口」）。
//
// 卡上有什么由 forms.list 给：形态名、轮转与结束两个标记、卡上的一句话，以及这份形态的合成结果。
// 本文件只做两件事：把合成结果换成「冻结组织」的形状交给 loop-graph-model 的 graphOf 画小图（不另写画法），
// 以及把「点哪张卡」翻成 project.create / project.onboard 的请求。页面不内置职能清单与形态清单，
// 运维那张灰卡由页面写（发布带里没有这份形态）。

import type { DraftOrganization, FormChoice } from "../../api/generated/types.gen.ts";
import {
  graphOf,
  type FrozenOrganization,
  type LoopGraph,
  type LoopItemView
} from "./loop-graph-model.ts";

/** 名字还空着就点卡：不发命令，写这一句。 */
export const FORM_NAME_HINT = "先写项目名字，再点形态卡。";

/** 接入已有项目要写源目录：缺一项时不发命令，写这一句。 */
export const SOURCE_HINT = "接入已有项目要写源目录的名称与路径。";

/** 默认那张卡的角标。「产品 · 工程 · 质检」排第一并标它。 */
export const DEFAULT_CARD_NOTE = "默认";

/** 运维那张灰卡的一句话：发布带里没有这份形态，页面自己写。 */
export const RELEASE_MISSING_NOTE = "发布带还没有";

/** 运维那张灰卡的形态名。 */
export const OPERATIONS_FORM_LABEL = "产品 · 工程 · 质检 · 运维";

/** 灰卡没有可提交的形态标识。 */
const NO_FORM = "";

/** 两张入口共用的方式：从一段想法新建，或把一个已有的代码目录接进来。 */
export type EntryMode = "idea" | "existing";

/** 一张形态卡：形态名、两个标记、一句话、小图，以及能不能选。 */
export interface FormCardView {
  /** 提交时带上的形态标识；灰卡没有 */
  form: string;
  label: string;
  /** 发布带里的默认形态排第一，标「默认」 */
  defaultCard: boolean;
  /** 轮转与结束两个标记 */
  markers: string[];
  /** 卡上的一句话 */
  cardLine: string;
  available: boolean;
  /** 不能选时写的那句话 */
  note: string;
  /** 小图；灰卡没有形态可读，为 null */
  graph: LoopGraph | null;
}

/** 点卡时读的几栏：名字空着、或接入时缺源目录，都不发命令。 */
export interface PickInput {
  mode: EntryMode;
  name: string;
  sourceName?: string;
  sourcePath?: string;
}

/** 一次入口提交要读的几栏。 */
export interface EntryInput {
  mode: EntryMode;
  name: string;
  form: string;
  initialDirectory?: string;
  sourceName?: string;
  sourcePath?: string;
}

/** 卡上的两个标记：轮转方式与结束方式，都由查询给，页面不另写一份。 */
function markersOf(choice: FormChoice): string[] {
  return [choice.routing_label, choice.ending].filter((text) => text !== "");
}

/**
 * 合成结果里的关注关系：谁接收谁的哪种成果（与 project.loop 的 organization.watched 同一口径）。
 *
 * 两处给出它：每个职能关注的成果，交出这一种成果的职能是另一端；核验声明里核验角色收到被核验的那一种成果。
 * 同一个（交出、接收、成果）只留一次，按定义的顺序给。
 */
function watchedRelations(organization: DraftOrganization): FrozenOrganization["watched"] {
  const handedIn = new Map<string, string[]>();
  for (const department of organization.departments) {
    for (const outcome of department.outcomes) {
      handedIn.set(outcome, [...(handedIn.get(outcome) ?? []), department.id]);
    }
  }
  const seen = new Set<string>();
  const relations: { source: string; recipient: string; outcome: string }[] = [];
  const add = (source: string, recipient: string, outcome: string): void => {
    const key = `${source}>${recipient}>${outcome}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    relations.push({ source, recipient, outcome });
  };
  for (const recipient of organization.departments) {
    for (const outcome of recipient.watched) {
      for (const source of handedIn.get(outcome) ?? []) {
        add(source, recipient.id, outcome);
      }
    }
  }
  for (const edge of organization.verification) {
    add(edge.verified, edge.verifier, edge.outcome);
  }
  return relations;
}

/** 核验关系：按核验角色的定义顺序，核验谁、核验哪种成果。 */
function verifiersOf(organization: DraftOrganization): FrozenOrganization["verifiers"] {
  const out: { role: string; verifies: { role: string; outcomes: string[] }[] }[] = [];
  for (const edge of organization.verification) {
    let verifier = out.find((entry) => entry.role === edge.verifier);
    if (verifier === undefined) {
      verifier = { role: edge.verifier, verifies: [] };
      out.push(verifier);
    }
    const verified = verifier.verifies.find((entry) => entry.role === edge.verified);
    if (verified === undefined) {
      verifier.verifies.push({ role: edge.verified, outcomes: [edge.outcome] });
    } else if (!verified.outcomes.includes(edge.outcome)) {
      verified.outcomes.push(edge.outcome);
    }
  }
  return out;
}

/**
 * 形态的合成结果换成冻结组织的形状：循环图读的是「冻结组织」，形态里还没有事项，
 * 只有职能、核验关系、关注关系与交完成的角色这几项。
 */
export function frozenOrganizationOf(organization: DraftOrganization): FrozenOrganization {
  const roles = organization.departments.map((department) => ({ id: department.id, label: department.label }));
  return {
    form: organization.form,
    routing: organization.routing,
    roles,
    verifiers: verifiersOf(organization),
    // 直做（一个角色的组织）由它自己交完成；成果驱动以核验角色的放行结束
    completing: roles.length === 1 ? roles[0] : null,
    watched: watchedRelations(organization),
    rejections: organization.verification.map((edge) => ({
      verifier: edge.verifier,
      role: edge.verified,
      outcome: edge.outcome
    }))
  };
}

/**
 * 一张形态卡的小循环图：与项目页的循环图同一种画法（loop-graph-model 的 graphOf）。
 *
 * 没有事项，所以流转传空、没有询问、没有轮次；主线与旁边的职能由这份形态的关注关系与接来源的职能排出来
 * （「产品 · 工程」的工程在主线、产品在旁边），结束那一头由核验角色决定（没有核验角色时写开环完成）。
 */
export function formGraph(choice: FormChoice): LoopGraph {
  const organization = frozenOrganizationOf(choice.organization);
  const item: LoopItemView = { work_item_id: "", status: "not_started", organization };
  return graphOf({
    item,
    flow: [],
    materials: null,
    // 接来源的职能取自这份形态的 sources：直做的形态靠它把主线上那一行放对
    current: { form: organization.form, sources: choice.organization.sources },
    currentRoles: organization.roles.map((role) => role.id)
  });
}

/**
 * 全部形态卡：发布带的每一份形态一张，末尾跟着运维那张灰卡。
 *
 * 发布带的清单把默认形态排在第一份（forms.list 的登记顺序），所以第一张标「默认」；
 * 页面不写形态标识，也不内置职能清单。
 */
export function formCards(forms: readonly FormChoice[] | null | undefined): FormCardView[] {
  const cards: FormCardView[] = (forms ?? []).map((choice, index) => ({
    form: choice.form,
    label: choice.label,
    defaultCard: index === 0,
    markers: markersOf(choice),
    cardLine: choice.card_line,
    available: true,
    note: index === 0 ? DEFAULT_CARD_NOTE : "",
    graph: formGraph(choice)
  }));
  cards.push({
    form: NO_FORM,
    label: OPERATIONS_FORM_LABEL,
    defaultCard: false,
    markers: [],
    cardLine: "",
    available: false,
    note: RELEASE_MISSING_NOTE,
    graph: null
  });
  return cards;
}

/** 点卡之前先看这两项：名字空着、或接入时缺源目录，都不发命令，写一句提示。 */
export function cardPickProblem(input: PickInput): string | null {
  if (input.name.trim() === "") {
    return FORM_NAME_HINT;
  }
  if (input.mode === "existing" && ((input.sourceName ?? "").trim() === "" || (input.sourcePath ?? "").trim() === "")) {
    return SOURCE_HINT;
  }
  return null;
}

/**
 * 一次入口提交的请求体：新建项目带名字、选的那份形态与可选的起始文件夹；
 * 接入已有项目带名字、源目录名称与路径、选的那份形态。长期目标不在这一步填（工单 #1647 起可选，在设置页写），
 * 所以两种请求都不带 goal。缺项时返回 null，不发命令。
 */
export function projectEntryBody(input: EntryInput): Record<string, unknown> | null {
  if (cardPickProblem(input) !== null || input.form === NO_FORM) {
    return null;
  }
  const name = input.name.trim();
  if (input.mode === "idea") {
    const directory = (input.initialDirectory ?? "").trim();
    return { name, form: input.form, ...(directory === "" ? {} : { initial_directory: directory }) };
  }
  return {
    name,
    source_name: (input.sourceName ?? "").trim(),
    source_path: (input.sourcePath ?? "").trim(),
    form: input.form
  };
}
