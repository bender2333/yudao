// 画面端到端与单元测试的夹具录制脚本（工单 #1574）。
//
// 只在人手动更新夹具时运行，不进测试；测试只读录下的文件，不启动 Yudao。
//
// 用法（先跑起来一个 Yudao 服务，例如 `uv run python -m harness demo --data-dir <目录>` 以后
// `uv run python -m harness api --data-dir <目录>`）：
//
//   node view/scripts/record-fixtures.mjs --base-url http://127.0.0.1:8765
//   node view/scripts/record-fixtures.mjs --base-url http://127.0.0.1:8765 --out view/tests/fixtures/session
//
// 录下的东西（与 view/tests/fixtures/session/ 的结构相同）：
//   - capabilities.json：GET /api/capabilities（查询、命令、事件种类与覆盖层）
//   - events.sse：GET /api/events?after=0&live=false 的原始帧（读到一段时间没有新帧为止）
//   - queries.json：两个项目各一组查询应答（name、params、response{position,data}）。
//     名字按项目取：第一个项目记作 demo；有 kernel_modification 决定请求的项目记作 kernel；
//     两个都没有时只记 demo。查询是画面要用的那一组，另外记 run.loops 供覆盖层「循环」的场景用。
//   - e2e/run-loops.json：demo 那次运行的 run.loops（位置与 data 原样）。
//
// 访问令牌放在环境变量 YUDAO_TOKEN 里（本机访问方式不需要），不写进文件。

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const viewRoot = resolve(here, "..");

function argument(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  if (index < 0) return fallback;
  const value = process.argv[index + 1];
  if (value === undefined || value.startsWith("--")) throw new Error(`--${name} 需要一个值`);
  return value;
}

const baseUrl = argument("base-url", process.env.YUDAO_BASE_URL ?? "http://127.0.0.1:8765").replace(/\/$/, "");
const out = resolve(argument("out", join(viewRoot, "tests", "fixtures", "session")));
const eventIdleMs = Number(argument("events-idle-ms", "5000"));
const eventMaxMs = Number(argument("events-max-ms", "120000"));
const token = process.env.YUDAO_TOKEN ?? "";
const headers = token ? { authorization: `Bearer ${token}` } : {};

async function getJson(path) {
  const response = await fetch(`${baseUrl}${path}`, { headers });
  if (!response.ok) throw new Error(`GET ${path} → HTTP ${response.status}`);
  return response.json();
}

async function query(name, params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) for (const item of value) search.append(key, String(item));
    else if (value !== undefined && value !== null) search.append(key, String(value));
  }
  const qs = search.toString();
  return getJson(`/api/queries/${name}${qs ? `?${qs}` : ""}`);
}

/** 读一段事件流：收到过帧以后连续 eventIdleMs 没有新字节就停；总时长不超过 eventMaxMs。 */
async function recordEvents() {
  const controller = new AbortController();
  const response = await fetch(`${baseUrl}/api/events?after=0&live=false`, {
    headers: { ...headers, accept: "text/event-stream" },
    signal: controller.signal,
  });
  if (!response.ok || response.body === null) throw new Error(`GET /api/events → HTTP ${response.status}`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  let chunks = 0;
  const started = Date.now();
  const stop = () => controller.abort();
  try {
    for (;;) {
      let timer = null;
      const timeout = new Promise((resolveTimeout) => {
        timer = setTimeout(() => resolveTimeout("idle"), eventIdleMs);
      });
      const result = await Promise.race([reader.read(), timeout]);
      if (timer !== null) clearTimeout(timer);
      if (result === "idle") {
        if (chunks === 0) throw new Error("事件流没有收到任何帧");
        break;
      }
      if (result.done) break;
      text += decoder.decode(result.value, { stream: true });
      chunks += 1;
      if (Date.now() - started > eventMaxMs) break;
    }
  } finally {
    stop();
    reader.cancel().catch(() => {});
  }
  return text;
}

function hasKernelDecision(decisions) {
  return (decisions.decisions ?? []).some((row) => row.kind === "kernel_modification" && row.status === "open");
}

async function recordProject(project) {
  const projectId = project.project_id;
  const queries = [];
  const add = async (name, params) => {
    const response = await query(name, params);
    queries.push({ name, params, response });
    return response;
  };
  await add("projects.list", {});
  const loop = await add("project.loop", { project_id: projectId });
  await add("decisions.list", { project_id: projectId, status: ["open"] });
  for (const department of ["product", "engineering", "quality"]) {
    await add("department.workspace", { project_id: projectId, department });
  }
  const row = (loop.data.work_items ?? []).find((item) => item.status === "in_progress" || item.status === "awaiting_initial_prd")
    ?? (loop.data.work_items ?? [])[0];
  if (row?.run_id) {
    await add("run.asks", { run_id: row.run_id });
    await add("run.loops", { run_id: row.run_id });
  }
  return queries;
}

async function main() {
  mkdirSync(join(out), { recursive: true });
  mkdirSync(join(out, "..", "e2e"), { recursive: true });

  const capabilities = await getJson("/api/capabilities");
  writeFileSync(join(out, "capabilities.json"), `${JSON.stringify(capabilities, null, 2)}\n`, "utf8");
  console.log(`capabilities.json：api_version=${capabilities.deployment?.api_version}`);

  const events = await recordEvents();
  writeFileSync(join(out, "events.sse"), events, "utf8");
  const frames = events.split(/\n\n/).filter((block) => block.includes("event: event")).length;
  console.log(`events.sse：${frames} 帧`);

  const projects = (await query("projects.list")).data.projects ?? [];
  if (projects.length === 0) throw new Error("projects.list 里没有项目，先跑 demo 或建立一个项目");
  // 先看每个项目的决定请求：有 kernel_modification 的记作 kernel，其余的第一个记作 demo
  const classified = [];
  for (const project of projects) {
    const decisions = await query("decisions.list", { project_id: project.project_id, status: ["open"] });
    classified.push({ project, kernel: hasKernelDecision(decisions.data) });
  }
  const kernel = classified.find((entry) => entry.kernel);
  const demo = classified.find((entry) => !entry.kernel) ?? classified[0];
  const chosen = [];
  if (demo) chosen.push({ project: demo.project, name: "demo" });
  if (kernel && kernel !== demo) chosen.push({ project: kernel.project, name: "kernel" });

  const recordings = [];
  let runLoops = null;
  for (const { project, name } of chosen) {
    const queries = await recordProject(project);
    const ids = queries.find((entry) => entry.name === "project.loop").response.data.work_items?.[0] ?? {};
    recordings.push({
      name,
      ids: { project_id: project.project_id, work_item_id: ids.work_item_id ?? "", run_id: ids.run_id ?? "" },
      queries,
    });
    console.log(`queries.json：${name} ← ${project.name}（${queries.length} 条应答）`);
    if (name === "demo") {
      const loops = queries.find((entry) => entry.name === "run.loops");
      if (loops) runLoops = loops.response;
    }
  }
  if (recordings.length === 0) throw new Error("没有可以录的项目");
  writeFileSync(join(out, "queries.json"), `${JSON.stringify({
    note: `录下的接口响应（工单 #1574）：${new Date().toISOString()} 从 ${baseUrl} 经 HTTP 读取。画面自己的测试只读这一份，不启动 Yudao。`,
    recordings,
  }, null, 2)}\n`, "utf8");

  if (runLoops === null) {
    // 没有 demo 时用第一组的 run.loops（覆盖层「循环」的场景只需要这一条）
    const first = recordings[0];
    const loops = first.queries.find((entry) => entry.name === "run.loops");
    runLoops = loops?.response ?? null;
  }
  if (runLoops !== null) {
    writeFileSync(join(out, "..", "e2e", "run-loops.json"), `${JSON.stringify({
      note: "录下的接口响应（工单 #1574）：harness.demo 跑完一轮以后经 HTTP 读取的 run.loops。覆盖层「循环」的场景用它。",
      response: runLoops,
    }, null, 2)}\n`, "utf8");
    console.log("e2e/run-loops.json：1 条应答");
  }
  console.log(`夹具写到 ${out}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
