// 项目头部一行与对话上方的时间条（工单 #1653；项目的组织设计说明 4.12「形态一键选用」、4.15「循环图跟着组织长」
// 的「其余规矩」；形态与核验角色设计说明「开环完成」）。
//
// 这一份核对「查询给出的事实推出页面写什么」：同样的 project.organization 与 project.loop 给出同样的标签与时间条，
// 不看页面怎么摆、不另存一份组织。守 R3（路线图已经走到的阶段写明的行为，经合同字段检查，不看内部）：
// 头部读项目现在的组织（project.organization 的 label、changes、organization.routing 与 departments 的核验标记），
// 时间条读选中事项的已用时间与上限（project.loop 的 elapsed_sec、time_limit_sec）。
//
// 确认框的后果原文由 cancel-text.ts 给，irreversible-confirm.test.ts 已经核对；这里只核对它接的是那一份，
// 不重复断言它的文字。

import { test } from "node:test";
import assert from "node:assert/strict";
import type {
  DraftOrganization, OrganizationDepartment, ProjectOrganizationResult,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  OUT_OF_RELEASE, projectHead, stopConfirm, timeBar,
} from "../../src/renderer/src/views/project/project-head-model.ts";
import { cancelConfirmLines, cancelConfirmTitle } from "../../src/renderer/src/views/project/cancel-text.ts";
import { OPEN_LOOP_STATUS_TEXT } from "../../src/renderer/src/views/project/labels.ts";

// 一份查询结果：默认是发布带的「工程」（一个职能、直做、开环、没有本项目改动）
function organization(over: Partial<ProjectOrganizationResult> = {}): ProjectOrganizationResult {
  const composed: DraftOrganization = {
    version: "v1",
    form: "single_role_direct",
    routing: "direct",
    routing_label: "直做",
    departments: [],
    outcome_kinds: [],
    verification: [],
    sources: { user_input: "engineering", onboarding: "engineering" },
  };
  return {
    project_id: "p1",
    form: "single_role_direct",
    label: "工程",
    version: "v1",
    form_in_release: true,
    departments: [{ id: "engineering", label: "工程", verifier: false, origin: "release" }],
    forms: [],
    history: [],
    changes: {},
    organization: composed,
    rejections: [],
    add_verifier: null,
    remove_verifier: null,
    ...over,
  };
}

function departments(...items: OrganizationDepartment[]): OrganizationDepartment[] {
  return items;
}

// 事项在 project.loop 里的那几栏：时间条只读 status、elapsed_sec、time_limit_sec、version
function item(over: Record<string, unknown> = {}): {
  work_item_id: string;
  status: string;
  elapsed_sec: number | null;
  time_limit_sec: number;
  version: number;
} {
  return {
    work_item_id: "w1",
    status: "in_progress",
    elapsed_sec: 750,
    time_limit_sec: 1800,
    version: 7,
    ...over,
  } as { work_item_id: string; status: string; elapsed_sec: number | null; time_limit_sec: number; version: number };
}

// ---------------------------------------------------------------- 头部一行标签

test("「工程」写形态名、直做、开环", () => {
  assert.deepEqual(projectHead(organization())?.tags, ["「工程」", "直做", OPEN_LOOP_STATUS_TEXT]);
});

test("「产品 · 工程 · 质检」写按成果、核验角色的显示名", () => {
  const head = projectHead(organization({
    form: "three_departments",
    label: "产品 · 工程 · 质检",
    departments: departments(
      { id: "product", label: "产品", verifier: false, origin: "release" },
      { id: "engineering", label: "工程", verifier: false, origin: "release" },
      { id: "quality", label: "质检", verifier: true, origin: "release" },
    ),
    organization: {
      version: "v1",
      form: "three_departments",
      // 发布里这一份的 routing_label 是「成果驱动」：页面上按设计说明的两个词写「按成果」
      routing: "watched_outputs",
      routing_label: "成果驱动",
      departments: [],
      outcome_kinds: [],
      verification: [],
      sources: { user_input: "product", onboarding: "product" },
    },
  }));
  assert.deepEqual(head?.tags, ["「产品 · 工程 · 质检」", "按成果", "核验：质检"]);
  assert.equal(head?.rotation, "按成果");
  assert.deepEqual(head?.verifiers, ["质检"]);
});

test("本项目改过几处写在形态名后面，不另加一行", () => {
  const head = projectHead(organization({
    changes: { departments: { engineering: { label: "工程组" }, product: { label: "产品组" } } },
  }));
  assert.deepEqual(head?.tags, ["「工程」（改过 2 处）", "直做", OPEN_LOOP_STATUS_TEXT]);
  assert.equal(head?.changed, 2);
});

test("改过几处不算观察者与由谁做（它们一步生效，不走高级）", () => {
  const head = projectHead(organization({
    changes: { observers: { watcher: { on: true } }, who: { engineering: { type: "outsourced" } } },
  }));
  assert.equal(head?.changed, 0);
  assert.deepEqual(head?.tags, ["「工程」", "直做", OPEN_LOOP_STATUS_TEXT]);
});

test("加独立核验以后写「工程 · 质检」、有核验，改过几处仍是 0", () => {
  // 加独立核验那一次点击带进来的：一个核验职能与它的核验声明（与 project.organization 的 add_verifier 同一份改动）
  const added = {
    add_departments: [{ id: "quality", label: "质检", target: "核验工程交的完成", evidence: "", work: "" }],
    verification: {
      verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["completion"] }] }],
      write_scopes: { quality: { scope: "check_materials", paths: [".yudao-qa-tests"] } },
    },
  };
  const head = projectHead(organization({
    label: "工程 · 质检",
    changes: added,
    departments: departments(
      { id: "engineering", label: "工程", verifier: false, origin: "release" },
      { id: "quality", label: "质检", verifier: true, origin: "added" },
    ),
  }));
  assert.deepEqual(head?.tags, ["「工程 · 质检」", "直做", "核验：质检"]);
  assert.equal(head?.changed, 0);
});

test("加独立核验之外还改过的地方照样算一处", () => {
  const head = projectHead(organization({
    label: "工程 · 质检",
    changes: {
      routing: "direct",
      add_departments: [{ id: "quality", label: "质检" }],
      verification: { verifiers: [{ role: "quality", verifies: [{ role: "engineering", outcomes: ["completion"] }] }] },
      departments: { engineering: { label: "工程组" } },
    },
    departments: departments(
      { id: "engineering", label: "工程组", verifier: false, origin: "changed" },
      { id: "quality", label: "质检", verifier: true, origin: "added" },
    ),
  }));
  assert.equal(head?.changed, 2);
  assert.equal(head?.tags[0], "「工程 · 质检」（改过 2 处）");
});

test("形态名用服务端给的 label，这一份不在发布里时不写英文标识", () => {
  const head = projectHead(organization({
    form: "single_role_direct",
    label: null,
    form_in_release: false,
    departments: [],
    organization: null,
  }));
  assert.deepEqual(head?.tags, [OUT_OF_RELEASE]);
  assert.ok(!JSON.stringify(head).includes("single_role_direct"), "页面上不出现发布带里的标识");
});

test("查询还没有数据时头部不出现，不写一行假的", () => {
  assert.equal(projectHead(null), null);
});

// ---------------------------------------------------------------- 对话上方的时间条

test("事项在做时写已用与上限，并有「停止」", () => {
  const bar = timeBar([item()], "w1");
  assert.equal(bar?.text, "正在处理 · 已用 12 分 30 秒 / 上限 30 分 0 秒");
  assert.equal(bar?.ratio, 750 / 1800);
  assert.deepEqual(bar?.stop, { work_item_id: "w1", base_version: 7, status: "in_progress" });
});

test("事项结束以后没有「停止」，已用时间与上限照写", () => {
  for (const status of ["adopted", "released_unsettled", "stopped"]) {
    const bar = timeBar([item({ status, elapsed_sec: 1800 })], "w1");
    assert.equal(bar?.stop, null, status);
    assert.equal(bar?.text, "已用 30 分 0 秒 / 上限 30 分 0 秒", status);
  }
});

test("排队中的事项也写已用与上限，但没有「停止」（还没有开始，停止无从谈起）", () => {
  const bar = timeBar([item({ status: "not_started", elapsed_sec: null })], "w1");
  assert.equal(bar?.stop, null);
  assert.equal(bar?.text, "已用 未知 / 上限 30 分 0 秒");
  assert.equal(bar?.ratio, null);
});

test("没有选中事项时没有时间条", () => {
  assert.equal(timeBar([item()], ""), null);
  assert.equal(timeBar([], "w1"), null);
  // 地址里的那件事项不在清单里时也不拿别的事项顶替
  assert.equal(timeBar([item()], "w2"), null);
});

test("「停止」先确认：确认框的标题与后果照取消事项的那一份", () => {
  const stop = timeBar([item()], "w1")?.stop;
  assert.notEqual(stop, null);
  if (stop === null || stop === undefined) {
    return;
  }
  const confirm = stopConfirm(stop);
  assert.equal(confirm.title, cancelConfirmTitle("in_progress"));
  assert.deepEqual(confirm.lines, cancelConfirmLines("in_progress"));
  assert.notEqual(confirm.confirm, confirm.cancel);
});
