// 七种元件对照表与四份清单的单元测试（画面与播放 docs/design/visualization.md「七种元件与对照表」「视觉通道表」「画面诚实性的不变式」，工单 #1380）。
//
// 守 docs/design/test-pyramid.md「测试按三环留」的 R2（只能向后兼容的画面合同事实元素、七种元件与承载事实的视觉通道表）
// 与 R3（路线图第 4 节步 1「跟着定义伸缩」：对照表与接口事件种类、能力清单覆盖层及壳顶栏缺口清单的一致核对）。

import { test } from "node:test";
import assert from "node:assert/strict";

import { FACT_ELEMENTS } from "../../src/pixel/contract.ts";
import {
  ELEMENT_KINDS,
  FACT_ELEMENTS_LIST_NAME,
  MAPPING_TABLE,
  VISUAL_CHANNELS,
  VISUAL_CHANNEL_IDS,
  VISUAL_CHANNELS_LIST_NAME,
  verifyMapping,
  type ElementKind,
  type MappingRow,
} from "../../src/translate/mapping.ts";
import { eventTypesFromInterface } from "./interface-description.ts";
import { FakeServer, loadFixtures, shellFor } from "./session-harness.ts";

/** 接口描述里的事件种类清单。 */
const EVENT_TYPES = eventTypesFromInterface();

/** 录制的能力清单里的覆盖层名称清单。 */
const FIXTURES = loadFixtures();
const CAPABILITY_OVERLAYS = (FIXTURES.capabilities.overlays ?? []).map((overlay) => overlay.name);

// 守 R2 与 R3：当前四份清单核对通过，单元测试输出写出缺口清单，并与壳（view/src/shell.ts）顶栏的缺口口径一致。
test("七种元件对照表：当前四份清单核对通过，写出缺口清单，并与壳的顶栏缺口口径一致", async (t) => {
  assert.ok(EVENT_TYPES.length > 0, "接口描述里缺少事件种类");
  assert.ok(CAPABILITY_OVERLAYS.length > 0, "能力清单夹具里缺少覆盖层");

  const report = verifyMapping({
    eventTypes: EVENT_TYPES,
    overlays: CAPABILITY_OVERLAYS,
  });
  t.diagnostic(
    report.gapLines.length === 0
      ? "对照表缺口清单：无"
      : `对照表缺口清单（${report.gapLines.length} 行）：\n${report.gapLines.join("\n")}`,
  );

  // 行名采用 CONTEXT.md 的领域词汇（例如「职能」），不使用已废弃的旧称「部门」作为概念行名
  const concepts = MAPPING_TABLE.map((entry) => entry.concept);
  assert.ok(concepts.includes("职能"), "对照表缺少「职能」概念行");
  assert.ok(!concepts.some((name) => name.includes("部门")), `对照表行名出现了旧词「部门」：${concepts.join("、")}`);

  // 核对壳（shell.ts 的 gapText）在相同能力清单下显示的事件与覆盖层缺口与对照表口径一致
  const defaultReport = verifyMapping({
    eventTypes: FIXTURES.capabilities.event_types,
    overlays: CAPABILITY_OVERLAYS,
  });
  const server = new FakeServer(FIXTURES, "demo");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  try {
    assert.deepEqual(shell.state.eventGaps, defaultReport.eventGaps);
    assert.deepEqual(shell.state.gap, defaultReport.gapLines);
  } finally {
    shell.close();
  }

  // 同时存在未归属事件与未登记覆盖层时，壳的缺口条目与对照表输出逐行一致（壳在事件缺口前多一行种类总数标题）
  const extendedCaps = {
    ...FIXTURES.capabilities,
    event_types: [...FIXTURES.capabilities.event_types, "future_unmapped_event"],
    overlays: [...(FIXTURES.capabilities.overlays ?? []), { name: "future_overlay", queries: ["project.loop"] }],
  };
  const extendedReport = verifyMapping({
    eventTypes: extendedCaps.event_types,
    overlays: extendedCaps.overlays.map((overlay) => overlay.name),
  });
  const extServer = new FakeServer(FIXTURES, "demo", extendedCaps);
  const extShell = shellFor(extServer);
  await extShell.open("http://view.test", "");
  try {
    assert.deepEqual(extShell.state.eventGaps, extendedReport.eventGaps);
    assert.deepEqual(extShell.state.gap, [
      `还没画的事件种类 ${extendedReport.eventGaps.length} 种`,
      ...extendedReport.gapLines,
    ]);
  } finally {
    extShell.close();
  }
});

// 守 R2：画面合同事实元素与承载事实的视觉通道是画面自有的向后兼容清单，缺一行立即报错并写明清单名与缺项。
test("事实元素或视觉通道清单多出一项或少一行：核对失败并写明是哪一份清单、缺哪一项", () => {
  const missingFact = "test_extra_fact_element";
  assert.throws(
    () => verifyMapping({
      eventTypes: EVENT_TYPES,
      overlays: CAPABILITY_OVERLAYS,
      factElements: [...FACT_ELEMENTS, missingFact],
    }),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.ok(
        error.message.includes(FACT_ELEMENTS_LIST_NAME),
        `错误提示未写明事实元素清单名：${error.message}`,
      );
      assert.ok(
        error.message.includes(missingFact),
        `错误提示未写明缺少的事实元素项：${error.message}`,
      );
      return true;
    },
  );

  const missingChannel = "floor.test_extra_visual_channel";
  assert.throws(
    () => verifyMapping({
      eventTypes: EVENT_TYPES,
      overlays: CAPABILITY_OVERLAYS,
      visualChannels: [...VISUAL_CHANNEL_IDS, missingChannel],
    }),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.ok(
        error.message.includes(VISUAL_CHANNELS_LIST_NAME),
        `错误提示未写明视觉通道清单名：${error.message}`,
      );
      assert.ok(
        error.message.includes(missingChannel),
        `错误提示未写明缺少的视觉通道项：${error.message}`,
      );
      return true;
    },
  );

  // 反向核对：从对照表里移走覆盖现有事实元素「stamp」或视觉通道「room.stream」的行，同样报出清单名与缺项
  const withoutStamp = MAPPING_TABLE.filter((entry) => !(entry.factElements ?? []).includes("stamp"));
  assert.throws(
    () => verifyMapping({ rows: withoutStamp }),
    (error: unknown) => error instanceof Error
      && error.message.includes(FACT_ELEMENTS_LIST_NAME)
      && error.message.includes("stamp"),
  );

  const withoutRoomStream = MAPPING_TABLE.filter((entry) => !(entry.visualChannels ?? []).includes("room.stream"));
  assert.throws(
    () => verifyMapping({ rows: withoutRoomStream, visualChannels: VISUAL_CHANNELS }),
    (error: unknown) => error instanceof Error
      && error.message.includes(VISUAL_CHANNELS_LIST_NAME)
      && error.message.includes("room.stream"),
  );
});

// 守 R2 与 R3：Yudao 服务新增事件种类或覆盖层时，画面照常通过单元测试，缺口清单各多一行并在测试输出写出。
test("往事件种类或覆盖层清单各多加一项：单元测试照常通过，缺口清单多一行并写出", (t) => {
  const before = verifyMapping({
    eventTypes: EVENT_TYPES,
    overlays: CAPABILITY_OVERLAYS,
  });

  const extraEvent = "test_only_future_event";
  const afterEvent = verifyMapping({
    eventTypes: [...EVENT_TYPES, extraEvent],
    overlays: CAPABILITY_OVERLAYS,
  });
  assert.equal(afterEvent.eventGaps.length, before.eventGaps.length + 1, "事件缺口数没有多一项");
  assert.equal(afterEvent.gapLines.length, before.gapLines.length + 1, "缺口清单行数没有多一行");
  const eventLine = afterEvent.gapLines.find((line) => line.includes(extraEvent));
  assert.ok(eventLine !== undefined, `缺口清单未写出新增事件：${afterEvent.gapLines.join("\n")}`);
  t.diagnostic(`新增事件后的缺口清单：\n${afterEvent.gapLines.join("\n")}`);

  const extraOverlay = "test_only_future_overlay";
  const afterOverlay = verifyMapping({
    eventTypes: EVENT_TYPES,
    overlays: [...CAPABILITY_OVERLAYS, extraOverlay],
  });
  assert.equal(afterOverlay.overlayGaps.length, before.overlayGaps.length + 1, "覆盖层缺口数没有多一项");
  assert.equal(afterOverlay.gapLines.length, before.gapLines.length + 1, "缺口清单行数没有多一行");
  const overlayLine = afterOverlay.gapLines.find((line) => line.includes(extraOverlay));
  assert.ok(overlayLine !== undefined, `缺口清单未写出新增覆盖层：${afterOverlay.gapLines.join("\n")}`);
  t.diagnostic(`新增覆盖层后的缺口清单：\n${afterOverlay.gapLines.join("\n")}`);
});

// 守 R2：每一行的元件取值只能是七种之一（地点、物、连接、流、规则、操作、仪表），纯装饰概念不进表。
test("元件种类约束：每一行只能取七种元件之一，纯装饰概念不进对照表", () => {
  assert.deepEqual(ELEMENT_KINDS, ["地点", "物", "连接", "流", "规则", "操作", "仪表"]);

  const seenKinds = new Set<ElementKind>();
  for (const entry of MAPPING_TABLE) {
    assert.ok(
      ELEMENT_KINDS.includes(entry.element),
      `行「${entry.concept}」的元件取值「${String(entry.element)}」不在七种元件之内`,
    );
    seenKinds.add(entry.element);
  }
  // 七种元件在对照表里全部有实际概念归入
  for (const kind of ELEMENT_KINDS) {
    assert.ok(seenKinds.has(kind), `七种元件里的「${kind}」在对照表里没有任何一行`);
  }

  // 设计说明「视觉通道表」列出的表演层纯装饰概念不进入对照表
  const decorativeConcepts = [
    "小人的走位与路径",
    "走位",
    "待机活动",
    "喝茶",
    "闲逛",
    "眨眼",
    "目光",
    "动画相位",
    "说话气泡",
    "飞行物",
  ];
  const rowNames = new Set(MAPPING_TABLE.map((entry) => entry.concept));
  for (const decoration of decorativeConcepts) {
    assert.ok(!rowNames.has(decoration), `纯装饰概念「${decoration}」进入了对照表`);
  }

  // 反向核对：混入非七种元件的装饰行时核对立即抛出错误
  const invalidRow: MappingRow = {
    concept: "待机喝茶",
    element: "装饰" as ElementKind,
    source: "表演层时钟",
    stateAndChange: "空闲时随机喝茶",
    spaceAndScene: "空间：楼；场景：房间",
    operation: "无",
    meter: "无",
    unpainted: "无",
  };
  assert.throws(
    () => verifyMapping({ rows: [...MAPPING_TABLE, invalidRow] }),
    (error: unknown) => error instanceof Error
      && error.message.includes("待机喝茶")
      && error.message.includes("七种元件"),
  );
});
