// 顶栏待决数量的重查口径（工单 #701）：决定请求可能写在 run 流、项目流或目录流里，
// 客户端按能力清单里 decisions.list 声明的事件种类重查，不再写死三种。
// 这里只核对口径的判断，与界面无关。

import { test } from "node:test";
import assert from "node:assert/strict";
import { pendingDecisionEventTypes } from "../../src/renderer/src/contract/pending-decisions.ts";

// 服务端在 decisions.list 的 changed_by 里登记的九种：run 流三种、项目流三种、目录流三种
const DECISION_EVENTS = [
  "decision_requested", "decision_answered", "decision_withdrawn",
  "project_decision_requested", "project_decision_answered", "project_decision_withdrawn",
  "instance_upgrade_requested", "instance_upgrade_answered", "instance_upgrade_withdrawn",
];

test("待决数量的重查按能力清单里 decisions.list 声明的事件种类", () => {
  const types = pendingDecisionEventTypes({
    queries: [{ name: "decisions.list", changed_by: DECISION_EVENTS }],
  });
  // run 流、项目流与目录流三种都算：项目流里的决定（接入已有项目的初始 PRD）回答以后顶栏要更新
  for (const name of DECISION_EVENTS) {
    assert.ok(types.has(name), `${name} 应当引起重查`);
  }
  // 与决定无关的种类不重查
  assert.ok(!types.has("tool_called"));
  assert.ok(!types.has("project_registered"));
});

test("能力清单里没有 decisions.list 时不重查", () => {
  assert.equal(pendingDecisionEventTypes({ queries: [] }).size, 0);
  assert.equal(pendingDecisionEventTypes({ queries: [{ name: "projects.list", changed_by: ["project_registered"] }] }).size, 0);
  // 还没有连上服务（能力清单为空）时同样不重查
  assert.equal(pendingDecisionEventTypes(null).size, 0);
});
