// 画面同步层的单元测试（工单 #1573）：连接、查询与命令、事件流的重连与视图同步。
//
// 不启动 Yudao、不连网络：能力清单与查询应答用录下的那一份，事件流用录下的 SSE 帧，
// 网络用一个假的 fetch 接住（核对地址、请求头、状态码与重连的间隔）。
//
// 守 R2（接口合同的路径、参数、请求头与拒绝的写法）与 R3（断线重连、缺口与重新同步的行为）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { connect, interfaceFor, queryUrl } from "../../src/sync/connection.ts";
import { EventStream, parseFrame, ReconnectBackoff } from "../../src/sync/stream.ts";
import { ViewSync, resubscribePosition } from "../../src/sync/sync.ts";
import type { StreamHandlers } from "../../src/sync/stream.ts";
import { loadCapabilities, loadEvents, until } from "./session-harness.ts";

const capabilitiesText = JSON.stringify(loadCapabilities());

/** 假 fetch：记录请求，按顺序给出应答。 */
function fakeFetch(responses: (() => Response)[]): { calls: { url: string; init?: RequestInit }[]; fetch: (url: string, init?: RequestInit) => Promise<Response> } {
  const calls: { url: string; init?: RequestInit }[] = [];
  return {
    calls,
    fetch: async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const next = responses.shift();
      if (!next) throw new Error("假 fetch 没有更多应答");
      return next();
    },
  };
}

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json" },
});

test("连接：录下的能力清单给出两边的接口版本；401 是没有令牌，形状不对是连不上", async () => {
  const recorded = JSON.parse(capabilitiesText) as { deployment: { api_version: number } };
  const ok = fakeFetch([() => json(recorded)]);
  const connected = await connect("http://view.test", "token-7", { fetch: ok.fetch });
  assert.equal(connected.state, "connected");
  if (connected.state === "connected") {
    assert.deepEqual(connected.versions, { view: 15, server: recorded.deployment.api_version });
    assert.equal(connected.access.identity, "token-7");
    // 令牌放在请求头里，不出现在地址里
    assert.equal(ok.calls[0]?.url, "http://view.test/api/capabilities");
    assert.equal((ok.calls[0]?.init?.headers as Record<string, string>).Authorization, "Bearer token-7");
  }

  const unauthorized = await connect("http://view.test", "", { fetch: async () => new Response("", { status: 401 }) });
  assert.deepEqual(unauthorized, { state: "unauthorized", address: "http://view.test" });

  const broken = await connect("http://view.test", "", { fetch: async () => json({ no: "deployment" }) });
  assert.equal(broken.state, "failed");
});

test("查询与命令：按接口合同的路径与参数发出，拒绝时给一句能显示的话", async () => {
  const runner = interfaceFor("http://view.test", "token-7", {
    fetch: fakeFetch([
      () => json({ position: 120, data: { ok: true } }),
      () => json({ reason: "stale_base", message: "基准版本过期" }, 409),
    ]).fetch,
  });
  const snapshot = await runner.query("decisions.list", { project_id: "p1", status: ["open", "answered"], at: null });
  assert.deepEqual(snapshot, { position: 120, data: { ok: true } });
  // 参数按合同写法：数组展开成重复的参数，空值不带
  const url = new URL(queryUrl("http://view.test", "decisions.list", { project_id: "p1", status: ["open", "answered"], at: null }));
  assert.equal(url.pathname, "/api/queries/decisions.list");
  assert.deepEqual(url.searchParams.getAll("status"), ["open", "answered"]);
  assert.equal(url.searchParams.has("at"), false);

  const rejected = await runner.command("decision.answer", { command_id: "cmd-1", decision_id: "d1", option: "approve", base_version: 1 });
  assert.deepEqual(rejected, { ok: false, message: "基准版本过期" });
});

test("事件流：录下的帧读成事件与位置；断开以后按 1、2、4……秒重连", async () => {
  const recorded = loadEvents("events.sse");
  // 第一帧单独发给第一次连接，其余留空：核对重连的间隔（收到过帧才把退避清零）
  const firstFrame = `${recorded.split(/\r?\n\r?\n/)[0] ?? ""}\n\n`;
  const before = new ReconnectBackoff();
  assert.equal(before.count, 0);
  assert.equal(before.nextDelayMs(), 1000);
  assert.equal(before.nextDelayMs(), 2000);
  assert.equal(before.nextDelayMs(), 4000);
  before.stoodUp();
  assert.equal(before.nextDelayMs(), 1000);

  const delays: number[] = [];
  const pending: (() => void)[] = [];
  const messages: number[] = [];
  let interrupted = 0;
  let fetches = 0;
  const handlers: StreamHandlers = {
    onConnected: () => undefined,
    onMessage: (message) => {
      if (message.kind === "event") messages.push(message.position);
    },
    onResync: () => undefined,
    onInterrupted: () => {
      interrupted += 1;
    },
  };
  const stream = new EventStream("http://view.test", handlers, "token-7", {
    fetch: async () => {
      fetches += 1;
      if (fetches === 1) {
        return new Response(firstFrame, { status: 200, headers: { "content-type": "text/event-stream" } });
      }
      return new Response(new ReadableStream<Uint8Array>({ start: (controller) => controller.close() }), { status: 200 });
    },
    setTimeout: (fn, ms) => {
      delays.push(ms);
      pending.push(fn);
      return delays.length;
    },
    clearTimeout: () => undefined,
  });
  stream.start(0);
  try {
    await until(() => messages.length === 1 && delays.length === 1, "第一帧与第一次重连");
    assert.deepEqual(messages, [1], "录下的第一帧是位置 1 的事件");
    assert.deepEqual(delays, [1000]);
    assert.equal(interrupted, 1, "断开只报一次");
    pending.shift()?.();
    await until(() => fetches === 2 && delays.length === 2, "第二次重连");
    assert.deepEqual(delays, [1000, 2000], "第二次断线等 2 秒");
    assert.equal(interrupted, 1, "同一次断开不重复报告");
    // 同一段录下的帧按位置逐帧解析：每帧的 previous 与上一帧相接
    const frames = recorded.split(/\r?\n\r?\n/).filter((block) => block.includes("event: event"));
    let position = 0;
    for (const block of frames) {
      const data = block.split(/\r?\n/).find((line) => line.startsWith("data:"));
      assert.ok(data);
      const parsed = parseFrame("event", data.slice(5).trim(), position);
      assert.equal(parsed.kind, "event");
      if (parsed.kind === "event") position = parsed.position;
    }
    assert.equal(position, 120, "录下的窗口读到位置 120");
  } finally {
    stream.stop();
  }
});

test("视图同步：位置不大于快照位置的事件不重查；合并的重新查询由 flush 推进；换视图丢弃迟到的结果", async () => {
  const calls: { name: string; params?: Record<string, unknown> }[] = [];
  const releases: (() => void)[] = [];
  const views = new ViewSync(async <T,>(name: string, params?: Record<string, unknown>) => {
    calls.push({ name, params });
    if (name === "late") {
      // 一个迟到的查询：等测试放行
      await new Promise<void>((resolve) => {
        releases.push(resolve);
      });
    }
    return { position: name === "late" ? 50 : 10, data: { name } as T };
  }, {
    queries: [
      { name: "project.loop", changed_by: ["department_activated"] },
      { name: "late", changed_by: [] },
    ],
  });

  const seen: number[] = [];
  await views.open("floor.loop", { query: "project.loop", params: { project_id: "p1" } }, (_data, position) => seen.push(position));
  assert.deepEqual(seen, [10]);
  // 位置不大于快照位置的事件不作用（快照已经是 10）
  views.applyEvent("department_activated", 10);
  await views.flush();
  assert.equal(calls.length, 1, "位置不大于快照位置的事件不触发重新查询");
  // 位置更大时排入合并队列：flush 推进一次
  views.applyEvent("department_activated", 11);
  views.applyEvent("department_activated", 12);
  await views.flush();
  assert.equal(calls.length, 2, "200 毫秒内的多条事件合并为一次重新查询");
  assert.deepEqual(seen, [10, 10]);

  // 打开第二个视图后立刻关闭：迟到的结果丢弃（不通知、不再查询）
  const opening = views.open("late", { query: "late" }, () => {
    throw new Error("迟到的结果不该交给已经关闭的视图");
  });
  await until(() => releases.length === 1, "迟到的查询开始");
  views.close("late");
  releases.shift()?.();
  await opening;
  assert.deepEqual(views.openViewIds, ["floor.loop"]);

  // 重新订阅的起点：视图位置与事件流位置里更晚的那个
  assert.equal(resubscribePosition(10, 4), 10);
  assert.equal(resubscribePosition(10, 14), 14);
  assert.equal(resubscribePosition(0, 7), 7);
  views.closeAll();
});
