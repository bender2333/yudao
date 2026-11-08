// 项目设置页「形态」一节的纯计算（工单 #1403）。验收：现在用哪一份与发布带每一份的名字与一句说明，
// 没有核验角色的那一份写明以开环完成结束、不经过放行；换成另一份的提交参数带上页面看到的当前值；
// 历史每一行的原值、新值、理由、时间与谁改的，以及「改回这一份」等于用原值再改一次。
// 用 node --test 运行，不依赖 Electron、网络与后端。

import { test } from "node:test";
import assert from "node:assert/strict";
import type {
  FormChange,
  FormChoice,
  ProjectOrganizationResult,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  FORM_CHANGE_HINT,
  NO_REASON,
  OPEN_LOOP_SENTENCE,
  adoptPayload,
  actorText,
  canAdopt,
  canChangeBack,
  changeBackPayload,
  choiceView,
  currentFormText,
  formChoices,
  historyRow,
  historyRows,
  otherChoices,
  reasonText,
  versionText,
} from "../../src/renderer/src/views/project/form-section-logic.ts";

const THREE = "three_departments";
const SINGLE = "single_role";

// 发布带的一份形态：字段与生成的 FormChoice 合同一致
function choice(overrides: Partial<FormChoice> = {}): FormChoice {
  return {
    form: THREE,
    label: "产品 · 工程 · 质检",
    description: "产品、工程、质检；质检核验工程。",
    version: "sha256:three",
    verifier_roles: ["quality"],
    open_loop: false,
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

test("发布带每一份都有名字与一句说明，说明原样用后端的说法，不另写", () => {
  const shown = formChoices(organization());
  assert.deepEqual(shown.map((item) => item.form), [THREE, SINGLE]);
  assert.equal(shown[0].description, "产品、工程、质检；质检核验工程。");
  assert.equal(shown[1].description, openLoopChoice().description);
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

test("现在用哪一份：在发布里时写名字与组织版本", () => {
  const text = currentFormText(organization());
  assert.match(text, /three_departments/);
  assert.match(text, /sha256:three/);
});

test("现在用的那一份不在发布里时写明，不拿别的形态顶替", () => {
  const text = currentFormText(organization({ form: "gone_form", version: null, form_in_release: false }));
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
  const row = historyRow(change(), SINGLE);
  assert.equal(row.previous, THREE);
  assert.equal(row.form, SINGLE);
  assert.equal(row.reason, "先试一轮一个人做");
  assert.equal(row.at, "2026-11-05T02:03:04+00:00");
  assert.equal(row.actor, "你");
  assert.equal(row.text, "three_departments → single_role");
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
  assert.equal(actorText("department:product"), "产品部门");
  assert.equal(actorText("someone-else"), "someone-else");
});

test("提示一句：改动只对之后新建的事项生效，正在跑的事项按原来的形态跑完（验收第 4 条）", () => {
  assert.equal(FORM_CHANGE_HINT, "改动只对之后新建的事项生效，正在跑的事项按原来的形态跑完。");
});
