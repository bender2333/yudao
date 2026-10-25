// 事项的进度（工单 #556）：从成果推算，页面上写 PRD 版本、交付版本与对最新交付的结论。
// 阶段状态机删掉以后，run 的状态只有进行中与三个终态。
// 工单 #904 按原型 v12 第 3.2 节改写写法：「PRD r2 · 交付 r1（依据 PRD r2）· 结论：放行」。

import { test } from "node:test";
import assert from "node:assert/strict";
import { RUN_STATUS_LABELS, progressLabel } from "../../src/renderer/src/views/project/labels.ts";

test("进度写当前 PRD 版本、最新交付版本与它依据的 PRD 版本", () => {
  assert.equal(
    progressLabel({
      product_spec_revision: 2,
      delivery_revision: 1,
      delivery_product_spec_revision: 1,
      conclusion: null,
    }),
    "PRD r2 · 交付 r1（依据 PRD r1）",
  );
});

test("对最新交付的结论写在进度里", () => {
  assert.equal(
    progressLabel({
      product_spec_revision: 1,
      delivery_revision: 1,
      delivery_product_spec_revision: 1,
      conclusion: "rework_engineering",
    }),
    "PRD r1 · 交付 r1（依据 PRD r1）· 结论：缺陷记录",
  );
  assert.equal(
    progressLabel({
      product_spec_revision: 1,
      delivery_revision: 1,
      delivery_product_spec_revision: 1,
      conclusion: "release",
    }),
    "PRD r1 · 交付 r1（依据 PRD r1）· 结论：放行",
  );
});

test("还没有成果时没有进度", () => {
  assert.equal(progressLabel(null), null);
  assert.equal(progressLabel({ product_spec_revision: null, delivery_revision: null, delivery_product_spec_revision: null, conclusion: null }), null);
});

test("run 状态只有进行中与三个终态", () => {
  assert.deepEqual(Object.keys(RUN_STATUS_LABELS).sort(), ["done", "failed", "paused", "running"]);
  assert.equal(RUN_STATUS_LABELS.running, "进行中");
  assert.equal(RUN_STATUS_LABELS.done, "已完成");
  assert.equal(RUN_STATUS_LABELS.paused, "已暂停");
  assert.equal(RUN_STATUS_LABELS.failed, "执行失败");
});
