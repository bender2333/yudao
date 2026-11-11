// 事项看板分组与页面名称的单元测试（工单 #303）：取消的事项不再落进部门列；
// run 状态与停止原因的中文名与控制核心一致，停止事项没有部门时页面省略这一格（工单 #556）。
// 工单 #904 在这里核对概览与看板的文字：所在部门一行写三个部门各自的状态与原因、按成果写的进度行、
// 看板卡片上正在工作的部门。工单 #1372 核对分组的口径：部门列按部门在事项上的状态分（几个部门同时
// 工作时同一事项在几列里，与部门状态行说的是同一件事）、部门列取自事项的部门（换了部门名的定义列跟着换）。
// 工单 #1709 核对「全部事项」列表：与看板同一份分组口径，每组写件数，件数与事项统计对得上；
// 开环完成与放行分在两组；同名的已停止事项靠事项标识与停止时间分辨；排队中的顺序就是执行顺序；
// 职能列取自事项冻结的组织。期望值写成字面值，不复用实现的公式。

import { test } from "node:test";
import assert from "node:assert/strict";
import { allItemsList,boardColumns,boardGroups } from "../../src/renderer/src/views/project/board.ts";
import { DECISION_BLOCKS,DEPARTMENT_STATE,RUN_STATUS_LABELS,STOP_NOTE_INLINE_LIMIT,STOP_REASON,departmentLine,departmentName,departmentsText,formatTime,isOpenLoopCompleted,label,progressLabel,stopNoteView,workItemStatusText,workingDepartmentsText } from "../../src/renderer/src/views/project/labels.ts";
import type { DepartmentState,WorkItemCard } from "../../src/renderer/src/api/generated/types.gen.ts";


const STOP_REASONS = [
  "released", "open_loop", "baseline_verified", "max_cycles", "model_steps_exhausted", "no_tool_call",
  "workspace_unrepresentable", "time_limit", "cancelled", "user_cancelled", "provider_error", "provider_timeout",
  "provider_protocol", "unsupported_protocol", "retry_after_too_long", "context_overflow",
  "compaction_failed", "host_commit_error", "run_event_version_changed",
];

function item(overrides: Partial<WorkItemCard> & { work_item_id: string }): WorkItemCard {
  const base: Omit<WorkItemCard, "work_item_id"> = {
    kind: "request",
    title: "事项",
    text: "",
    run_id: "run_1",
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    status: "in_progress",
    department: null,
    progress: null,
    round: 1,
    stop_reason: null,
    stop_note: null,
    human_action: null,
    pending_question: null,
    adoption_id: null,
    start_error: null,
  };
  return { ...base, ...overrides };
}

test("取消的事项进已停止列，不落进任何部门列", () => {
  const stopped = item({ work_item_id: "w3", status: "stopped", department: null, stop_reason: "cancelled" });
  const columns = boardColumns([stopped]);
  assert.deepEqual(columns.stopped.map((entry) => entry.work_item_id), ["w3"]);
  assert.deepEqual(columns.departments, []);
  assert.deepEqual(columns.queue, []);
});

test("部门列按部门分列，已放行与已采纳各自一列", () => {
  // 进行中的事项由它所用的定义给出三个部门的状态（服务端按定义顺序给出，这里也是那个顺序）；
  // 每件事项只有一个部门在它上面工作，因此各自只有一列放着它
  const waiting = { state: "waiting" } as const;
  const states = (working: string): Record<string, DepartmentState> => ({
    product: working === "product" ? { state: "working" } : waiting,
    engineering: working === "engineering" ? { state: "working" } : waiting,
    quality: working === "quality" ? { state: "working" } : waiting,
  });
  const columns = boardColumns([
    item({ work_item_id: "w1", status: "not_started" }),
    item({ work_item_id: "w2", status: "in_progress", department: "engineering", departments: states("engineering") }),
    item({ work_item_id: "w3", status: "in_progress", department: "quality", departments: states("quality") }),
    item({ work_item_id: "w4", status: "in_progress", department: "product", departments: states("product") }),
    item({ work_item_id: "w5", status: "released_unsettled", department: null }),
    item({ work_item_id: "w6", status: "adopted", department: null }),
  ]);
  assert.deepEqual(columns.queue.map((entry) => entry.work_item_id), ["w1"]);
  assert.deepEqual(columns.departments.map((column) => column.department), ["product", "engineering", "quality"]);
  assert.deepEqual(columns.departments.map((column) => column.items.map((entry) => entry.work_item_id)), [
    ["w4"], ["w2"], ["w3"],
  ]);
  assert.deepEqual(columns.released.map((entry) => entry.work_item_id), ["w5"]);
  assert.deepEqual(columns.adopted.map((entry) => entry.work_item_id), ["w6"]);
});

test("开环完成的事项进开环完成一列，已放行里没有它（工单 #1421）", () => {
  // 项目流里两种结束方式都是 released_unsettled，只有结束原因不同：判断只读卡片上的这两个字段
  const openLoop = item({ work_item_id: "w1", status: "released_unsettled", department: null, stop_reason: "open_loop" });
  const released = item({ work_item_id: "w2", status: "released_unsettled", department: null, stop_reason: "released" });
  // 结束原因还没有写下的（结算还没跑）仍按放行待采纳，不猜成开环完成
  const unsettled = item({ work_item_id: "w3", status: "released_unsettled", department: null, stop_reason: null });
  const columns = boardColumns([openLoop, released, unsettled]);
  assert.deepEqual(columns.open_loop.map((entry) => entry.work_item_id), ["w1"]);
  assert.deepEqual(columns.released.map((entry) => entry.work_item_id), ["w2", "w3"]);
  // 看板的固定组在「已放行」之后是「开环完成」
  const groups = boardGroups([openLoop, released]);
  assert.deepEqual(groups.map((group) => group.title), ["排队中", "已放行", "开环完成", "已采纳", "已停止"]);
  assert.deepEqual(groups[1].items.map((entry) => entry.work_item_id), ["w2"]);
  assert.deepEqual(groups[2].items.map((entry) => entry.work_item_id), ["w1"]);
});

test("事项状态写「开环完成」还是「已放行」只看卡片上的状态与结束原因（工单 #1421）", () => {
  assert.equal(isOpenLoopCompleted({ status: "released_unsettled", stop_reason: "open_loop" }), true);
  assert.equal(isOpenLoopCompleted({ status: "released_unsettled", stop_reason: "released" }), false);
  assert.equal(isOpenLoopCompleted({ status: "released_unsettled" }), false);
  // 采纳以后是另一种状态：开环完成的记录留在结束原因上，页面按状态写已采纳
  assert.equal(isOpenLoopCompleted({ status: "adopted", stop_reason: "open_loop" }), false);
  assert.equal(workItemStatusText({ status: "released_unsettled", stop_reason: "open_loop" }), "开环完成");
  assert.equal(workItemStatusText({ status: "released_unsettled", stop_reason: "released" }), "已放行");
  assert.equal(workItemStatusText({ status: "adopted", stop_reason: "open_loop" }), "已采纳");
  // 开环完成的写法里没有「放行」，也没有英文内部标识
  assert.equal(/[A-Za-z]/.test(workItemStatusText({ status: "released_unsettled", stop_reason: "open_loop" })), false);
  assert.equal(workItemStatusText({ status: "released_unsettled", stop_reason: "open_loop" }).includes("放行"), false);
});

test("两个部门同时工作时，事项在两个部门的列里，与部门状态行说的是同一件事", () => {
  // 试用里的一次读数（试用工单 #994 的 F1，卡点 N-08）：「工程 一轮工作中 · 质检 一轮工作中（预测性探索…）」，
  // 看板却是「工程(0) 质检(1)」。看板的分组改按各部门的状态分过去以后，同一个事项在工程与质检两列里
  const card = item({
    work_item_id: "w1",
    status: "in_progress",
    department: "quality",
    departments: {
      product: { state: "waiting" },
      engineering: { state: "working" },
      quality: { state: "working", note: "预测性探索：按 PRD r1 起草测试用例" },
    },
  });
  const columns = boardColumns([card]);
  // 部门状态行（概览「当前事项」那一行）说工程与质检在一轮工作中
  assert.equal(
    departmentsText(card.departments),
    "产品 等待工作 · 工程 一轮工作中 · 质检 一轮工作中（预测性探索：按 PRD r1 起草测试用例）",
  );
  // 看板上这两个部门的列里都有这个事项，等待工作的产品列里没有
  assert.deepEqual(columns.departments.map((column) => column.title), ["产品", "工程", "质检"]);
  assert.deepEqual(columns.departments.map((column) => column.items.map((entry) => entry.work_item_id)), [
    [], ["w1"], ["w1"],
  ]);
  // 状态行说在一轮工作中的每一个部门，看板上它的列里都有这个事项——两边说的是同一件事
  for (const column of columns.departments) {
    const working = card.departments?.[column.department]?.state === "working";
    assert.equal(column.items.length > 0, working, column.department);
  }
});

test("部门列取自事项的部门，换了部门名的定义，列跟着换，不写死三个部门", () => {
  // 三个部门改名的定义（harness/tests/test_watched_outputs_renamed.py 那一份的部门编号）：
  // 看板的分组跟着事项的部门走，默认定义的产品、工程、质检三列一列都不出现
  const columns = boardColumns([
    item({
      work_item_id: "w1",
      status: "in_progress",
      department: "requirements",
      departments: {
        requirements: { state: "working" },
        build: { state: "waiting" },
        inspection: { state: "waiting" },
      },
    }),
  ]);
  assert.deepEqual(columns.departments.map((column) => column.department), ["requirements", "build", "inspection"]);
  assert.deepEqual(columns.departments.map((column) => column.items.map((entry) => entry.work_item_id)), [["w1"], [], []]);
  for (const fixed of ["product", "engineering", "quality"]) {
    assert.equal(columns.departments.some((column) => column.department === fixed), false, fixed);
  }
});

test("部门都在等待工作、也没有所在部门时，按所在部门放；两样都没有的事项在排队中", () => {
  const allWaiting: Record<string, DepartmentState> = {
    product: { state: "waiting" },
    engineering: { state: "waiting" },
    quality: { state: "waiting" },
  };
  const idle = item({ work_item_id: "w1", status: "in_progress", department: "engineering", departments: allWaiting });
  const columns = boardColumns([idle]);
  // 部门列还是定义里的三个（部门列不因没有人在工作而消失），事项按所在部门落在工程列
  assert.deepEqual(columns.departments.map((column) => column.department), ["product", "engineering", "quality"]);
  assert.deepEqual(columns.departments.map((column) => column.items.map((entry) => entry.work_item_id)), [
    [], ["w1"], [],
  ]);
  // 等待确认初始 PRD 的事项没有部门在它上面工作，也没有所在部门：在排队中，不从看板上消失
  const awaiting = item({ work_item_id: "w2", status: "awaiting_initial_prd", department: null, departments: null });
  assert.deepEqual(boardColumns([awaiting]).queue.map((entry) => entry.work_item_id), ["w2"]);
});

test("看板按显示顺序给出各组：排队中、各部门、已放行、开环完成、已采纳、已停止", () => {
  const groups = boardGroups([
    item({
      work_item_id: "w1",
      status: "in_progress",
      department: "engineering",
      departments: {
        product: { state: "waiting" },
        engineering: { state: "working" },
        quality: { state: "waiting" },
      },
    }),
  ]);
  assert.deepEqual(groups.map((group) => group.title),
    ["排队中", "产品", "工程", "质检", "已放行", "开环完成", "已采纳", "已停止"]);
  assert.deepEqual(groups[2].items.map((entry) => entry.work_item_id), ["w1"]);
  // 项目里没有进行中的事项（只有已采纳的事项）时没有部门列：只有按状态分的五组
  const adoptedOnly = boardGroups([item({ work_item_id: "w2", status: "adopted", department: null })]);
  assert.deepEqual(adoptedOnly.map((group) => group.title), ["排队中", "已放行", "开环完成", "已采纳", "已停止"]);
  assert.deepEqual(adoptedOnly[3].items.map((entry) => entry.work_item_id), ["w2"]);
  // 一个事项都没有时也是这五组，界面按「项目还没有事项」写空态
  assert.deepEqual(boardGroups([]).map((group) => group.title),
    ["排队中", "已放行", "开环完成", "已采纳", "已停止"]);
});


test("停止原因与 run 状态的中文名只覆盖控制核心与定义里的取值", () => {
  assert.deepEqual(Object.keys(STOP_REASON).sort(), [...STOP_REASONS].sort());
  assert.equal(label(STOP_REASON, "released"), "已完成并放行");
  assert.equal(label(STOP_REASON, "cancelled"), "运行已被取消");
  // 开环完成是另一种结束方式（工单 #1421）：中文名与「放行」分开，页面上不出现 open_loop
  assert.equal(label(STOP_REASON, "open_loop"), "开环完成");
  assert.equal(label(STOP_REASON, "open_loop").includes("放行"), false);
  for (const name of [...Object.values(RUN_STATUS_LABELS), ...Object.values(STOP_REASON)]) {
    assert.equal(/[A-Za-z]/.test(name.replace("Yudao", "")), false, name);
  }
});

test("决定卡片的阻塞范围标记是中文：不出现内部词 run 与 action", () => {
  assert.deepEqual(Object.keys(DECISION_BLOCKS).sort(), ["action", "run"]);
  assert.equal(label(DECISION_BLOCKS, "run"), "整次运行");
  assert.equal(label(DECISION_BLOCKS, "action"), "单个动作");
  for (const name of Object.values(DECISION_BLOCKS)) {
    assert.equal(/[A-Za-z]/.test(name), false, name);
  }
});

test("停止的事项没有部门时不写「未知部门」，页面自己决定省略还是写「没有」", () => {
  assert.equal(departmentName(null), "");
  assert.equal(departmentName(""), "");
  assert.equal(departmentName("engineering"), "工程");
});

// ---------------------------------------------------------------------------
// 概览「当前事项」的两行与看板卡片（工单 #904）：所在部门一行写三个部门各自的状态与原因，
// 进度行按成果写，看板卡片写正在工作的部门。期望值是字面值。

test("所在部门一行写三个部门各自的状态与原因，按查询给出的顺序", () => {
  assert.equal(
    departmentLine({
      product: { state: "waiting" },
      engineering: { state: "working" },
      quality: { state: "working", note: "预测性探索：按 PRD r1 起草测试用例" },
    }, "quality"),
    "产品 等待工作 · 工程 一轮工作中 · 质检 一轮工作中（预测性探索：按 PRD r1 起草测试用例）",
  );
  // 只有一个部门有状态时只写它（查询给几个部门就写几个）
  assert.equal(
    departmentsText({ engineering: { state: "verifying", note: "等质检核验交付 r1" } }),
    "工程 核验中（等质检核验交付 r1）",
  );
});

test("没有 departments 时照旧写所在职能，没有职能时写大厅", () => {
  assert.equal(departmentLine(null, "engineering"), "所在职能：工程");
  assert.equal(departmentLine(undefined, null), "所在职能：大厅");
  assert.equal(departmentsText(null), null);
  assert.equal(departmentLine({}, "product"), "所在职能：产品");
});

test("部门状态的中文名用总图外环的五个词，只写这一处", () => {
  assert.deepEqual(Object.keys(DEPARTMENT_STATE).sort(), ["asking", "verifying", "waiting", "waiting_user", "working"]);
  assert.equal(DEPARTMENT_STATE.waiting_user, "等用户");
  assert.equal(DEPARTMENT_STATE.working, "一轮工作中");
  assert.equal(DEPARTMENT_STATE.asking, "询问中");
  assert.equal(DEPARTMENT_STATE.verifying, "核验中");
  assert.equal(DEPARTMENT_STATE.waiting, "等待工作");
});

test("进度行的三种写法：有交付、没有交付、没有结论", () => {
  // 有交付：当前 PRD 版本、交付版本与它依据的 PRD、对最新交付的结论
  assert.equal(
    progressLabel({
      product_spec_revision: 2,
      delivery_revision: 1,
      delivery_product_spec_revision: 2,
      conclusion: "release",
    }),
    "PRD r2 · 交付 r1（依据 PRD r2）· 结论：放行",
  );
  // 没有交付
  assert.equal(
    progressLabel({ product_spec_revision: 2, delivery_revision: null, delivery_product_spec_revision: null, conclusion: null }),
    "PRD r2 · 还没有交付",
  );
  // 没有结论：这一项不写
  assert.equal(
    progressLabel({ product_spec_revision: 1, delivery_revision: 1, delivery_product_spec_revision: 1, conclusion: null }),
    "PRD r1 · 交付 r1（依据 PRD r1）",
  );
  // 还没有成果时不写这一行
  assert.equal(
    progressLabel({ product_spec_revision: null, delivery_revision: null, delivery_product_spec_revision: null, conclusion: null }),
    null,
  );
});

test("看板卡片写正在工作的部门，按查询给出的顺序", () => {
  assert.equal(
    workingDepartmentsText({
      department: "product",
      departments: {
        product: { state: "waiting", note: null },
        engineering: { state: "asking", note: "在等待产品的回答" },
        quality: { state: "working", note: "预测性探索：按 PRD r1 起草测试用例" },
      },
    }),
    "工程、质检在工作",
  );
  assert.equal(
    workingDepartmentsText({
      department: null,
      departments: {
        product: { state: "waiting" },
        engineering: { state: "working" },
        quality: { state: "waiting" },
      },
    }),
    "工程在工作",
  );
});

test("没有部门在工作时看板卡片不写这一格", () => {
  assert.equal(
    workingDepartmentsText({
      department: "engineering",
      departments: {
        product: { state: "waiting" },
        engineering: { state: "waiting_user", note: null },
        quality: { state: "verifying", note: "等质检核验交付 r1" },
      },
    }),
    "",
  );
});

test("查询结果里没有 departments 时看板卡片照旧写事项所在的部门", () => {
  assert.equal(workingDepartmentsText({ department: "engineering" }), "工程");
  assert.equal(workingDepartmentsText({ department: null }), "");
});

// ---------------------------------------------------------------------------
// 停止说明（工单 #1162）：停止原因下面写让事项停下的那条错误的原文，原样显示；
// 空白当作没有这一项；太长时折起来。期望值写成字面值。

test("停止说明原样写错误原文，不改写也不截断", () => {
  const stopped = item({
    work_item_id: "w1",
    status: "stopped",
    stop_reason: "provider_error",
    stop_note: "模型服务返回 HTTP 400：input length 131072 exceeds the maximum",
  });
  assert.deepEqual(stopNoteView(stopped.stop_note), {
    kind: "inline",
    text: "模型服务返回 HTTP 400：input length 131072 exceeds the maximum",
  });
});

test("没有停止说明时不写这一项：放行完成、用户自己停下、字段缺失与空白都一样", () => {
  assert.deepEqual(stopNoteView(item({ work_item_id: "w1", status: "released_unsettled" }).stop_note), { kind: "none" });
  assert.deepEqual(stopNoteView(item({ work_item_id: "w2", status: "stopped", stop_reason: "cancelled" }).stop_note), { kind: "none" });
  assert.deepEqual(stopNoteView(null), { kind: "none" });
  assert.deepEqual(stopNoteView(undefined), { kind: "none" });
  assert.deepEqual(stopNoteView("   "), { kind: "none" });
});

test("停止说明太长时折起来，全文照旧保留", () => {
  const long = `上游返回 400：${"x".repeat(200)}`;
  assert.deepEqual(stopNoteView(long), { kind: "folded", text: long });
  // 恰好到那一个字数的仍然一行写完
  assert.equal(stopNoteView("x".repeat(STOP_NOTE_INLINE_LIMIT)).kind, "inline");
  assert.equal(stopNoteView("x".repeat(STOP_NOTE_INLINE_LIMIT + 1)).kind, "folded");
});

// ---------------------------------------------------------------------------
// 已收下的交付（工单 #1239）：事项停止时，交付已经收下这件事写在停止说明下面一行，
// 带交付的版本与收下的时间；没有这一项时停止说明照旧（上面三条用例已经核对）。

test("停止说明下面多写一行：交付的版本与收下的时间", () => {
  const stopped = item({
    work_item_id: "w1",
    status: "stopped",
    stop_reason: "provider_error",
    stop_note: "模型服务返回 HTTP 400：input length 131072 exceeds the maximum",
    kept_delivery: { version: 2, accepted_at: "2026-01-02T03:04:05Z" },
  });
  const view = stopNoteView(stopped.stop_note, stopped.kept_delivery);
  assert.equal(view.kind, "inline");
  // 时间按页面统一的那一种写法（共用的 formatTime），句中其余是字面值
  assert.equal(view.keptDelivery, `交付 r2 已于 ${formatTime("2026-01-02T03:04:05Z")} 收下，尚未经质检放行`);
});

test("收下的时间缺失时写未知时间，整句照旧写出", () => {
  assert.equal(stopNoteView(null, { version: 3 }).keptDelivery, "交付 r3 已于 未知时间 收下，尚未经质检放行");
});

test("用户自己取消时没有停止说明，已收下的交付照旧写出来", () => {
  // 取消说的是用户的这次决定，交付仍然在：停止说明不写，已收下的交付照旧写
  const view = stopNoteView(null, { version: 1, accepted_at: "2026-01-02T03:04:05Z" });
  assert.equal(view.kind, "none");
  assert.equal(view.keptDelivery, `交付 r1 已于 ${formatTime("2026-01-02T03:04:05Z")} 收下，尚未经质检放行`);
});

test("没有已收下的交付时停止说明不变", () => {
  assert.equal(stopNoteView("出错了").keptDelivery, undefined);
  assert.equal(stopNoteView("出错了", null).keptDelivery, undefined);
  assert.equal(stopNoteView(null).keptDelivery, undefined);
  assert.deepEqual(stopNoteView(null, null), { kind: "none" });
});

// ---------------------------------------------------------------------------
// 全部事项的分组列表（工单 #1709；依据 docs/design/project-organization.md「事项面板与全部事项」、
// docs/design/app-and-interface.md「事项看板在页面上的显示」）：列表与看板用同一份分组与计数，
// 每组写这一组的件数；开环完成与放行分在两组；同名的已停止事项靠事项标识与停止时间分辨；
// 排队中的顺序就是执行顺序，不重排；职能列取自事项冻结的组织。期望值写成字面值。

const working = { state: "working" } as const;

test("各组件数与事项统计一致，一件同时在几个职能列里时总数不重复算", () => {
  const items = [
    // 排队中：还没交给任何职能（已登记没开始、成果挂起、等待确认初始 PRD）
    item({ work_item_id: "q1", status: "not_started", department: "engineering" }),
    item({ work_item_id: "q2", status: "held", department: "engineering" }),
    item({ work_item_id: "q3", status: "awaiting_initial_prd", department: null }),
    // 进行中：工程在看
    item({ work_item_id: "w1", departments: { engineering: working }, department: "engineering" }),
    item({ work_item_id: "w2", departments: { engineering: working }, department: "engineering" }),
    // 结束的三种
    item({ work_item_id: "r1", status: "released_unsettled", stop_reason: "released", department: "engineering" }),
    item({ work_item_id: "o1", status: "released_unsettled", stop_reason: "open_loop", department: "engineering" }),
    item({ work_item_id: "a1", status: "adopted", department: "engineering" }),
    item({ work_item_id: "a2", status: "adopted", department: "engineering" }),
    item({ work_item_id: "s1", status: "stopped", stop_reason: "cancelled", department: "engineering" }),
  ];
  const list = allItemsList(items);
  const countOf = (title: string): number => list.groups.filter((group) => group.title === title)[0]?.count ?? -1;
  // 逐项与 project.overview 的 stats 对上（stats：total 10、not_started 1、held 1、in_progress 2、
  // released_unsettled 1、open_loop 1、adopted 2、stopped 1；开环完成不在 released_unsettled 里，
  // 「等待确认初始 PRD」没有单独一项，它在看板落进排队中）
  assert.equal(countOf("排队中"), 1 + 1 + 1);
  assert.equal(countOf("工程"), 2);
  assert.equal(countOf("已放行"), 1);
  assert.equal(countOf("开环完成"), 1);
  assert.equal(countOf("已采纳"), 2);
  assert.equal(countOf("已停止"), 1);
  assert.equal(list.total, 10);
});

test("开环完成与放行分在两组，开环完成不写成放行", () => {
  const released = item({ work_item_id: "r1", status: "released_unsettled", stop_reason: "released" });
  const openLoop = item({ work_item_id: "o1", status: "released_unsettled", stop_reason: "open_loop" });
  const list = allItemsList([released, openLoop]);
  const group = (title: string) => list.groups.filter((entry) => entry.title === title)[0];
  assert.deepEqual(group("已放行").cards.map((card) => card.workItemId), ["r1"]);
  assert.deepEqual(group("开环完成").cards.map((card) => card.workItemId), ["o1"]);
  assert.equal(group("已放行").count, 1);
  assert.equal(group("开环完成").count, 1);
  assert.equal(group("开环完成").cards[0].statusText, "开环完成");
  assert.ok(!group("开环完成").cards[0].statusText.includes("放行"));
});

test("同名的已停止事项靠事项标识与停止时间分辨，停止原因照清单的说法写", () => {
  const first = item({
    work_item_id: "w1", title: "修登录", status: "stopped", stop_reason: "time_limit",
    stopped_at: "2026-01-02T03:04:05Z",
  });
  const second = item({
    work_item_id: "w2", title: "修登录", status: "stopped", stop_reason: "provider_error",
    stopped_at: "2026-01-03T03:04:05Z",
  });
  const cards = allItemsList([first, second]).groups.filter((group) => group.title === "已停止")[0].cards;
  assert.equal(cards[0].title, cards[1].title);
  assert.notEqual(cards[0].identity, cards[1].identity);
  assert.equal(cards[0].identity, `事项标识 w1 · 停止于 ${formatTime("2026-01-02T03:04:05Z")}`);
  assert.equal(cards[1].identity, `事项标识 w2 · 停止于 ${formatTime("2026-01-03T03:04:05Z")}`);
  assert.equal(cards[0].stopText, "运行时间已达上限");
  assert.equal(cards[1].stopText, "模型服务失败");
});

test("排队中的按执行顺序排，不按标题重排", () => {
  // 查询按登记顺序给出排队中的事项，这个顺序就是执行顺序；列表照原样写
  const items = [
    item({ work_item_id: "w3", title: "丙", status: "not_started" }),
    item({ work_item_id: "w1", title: "甲", status: "held" }),
    item({ work_item_id: "w2", title: "乙", status: "awaiting_initial_prd" }),
  ];
  const queue = allItemsList(items).groups[0];
  assert.equal(queue.title, "排队中");
  assert.deepEqual(queue.cards.map((card) => card.workItemId), ["w3", "w1", "w2"]);
});

test("只有一个职能的项目，分组里没有别的职能", () => {
  const items = [
    item({ work_item_id: "w1", departments: { engineering: working }, department: "engineering" }),
    item({ work_item_id: "w2", status: "adopted", departments: null, department: "engineering" }),
  ];
  const list = allItemsList(items);
  assert.deepEqual(
    list.groups.map((group) => group.title),
    ["排队中", "工程", "已放行", "开环完成", "已采纳", "已停止"],
  );
  assert.deepEqual(list.groups.filter((group) => group.title === "工程")[0].cards.map((card) => card.workItemId), ["w1"]);
  assert.ok(!list.groups.some((group) => group.title === "产品" || group.title === "质检"));
  assert.ok(!list.groups.some((group) => group.key === "department:product" || group.key === "department:quality"));
});

test("没有事项时总数是零，五组都是零件", () => {
  const list = allItemsList([]);
  assert.equal(list.total, 0);
  assert.deepEqual(list.groups.map((group) => group.title), ["排队中", "已放行", "开环完成", "已采纳", "已停止"]);
  assert.deepEqual(list.groups.map((group) => group.count), [0, 0, 0, 0, 0]);
});
