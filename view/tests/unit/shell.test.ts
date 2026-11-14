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
      // 门牌（sign）的来源事件在录下的位置 2：画面回调携带元件、位置与事项标识（工单 #1382，R3：壳与画面回调边界）
      const path = shell.openFactLink({ element: "sign", position: 2, workItemId: ids.work_item_id });
      const expected = `/#/p/${ids.project_id}/overview?at=2&w=${ids.work_item_id}`;
      assert.equal(path, expected);
      assert.equal(pagePathFor({ projectId: ids.project_id, workItemId: ids.work_item_id, position: 2 }), expected);
      // 回调携带 position 为 null 时，壳回退读当前楼层状态里的位置
      const fallback = shell.openFactLink({ element: "sign", position: null, workItemId: ids.work_item_id });
      assert.equal(fallback, expected);
      assert.deepEqual(opened, [
        { url: expected, target: "_blank", features: "noopener" },
        { url: expected, target: "_blank", features: "noopener" },
      ]);
      // 只写路径、同一来源：地址以 / 开头，不写来源
      assert.ok(expected.startsWith("/"));
      assert.ok(!expected.includes("://"));
    } finally {
      detach();
      shell.close();
    }
  });
});

test("决定卡片上的页面链接：打开 Yudao 页面的地址", async () => {
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
      assert.deepEqual(opened.map((entry) => entry.url), [
        "/#/sys/models",
        "/#/p/demo/settings?section=departments",
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

// 守 R2 与 R3（工单 #1385）：定义里出现场景声明未登记专属外观的角色标识时，壳顶栏缺口清单写明该角色标识与通用外观，画面照常推进。
test("缺口清单：定义含未声明专属外观的角色 security 时列出该角色标识，切回已声明角色项目后消退", async () => {
  const base = loadFixtures();
  const demo = recordingOf(base, "demo");
  const ref = { position: 5, source: "rule" as const };
  const securityLoop = {
    project_id: "proj_sec",
    work_items: [
      {
        work_item_id: "wi_sec",
        kind: "request",
        sign: "审查鉴权边界",
        color_index: 1,
        status: "in_progress",
        department: "security",
        progress: null,
        round: 1,
        started_at: "2026-11-14T10:00:00+08:00",
        elapsed_sec: 30,
        time_limit_sec: 3600,
        pending_question: null,
        run_id: "run_sec",
        adoption_id: null,
        recovery_state: null,
        version: 1,
        organization: {
          form: "engineering_security",
          routing: "watched_outputs",
          entry: { id: "engineering", label: "工程", ref },
          roles: [
            { id: "engineering", label: "工程", ref },
            { id: "security", label: "安全审校", ref },
          ],
          verifiers: [{ role: "security", verifies: [{ role: "engineering", outcomes: ["completion"] }], ref }],
          completing: null,
          watched: [{ source: "engineering", recipient: "security", outcome: "completion", ref }],
          asks: [{ requester: "security", recipient: "engineering", ref }],
          rejections: [{ verifier: "security", role: "engineering", outcome: "completion", ref }],
        },
      },
    ],
    adoptions: [],
  };
  const customRecording = {
    name: "sec_recording",
    ids: { project_id: "proj_sec", work_item_id: "wi_sec", run_id: "run_sec" },
    queries: [
      {
        name: "projects.list",
        params: {},
        response: {
          position: 20,
          data: {
            projects: [
              {
                project_id: "proj_sec",
                name: "安全审校示例项目",
                goal: "验证通用外观",
                pinned: false,
                archived: false,
                last_activity_at: "2026-11-14T10:01:00+08:00",
                decisions_waiting: 0,
              },
              ...(demo.queries.find((q) => q.name === "projects.list")?.response.data as { projects: unknown[] }).projects,
            ],
          },
        },
      },
      {
        name: "project.loop",
        params: { project_id: "proj_sec" },
        response: { position: 20, data: securityLoop },
      },
      {
        name: "project.loop",
        params: { project_id: "proj_sec", work_item: "wi_sec" },
        response: { position: 20, data: securityLoop },
      },
      {
        name: "decisions.list",
        params: { project_id: "proj_sec", status: ["open"] },
        response: { position: 20, data: { decisions: [] } },
      },
      {
        name: "run.asks",
        params: { run_id: "run_sec" },
        response: { position: 20, data: { asks: [] } },
      },
      {
        name: "department.workspace",
        params: { project_id: "proj_sec", department: "security", work_item: "wi_sec" },
        response: {
          position: 20,
          data: {
            room: {
              department: "security",
              level: "S5",
              status: "working",
              crt: { target: "审查鉴权边界", model: "test-model", protocol: "Responses", status: "进行中", cycle: 1 },
              roles: [{ id: "sec-reviewer", name: "安全审校员", kind: "agent", status: "working", task: null }],
              pose: { role_id: "sec-reviewer", action: "reading" },
              door: null,
              hold_card: null,
              mailbox: 0,
              summaries: 0,
              scrolls: 1,
              pinned_notes: 0,
              semantic_cards: 0,
              machine: null,
              remote_unknown: false,
              waiting_provider: false,
              pipes: { out: "idle", letters_waiting: 0 },
              existing_read: false,
              trial: null,
              tool_panel: null,
              self_test: null,
            },
          },
        },
      },
      ...demo.queries.filter((q) => q.name !== "projects.list"),
    ],
  };
  const fixtures = {
    capabilities: base.capabilities,
    recordings: [...base.recordings, customRecording],
  };
  const server = new FakeServer(fixtures as never, "sec_recording");
  const shell = shellFor(server);
  await shell.open("http://view.test", "");
  try {
    await until(
      () => shell.state.gap.some((line) => line.includes("security") && line.includes("通用外观")),
      "楼场景列出未声明外观角色 security",
    );

    shell.goFloor("proj_sec", "wi_sec");
    const floorSurface = fakeSurface();
    const detachFloor = shell.attachHost(fakeHost, fakeClock, async () => floorSurface);
    await until(() => floorSurface.jumped.length + floorSurface.states.length > 0, "楼层状态送达");
    assert.ok(
      shell.state.gap.some((line) => line.includes("security") && line.includes("安全审校") && line.includes("通用外观")),
      `楼层缺口清单未列出 security：${shell.state.gap.join("\n")}`,
    );
    detachFloor();

    shell.goRoom("security");
    const roomSurface = fakeSurface();
    const detachRoom = shell.attachHost(fakeHost, fakeClock, async () => roomSurface);
    await until(() => roomSurface.jumped.length + roomSurface.states.length > 0, "房间状态送达");
    assert.ok(
      shell.state.gap.some((line) => line.includes("security") && line.includes("通用外观")),
      `房间缺口清单未列出 security：${shell.state.gap.join("\n")}`,
    );
    assert.equal(shell.state.crumbs.at(-1)?.label, "安全审校");
    detachRoom();

    // 切到只有默认已声明角色的项目楼层时，未声明角色外观的缺口行随之消退
    shell.goFloor(demo.ids.project_id, demo.ids.work_item_id);
    const demoSurface = fakeSurface();
    const detachDemo = shell.attachHost(fakeHost, fakeClock, async () => demoSurface);
    await until(() => demoSurface.jumped.length + demoSurface.states.length > 0, "默认项目楼层状态送达");
    assert.equal(
      shell.state.gap.some((line) => line.includes("security")),
      false,
      `切回已声明角色项目后仍残留 security 缺口：${shell.state.gap.join("\n")}`,
    );
    detachDemo();
  } finally {
    shell.close();
  }
});
