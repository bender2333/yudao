// 从想法新建时填写起始文件夹的端到端测试（工单 #323 的验收）：Playwright 打开 Chromium 页面，
// 连接真实运行的后端（tests/e2e/backend.py 的 --script initial，FakeAdapter 驱动）。模型回答由
// FakeAdapter 给出，不使用 mock：起始文件夹是真实目录，新建项目时命令真的采集它的代码快照。
//
// 三条验收：
//   1. 填写起始文件夹新建项目，概览写明「起点：起始文件夹（N 个文件）」，N 等于目录里的文件数；
//      开始事项以后部门工作间的动作与回执里能读到起始文件夹里的文件；
//   2. 填写不存在的路径时表单显示 source_invalid 的原因，没有出现新项目；留空时概览没有起点行；
//   3. 1440×900 与 1920×1080 下表单与起点行没有横向滚动。
// 控制台错误为零。

import { expect, test, type Locator, type Page } from "@playwright/test";
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

const GOAL = "以已有文件为起点继续做";

let backend: Backend;

// 启动后端到首行输出的用时由 git 子进程决定：并发负载下可能到 60 至 75 秒（#214）。
// 这个会合点单独放宽，各条测试自己的时限不变（同 onboarding.spec.ts 的处理）。
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend({ script: "initial" });
});

test.afterAll(async () => {
  await backend?.stop();
});

async function openClient(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  return client;
}

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    // 浏览器对非 2xx 响应自己记一条控制台消息，那不是应用的错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

// 等待某个条件成立：界面按事件流自动重查询，这里轮询页面文本，不刷新页面
async function waitUntil(check: () => Promise<boolean>, page: Page, description: string, timeoutMs = 120_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      const text = await page.evaluate(() => document.body.innerText).catch(() => "");
      throw new Error(`等待超时：${description}（当前页面文本：${text.slice(0, 400)}）`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}

async function section(page: Page, heading: string): Promise<Locator> {
  return page.locator("section.card").filter({ has: page.getByRole("heading", { name: heading, exact: true }) }).first();
}

// 从想法新建的表单：侧栏的「从想法新建」按钮展开的表单
async function newProjectForm(page: Page): Promise<Locator> {
  await page.locator(".sidebar .nav-item", { hasText: "从想法新建" }).click();
  const form = page.locator("form.card").filter({ has: page.getByRole("heading", { name: "从想法新建项目" }) });
  await expect(form).toBeVisible();
  return form;
}

async function fillNewProjectForm(form: Locator, name: string, directory: string): Promise<void> {
  await form.getByLabel("项目名称").fill(name);
  await form.getByLabel("长期目标").fill(GOAL);
  await form.getByLabel("起始文件夹（可选）").fill(directory);
}

// 起始文件夹里的文件：工作区相对路径，用「/」连接（list_files 的输出与概览的文件数都按这个口径）
function listedFiles(root: string): string[] {
  const paths: string[] = [];
  for (const entry of readdirSync(root)) {
    const full = join(root, entry);
    if (statSync(full).isDirectory()) {
      paths.push(...listedFiles(full));
    } else {
      paths.push(full.slice(root.length + 1).replaceAll("\\", "/"));
    }
  }
  return paths;
}

type ProjectRow = { name: string; project_id: string };

// 项目列表直接读服务端：界面上的名称可能被前面的用例改过，标识不写死
async function projects(page: Page): Promise<ProjectRow[]> {
  return page.evaluate(
    async (address) => {
      const response = await fetch(`${address}/api/queries/projects.list?include_archived=true`);
      return (await response.json()) as { data?: { projects: ProjectRow[] } };
    },
    backend.address,
  ).then((envelope) => envelope.data?.projects ?? []);
}

async function projectId(page: Page, name: string): Promise<string> {
  const found = (await projects(page)).find((project) => project.name === name);
  if (found === undefined) {
    throw new Error(`projects.list 里没有项目 ${name}（现有：${(await projects(page)).map((p) => p.name).join("、")}）`);
  }
  return found.project_id;
}

async function navigate(page: Page, id: string, view: string): Promise<void> {
  await page.evaluate((hash) => {
    window.location.hash = hash;
  }, `#/p/${id}/${view}`);
  await expect(page.locator(".tabbar .tab").first()).toBeVisible();
}

// 布局验收：文档与页面内每个可见容器都不出现横向溢出（滚动容器允许，溢出到窗口外不允许）
async function overflowReport(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const offenders: string[] = [];
    const root = document.documentElement;
    if (root.scrollWidth - root.clientWidth > 1) {
      offenders.push(`html +${root.scrollWidth - root.clientWidth}`);
    }
    for (const node of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
      // 输入框与下拉框内部滚动画下的文字，不是把内容溢出到窗口外（同 project.spec.ts 的口径）
      if (["INPUT", "SELECT", "TEXTAREA"].includes(node.tagName)) {
        continue;
      }
      const over = node.scrollWidth - node.clientWidth;
      if (over <= 1 || node.offsetParent === null) {
        continue;
      }
      const style = getComputedStyle(node);
      if (style.overflowX === "auto" || style.overflowX === "scroll") {
        continue;
      }
      const classes = typeof node.className === "string" && node.className.trim() !== "" ? `.${node.className.trim().split(/\s+/).join(".")}` : "";
      offenders.push(`${node.tagName.toLowerCase()}${classes} +${over}`);
    }
    return offenders;
  });
}

test.describe("起始文件夹（1440×900）", () => {
  test("填写起始文件夹新建项目，概览写明起点，开始事项以后部门工作间读到起点文件", async () => {
    test.setTimeout(300_000);
    const client = await openClient({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const page = client.page;
    try {
      const source = backend.sourceDir;
      if (source === null) {
        throw new Error("后端没有报出起始文件夹脚本的目录");
      }
      const files = listedFiles(source);
      const name = `起点项目 ${Date.now()}`;
      const form = await newProjectForm(page);
      // 表单的说明照原型 v13（工单 #1160）：起始文件夹是可选项，是一份快照；新建项目不调用模型。
      // 最后一段按工单 #1240 改写：需求材料在项目建好以后到概览里作为新事项开始时提交
      await expect(form).toContainText("起始文件夹（可选）");
      await expect(form).toContainText("填写时，新建项目取这个文件夹的一份快照，作为项目的起点；以后对这个文件夹的修改不影响项目。不填时从空目录开始。");
      await expect(form).toContainText("新建项目不调用模型。需求材料（原文或文件）在项目建好以后，到概览里作为新事项开始时提交。");
      await fillNewProjectForm(form, name, source);
      expect(await overflowReport(page)).toEqual([]);
      await form.getByRole("button", { name: "新建项目" }).click();

      // 新建成功以后停在新项目的概览（工单 #1160）：不用再点侧栏，地址就是这个项目的概览
      const id = await projectId(page, name);
      await waitUntil(async () => (await page.evaluate(() => window.location.hash)) === `#/p/${id}/overview`,
        page, "新建成功以后转到新项目的概览");
      await expect(page.locator(".project-entry").filter({ hasText: name })).toBeVisible();

      // 概览：起点说明写在项目摘要里，文件数与目录里的实际文件数相同
      const summary = await section(page, "项目摘要");
      await expect(summary).toContainText(`起点：起始文件夹（${files.length} 个文件）`);
      expect(await overflowReport(page)).toEqual([]);

      // 开始事项：概览的那一个框提交为新事项
      await page.getByLabel("新的想法或材料").fill("在起始文件夹的基础上继续做");
      await page.getByRole("button", { name: "作为新事项开始" }).click();

      // 部门工作间的动作与回执：产品先列出工作区里的文件、再读起点文件夹里的一个文件，
      // 事件到达以后页面自动显示（页面不刷新）
      await navigate(page, id, "dept/product");
      const actions = page.locator("section.card").filter({ has: page.getByRole("tab", { name: "动作与回执" }) });
      const listRow = actions.locator("tbody tr").filter({ hasText: "list_files" });
      const readRow = actions.locator("tbody tr").filter({ hasText: "read_file" });
      await waitUntil(async () => (await listRow.filter({ hasText: "成功" }).count()) > 0, page,
        "部门工作间出现列出工作区文件的成功动作", 180_000);
      await expect(readRow.filter({ hasText: "成功" })).toBeVisible();

      // 表格里没有「登记名」一列：命令登记按 ADR-0038 删除以后，这一列恒为「没有回执」（工单 #655）
      await expect(actions.locator("thead th").filter({ hasText: "登记名" })).toHaveCount(0);

      // 列出文件的回执里是起始文件夹里的文件：点时间看这条事件的原始载荷
      await listRow.locator("button.link").click();
      const modal = page.locator(".modal-backdrop");
      await expect(modal.locator(".modal-head h2")).toContainText("事件 evt_");
      for (const file of listedFiles(source)) {
        await expect(modal.locator("pre.raw")).toContainText(file);
      }
      await modal.getByRole("button", { name: "关闭" }).click();

      // 读到的内容就是起始文件夹里那个文件的内容
      await readRow.locator("button.link").click();
      await expect(page.locator(".modal-backdrop pre.raw")).toContainText("Print the given argument.");
      await page.locator(".modal-backdrop").getByRole("button", { name: "关闭" }).click();
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  });

test.describe("起始文件夹（1920×1080）", () => {
  });