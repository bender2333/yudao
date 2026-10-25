// 概览页两个输入框各自独立（工单 #652）：「记录原文」与「新的要求」各有各的草稿与状态，
// 写在一个框里的文字不出现在另一个框里，提交一个框只清空那个框。
//
// 页面在渲染进程里真实挂载概览页的新事项输入区（overview.tsx 的 NewItemComposer）：
// 用真实浏览器输入与点击，读回两个框的值与两个按钮的可用状态。
// 组件依赖的查询能力由调用方给出（能力清单在能力读不到时按钮不出现，这里给出的是有的情形）。

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer, type ViteDevServer } from "vite";
import { chromium, type Browser, type Page } from "@playwright/test";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DEPARTMENT_STATE, departmentLine, departmentsText, progressLabel } from "../../src/renderer/src/views/project/labels.ts";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..", "..");

// 页面里运行的驱动：挂载真实的输入区，按场景操作以后读回页面的状态。
// 这段代码经字符串化以后在浏览器里求值，模块只能动态引入。
async function driver(input: { scenario: string }): Promise<Record<string, unknown>> {
  // 驱动的源码会被送进浏览器求值，用到的东西都写在函数内部
  const recordLabel = "记录原文（保存为本项目的材料）";
  const requirementLabel = "新的要求";
  const React = (await import(/* @vite-ignore */ "/@id/react" as string)).default as typeof import("react");
  const ReactDOMClient = (await import(/* @vite-ignore */ "/@id/react-dom/client" as string)).default as typeof import("react-dom/client");
  const { NewItemComposer } = await import(/* @vite-ignore */ "/src/views/project/overview.tsx" as string) as typeof import("../../src/renderer/src/views/project/overview.tsx");

  const calls: { name: string; body: Record<string, unknown> }[] = [];
  const command = {
    busy: false,
    submitted: false,
    problem: null,
    accepted: null,
    submit: async (name: string, body: Record<string, unknown>): Promise<boolean> => {
      calls.push({ name, body });
      return true;
    },
  };
  type ComposerProps = Parameters<typeof NewItemComposer>[0];
  // 起点说明由调用方给出：有起点时新建事项处写「新事项从……开始」，没有时不写（工单 #907）
  let props: ComposerProps = { projectId: "p_overview", command, canRecord: true, canCreate: true };

  let container: HTMLDivElement | null = null;
  let root: ReturnType<typeof ReactDOMClient.createRoot> | null = null;

  const mount = (): void => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = ReactDOMClient.createRoot(container);
    root.render(React.createElement(NewItemComposer, props));
  };
  const unmount = (): void => {
    if (root !== null) root.unmount();
    if (container !== null) container.remove();
    root = null;
    container = null;
  };
  const wait = async (): Promise<void> => {
    await new Promise<void>((resolve) => setTimeout(resolve, 60));
  };
  const area = (label: string): HTMLTextAreaElement | null => {
    if (container === null) return null;
    for (const item of container.querySelectorAll("label")) {
      const title = item.querySelector("span");
      if (title !== null && title.textContent === label) {
        const found = item.querySelector("textarea");
        if (found !== null) return found;
      }
    }
    return null;
  };
  const button = (text: string): HTMLButtonElement | null => {
    if (container === null) return null;
    for (const item of container.querySelectorAll("button")) {
      if (item.textContent.trim() === text) return item;
    }
    return null;
  };
  const type = async (label: string, value: string): Promise<void> => {
    const target = area(label);
    if (target === null) throw new Error(`页面上没有这个输入框：${label}`);
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
    if (setter === undefined) throw new Error("浏览器没有提供输入框的取值写入方法");
    setter.call(target, value);
    target.dispatchEvent(new Event("input", { bubbles: true }));
    await wait();
  };
  // 新建事项处关于起点的那句话；没有这一句时返回空串
  const startNote = (): string => {
    if (container === null) return "";
    for (const item of container.querySelectorAll("p")) {
      const text = item.textContent ?? "";
      if (text.includes("新事项从")) return text;
    }
    return "";
  };
  const click = async (text: string): Promise<void> => {
    const target = button(text);
    if (target === null) throw new Error(`页面上没有这个按钮：${text}`);
    target.click();
    await wait();
  };
  const read = (): Record<string, unknown> => {
    const record = area(recordLabel);
    const requirement = area(requirementLabel);
    const recordButton = button("记录原文");
    const createButton = button("作为新事项开始");
    return {
      record: record === null ? null : record.value,
      requirement: requirement === null ? null : requirement.value,      recordDisabled: recordButton === null ? null : recordButton.disabled,
      createDisabled: createButton === null ? null : createButton.disabled,
    };
  };

  const result: Record<string, unknown> = {};
  window.sessionStorage.clear();
  mount();
  await wait();

  if (input.scenario === "independence") {
    await type(requirementLabel, "写进新要求的文字");
    result.requirementOnly = read();
    // 清掉草稿重新挂载，再单独写「记录原文」
    unmount();
    window.sessionStorage.clear();
    mount();
    await wait();
    await type(recordLabel, "写进记录原文的文字");
    result.recordOnly = read();
  } else if (input.scenario === "disabled") {
    result.initial = read();
    await type(recordLabel, "写进记录原文的文字");
    result.afterRecord = read();
    await type(requirementLabel, "写进新要求的文字");
    result.afterBoth = read();
  } else if (input.scenario === "submit-record") {
    await type(recordLabel, "写进记录原文的文字");
    await type(requirementLabel, "写进新要求的文字");
    await click("记录原文");
    result.afterSubmit = read();
    result.calls = calls;
  } else if (input.scenario === "submit-requirement") {
    await type(recordLabel, "写进记录原文的文字");
    await type(requirementLabel, "写进新要求的文字");
    await click("作为新事项开始");
    result.afterSubmit = read();
    result.calls = calls;
  } else if (input.scenario === "start-point") {
    // 概览给的起点说明以「起点：」开头，新建事项处取它后面的部分
    props = { ...props, startPoint: "起点：起始文件夹（3 个文件）" };
    unmount();
    mount();
    await wait();
    result.startNote = startNote();
  } else if (input.scenario === "no-start-point") {
    result.startNote = startNote();
  } else if (input.scenario === "draft-persist") {
    await type(recordLabel, "写进记录原文的文字");
    await type(requirementLabel, "写进新要求的文字");
    result.before = read();
    // 离开这一页再回来：组件重新挂载，草稿各自还在
    unmount();
    mount();
    await wait();
    result.after = read();
  } else {
    throw new Error(`没有这个场景：${input.scenario}`);
  }

  unmount();
  return result;
}

let server: ViteDevServer | null = null;
let browser: Browser | null = null;
let page: Page | null = null;

before(async () => {
  server = await createServer({
    root: join(clientRoot, "src", "renderer"),
    // 单元测试文件之间是并行运行的：缓存目录与其他测试分开，避免同时改写同一份缓存
    cacheDir: join(clientRoot, "node_modules", ".vite-overview"),
    plugins: [],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
    logLevel: "error",
    appType: "spa",
    optimizeDeps: { include: ["react", "react/jsx-runtime", "react-dom/client", "pixi.js"] },
  });
  await server.listen();
  const address = server.resolvedUrls?.local[0];
  if (!address) throw new Error("渲染进程的模块服务器没有给出地址");
  browser = await chromium.launch(process.env.CHROMIUM_EXE ? { executablePath: process.env.CHROMIUM_EXE } : {});
  page = await browser.newPage();
  await page.route(address + "overview.html", (route) => route.fulfill({
    contentType: "text/html",
    body: "<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>",
  }));
  await page.goto(address + "overview.html");
});

after(async () => {
  await browser?.close();
  await server?.close();
});

// 在页面上跑一个场景，返回页面读回的状态
async function run(scenario: string): Promise<Record<string, unknown>> {
  if (page === null) throw new Error("页面没有打开");
  const outcome = await page.evaluate(async (input: { fnSource: string; scenario: string }) => {
    try {
      const fn = (0, eval)(`(${input.fnSource})`) as (i: { scenario: string }) => Promise<Record<string, unknown>>;
      return { ok: await fn({ scenario: input.scenario }) };
    } catch (e) {
      return { failed: String((e as Error)?.stack ?? e) };
    }
  }, { fnSource: driver.toString(), scenario });
  if ("failed" in outcome) {
    throw new Error(`驱动失败：${String(outcome.failed)}`);
  }
  return outcome.ok;
}

test("两个输入框各有各的状态：一个框里的文字不出现在另一个框里", async () => {
  const report = await run("independence");
  const requirementOnly = report.requirementOnly as Record<string, unknown>;
  assert.equal(requirementOnly.requirement, "写进新要求的文字");
  assert.equal(requirementOnly.record, "", "在「新的要求」里写文字以后，「记录原文」框仍是空的");
  const recordOnly = report.recordOnly as Record<string, unknown>;
  assert.equal(recordOnly.record, "写进记录原文的文字");
  assert.equal(recordOnly.requirement, "", "在「记录原文」里写文字以后，「新的要求」框仍是空的");
});

test("两个按钮各自看自己的框：空的那个按钮保持禁用", async () => {
  const report = await run("disabled");
  const initial = report.initial as Record<string, unknown>;
  assert.equal(initial.recordDisabled, true);
  assert.equal(initial.createDisabled, true);
  const afterRecord = report.afterRecord as Record<string, unknown>;
  assert.equal(afterRecord.recordDisabled, false, "「记录原文」里有字时它的按钮可用");
  assert.equal(afterRecord.createDisabled, true, "「新的要求」还是空的时候它的按钮仍禁用");
  const afterBoth = report.afterBoth as Record<string, unknown>;
  assert.equal(afterBoth.recordDisabled, false);
  assert.equal(afterBoth.createDisabled, false);
});

test("新建事项处写明从项目的起点开始，没有起点信息时不写（工单 #907）", async () => {
  const withPoint = await run("start-point");
  assert.equal(withPoint.startNote, "新事项从起始文件夹（3 个文件）开始");
  const without = await run("no-start-point");
  assert.equal(without.startNote, "", "没有起点信息时新建事项处不写这句话");
});

test("提交「记录原文」只清它自己那个框，「新的要求」里的文字留着", async () => {
  const report = await run("submit-record");
  const afterSubmit = report.afterSubmit as Record<string, unknown>;
  assert.equal(afterSubmit.record, "", "提交成功以后「记录原文」框清空");
  assert.equal(afterSubmit.requirement, "写进新要求的文字", "「新的要求」框里的内容不受影响");
  assert.deepEqual(report.calls, [
    { name: "material.record", body: { project_id: "p_overview", text: "写进记录原文的文字" } },
  ]);
});

test("提交「作为新事项开始」只清它自己那个框，「记录原文」里的文字留着", async () => {
  const report = await run("submit-requirement");
  const afterSubmit = report.afterSubmit as Record<string, unknown>;
  assert.equal(afterSubmit.requirement, "", "提交成功以后「新的要求」框清空");
  assert.equal(afterSubmit.record, "写进记录原文的文字", "「记录原文」框里的内容不受影响");
  assert.deepEqual(report.calls, [
    { name: "work_item.create", body: { project_id: "p_overview", text: "写进新要求的文字" } },
  ]);
});

test("离开这一页再回来：两个框各自保留自己的草稿，互不覆盖", async () => {
  const report = await run("draft-persist");
  const before = report.before as Record<string, unknown>;
  assert.equal(before.record, "写进记录原文的文字");
  assert.equal(before.requirement, "写进新要求的文字");
  const after = report.after as Record<string, unknown>;
  assert.equal(after.record, "写进记录原文的文字", "回到这一页以后「记录原文」保留自己的草稿");
  assert.equal(after.requirement, "写进新要求的文字", "回到这一页以后「新的要求」保留自己的草稿");
});

// ---------------------------------------------------------------------------
// 概览「当前事项」的两行文字（工单 #904）：所在部门一行写三个部门各自的状态与原因，进度行按成果写。
// 两者都是纯函数，期望值写成字面值，不复用实现的公式。

test("所在部门一行写三个部门各自的状态与原因，按产品、工程、质检的顺序", () => {
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

test("没有 departments 时照旧写所在部门，没有部门时写大厅", () => {
  assert.equal(departmentLine(null, "engineering"), "所在部门：工程");
  assert.equal(departmentLine(undefined, null), "所在部门：大厅");
  assert.equal(departmentsText(null), null);
  assert.equal(departmentLine({}, "product"), "所在部门：产品");
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
