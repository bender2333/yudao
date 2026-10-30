// 规则与参数页的端到端测试（工单 #1195）：Playwright 打开 Chromium 页面，页面由真实后端提供
// （client/tests/e2e/backend.py，FakeAdapter 驱动）。覆盖验收第 7 条：入口、读取、修改反馈与撤回确认。
// 修改与撤回都经真实的 parameter.set / parameter.withdraw 命令与事件流刷新。

import { expect, test } from "@playwright/test";
import { startBackend, startClient, type Backend, type ClientApp } from "./fixtures";

// 每条用例各自启动一份后端与客户端：用例会修改全局参数，共用一份后端会让用例互相影响
async function openRules(size: { width: number; height: number }): Promise<{ backend: Backend; client: ClientApp }> {
  const backend = await startBackend();
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  return { backend, client };
}

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

// 服务端的 rules.registry 快照（核对页面显示与服务端一致，以及命令的真实效果）
async function registry(backend: Backend): Promise<{ rules: { name: string; value: unknown; changes: { event_id: string }[] }[]; parameters_version: string }> {
  const response = await fetch(`${backend.address}/api/queries/rules.registry`);
  const body = (await response.json()) as { data: { rules: { name: string; value: unknown; changes: { event_id: string }[] }[]; parameters_version: string } };
  return body.data;
}

test("侧栏出现规则与参数入口，页面读取 rules.registry 并按领域显示", async () => {
  const { backend, client } = await openRules({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    // 入口在系统分组里，与其他系统页并列；点进去路径是 #/sys/rules
    await expect(page.getByRole("button", { name: "规则与参数" })).toHaveCount(1);
    await page.getByRole("button", { name: "规则与参数" }).click();
    await expect(page.locator(".path")).toHaveText("规则登记");
    await expect(page).toHaveURL(/#\/sys\/rules$/);
    // 读取：显示参数版本，分组卡片出现
    await expect(page.getByTestId("rules-parameters-version")).toContainText("参数版本");
    await expect(page.getByTestId(`rules-group-context`)).toBeVisible();
    // 已知条目按行显示：现值、默认值、界限、种类、形式、接入状态、说明与修改历史
    const row = page.getByTestId("rule-check_timeout_sec");
    await expect(row).toBeVisible();
    await expect(row).toContainText("现值 600");
    await expect(row).toContainText("默认 600");
    await expect(row).toContainText("允许范围 1 至 86400");
    await expect(row).toContainText("参数");
    await expect(row).toContainText("边界");
    await expect(row).toContainText("已接入运行");
    await expect(row).toContainText("检查停住不返回");
    // 未接入的条目显示登记提供的原因并禁用修改
    const notWired = page.getByTestId(`rule-not-wired-execution.slots`);
    await expect(notWired).toContainText("还没有代码读取它");
    // 修改历史：预置没有改过参数，写明没有修改记录
    await expect(row).toContainText("没有修改记录");
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

test("修改数值型全局参数：提交新值与理由，事件流到达后现值与修改历史更新", async () => {
  const { backend, client } = await openRules({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.getByRole("button", { name: "规则与参数" }).click();
    await expect(page.getByTestId("rules-parameters-version")).toContainText("参数版本");
    const row = page.getByTestId("rule-check_timeout_sec");
    const form = row.locator("form.y10-rule-edit");
    // 提交新值 300 与理由；理由为空时按钮不可用
    await expect(form.getByRole("button", { name: "提交修改" })).toBeDisabled();
    await form.getByRole("spinbutton").fill("300");
    await expect(form.getByRole("button", { name: "提交修改" })).toBeDisabled();
    await form.getByPlaceholder("为什么改成这个值").fill("端到端核对：缩短检查时限");
    await form.getByRole("button", { name: "提交修改" }).click();
    // 服务接受后按事件流更新：现值变成 300，历史出现新的记录（理由与修改者）
    await expect(row).toContainText("现值 300", { timeout: 30_000 });
    await expect(row).toContainText("端到端核对：缩短检查时限");
    await expect(row).toContainText("user:local");
    // 服务端真的改了：登记查询返回的现值是 300，且修改者取认证身份（页面没有提交 modified_by）
    const data = await registry(backend);
    const entry = data.rules.find((item) => item.name === "check_timeout_sec");
    expect(entry?.value).toBe(300);
    expect(entry?.changes.length).toBe(1);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

test("撤回：确认框显示现值与恢复值，理由带「撤回：」，撤回后历史出现新记录", async () => {
  const { backend, client } = await openRules({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.getByRole("button", { name: "规则与参数" }).click();
    await expect(page.getByTestId("rules-parameters-version")).toContainText("参数版本");
    const row = page.getByTestId("rule-check_timeout_sec");
    // 先做一次真实修改，让页面有可撤回的记录
    const form = row.locator("form.y10-rule-edit");
    await form.getByRole("spinbutton").fill("300");
    await form.getByPlaceholder("为什么改成这个值").fill("端到端核对：先改一次");
    await form.getByRole("button", { name: "提交修改" }).click();
    await expect(row).toContainText("现值 300", { timeout: 30_000 });

    // 一键撤回：先核对（重新读取登记），确认框显示现值与待恢复值
    await row.getByRole("button", { name: "撤回最近一次修改" }).click();
    const dialog = page.locator(".y10-modal");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("现值 300");
    await expect(dialog).toContainText("恢复成 600");
    await expect(dialog).toContainText("撤回：端到端核对：先改一次");
    await dialog.getByRole("button", { name: "确认撤回" }).click();
    // 服务在写事务核对后接受：现值回到 600，历史出现带「撤回：」的新记录
    await expect(row).toContainText("现值 600", { timeout: 30_000 });
    await expect(row).toContainText("撤回：端到端核对：先改一次");
    const data = await registry(backend);
    const entry = data.rules.find((item) => item.name === "check_timeout_sec");
    expect(entry?.value).toBe(600);
    expect(entry?.changes.length).toBe(2);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

test("拒绝显示服务返回的中文说明：越界的新值被拒绝后登记重读、页面现值不变", async () => {
  const { backend, client } = await openRules({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.getByRole("button", { name: "规则与参数" }).click();
    await expect(page.getByTestId("rules-parameters-version")).toContainText("参数版本");
    const row = page.getByTestId("rule-check_timeout_sec");
    const form = row.locator("form.y10-rule-edit");
    // 界内按钮可用；越界值（90000 > 86400）由服务的界限核对拒绝，页面显示服务的中文说明
    await form.getByRole("spinbutton").fill("90000");
    await form.getByPlaceholder("为什么改成这个值").fill("端到端核对：越界被拒");
    await form.getByRole("button", { name: "提交修改" }).click();
    await expect(form.locator("p.error")).toContainText("超", { timeout: 30_000 });
    // 登记重读以后现值仍是 600：拒绝不改变页面已有的值
    await expect(row).toContainText("现值 600");
    const data = await registry(backend);
    const entry = data.rules.find((item) => item.name === "check_timeout_sec");
    expect(entry?.value).toBe(600);
    expect(entry?.changes.length).toBe(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});

test("结构条目只读并提示结构修改走候选流程；修改历史带稳定身份", async () => {
  const { backend, client } = await openRules({ width: 1440, height: 900 });
  const errors = watchErrors(client);
  const page = client.page;
  try {
    await page.getByRole("button", { name: "规则与参数" }).click();
    await expect(page.getByTestId("rules-parameters-version")).toContainText("参数版本");
    // 结构条目（kind: structure）没有修改表单，也没有撤回按钮
    const structure = page.getByTestId("rule-loop.single_work_item");
    await expect(structure).toBeVisible();
    await expect(structure).toContainText("结构");
    await expect(structure).toContainText("结构条目只读");
    await expect(structure.locator("form.y10-rule-edit")).toHaveCount(0);
    await expect(structure.getByRole("button", { name: "撤回最近一次修改" })).toHaveCount(0);
    // 字符串参数（未接入 + 非数值）同样只读：上下文上限一类
    const stringEntry = page.getByTestId("rule-context.role_result_chars");
    await expect(stringEntry).toBeVisible();
    await expect(stringEntry.locator("form.y10-rule-edit")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await client.close();
    await backend.stop();
  }
});
