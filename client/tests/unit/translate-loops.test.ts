// 循环与收敛的翻译层（工单 #400 的验收）：run.loops 的结果翻成观测页的行与覆盖层「循环」的标签。
// 这里只核对翻译：层与状态的中文名、已用量与上限的写法（含不设上限）、每棵树的实例、缺什么事实、
// 图例与信息条。判定不在这一层，测试也不自己推状态。

import assert from "node:assert/strict";
import test from "node:test";
import type { RunLoopsResult } from "../../src/renderer/src/api/generated/types.gen.ts";
import {
  amountText, loopLayerLabel, loopRows, loopRuleText, loopStateLabel, loopsOverlay,
} from "../../src/renderer/src/translate/floor.ts";
import { OVERLAY_LABELS, overlayProblems } from "../../src/renderer/src/translate/coverage.ts";

function result(overrides: Partial<RunLoopsResult> = {}): RunLoopsResult {
  const base: RunLoopsResult = {
    run_id: "run-1",
    project_id: "proj-1",
    work_item_id: "item-1",
    status: "running",
    stop_reason: null,
    parameters: { "convergence.rounds": 3, "convergence.step_window": 8, "convergence.step_repeat": 3 },
    method: { trend_switch_rounds: 8, flip_threshold: 2 },
    layers: [
      { name: "project_loop", state: "undetermined", missing: "项目层缺少故障记录：运维记录故障以后判定", amounts: {} },
      { name: "work_item", state: "undetermined", missing: "事项层缺少计划条目完成的主机事实", amounts: {} },
      {
        name: "run", state: "undetermined", missing: "run 层缺少逐条核验结论（#1194 接入逐条核验数据以后判定）",
        amounts: {
          elapsed_ms: { used: 1000, limit: 7200000, unlimited: false },
          model_steps: { used: 3, limit: 999999, unlimited: true },
        },
      },
      { name: "activation", state: "undetermined", missing: "激活层缺少计划条目完成的主机事实",
        amounts: { activations: { used: 1, limit: 999999, unlimited: true } } },
      { name: "step", state: "converging", missing: null, amounts: { model_steps: { used: 3, limit: 999999, unlimited: true } } },
    ],
    activations: [
      {
        activation_id: "act-1", department: "engineering", started_at: "2026-10-31T00:00:00+00:00",
        finished_at: null, state: "undetermined", missing: "激活层缺少计划条目完成的主机事实",
        steps: [
          { step_id: 1, activation_id: "act-1", purpose: "work", requested_at: "2026-10-31T00:00:00+00:00",
            attempts: 1, accepted: true, facts: [{ kind: "write", position: 12 }], calls: ["write_file:abc"] },
          { step_id: 2, activation_id: "act-1", purpose: "compaction", requested_at: "2026-10-31T00:01:00+00:00",
            attempts: 1, accepted: false, facts: [], calls: [] },
        ],
      },
    ],
    rounds: 1,
    trend: null,
  };
  return { ...base, ...overrides };
}

test("层与状态的中文名：五种状态与不判定都有中文，不出现英文内部标识", () => {
  // 守 R1（页面不出现英文内部标识）：层与状态都翻成中文，未登记的值照原样（不吞掉内容）
  assert.equal(loopStateLabel("converging"), "收敛中");
  assert.equal(loopStateLabel("stalled"), "停滞");
  assert.equal(loopStateLabel("oscillating"), "震荡");
  assert.equal(loopStateLabel("drifting"), "漂移");
  assert.equal(loopStateLabel("boundary"), "达到边界");
  assert.equal(loopStateLabel("undetermined"), "不判定");
  assert.equal(loopLayerLabel("run"), "运行");
  assert.equal(loopLayerLabel("step"), "步骤");
  assert.equal(loopStateLabel("其它"), "其它");
});

test("已用量与上限：不设上限时写「不设上限」并保留数值", () => {
  // 守 R1（已用量与不设上限标识同时给）：数值照写，不设上限不写成空值
  assert.equal(amountText({ used: 3, limit: 999999, unlimited: true }, " 步"), "3 步 / 不设上限");
  assert.equal(amountText({ used: 1000, limit: 7200000, unlimited: false }, " 毫秒"), "1000 毫秒 / 7200000 毫秒");
  assert.equal(amountText(undefined, " 步"), "—");
});

test("观测页的行：五层与每次激活的步骤循环各一行，实例写部门与第几次激活", () => {
  // 守 R1（实例树的层、已用边界与收敛状态与 run.loops 一致）：行与查询结果一一对应
  const rows = loopRows(result());
  assert.deepEqual(rows.map((row) => row.layer), ["project_loop", "work_item", "run", "activation", "step"]);
  assert.deepEqual(rows.map((row) => row.layerLabel), ["项目循环", "事项", "运行", "激活", "步骤"]);
  assert.equal(rows[2].instance, "运行");
  assert.equal(rows[3].instance, "工程 · 第 1 次激活");
  assert.equal(rows[4].instance, "工程 · 第 1 次激活 · 步骤循环");
  // 步骤层的状态是查询给的那一个；压缩步不算工作步
  assert.equal(rows[4].stateLabel, "收敛中");
  assert.equal(rows[4].used, "1 步");
  // 「不判定」的行写明缺少的事实；run 行按查询的停止原因写
  assert.match(rows[0].missing, /故障记录/);
  assert.match(rows[2].missing, /核验结论/);
  assert.equal(rows[2].stopReason, "");
});

test("观测页的行：停止的运行写出停止原因的中文", () => {
  const rows = loopRows(result({ status: "done", stop_reason: "model_steps_exhausted" }));
  assert.match(rows[2].stopReason, /[\u4e00-\u9fa5]/);
});

test("观测页的判定依据：三项冻结参数与两个方法常量", () => {
  // 守 R1（判定用的规则与轮数写在页面上）：参数取查询里的冻结值，方法常量照写
  const text = loopRuleText(result());
  assert.match(text, /收敛判定看最近几轮 3/);
  assert.match(text, /步骤停滞看连续几步 8/);
  assert.match(text, /同一次调用重复几次算震荡 3/);
  assert.match(text, /轮数达到 8 改用趋势检验/);
  assert.match(text, /翻转 2 次算震荡/);
  assert.equal(loopRuleText(null), "");
});

test("覆盖层「循环」的数据：信息条写 run 层，房间写激活与步骤，图例六行", () => {
  // 守 R1（覆盖层与 run.loops 一致）：信息条是 run 层的状态，房间是这次激活，图例是五态与不判定
  const overlay = loopsOverlay(result());
  assert.match(overlay.bar.text, /^运行 · 不判定$/);
  assert.equal(overlay.rooms.length, 1);
  assert.equal(overlay.rooms[0].department, "engineering");
  assert.equal(overlay.rooms[0].text, "第 1 次激活 · 不判定");
  assert.equal(overlay.rooms[0].step_text, "步骤 1 步 · 收敛中");
  assert.deepEqual(overlay.legend.map((row) => row.state),
                   ["converging", "stalled", "oscillating", "drifting", "boundary", "undetermined"]);
  assert.deepEqual(overlay.legend.map((row) => row.label),
                   ["收敛中", "停滞", "震荡", "漂移", "达到边界", "不判定"]);
});

test("覆盖层「循环」在没有运行时的说法与停止原因", () => {
  const empty = loopsOverlay(null);
  assert.equal(empty.bar.text, "还没有运行");
  assert.deepEqual(empty.rooms, []);
  const stopped = loopsOverlay(result({ status: "done", stop_reason: "time_limit" }));
  assert.match(stopped.bar.text, /停止：/);
});

test("覆盖层「循环」在覆盖层登记表里有一行，覆盖核对通过", () => {
  // 守 R1（翻译层覆盖核对）：能力清单里的覆盖层都要有中文名，缺一行时核对报错
  assert.equal(OVERLAY_LABELS.loops, "循环");
  assert.deepEqual(overlayProblems(["flow", "sources", "loops"]), []);
  assert.deepEqual(overlayProblems(["loops", "unknown"]), ["覆盖层 unknown 在翻译层没有中文名"]);
});
