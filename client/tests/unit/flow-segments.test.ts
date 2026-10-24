// 流转覆盖层的分段（工单 #415；工单 #866 换成现在的流转种类）：project.flow 的行只按起点、
// 终点与是否返工分组，同一对部门的两种非返工流转并入同一段，返工那条另成一段，
// 段落的 kind 取第一条该组记录的种类。
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

// 真实事件场景（工单 #866 验收标准 1、2）：应用层给出的流转种类只有版本交付、询问与问题反馈三种
// （harness/app/read_models.py 的流转推导）。工程→质检有版本交付与询问两种非返工流转，合成一段；
// 质检→工程有询问与问题反馈，各成一段（问题反馈是返工那条）。
// 应有的结果写死：非返工一段、返工一段，段数与次数都写在这里。
const realScene = [
  row("engineering", "quality", "版本交付", "2026-01-01T00:00:00Z"),
  row("engineering", "quality", "询问", "2026-01-02T00:00:00Z"),
  row("quality", "engineering", "询问", "2026-01-03T00:00:00Z"),
  row("quality", "engineering", "问题反馈", "2026-01-04T00:00:00Z"),
];

test("同一对部门的两种非返工流转并入一段，返工那条另成一段", () => {
  const segments = flowSegmentsOf(realScene);
  // 三段：工程→质检一段、质检→工程的非返工段与返工段
  assert.equal(segments.length, 3);
  const pair = segments.filter((seg) => seg.from === "quality" && seg.to === "engineering");
  // 同一对部门只有两段：非返工一段与返工一段
  assert.equal(pair.length, 2);
  const plain = pair.find((seg) => seg.kind !== "rework");
  const rework = pair.find((seg) => seg.kind === "rework");
  assert.deepEqual(plain, {
    from: "quality",
    to: "engineering",
    count: 1,
    last_at: "2026-01-03T00:00:00Z",
    kind: "询问",
  });
  assert.deepEqual(rework, {
    from: "quality",
    to: "engineering",
    count: 1,
    last_at: "2026-01-04T00:00:00Z",
    kind: "rework",
  });
  // 工程→质检的版本交付与询问合成一段
  const delivery = segments.find((seg) => seg.from === "engineering" && seg.to === "quality");
  assert.deepEqual(delivery, {
    from: "engineering",
    to: "quality",
    count: 2,
    last_at: "2026-01-02T00:00:00Z",
    kind: "版本交付",
  });
});

test("同一对部门的两种非返工流转的次数求和、最后时间取较晚的一条", () => {
  const segments = flowSegmentsOf([
    row("engineering", "quality", "版本交付", "2026-01-01T00:00:00Z"),
    row("engineering", "quality", "询问", "2026-01-02T00:00:00Z"),
  ]);
  assert.equal(segments.length, 1);
  assert.deepEqual(segments[0], {
    from: "engineering",
    to: "quality",
    count: 2,
    last_at: "2026-01-02T00:00:00Z",
    kind: "版本交付",
  });
});

test("返工那条（问题反馈）单独成段，不与同一对部门的非返工行合并", () => {
  const segments = flowSegmentsOf([
    row("quality", "engineering", "询问", "2026-01-01T00:00:00Z"),
    row("quality", "engineering", "问题反馈", "2026-01-02T00:00:00Z"),
  ]);
  assert.equal(segments.length, 2);
  assert.deepEqual(segments.map((seg) => [seg.kind, seg.count]),
    [["询问", 1], ["rework", 1]]);
});

test("方向不同或缺少一端的行不进分段", () => {
  const segments = flowSegmentsOf([
    row("engineering", "quality", "版本交付", "2026-01-01T00:00:00Z"),
    row("quality", "engineering", "询问", "2026-01-01T00:00:00Z"),
    { ...row("quality", "engineering", "询问", "2026-01-01T00:00:00Z"), direction_to: null },
  ]);
  assert.equal(segments.length, 2);
  assert.deepEqual(segments.map((seg) => [seg.from, seg.to]), [["engineering", "quality"], ["quality", "engineering"]]);
});

test("没有查询结果时没有分段", () => {
  assert.deepEqual(flowSegmentsOf(null), []);
  assert.deepEqual(flowSegmentsOf([]), []);
});
