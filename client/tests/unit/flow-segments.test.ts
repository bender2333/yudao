// 流转覆盖层的分段（工单 #415）：project.flow 的行只按起点、终点与是否返工分组，
// 同一对部门的两种非返工流转并入同一段，返工另成一段，段落的 kind 取第一条该组记录的种类。
//
// 预期由工单规定，直接写出应有的段数、次数与标签：这里不复现实现的分组公式，
// 因此实现若把同一对部门的两种非返工流转拆成两段，这些字面值立刻失败。

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

// 真实事件场景（工单 #415 验收标准 1、2）：交付历史项目在 quality→engineering 上有
// 一条「咨询」与一条「问题反馈」（两种非返工流转），加上质检退回工程产生的「返工」。
// 应有的结果写死：非返工一段（次数 2）、返工一段（次数 1），共两段。
const realScene = [
  row("product", "engineering", "需求交接", "2026-01-01T00:00:00Z"),
  row("engineering", "quality", "版本交付", "2026-01-02T00:00:00Z"),
  row("quality", "product", "咨询", "2026-01-03T00:00:00Z"),
  row("quality", "engineering", "咨询", "2026-01-04T00:00:00Z"),
  row("quality", "engineering", "问题反馈", "2026-01-05T00:00:00Z"),
  row("quality", "engineering", "返工", "2026-01-06T00:00:00Z"),
  row("engineering", "engineering", "需求交接", "2026-01-07T00:00:00Z"),
  row("engineering", "quality", "版本交付", "2026-01-08T00:00:00Z"),
];

test("真实场景下同一对部门的两种非返工流转并入一段，返工单独成段", () => {
  const segments = flowSegmentsOf(realScene);
  // 六段：product→engineering、engineering→quality、quality→product、
  // quality→engineering 的非返工段与返工段、engineering→engineering
  assert.equal(segments.length, 6);
  const pair = segments.filter((seg) => seg.from === "quality" && seg.to === "engineering");
  // 同一对部门只有两段：非返工一段与返工一段
  assert.equal(pair.length, 2);
  const plain = pair.find((seg) => seg.kind !== "rework");
  const rework = pair.find((seg) => seg.kind === "rework");
  assert.deepEqual(plain, {
    from: "quality",
    to: "engineering",
    count: 2,
    last_at: "2026-01-05T00:00:00Z",
    kind: "咨询",
  });
  assert.deepEqual(rework, {
    from: "quality",
    to: "engineering",
    count: 1,
    last_at: "2026-01-06T00:00:00Z",
    kind: "rework",
  });
});

test("同一对部门的两种非返工流转的次数求和、最后时间取较晚的一条", () => {
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
