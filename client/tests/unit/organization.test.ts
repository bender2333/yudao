// 页面的部门从事实来（工单 #1457）：项目现在组织里的部门 → 部门页签、默认部门与显示名；
// 事项冻结的组织 → 每个事项的部门；看板的部门列 = 现在组织里的部门 + 还在跑的事项里旧组织的部门。
// 期望值写成字面值，不复用实现的公式。

import { test } from "node:test";
import assert from "node:assert/strict";

import type {
  ProjectLoopResult, ProjectOrganizationResult, WorkItemCard,
} from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  boardDepartments, defaultDepartment, departmentLabel, departmentLabels, departmentTabs, itemDepartments,
  projectDepartments, type DepartmentView,
} from "../../src/renderer/src/views/project/organization.ts";

// 项目现在的组织：只有这一张工单用到的几项
function organization(departments: { id: string; label: string; verifier?: boolean }[] | null)
  : ProjectOrganizationResult | null {
  if (departments === null) {
    return null;
  }
  return { departments } as unknown as ProjectOrganizationResult;
}

// 一个事项卡：只有看板分组用到的几项
function item(work_item_id: string, status: string): WorkItemCard {
  return { work_item_id, status } as unknown as WorkItemCard;
}

// 事项各自冻结的组织：每个事项的 roles 就是它那一份定义里的部门
function loop(items: { work_item_id: string; roles: { id: string; label: string }[] | null }[]): ProjectLoopResult {
  return {
    work_items: items.map((entry) => ({
      work_item_id: entry.work_item_id,
      organization: entry.roles === null ? null : {
        form: "form",
        roles: entry.roles.map((role) => ({ ...role })),
      },
    })),
  } as unknown as ProjectLoopResult;
}

const THREE: DepartmentView[] = [
  { id: "product", label: "产品" },
  { id: "engineering", label: "工程" },
  { id: "quality", label: "质检" },
];

// ---------------------------------------------------------------------------
// 项目现在的组织
// ---------------------------------------------------------------------------

test("项目现在组织里的部门按定义里的顺序给出，查询没有数据时为空", () => {
  assert.deepEqual(projectDepartments(organization([
    { id: "engineering", label: "工程" },
    { id: "quality", label: "质检", verifier: true },
  ])), [{ id: "engineering", label: "工程" }, { id: "quality", label: "质检" }]);
  assert.deepEqual(projectDepartments(organization(null)), []);
  assert.deepEqual(projectDepartments(organization([])), []);
});

test("部门页签按现在组织里的部门列：一个角色直做的项目只有一个部门页签", () => {
  assert.deepEqual(departmentTabs("p1", THREE, { workItem: "w1" }), [
    { label: "产品", hash: "#/p/p1/dept/product?w=w1", query: "department.workspace" },
    { label: "工程", hash: "#/p/p1/dept/engineering?w=w1", query: "department.workspace" },
    { label: "质检", hash: "#/p/p1/dept/quality?w=w1", query: "department.workspace" },
  ]);
  assert.deepEqual(departmentTabs("p1", [{ id: "engineering", label: "工程" }], { workItem: null }), [
    { label: "工程", hash: "#/p/p1/dept/engineering", query: "department.workspace" },
  ]);
  assert.deepEqual(departmentTabs("p1", [], { workItem: null }), []);
});

test("部门页的默认部门：地址里有就用地址里的，没有时取现在组织里的第一个", () => {
  assert.equal(defaultDepartment("quality", THREE), "quality");
  assert.equal(defaultDepartment(null, THREE), "product");
  assert.equal(defaultDepartment(undefined, [{ id: "engineering", label: "工程" }]), "engineering");
  assert.equal(defaultDepartment(null, []), "");
});

test("部门显示名取组织给的，组织里没有的部门才退回页面上原来的写法", () => {
  const labels = departmentLabels(THREE);
  assert.deepEqual(labels, { product: "产品", engineering: "工程", quality: "质检" });
  assert.equal(departmentLabel("engineering", labels), "工程");
  assert.equal(departmentLabel("quality", { quality: "验收" }), "验收");
  assert.equal(departmentLabel("product", {}), "产品");
  assert.equal(departmentLabel(null, labels), "");
});

// ---------------------------------------------------------------------------
// 事项冻结的组织
// ---------------------------------------------------------------------------

test("每个事项的部门取它冻结的组织，形态不在发布里的事项没有部门", () => {
  const departments = itemDepartments(loop([
    { work_item_id: "w1", roles: [{ id: "product", label: "产品" }, { id: "engineering", label: "工程" }] },
    { work_item_id: "w2", roles: [{ id: "engineering", label: "工程" }] },
    { work_item_id: "w3", roles: null },
  ]));
  assert.deepEqual(departments, {
    w1: [{ id: "product", label: "产品" }, { id: "engineering", label: "工程" }],
    w2: [{ id: "engineering", label: "工程" }],
    w3: [],
  });
  assert.deepEqual(itemDepartments(null), {});
});

// ---------------------------------------------------------------------------
// 看板的部门列
// ---------------------------------------------------------------------------

test("看板的部门列以现在组织里的部门在前，再加还在跑的事项里旧组织的部门", () => {
  const departments = boardDepartments({
    current: [{ id: "engineering", label: "工程" }, { id: "design", label: "设计" }],
    items: [
      item("w1", "in_progress"),
      item("w2", "in_progress"),
      item("w3", "adopted"),
    ],
    itemDepartments: {
      // 中途换了形态：w1 是旧组织（产品、工程），w2 是新组织（工程、设计），w3 已经结束
      w1: [{ id: "product", label: "产品" }, { id: "engineering", label: "工程" }],
      w2: [{ id: "engineering", label: "工程" }, { id: "design", label: "设计" }],
      w3: [{ id: "quality", label: "质检" }],
    },
  });
  // 现在组织里的部门一个不少；旧组织里的产品跟在后面；已经结束的事项不添列；同一个部门只出现一次
  assert.deepEqual(departments, [
    { id: "engineering", label: "工程" },
    { id: "design", label: "设计" },
    { id: "product", label: "产品" },
  ]);
});

test("只有一个角色的项目看板只有那一个部门列", () => {
  assert.deepEqual(boardDepartments({
    current: [{ id: "engineering", label: "工程" }],
    items: [item("w1", "in_progress")],
    itemDepartments: { w1: [{ id: "engineering", label: "工程" }] },
  }), [{ id: "engineering", label: "工程" }]);
});
