// 端到端装置的预置（工单 #852）：后端起服务以前先预置四个项目，预置的状态是端到端用例的底座。
// 这一条把预置本身钉住：四个项目各自的状态、第三个项目停在等待回答的决定请求上、
// 第四个项目还没有事项，以及执行槽位被占着的时候新建事项被服务端以 busy 拒绝。
//
// 装置以前给三个部门一份按先后排队的脚本：部门同时运行以后（工单 #557）先到的会话会把后面那个项目的
// 轮次取走，第二个项目因此停在等待回答的决定请求上，第三个项目的新建事项被拒，后端提前退出。

import { expect, test } from "@playwright/test";
import { startBackend } from "./fixtures";

const SAMPLE = "示例项目";
const HISTORY = "交付历史";
const BLOCKED = "文本工具";
const LIVE = "实时项目";

test("预置：四个项目，第三个的事项停在等待回答的决定请求上，第四个还没有事项", async () => {
  test.setTimeout(300_000);
  const backend = await startBackend();
  try {
    type ProjectRow = { project_id: string; name: string };
    const projects = await query<{ projects: ProjectRow[] }>(backend.address, "projects.list");
    expect(projects.projects.map((row) => row.name)).toEqual(
      expect.arrayContaining([SAMPLE, HISTORY, BLOCKED, LIVE]));

    // 第一个项目走完一轮三部门：事项已放行并被采纳
    const sample = await query<{ work_items: { title: string; status: string }[] }>(
      backend.address, "project.overview", { project_id: projectOf(projects.projects, SAMPLE) });
    expect(sample.work_items.map((item) => item.status)).toEqual(["adopted"]);

    // 第二个项目走完一轮包含询问与回答、返工、放行的运行
    const history = await query<{ work_items: { status: string }[] }>(
      backend.address, "project.overview", { project_id: projectOf(projects.projects, HISTORY) });
    expect(history.work_items.map((item) => item.status)).toEqual(["adopted"]);

    // 第三个项目的事项停在模型不可用：有一个等待回答的决定请求，事项还在进行中
    const blocked = projectOf(projects.projects, BLOCKED);
    const decisions = await query<{ decisions: { kind: string; status: string }[] }>(
      backend.address, "decisions.list", { status: ["open"] });
    expect(decisions.decisions.length).toBe(1);
    expect(decisions.decisions[0].kind).toBe("model_unavailable");
    const running = await query<{ work_items: { status: string }[] }>(
      backend.address, "project.overview", { project_id: blocked });
    expect(running.work_items.map((item) => item.status)).toEqual(["in_progress"]);

    // 第四个项目只建档，还没有事项：端到端用例在界面上提交需求开始事项
    const live = await query<{ work_items: unknown[] }>(
      backend.address, "project.overview", { project_id: projectOf(projects.projects, LIVE) });
    expect(live.work_items).toEqual([]);

    // 执行槽位被第三个项目占着：在别的项目里新建事项被服务端拒绝，理由是 busy
    const rejected = await post(backend.address, "work_item.create", {
      project_id: projectOf(projects.projects, SAMPLE), text: "槽位被占着的时候新建的事项",
    });
    expect(rejected.status).toBe(409);
    expect(rejected.body.reason).toBe("busy");
  } finally {
    await backend.stop();
  }
});

function projectOf(projects: { project_id: string; name: string }[], name: string): string {
  const row = projects.find((item) => item.name === name);
  if (row === undefined) throw new Error(`projects.list 里没有项目 ${name}`);
  return row.project_id;
}

async function query<T>(address: string, query: string, params: Record<string, unknown> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.append(key, String(value));
  }
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetch(`${address}/api/queries/${query}${suffix}`);
  const envelope = (await response.json()) as { data?: T; reason?: string; message?: string };
  if (envelope.data === undefined) {
    throw new Error(`查询 ${query} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

async function post(address: string, command: string, body: Record<string, unknown>): Promise<{
  status: number; body: { reason?: string; message?: string };
}> {
  const response = await fetch(`${address}/api/commands/${command}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command_id: crypto.randomUUID(), ...body }),
  });
  return { status: response.status, body: (await response.json()) as { reason?: string; message?: string } };
}
