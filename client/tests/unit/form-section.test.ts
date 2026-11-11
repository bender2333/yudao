// 项目设置页「形态」一节的纯计算（工单 #1403）。验收：现在用哪一份与发布带每一份的名字与一句说明，
// 没有核验角色的那一份写明以开环完成结束、不经过放行；换成另一份的提交参数带上页面看到的当前值；
// 历史每一行的原值、新值、理由、时间与谁改的，以及「改回这一份」等于用原值再改一次。
// 用 node --test 运行，不依赖 Electron、网络与后端。

import { test } from "node:test";
import assert from "node:assert/strict";
import type {
  DraftDepartment,
  DraftOrganization,
  FormChange,
  FormChoice,
  ProjectOrganizationResult,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import type { CommandProblem } from "../../src/renderer/src/contract/command-problem.ts";
import {
  FORM_CHANGE_HINT,
  NO_REASON,
  OPEN_LOOP_SENTENCE,
  ORGANIZATION_CHANGE_HINT,
  ORGANIZATION_NOT_READ,
  adoptPayload,
  actorText,
  canAddVerifier,
  canAdopt,
  canChangeBack,
  canRemoveVerifier,
  changeBackPayload,
  choiceView,
  currentFormText,
  discardedLines,
  formChoices,
  historyRow,
  historyRows,
  needsRefresh,
  organizationLine,
  otherChoices,
  reasonText,
  switchNeedsConfirm,
  versionText,
  verifierPayload,
} from "../../src/renderer/src/views/project/form-section-logic.ts";

const THREE = "three_departments";
const SINGLE = "single_role";
const SEVERAL = "several_roles_direct";

// 发布带的一份形态：字段与生成的 FormChoice 合同一致
// 工单 #1647 给 FormChoice 加了五样（轮转、结束方式、卡上的一句话与合成结果），这一节只读形态名、
// 一句说明与核验角色，其余按默认形态写一份占位
function draft(overrides: Partial<DraftOrganization> = {}): DraftOrganization {
  return {
    version: "sha256:three",
    form: THREE,
    routing: "watched_outputs",
    routing_label: "成果驱动",
    departments: [],
    outcome_kinds: [],
    verification: [],
    sources: {},
    ...overrides,
  };
}

function choice(overrides: Partial<FormChoice> = {}): FormChoice {
  return {
    form: THREE,
    label: "产品 · 工程 · 质检",
    description: "产品、工程、质检；质检核验工程。",
    version: "sha256:three",
    verifier_roles: ["quality"],
    open_loop: false,
    routing: "watched_outputs",
    routing_label: "成果驱动",
    ending: "独立核验放行",
    card_line: "产品写需求、工程做、质检核验，放行才算完成",
    organization: draft(),
    ...overrides,
  };
}

// 没有核验角色的那一份：后端的一句说明里已经写了开环，核验角色为空
function openLoopChoice(): FormChoice {
  return choice({
    form: SINGLE,
    label: "工程",
    description: "工程；没有核验角色，事项以开环完成结束。",
    version: "sha256:single",
    verifier_roles: [],
    open_loop: true,
  });
}

function change(overrides: Partial<FormChange> = {}): FormChange {
  return {
    event_id: "e-1",
    previous_form: THREE,
    form: SINGLE,
    reason: "先试一轮一个人做",
    at: "2026-11-05T02:03:04+00:00",
    actor: "user:local",
    ...overrides,
  };
}

// 一个项目现在的组织：发布带两份，现在用三部门，还没有改过
function organization(overrides: Partial<ProjectOrganizationResult> = {}): ProjectOrganizationResult {
  return {
    project_id: "p-1",
    form: THREE,
    label: "产品 · 工程 · 质检",
    version: "sha256:three",
    form_in_release: true,
    departments: [],
    forms: [choice(), openLoopChoice()],
    history: [],
    ...overrides,
  };
}

test("发布带每一份都有形态名与一句说明，说明原样用后端的说法，不另写", () => {
  const shown = formChoices(organization());
  assert.deepEqual(shown.map((item) => item.form), [THREE, SINGLE]);
  // 形态名取自服务端的 label（工单 #1601）：显示的是「工程」，不是 single_role 这类发布带里的标识
  assert.deepEqual(shown.map((item) => item.label), ["产品 · 工程 · 质检", "工程"]);
  assert.equal(shown[0].description, "产品、工程、质检；质检核验工程。");
  assert.equal(shown[1].description, openLoopChoice().description);
});

test("形态区显示服务端给的形态名，不显示 single_role_direct 这类标识（工单 #1602 验收第 2 条）", () => {
  // 现在用的那一份与发布带的每一份都写 label：服务端给的三种形态名照显示
  const shown = formChoices(organization({
    forms: [
      choice({ form: "default", label: "产品 · 工程 · 质检" }),
      choice({ form: "single_role_direct", label: "工程", verifier_roles: [], open_loop: true }),
      choice({ form: "several_roles_direct", label: "产品 · 工程", verifier_roles: [], open_loop: true }),
    ],
  }));
  assert.deepEqual(shown.map((item) => item.label), ["产品 · 工程 · 质检", "工程", "产品 · 工程"]);
  // 标识仍留在 form 上，供提交与 data-testid 使用，但不写成页面上的名字
  assert.deepEqual(shown.map((item) => item.form), ["default", "single_role_direct", "several_roles_direct"]);
  assert.match(currentFormText(organization({ label: "产品 · 工程 · 质检" })), /现在用 产品 · 工程 · 质检/);
  assert.doesNotMatch(currentFormText(organization({ form: "single_role_direct", label: "工程" })), /single_role_direct/);
});

test("现在用的那一份在清单里标出来，其余不标", () => {
  const shown = formChoices(organization());
  assert.deepEqual(shown.map((item) => item.isCurrent), [true, false]);
});

test("没有核验角色的那一份另写一句：开环完成结束、不经过放行（验收第 3 条）", () => {
  const shown = formChoices(organization());
  // 有核验角色的那一份不写这一句
  assert.equal(shown[0].openLoop, "");
  // 没有核验角色的那一份写明，字句与验收要求的一致
  assert.equal(shown[1].openLoop, OPEN_LOOP_SENTENCE);
  assert.equal(OPEN_LOOP_SENTENCE, "没有核验角色，事项以开环完成结束，不经过放行");
  // 只看核验角色是否为空：后端标了开环但没有写核验角色时，按同一句话写
  assert.equal(choiceView(choice({ verifier_roles: [], open_loop: false }), THREE).openLoop, OPEN_LOOP_SENTENCE);
  assert.equal(choiceView(choice({ verifier_roles: ["quality"], open_loop: true }), THREE).openLoop, "");
});

test("现在用哪一份：在发布里时写形态名与组织版本", () => {
  const text = currentFormText(organization());
  assert.match(text, /产品 · 工程 · 质检/);
  assert.match(text, /sha256:three/);
  assert.doesNotMatch(text, /three_departments/);
});

test("现在用的那一份不在发布里时写明，不拿别的形态顶替", () => {
  const text = currentFormText(organization({
    form: "gone_form", label: null, version: null, form_in_release: false }));
  // 取不到形态名时退回标识，照实写明是哪一份
  assert.match(text, /gone_form/);
  assert.match(text, /不在这一版发布里/);
  // 没有版本时不写一个假的版本号
  assert.equal(text.includes("null"), false);
  assert.equal(versionText(organization({ form: "gone_form", version: null, form_in_release: false })),
    "不在这一版发布里");
  assert.equal(versionText(organization()), "sha256:three");
});

test("换成另一份：可以选的是发布带里现在这一份以外的几份", () => {
  assert.deepEqual(otherChoices(organization()).map((item) => item.form), [SINGLE]);
  // 现在这一份不在发布里时，发布带的几份都能选回来
  assert.deepEqual(
    otherChoices(organization({ form: "gone_form", version: null, form_in_release: false })).map((item) => item.form),
    [THREE, SINGLE]);
});

test("选了一份且不是现在这一份才能提交", () => {
  assert.equal(canAdopt({ form: "", currentForm: THREE }), false);
  assert.equal(canAdopt({ form: THREE, currentForm: THREE }), false);
  assert.equal(canAdopt({ form: SINGLE, currentForm: THREE }), true);
});

test("换成另一份的提交带上页面看到的当前值", () => {
  assert.deepEqual(adoptPayload({ projectId: "p-1", form: SINGLE, reason: " 先试一轮一个人做 ",
                                  baseVersion: "sha256:three" }), {
    project_id: "p-1",
    form: SINGLE,
    changes: {},
    reason: "先试一轮一个人做",
    base_version: "sha256:three",
  });
  // 现在这一份不在发布里时页面看到的版本是空：照样带上，服务端按空版本核对
  assert.equal(adoptPayload({ projectId: "p-1", form: THREE, reason: "", baseVersion: null }).base_version, null);
});

test("历史一行：原值、新值、理由、时间与谁改的", () => {
  const row = historyRow(change(), SINGLE, { [THREE]: "产品 · 工程 · 质检", [SINGLE]: "工程" });
  assert.equal(row.previous, THREE);
  assert.equal(row.form, SINGLE);
  assert.equal(row.reason, "先试一轮一个人做");
  assert.equal(row.at, "2026-11-05T02:03:04+00:00");
  assert.equal(row.actor, "你");
  // 页面上写形态名；标识只在没有形态名时退回
  assert.equal(row.text, "产品 · 工程 · 质检 → 工程");
  assert.equal(historyRow(change(), SINGLE).text, "three_departments → single_role");
});

test("没有写理由的那一次照实写「没有写理由」，不空着", () => {
  assert.equal(reasonText(""), NO_REASON);
  // 只有空白也算没有写
  assert.equal(reasonText("   "), NO_REASON);
  assert.equal(reasonText("换个做法"), "换个做法");
  assert.equal(historyRow(change({ reason: "" }), SINGLE).reason, NO_REASON);
});

test("历史按事件的先后排，早的在前，每次改动一行", () => {
  const rows = historyRows(organization({
    history: [
      change({ event_id: "e-1" }),
      change({ event_id: "e-2", previous_form: SINGLE, form: THREE, reason: "" }),
    ],
  }));
  assert.deepEqual(rows.map((row) => row.eventId), ["e-1", "e-2"]);
  assert.deepEqual(rows.map((row) => [row.previous, row.form]), [[THREE, SINGLE], [SINGLE, THREE]]);
  // 改动那一行写形态名：发布带里有的取它的 label
  assert.deepEqual(rows.map((row) => row.text),
    ["产品 · 工程 · 质检 → 工程", "工程 → 产品 · 工程 · 质检"]);
});

test("改回这一份：每一条都能用原值再改一次；已经是现在这一份时不给（等于没改）", () => {
  assert.equal(canChangeBack(THREE, SINGLE), true);
  assert.equal(canChangeBack(THREE, THREE), false);
  assert.deepEqual(changeBackPayload({ projectId: "p-1", previousForm: THREE, baseVersion: "sha256:single" }), {
    project_id: "p-1",
    form: THREE,
    changes: {},
    reason: "",
    base_version: "sha256:single",
  });
});

test("谁改的：认得的写成页面上的说法，认不出的照实写", () => {
  assert.equal(actorText("user:local"), "你");
  assert.equal(actorText("system"), "系统");
  // 职能提出者写职能的显示名，不再加「部门」两字
  assert.equal(actorText("department:product"), "产品");
  assert.equal(actorText("someone-else"), "someone-else");
});

test("提示一句：改动只对之后新建的事项生效，正在跑的事项按原来的形态跑完（验收第 4 条）", () => {
  assert.equal(FORM_CHANGE_HINT, "改动只对之后新建的事项生效，正在跑的事项按原来的形态跑完。");
});

// ---------------------------------------------------------------- 组织一行与两个按钮（工单 #1649）

/** 合成结果里的一个职能：只写这一节读的那几栏，其余按空值。 */
function department(fields: Partial<DraftDepartment> & Pick<DraftDepartment, "id" | "label">): DraftDepartment {
  return {
    target: "", evidence: "", work: "", watched: [], outcomes: [], verifier: false, write_scope: "",
    ...fields,
  };
}

/** 一个项目现在的组织：只有一个职能、没有核验（「工程」）。 */
function singleOrganization(overrides: Partial<ProjectOrganizationResult> = {}): ProjectOrganizationResult {
  return organization({
    form: SINGLE,
    label: "工程",
    version: "sha256:single",
    organization: draft({
      version: "sha256:single", form: SINGLE, routing: "direct", routing_label: "直做",
      departments: [department({ id: "engineering", label: "工程" })],
    }),
    ...overrides,
  });
}

/** 产品 · 工程 · 质检：质检核验工程交出的那一版。 */
function threeOrganization(): ProjectOrganizationResult {
  return organization({
    organization: draft({
      departments: [
        department({ id: "product", label: "产品", outcomes: ["product_spec"] }),
        department({ id: "engineering", label: "工程", watched: ["product_spec"], outcomes: ["delivery_spec"] }),
        department({ id: "quality", label: "质检", verifier: true, watched: ["delivery_spec"] }),
      ],
    }),
  });
}

test("组织一行：只有一个职能、没有核验时写没有人核验，并写明加独立核验以后会等它放行", () => {
  assert.equal(organizationLine(singleOrganization()), "工程，只有一个职能，没有人核验；加独立核验就会等它放行");
});

test("组织一行：有核验角色时写谁核验后放行与轮转方式，都由合成结果写出", () => {
  assert.equal(organizationLine(threeOrganization()), "产品 · 工程 · 质检，质检核验后放行，轮转是成果驱动");
});

test("组织一行：两个职能、没有核验角色时照实写没有核验角色、开环完成", () => {
  const two = organization({
    form: SEVERAL,
    organization: draft({
      form: SEVERAL, routing: "direct", routing_label: "直做",
      departments: [department({ id: "product", label: "产品" }), department({ id: "engineering", label: "工程" })],
    }),
  });
  assert.equal(organizationLine(two), "产品 · 工程，没有核验角色，开环完成；加独立核验就会等它放行");
});

test("合成结果读不出来时照实写明，不编一个职能清单", () => {
  assert.equal(organizationLine(organization()), ORGANIZATION_NOT_READ);
});

test("加独立核验：查询给了那份改动就一次点击生效，理由不写，带上页面看到的组织版本", () => {
  const changes = { add_departments: { quality: { label: "质检" } } };
  assert.equal(canAddVerifier(singleOrganization({ add_verifier: changes })), true);
  assert.equal(canAddVerifier(singleOrganization()), false);
  assert.deepEqual(
    verifierPayload({ projectId: "p-1", form: SINGLE, changes, baseVersion: "sha256:single" }), {
      project_id: "p-1",
      form: SINGLE,
      changes,
      reason: "",
      base_version: "sha256:single",
      mode: "verifier",
    });
});

test("去掉独立核验在同一处：用的是查询给的那份改动，命令还是同一条", () => {
  const changes = { remove_departments: ["quality"] };
  const adopted = singleOrganization({ label: "工程 · 质检", remove_verifier: changes });
  assert.equal(canRemoveVerifier(adopted), true);
  assert.equal(canRemoveVerifier(singleOrganization()), false);
  assert.equal(verifierPayload({ projectId: "p-1", form: SINGLE, changes, baseVersion: "sha256:x" }).mode, "verifier");
});

test("换形态：本项目没有改动时点卡一步生效；有改动时先确认一次，列出会丢掉哪些", () => {
  assert.equal(switchNeedsConfirm(organization()), false);
  assert.equal(switchNeedsConfirm(organization({ changes: { departments: { quality: { label: "质检组" } } } })), true);
  // 查询给的空句子不排进确认清单里
  assert.deepEqual(discardedLines(["质检的提示", "", "   ", "工程的写范围"]), ["质检的提示", "工程的写范围"]);
});

test("换形态的提交带上页面看到的组织版本；版本对不上时刷新页面并照实写明", () => {
  assert.deepEqual(adoptPayload({ projectId: "p-1", form: SINGLE, reason: "", baseVersion: "sha256:three" }), {
    project_id: "p-1",
    form: SINGLE,
    changes: {},
    reason: "",
    base_version: "sha256:three",
  });
  const stale: CommandProblem = {
    kind: "rejected",
    rejection: { command_id: "c-1", reason: "stale_base", message: "组织改过了", current_version: "sha256:new" },
  };
  assert.equal(needsRefresh(stale), true);
  assert.equal(needsRefresh({ kind: "rejected",
    rejection: { command_id: "c-2", reason: "not_allowed", message: "不认这份改动" } }), false);
  assert.equal(needsRefresh(null), false);
});

test("组织一行下面那一句：只对之后新建的事项生效，正在跑的事项按原来的组织做完", () => {
  assert.equal(ORGANIZATION_CHANGE_HINT, "改动只对之后新建的事项生效，正在跑的事项按原来的组织做完。");
});