// 项目设置页的「形态」一节（工单 #1403 的验收）：Playwright 打开 Chromium 页面，页面由真实后端提供
// （client/tests/e2e/backend.py --script forms，两份形态在起服务时交给组装处，模型回答由 FakeAdapter 给出）。
//
// 覆盖：现在用哪一份与发布带的每一份（名字、一句说明；没有核验角色的那一份写明以开环完成结束、不经过放行）；
// 换成另一份（选一份、写理由、确认）以后历史多一条，写着原值、新值、理由、时间与谁改的；
// 点「改回这一份」以后项目回到三部门，两条历史都在；当前值已被别处改过时提交被拒绝，页面原样显示拒绝说明，
// 服务端没有因此多写一条改动；改动只对之后新建的事项生效这一句提示在页面上；控制台错误为零。

import { expect, test, type Page } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const PROJECT = "形态项目";
const THREE = "three_departments";
const WITHOUT_VERIFIER = "three_departments_without_verifier";
const OPEN_LOOP_SENTENCE = "没有核验角色，事项以开环完成结束，不经过放行";
const FORM_HINT = "改动只对之后新建的事项生效，正在跑的事项按原来的形态跑完。";
const STALE_MESSAGE = "项目的组织已经被改过，请重新读取以后再选一次";

let backend: Backend;

// 后端（含两份形态的发布）由整个文件共用：三条用例按顺序改同一个项目的形态，后一条接着前一条的状态
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "forms" });
});

test.afterAll(async () => {
  await backend?.stop();
});

// 三条用例按顺序跑：第二条接着第一条的形态，第三条接着第二条
test.describe.configure({ mode: "serial" });

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

type OrganizationView = {
  form: string;
  version: string | null;
  form_in_release: boolean;
  history: { event_id: string; previous_form: string; form: string; reason: string; actor: string }[];
};

// 直接问服务端（不经过页面）：用来核对拒绝以后服务端没有多写一条改动
async function queryServer<T>(name: string, params: Record<string, string> = {}): Promise<T> {
  const search = new URLSearchParams(params);
  const response = await fetch(`${backend.address}/api/queries/${name}?${search.toString()}`);
  const envelope = (await response.json()) as QueryEnvelope<T>;
  if (envelope.data === undefined) {
    throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
  }
  return envelope.data;
}

async function adoptOnServer(projectId: string, form: string, baseVersion: string | null,
                             reason = ""): Promise<void> {
  const response = await fetch(`${backend.address}/api/commands/organization.adopt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      command_id: crypto.randomUUID(), project_id: projectId, form, changes: {}, reason, base_version: baseVersion,
    }),
  });
  if (response.status !== 200) {
    throw new Error(`组织采用被服务端拒绝：HTTP ${response.status} ${await response.text()}`);
  }
}

async function projectId(page: Page): Promise<string> {
  const listed = await queryServer<{ projects: { name: string; project_id: string }[] }>("projects.list");
  const row = listed.projects.find((project) => project.name === PROJECT);
  if (row === undefined) {
    throw new Error(`projects.list 里没有项目 ${PROJECT}（现有：${listed.projects.map((item) => item.name).join("、")}）`);
  }
  return row.project_id;
}

// 打开设置页并等「形态」这一节画出来
async function openSettings(client: ClientApp): Promise<string> {
  const page = client.page;
  const id = await projectId(page);
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `#/p/${id}/settings`);
  await expect(page.locator("#form").getByRole("heading", { name: "形态", exact: true })).toBeVisible();
  return id;
}

// 收集页面的控制台错误；这一节的验收要求控制台错误为零。
// 服务端按设计用 409 拒绝基准版本过期的采用（第三条用例核对的就是那条提示），浏览器会把这次响应记成资源错误
function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    if (message.type() === "error"
        && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test("现在用哪一份、发布带的每一份各叫什么、一句说明，没有核验角色的那份写明开环", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    await openSettings(client);
    const section = page.locator("#form");

    // 现在用的是发布带里的三部门，写明组织版本
    await expect(page.getByTestId("form-current")).toHaveText(new RegExp(`^现在用 ${THREE}（组织版本 sha256:`));
    // 发布带的两份都列出来，各带一句说明（说明由后端按那份定义给出，页面不另写）
    const choices = page.getByTestId("form-choices");
    await expect(choices).toContainText(THREE);
    await expect(choices).toContainText(WITHOUT_VERIFIER);
    await expect(page.getByTestId(`form-choice-${THREE}`)).toContainText("现在用这一份");
    await expect(choices).toContainText("质检核验工程");
    // 没有核验角色的那一份写明：开环完成结束、不经过放行；有核验角色的那一份不写这一句
    await expect(page.getByTestId(`form-open-loop-${WITHOUT_VERIFIER}`)).toHaveText(OPEN_LOOP_SENTENCE);
    await expect(page.getByTestId(`form-open-loop-${THREE}`)).toHaveCount(0);
    // 一句提示：改动只对之后新建的事项生效
    await expect(page.getByTestId("form-hint")).toHaveText(FORM_HINT);
    // 还没有改过：历史是空的
    await expect(page.getByTestId("form-history")).toContainText("还没有改过形态");
    // 换成另一份的候选里没有现在用的这一份
    const options = page.getByTestId("form-select").locator("option");
    await expect(options).toHaveText(["选择一份形态", WITHOUT_VERIFIER]);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("换成另一份并写理由，历史多一条；点改回以后回到三部门，两条历史都在", async () => {
  test.setTimeout(300_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    const id = await openSettings(client);
    const section = page.locator("#form");

    // 换成没有核验角色的那一份：选一份、写理由、确认
    await page.getByTestId("form-select").selectOption(WITHOUT_VERIFIER);
    await section.locator("textarea").fill("先试一轮没有核验角色");
    await section.getByRole("button", { name: "换成这一份" }).click();
    await expect(page.getByTestId("form-current"))
      .toHaveText(new RegExp(`^现在用 ${WITHOUT_VERIFIER}（组织版本 sha256:three-departments-without-verifier）`));

    // 历史多一条：原值 → 新值、理由、时间、谁改的
    const rows = page.getByTestId("form-history").locator("tbody tr");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText(`${THREE} → ${WITHOUT_VERIFIER}`);
    await expect(rows.first()).toContainText("先试一轮没有核验角色");
    await expect(rows.first()).toContainText("你");
    // 时间写在那一行里（页面的写法：月/日 时:分:秒）
    await expect(rows.first().locator("td").nth(2)).toHaveText(/\d{2}\/\d{2}\s+\d{2}:\d{2}:\d{2}/);

    // 改回这一份：等于用原值再改一次，项目回到三部门
    await page.getByTestId("form-history").getByRole("button", { name: "改回这一份" }).first().click();
    await expect(page.getByTestId("form-current")).toHaveText(new RegExp(`^现在用 ${THREE}（组织版本 sha256:`));
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(1)).toContainText(`${WITHOUT_VERIFIER} → ${THREE}`);
    // 改回这一次没有写理由：照实写「没有写理由」
    await expect(rows.nth(1)).toContainText("没有写理由");
    // 已经是现在这一份的那些行不再给「改回这一份」：只剩第二条（它的原值是另一份）
    await expect(page.getByTestId("form-history").getByRole("button", { name: "改回这一份" })).toHaveCount(1);

    // 服务端的两条事件与页面一致
    const saved = await queryServer<OrganizationView>("project.organization", { project_id: id });
    expect(saved.form).toBe(THREE);
    expect(saved.history.map((record) => [record.previous_form, record.form, record.reason])).toEqual([
      [THREE, WITHOUT_VERIFIER, "先试一轮没有核验角色"],
      [WITHOUT_VERIFIER, THREE, ""],
    ]);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});

test("当前值已被别处改过时提交被拒绝，页面原样显示拒绝说明，不悄悄覆盖", async () => {
  test.setTimeout(300_000);
  // 页面第一次读到的 project.organization 冻住：别处改过以后，页面看到的仍是旧的那一份（旧的组织版本）。
  // 页面因此带着过期的当前值提交，走的是真实服务端的 stale_base 拒绝，不是替身
  let frozen: string | null = null;
  const client = await startClient(backend, { width: 1440, height: 900 }, {
    intercept: async (page) => {
      await page.route("**/api/queries/project.organization**", async (route) => {
        if (frozen !== null) {
          await route.fulfill({ status: 200, contentType: "application/json", body: frozen });
          return;
        }
        const response = await route.fetch();
        const body = await response.text();
        if (response.ok()) {
          frozen = body;
        }
        await route.fulfill({ response, body });
      });
    },
  });
  const errors = watchErrors(client);
  try {
    const page = client.page;
    const id = await openSettings(client);
    const section = page.locator("#form");
    // 页面看到的是三部门（第二条用例改回以后的状态）
    await expect(page.getByTestId("form-current")).toHaveText(new RegExp(`^现在用 ${THREE}（`));
    if (frozen === null) {
      throw new Error("页面没有读到 project.organization");
    }
    const seen = (JSON.parse(frozen) as { data: OrganizationView }).data;

    // 别处改过了：项目已经换成没有核验角色的那一份，页面的快照还是旧的那一份
    await adoptOnServer(id, WITHOUT_VERIFIER, seen.version, "别处换成这一份");

    // 页面照它看到的当前值提交：服务端拒绝，页面原样显示拒绝说明
    await page.getByTestId("form-select").selectOption(WITHOUT_VERIFIER);
    await section.locator("textarea").fill("页面这一边也换");
    await section.getByRole("button", { name: "换成这一份" }).click();
    await expect(section.locator("p.error")).toContainText(STALE_MESSAGE);

    // 不悄悄覆盖：服务端没有因此多写一条改动，现在用的仍是别处换的那一份
    const saved = await queryServer<OrganizationView>("project.organization", { project_id: id });
    expect(saved.form).toBe(WITHOUT_VERIFIER);
    expect(saved.history.map((record) => record.form)).toEqual([WITHOUT_VERIFIER, THREE, WITHOUT_VERIFIER]);
    expect(saved.history.every((record) => record.reason !== "页面这一边也换")).toBe(true);

    // 重新读取以后页面按服务端的现状显示：现在用别处换的那一份，三条历史都在
    await page.unroute("**/api/queries/project.organization**");
    await page.reload();
    await expect(page.locator("#form").getByRole("heading", { name: "形态", exact: true })).toBeVisible();
    await expect(page.getByTestId("form-current")).toHaveText(new RegExp(`^现在用 ${WITHOUT_VERIFIER}（`));
    await expect(page.getByTestId("form-history").locator("tbody tr")).toHaveCount(3);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
