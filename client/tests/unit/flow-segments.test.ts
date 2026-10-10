// 流转覆盖层的分段（工单 #379，来自 #366 的审查）：project.flow 的行只按起点、终点与是否返工分组，
// 同一对部门的两种非返工流转并入同一段，段落的 kind 取第一条该组记录的种类。
// 分组函数是页面实现（views/project/floor-screen.tsx）与端到端用例共用的同一份，不另写一份公式。

import { test } from "node:test";
import assert from "node:assert/strict";
import { flowSegmentsOf } from "../../src/renderer/src/views/project/flow-segments.ts";
import type { FlowRecord } from "../../src/renderer/src/api/generated/types.gen";

function row(from: string, to: string, kind: string, at: string): FlowRecord {
  return {
    flow_id: `f_${from}_${to}_${kind}_${at}`,
    kind,
    status: "已完成",
    content: "",
    direction_from: from,
    direction_to: to,
    run_id: "run_1",
    work_item_id: "wi_1",
    position: 1,
    seq: 1,
    event_id: "evt_1",
    created_at: at,
  };
}

test("同一对部门的两种非返工流转并入同一段，次数相加、最后时间取较晚的一条", () => {
  const segments = flowSegmentsOf([
    row("product", "engineering", "需求交接", "2026-01-01T00:00:00Z"),
    row("product", "engineering", "咨询", "2026-01-02T00:00:00Z"),
  ]);
  assert.equal(segments.length, 1);
  assert.deepEqual(segments[0], {
    from: "product",
    to: "engineering",
    count: 2,
    last_at: "2026-01-02T00:00:00Z",
    kind: "需求交接",
  });
});

test("返工单独成段，不与同一对部门的非返工行合并", () => {
  const segments = flowSegmentsOf([
    row("quality", "engineering", "问题反馈", "2026-01-01T00:00:00Z"),
    row("quality", "engineering", "返工", "2026-01-02T00:00:00Z"),
  ]);
  assert.equal(segments.length, 2);
  assert.deepEqual(segments.map((seg) => [seg.kind, seg.count]),
    [["问题反馈", 1], ["rework", 1]]);
});

test("方向不同或缺少一端的行不进分段", () => {
  const segments = flowSegmentsOf([
    row("product", "engineering", "需求交接", "2026-01-01T00:00:00Z"),
    row("engineering", "product", "需求交接", "2026-01-01T00:00:00Z"),
    { ...row("product", "engineering", "咨询", "2026-01-01T00:00:00Z"), direction_to: null },
  ]);
  assert.equal(segments.length, 2);
  assert.deepEqual(segments.map((seg) => [seg.from, seg.to]), [["product", "engineering"], ["engineering", "product"]]);
});

test("没有查询结果时没有分段", () => {
  assert.deepEqual(flowSegmentsOf(null), []);
  assert.deepEqual(flowSegmentsOf([]), []);
});
