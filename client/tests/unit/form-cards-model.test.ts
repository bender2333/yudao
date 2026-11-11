// 形态卡与小循环图的模型（工单 #1648，docs/design/project-organization.md「形态一键选用」「新建的入口」）。
// 守 R3（路线图已走到「新建项目、接入已有项目都选卡」这个阶段，设计说明写明了卡上有哪几样、小图怎么画）：
// 卡上的形态名、两个标记与一句话、运维那张灰卡、名字空着时点卡不发命令，以及小图与项目页同一种画法
// （「产品 · 工程」的产品在旁边，「产品 · 工程 · 质检」的质检带核验标记，「工程」只有一行、结束写开环完成）。
// 小图不另写画法：这份模型把形态的合成结果换成冻结组织的形状，交给 loop-graph-model 的 graphOf。

import { test } from "node:test";
import assert from "node:assert/strict";
import type { DraftDepartment, DraftOrganization, FormChoice } from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  FORM_NAME_HINT,
  OPERATIONS_FORM_LABEL,
  RELEASE_MISSING_NOTE,
  cardPickProblem,
  formCards,
  projectEntryBody
} from "../../src/renderer/src/views/project/form-cards-model.ts";

// 发布带里三份形态的合成结果（按 harness/definitions 里那三份定义写，字段是 forms.list 的 organization）：
// three_departments（产品 · 工程 · 质检，核验角色质检）、single_role_direct（工程）、
// several_roles_direct（产品 · 工程，产品只在工程询问时回答）。
function department(id: string, label: string, watched: string[], outcomes: string[],
                    verifier = false): DraftDepartment {
  return { id, label, target: `${label}负责的事`, evidence: `${label}凭什么判断`, work: `${label}怎么工作`,
           watched, outcomes, verifier, write_scope: "" };
}

function organization(spec: { form: string; sourcing: string; departments: DraftDepartment[];
                             verification: { verifier: string; verified: string; outcome: string }[];
                             routing: string; routingLabel: string }): DraftOrganization {
  return {
    version: "v1",
    form: spec.form,
    routing: spec.routing,
    routing_label: spec.routingLabel,
    departments: spec.departments,
    outcome_kinds: [{ id: "product_spec", label: "PRD" }, { id: "delivery_spec", label: "交付" }],
    verification: spec.verification,
    sources: { user_input: spec.sourcing, onboarding: spec.sourcing }
  };
}

function choice(over: { form: string; label: string; organization: DraftOrganization; ending: string;
                       cardLine: string }): FormChoice {
  const verifiers = over.organization.verification.map((edge) => edge.verifier);
  return {
    form: over.form,
    label: over.label,
    description: `${over.label}的说明`,
    version: "v1",
    verifier_roles: verifiers,
    open_loop: verifiers.length === 0,
    routing: over.organization.routing,
    routing_label: over.organization.routing_label,
    ending: over.ending,
    card_line: over.cardLine,
    organization: over.organization
  };
}

const THREE = choice({
  form: "three_departments", label: "产品 · 工程 · 质检", ending: "独立核验放行",
  cardLine: "产品写需求、工程做、质检核验，放行才算完成",
  organization: organization({
    form: "three_departments", sourcing: "product", routing: "watched_outputs", routingLabel: "成果驱动",
    departments: [
      department("product", "产品", ["user_input", "guidance"], ["product_spec"]),
      department("engineering", "工程", ["product_spec", "defect_record", "guidance"], ["delivery_spec"]),
      department("quality", "质检", ["delivery_spec", "guidance", "structure", "product_spec"], [], true)
    ],
    verification: [{ verifier: "quality", verified: "engineering", outcome: "delivery_spec" }]
  })
});

const SINGLE = choice({
  form: "single_role_direct", label: "工程", ending: "开环完成",
  cardLine: "工程一个角色做完就结束，没有人核验",
  organization: organization({
    form: "single_role_direct", sourcing: "engineering", routing: "direct", routingLabel: "直做",
    departments: [department("engineering", "工程", ["guidance"], ["delivery_spec"])],
    verification: []
  })
});

const SEVERAL = choice({
  form: "several_roles_direct", label: "产品 · 工程", ending: "开环完成",
  cardLine: "工程做并交付，要求不清就问产品，没有人核验",
  organization: organization({
    form: "several_roles_direct", sourcing: "engineering", routing: "direct", routingLabel: "直做",
    departments: [
      department("product", "产品", [], []),
      department("engineering", "工程", ["guidance"], ["delivery_spec"])
    ],
    verification: []
  })
});

const RELEASE = [THREE, SINGLE, SEVERAL];

function card(forms: FormChoice[], label: string) {
  const found = formCards(forms).find((entry) => entry.label === label);
  assert.ok(found !== undefined, `没有找到「${label}」这张卡`);
  return found;
}

test("新建项目是四张卡，产品 · 工程 · 质检 排第一并标默认", () => {
  const cards = formCards(RELEASE);
  assert.deepEqual(cards.map((entry) => entry.label),
                   ["产品 · 工程 · 质检", "工程", "产品 · 工程", "产品 · 工程 · 质检 · 运维"]);
  assert.equal(cards[0].defaultCard, true);
  assert.deepEqual(cards.slice(1, 3).map((entry) => entry.defaultCard), [false, false]);
  // 每一张卡都写形态名与它那份形态的标识：点卡时提交的是这个标识
  assert.deepEqual(cards.slice(0, 3).map((entry) => entry.form),
                   ["three_departments", "single_role_direct", "several_roles_direct"]);
});

test("运维那张灰卡写发布带还没有，不能选，也不画小图", () => {
  const cards = formCards(RELEASE);
  const last = cards.at(-1);
  assert.ok(last !== undefined);
  assert.equal(last.label, OPERATIONS_FORM_LABEL);
  assert.equal(last.available, false);
  assert.equal(last.note, RELEASE_MISSING_NOTE);
  assert.equal(last.graph, null);
  assert.equal(last.form, "");
  // 前三张都能选，且都有小图
  assert.deepEqual(cards.slice(0, 3).map((entry) => entry.available), [true, true, true]);
  assert.deepEqual(cards.slice(0, 3).map((entry) => entry.graph === null), [false, false, false]);
});

test("每张可选卡都有轮转与结束两个标记与一句话", () => {
  const cards = formCards(RELEASE);
  assert.deepEqual(cards[0].markers, ["成果驱动", "独立核验放行"]);
  assert.equal(cards[0].cardLine, "产品写需求、工程做、质检核验，放行才算完成");
  assert.deepEqual(cards[1].markers, ["直做", "开环完成"]);
  assert.equal(cards[1].cardLine, "工程一个角色做完就结束，没有人核验");
  assert.deepEqual(cards[2].markers, ["直做", "开环完成"]);
  assert.equal(cards[2].cardLine, "工程做并交付，要求不清就问产品，没有人核验");
  // 灰卡没有标记也没有一句话：它没有形态可读
  const last = cards.at(-1);
  assert.deepEqual(last?.markers, []);
  assert.equal(last?.cardLine, "");
});

test("「产品 · 工程」的小图：工程在主线，产品在旁边，不画成先后两步", () => {
  const graph = card(RELEASE, "产品 · 工程").graph;
  assert.ok(graph !== null);
  assert.deepEqual(graph.chain.map((node) => node.id), ["engineering"]);
  assert.deepEqual(graph.side.map((part) => part.node.id), ["product"]);
  assert.equal(graph.side[0].partner, "engineering");
  // 产品不在主线上：它不是先后两步里的第一步
  assert.equal(graph.chain.some((node) => node.id === "product"), false);
});

test("「产品 · 工程 · 质检」的小图：质检节点带核验标记，三个职能都在主线上", () => {
  const graph = card(RELEASE, "产品 · 工程 · 质检").graph;
  assert.ok(graph !== null);
  assert.deepEqual(graph.chain.map((node) => node.id), ["product", "engineering", "quality"]);
  assert.deepEqual(graph.chain.map((node) => node.verifier), [false, false, true]);
  assert.equal(graph.side.length, 0);
  assert.equal(graph.endText, "质检放行才结束");
});

test("「工程」的小图只有一行，结束写开环完成", () => {
  const graph = card(RELEASE, "工程").graph;
  assert.ok(graph !== null);
  assert.deepEqual(graph.chain.map((node) => node.id), ["engineering"]);
  assert.equal(graph.side.length, 0);
  assert.equal(graph.endText, "开环完成");
  // 小图上不写上一件事项的状态与轮次：形态里还没有事项
  assert.equal(graph.chain[0].state, "");
  assert.equal(graph.rounds, 0);
});

test("名字空着时点卡不发命令，提示先写名字", () => {
  assert.equal(cardPickProblem({ mode: "idea", name: "  ", sourceName: "", sourcePath: "" }), FORM_NAME_HINT);
  assert.match(FORM_NAME_HINT, /名字/);
  assert.equal(cardPickProblem({ mode: "idea", name: "枢道", sourceName: "", sourcePath: "" }), null);
});

test("接入已有项目要写源目录，缺了不发命令", () => {
  const problem = cardPickProblem({ mode: "existing", name: "枢道", sourceName: "yudao", sourcePath: "" });
  assert.ok(problem !== null);
  assert.match(problem, /源目录/);
  assert.equal(cardPickProblem({ mode: "existing", name: "枢道", sourceName: "yudao", sourcePath: "C:/work/yudao" }), null);
});

test("新建项目的命令带选的那份形态，起始文件夹有才带，不带长期目标", () => {
  assert.deepEqual(projectEntryBody({ mode: "idea", name: " 枢道 ", form: "single_role_direct" }),
                   { name: "枢道", form: "single_role_direct" });
  assert.deepEqual(projectEntryBody({ mode: "idea", name: "枢道", form: "several_roles_direct",
                                     initialDirectory: " C:/work/yudao " }),
                   { name: "枢道", form: "several_roles_direct", initial_directory: "C:/work/yudao" });
  // 名字空着时不发命令：没有可提交的内容
  assert.equal(projectEntryBody({ mode: "idea", name: "", form: "three_departments" }), null);
});

test("接入已有项目的命令带源目录与选的那份形态，不带长期目标", () => {
  assert.deepEqual(projectEntryBody({ mode: "existing", name: "枢道", form: "several_roles_direct",
                                     sourceName: " yudao ", sourcePath: " C:/work/yudao " }),
                   { name: "枢道", source_name: "yudao", source_path: "C:/work/yudao",
                     form: "several_roles_direct" });
  // 源目录缺一项时不发命令
  assert.equal(projectEntryBody({ mode: "existing", name: "枢道", form: "three_departments",
                                 sourceName: "yudao", sourcePath: "" }), null);
});
