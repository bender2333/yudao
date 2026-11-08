// 壳的单元测试（工单 #1573）：画面回调变成现有的命令与页面的地址。
//
// 不启动 Yudao、不连网络：录下的接口响应与能力清单驱动壳；命令由一个记录的替身接住（假的传输层）。
//   - 回答决定：发出 decision.answer，带身份与 command_id；同一个 command_id 重发只生效一次；
//   - 能力清单里没有这条命令时，决定板的选项不可操作，缺口清单写明；
//   - 点开回链：得出页面现有带位置的地址（只写路径、同一来源），在新标签页打开；
//   - 接口版本不一致时写明两边各是第几版，不报错退出。
//
// 守 R1（事实只经接口、命令只由用户操作经壳发出）与 R2（页面地址的写法是合同：参数顺序与页面一致）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { pagePathFor } from "../../src/shell.ts";
import { parseFrame } from "../../src/sync/stream.ts";
import {
  FakeServer, fakeClock, fakeHost, fakeSurface, loadEvents, loadFixtures, recordingOf, shellFor, until,
} from "./session-harness.ts";

/** 一个记录的 window.open：核对新标签页的打开方式与地址。 */
interface Opened {
  url: string;
  target: string;
  features: string | undefined;
}

/** 在测试里临时装一个 window.open（壳的默认打开方式用它）。 */
function withWindowOpen(run: (opened: Opened[]) => Promise<void>): Promise<void> {
  const opened: Opened[] = [];
  const globals = globalThis as { window?: unknown };
  const previous = globals.window;
  globals.window = {
    open: (url: string, target: string, features?: string) => {
      opened.push({ url, target, features });
      return null;
    },
  };
  return run(opened).finally(() => {
    globals.window = previous;
  });
}

test("回答决定：壳发出 decision.answer，带身份与 command_id；同一个 command_id 重发只生效一次", async () => {
  const fixtures = loadFixtures();
  const ids = recordingOf(fixtures, "kernel").ids;
  const server = new FakeServer(fixtures, "kernel");
  let issued = 0;
  const shell = shellFor(server, { newCommandId: () => `cmd-${(issued += 1)}` });
  await shell.open("http://view.test", "token-7");
  shell.goFloor(ids.project_id, ids.work_item_id);
  const surface = fakeSurface();
  const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
  try {
    await until(() => (surface.decisions.at(-1) ?? []).length === 1, "大厅板上的决定卡片");
    const face = (surface.decisions.at(-1) ?? [])[0];
    assert.equal(face.kind, "kernel_modification");
    assert.deepEqual(face.options.map((option) => option.id), ["approve", "reject"]);
    assert.equal(shell.state.decisionsOperable, true);

    const first = await shell.decide({ decision_id: face.id, option: "approve", note: "", base_version: face.version });
    assert.deepEqual(first, { accepted: true, message: "" });
    assert.equal(server.sent.length, 1);
    assert.equal(server.sent[0]?.name, "decision.answer");
    assert.deepEqual(server.sent[0]?.body, {
      command_id: "cmd-1",
      decision_id: face.id,
      option: "approve",
      base_version: face.version,
    });
    // 带身份：命令经这次连接发出，身份是打开画面时给的令牌
    assert.equal(server.sent[0]?.identity, "token-7");
    assert.equal(shell.identity, "token-7");

    // 同一个回答重发（画面重发或连点）：不再发一次，返回第一次的结果
    const second = await shell.decide({ decision_id: face.id, option: "approve", note: "", base_version: face.version });
    assert.deepEqual(second, { accepted: true, message: "" });
    assert.equal(server.sent.length, 1, "同一个 command_id 重发不该再发一条命令");

    // 另一个选项是一次新的操作：新的 command_id
    const other = await shell.decide({ decision_id: face.id, option: "reject", note: "不同意", base_version: face.version });
    assert.deepEqual(other, { accepted: true, message: "" });
    assert.equal(server.sent.length, 2);
    assert.notEqual(server.sent[1]?.body.command_id, "cmd-1");
    assert.equal(server.sent[1]?.body.note, "不同意");
  } finally {
    detach();
    shell.close();
  }
});

test("能力清单里没有回答决定的命令：选项不可操作，缺口清单写明，命令一条也不发", async () => {
  const fixtures = loadFixtures();
  const withoutCommand = {
    ...fixtures.capabilities,
    commands: fixtures.capabilities.commands.filter((command) => command.name !== "decision.answer"),
  };
  const server = new FakeServer(fixtures, "kernel", withoutCommand);
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  try {
    assert.equal(shell.state.decisionsOperable, false);
    assert.ok(shell.state.gap.some((line) => line.includes("没有命令 decision.answer")),
      `缺口清单里没有写缺的命令：${shell.state.gap.join("\n")}`);
    const result = await shell.decide({ decision_id: "dec-1", option: "approve", note: "", base_version: 1 });
    assert.equal(result.accepted, false);
    assert.match(result.message ?? "", /能力清单里没有命令 decision\.answer/);
    assert.equal(server.sent.length, 0, "能力清单里没有的命令不该发出去");
  } finally {
    shell.close();
  }
});

test("点开回链：带上项目、事项与位置，得出页面现有带位置的地址，在新标签页打开（只写路径）", async () => {
  const fixtures = loadFixtures();
  const ids = recordingOf(fixtures, "demo").ids;
  const server = new FakeServer(fixtures, "demo");
  await withWindowOpen(async (opened) => {
    const shell = shellFor(server);
    await shell.open("http://view.test", "");
    shell.goFloor(ids.project_id, ids.work_item_id);
    const surface = fakeSurface();
    const detach = shell.attachHost(fakeHost, fakeClock, async () => surface);
    try {
      await until(() => surface.jumped.length + surface.states.length > 0, "楼层的状态");
      // 门牌（sign）的来源事件在录下的位置 2
      const path = shell.openFactLink(ids.work_item_id, "sign");
      const expected = `/#/p/${ids.project_id}/overview?at=2&w=${ids.work_item_id}`;
      assert.equal(path, expected);
      assert.equal(pagePathFor({ projectId: ids.project_id, workItemId: ids.work_item_id, position: 2 }), expected);
      assert.deepEqual(opened, [{ url: expected, target: "_blank", features: "noopener" }]);
      // 只写路径、同一来源：地址以 / 开头，不写来源
      assert.ok(expected.startsWith("/"));
      assert.ok(!expected.includes("://"));
    } finally {
      detach();
      shell.close();
    }
  });
});

test("决定卡片上的页面链接与「在时间轴上查看」：都打开 Yudao 页面的地址", async () => {
  const fixtures = loadFixtures();
  const ids = recordingOf(fixtures, "demo").ids;
  const server = new FakeServer(fixtures, "demo");
  await withWindowOpen(async (opened) => {
    const shell = shellFor(server);
    await shell.open("http://view.test", "");
    shell.goFloor(ids.project_id, ids.work_item_id);
    try {
      shell.openPageTarget("#/sys/models");
      shell.openPageTarget("#/p/demo/settings?section=departments");
      shell.openTimelineLink(34);
      assert.deepEqual(opened.map((entry) => entry.url), [
        "/#/sys/models",
        "/#/p/demo/settings?section=departments",
        `/#/p/${ids.project_id}/overview?at=34&w=${ids.work_item_id}`,
      ]);
      assert.ok(opened.every((entry) => entry.target === "_blank" && entry.features === "noopener"));
    } finally {
      shell.close();
    }
  });
});

test("接口版本不一致：写明两边各是第几版，画面照常连上，不报错退出", async () => {
  const fixtures = loadFixtures();
  const older = new FakeServer(fixtures, "demo");
  older.versions = { view: 15, server: 14 };
  const olderShell = shellFor(older);
  await olderShell.open("http://view.test", "");
  try {
    assert.equal(olderShell.state.status.kind, "connected");
    assert.match(olderShell.state.versionNote ?? "", /画面第 15 版/);
    assert.match(olderShell.state.versionNote ?? "", /Yudao 第 14 版/);
    assert.match(olderShell.state.versionNote ?? "", /缺画面要用的查询或命令/);
  } finally {
    olderShell.close();
  }

  const newer = new FakeServer(fixtures, "demo");
  newer.versions = { view: 15, server: 16 };
  const newerShell = shellFor(newer);
  await newerShell.open("http://view.test", "");
  try {
    assert.equal(newerShell.state.status.kind, "connected");
    assert.match(newerShell.state.versionNote ?? "", /Yudao 比画面新/);
    assert.match(newerShell.state.versionNote ?? "", /列进缺口清单/);
  } finally {
    newerShell.close();
  }
});

test("场景之间切换不经页面：楼 → 楼层 → 房间只换画面，不打开页面的地址", async () => {
  const fixtures = loadFixtures();
  const ids = recordingOf(fixtures, "demo").ids;
  const server = new FakeServer(fixtures, "demo");
  const opened: string[] = [];
  const shell = shellFor(server, { openPage: (url) => opened.push(url) });
  await shell.open("http://view.test", "");
  try {
    assert.equal(shell.state.scene.kind, "building");
    shell.goFloor(ids.project_id, ids.work_item_id);
    assert.deepEqual(shell.state.scene, { kind: "floor", projectId: ids.project_id, workItemId: ids.work_item_id });
    shell.goRoom("quality");
    assert.deepEqual(shell.state.scene, {
      kind: "room", projectId: ids.project_id, department: "quality", workItemId: ids.work_item_id,
    });
    shell.goBuilding();
    assert.equal(shell.state.scene.kind, "building");
    assert.deepEqual(opened, [], "场景切换不该打开页面");
  } finally {
    shell.close();
  }
});

test("同步层：录下的帧 previous 对不上时报缺口，resync 时重新查询已打开的视图并从快照位置重新订阅", async () => {
  const fixtures = loadFixtures();
  // 用录下的第一帧核对缺口检测：它的 previous 是 0，已收到 5 时就对不上
  const firstFrame = loadEvents("events.sse").split(/\r?\n\r?\n/)[0] ?? "";
  const data = firstFrame.split(/\r?\n/).find((line) => line.startsWith("data:"));
  assert.ok(data, "录下的帧里有 data 行");
  const gap = parseFrame("event", data.slice(5).trim(), 5);
  assert.deepEqual(gap, { kind: "gap", expected: 5, got: 0 });

  const server = new FakeServer(fixtures, "demo");
  server.manual = true;
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  try {
    await until(() => server.handlers !== null, "事件流的回调");
    const surface = fakeSurface();
    shell.attachHost(fakeHost, fakeClock, async () => surface);
    await until(() => surface.jumped.length + surface.states.length > 0, "楼的状态");
    const queriedBefore = server.queried.length;
    const jumpsBefore = surface.jumped.length;
    // 发现缺口：同步层重新读能力清单、重新查询已打开的视图，再从快照位置重新订阅
    server.handlers?.onResync("position gap: expected 5, got 0");
    await until(() => server.streamStarts.length >= 2, "重新订阅事件流");
    assert.equal(server.connectCount, 2, "重新同步时核对一次能力清单");
    assert.ok(server.queried.length > queriedBefore, "重新同步时重新查询已打开的视图");
    await until(() => surface.jumped.length > jumpsBefore, "重新同步以后画面跳到最新的状态");
    // 重新订阅的起点是已打开视图快照位置里最小的那个（楼：项目列表与各项目的楼层，都是 120）
    assert.equal(server.streamStarts[0], 0);
    assert.equal(server.streamStarts.at(-1), 120);
  } finally {
    shell.close();
  }
});

test("同步层：断线重新连上时核对本次启动的身份，服务重启以后重新读能力清单", async () => {
  const fixtures = loadFixtures();
  const server = new FakeServer(fixtures, "demo");
  server.manual = true;
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  try {
    assert.equal(shell.state.decisionsOperable, true);
    // 服务重启：本次启动的身份变了，能力清单也换了（不再列出回答决定的命令）
    const restarted = {
      ...fixtures.capabilities,
      deployment: { ...fixtures.capabilities.deployment, boot_id: "boot-after-restart" },
      commands: fixtures.capabilities.commands.filter((command) => command.name !== "decision.answer"),
    };
    server.setCapabilities(restarted);
    server.handlers?.onConnected({ reconnected: true });
    await until(() => shell.state.decisionsOperable === false, "重新读到能力清单");
    assert.equal(server.connectCount, 2, "重新连上时核对一次本次启动的身份");
    assert.ok(shell.state.gap.some((line) => line.includes("没有命令 decision.answer")),
      `重新读到的能力清单没有写进缺口清单：${shell.state.gap.join("\n")}`);
  } finally {
    shell.close();
  }
});

test("缺口清单：缺的查询各写一行，壳上写出还没画的事件种类数并与缺口清单一致", async () => {
  const fixtures = loadFixtures();
  const capabilities = {
    ...fixtures.capabilities,
    queries: fixtures.capabilities.queries.filter((query) => query.name !== "run.asks"),
    event_types: [...fixtures.capabilities.event_types, "future_event"],
  };
  const server = new FakeServer(fixtures, "demo", capabilities);
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  try {
    assert.ok(shell.state.gap.some((line) => line.includes("没有查询 run.asks")),
      `缺口清单里没有写缺的查询：${shell.state.gap.join("\n")}`);
    // 壳上的数读缺口清单的长度：一种还没画的事件占一行
    assert.equal(shell.state.eventGaps.length, 1);
    assert.deepEqual(shell.state.eventGaps[0], { type: "future_event", scenes: ["floor", "room", "building"] });
    assert.ok(shell.state.gap.includes(`还没画的事件种类 ${shell.state.eventGaps.length} 种`),
      `壳上没有写还没画的事件种类数：${shell.state.gap.join("\n")}`);
    assert.ok(shell.state.gap.some((line) => line.includes("future_event") && line.includes("没有归属")),
      `缺口清单里没有写出还没画的事件：${shell.state.gap.join("\n")}`);
  } finally {
    shell.close();
  }
});
