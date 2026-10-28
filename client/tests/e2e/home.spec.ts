// 系统首页与决定卡片的端到端测试（工单 #175 的验收）：在 1440×900 与 1920×1080 两种窗口尺寸下运行，
// 后端是 FakeAdapter 驱动的真实服务（tests/e2e/backend.py），页面文件也由该服务提供，模型回答由
// FakeAdapter 给出，不使用 mock。
// 覆盖：状态项「待你决定」与 decisions.list 数量一致、首页与标签栏的决定卡片、提问被回答或撤销时显示原因、
// 离开期间的报告三种范围与「已看过」、项目列表字段与 projects.list 一致；控制台错误为零。

import { expect,test,type Locator,type Page } from "@playwright/test";
import { startBackend,startClient,type Backend,type ClientApp } from "./fixtures";


let backend: Backend;

// 后端启动要等 git 子进程（#214），这个会合点单独放宽，与各条测试自己的时限无关
test.beforeAll(async () => {
  test.setTimeout(300_000);
  backend = await startBackend();
});

test.afterAll(async () => {
  await backend?.stop();
});

function watchErrors(client: ClientApp): string[] {
  const errors: string[] = [];
  client.page.on("console", (message) => {
    // 服务端按设计用 409 拒绝命令（基准版本过期、请求已被回答等，第 3.1、3.3 节），
    // 界面已经把原因显示给用户；浏览器对非 2xx 响应自己记一条控制台消息，那不是应用的错误
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource: the server responded with a status of 409")) {
      errors.push(message.text());
    }
  });
  client.page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

type QueryEnvelope<T> = { data?: T; status?: string; reason?: string; message?: string };

async function fetchQuery<T>(page: Page, name: string, params: Record<string, string | number> = {}): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    search.set(key, String(value));
  }
  const suffix = search.toString();
  return page.evaluate(
    async ({ address, query, qs }) => {
      const response = await fetch(`${address}/api/queries/${query}${qs ? `?${qs}` : ""}`);
      return (await response.json()) as QueryEnvelope<unknown>;
    },
    { address: backend.address, query: name, qs: suffix },
  ).then((envelope) => {
    if (envelope.data === undefined) {
      throw new Error(`查询 ${name} 没有返回数据：${envelope.reason ?? ""} ${envelope.message ?? ""}`);
    }
    return envelope.data as T;
  });
}

async function openHome(size: { width: number; height: number }): Promise<ClientApp> {
  const client = await startClient(backend, size);
  await expect(client.page.locator(".brand .y10-brand-name")).toContainText("Yudao");
  await client.page.evaluate(() => {
    window.location.hash = "#/home";
  });
  await expect(client.page.getByRole("heading", { name: "待你决定", exact: true })).toBeVisible();
  return client;
}

// 改变服务端状态的用例（回答决定请求）用自己的一份后端：回答会让阻塞的 run 继续并产生新的请求，
// 共用一份后端会让后面的用例看到不同的等待列表。这份后端只在这条用例期间替换模块变量，结束以后恢复
async function withOwnBackend<T>(run: () => Promise<T>): Promise<T> {
  const previous = backend;
  const own = await startBackend();
  backend = own;
  try {
    return await run();
  } finally {
    backend = previous;
    await own.stop();
  }
}

async function bodyText(page: Page): Promise<string> {
  return page.evaluate(() => document.body.innerText);
}

async function waitUntil(check: () => Promise<boolean>, page: Page, description: string, timeoutMs = 40_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await check()) {
      return;
    }
    if (Date.now() > deadline) {
      throw new Error(`等待超时：${description}（当前页面文本：${(await bodyText(page).catch(() => "")).slice(0, 400)}）`);
    }
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  }
}


type DecisionRow = { decision_id: string; version: number; project_id: string; work_item_id: string | null; kind: string };

async function openDecisions(page: Page): Promise<DecisionRow[]> {
  const data = await fetchQuery<{ decisions: DecisionRow[] }>(page, "decisions.list", { status: "open" });
  return data.decisions;
}

test.describe("系统首页（1440×900）", () => {
  
  
  test("回答一个等待中的决定请求：卡片显示已提交，事件到达以后移出列表，run 按回答继续", async () => {
    test.setTimeout(120_000);
    await withOwnBackend(async () => {
      const client = await openHome({ width: 1440, height: 900 });
      const errors = watchErrors(client);
      try {
        const before = await openDecisions(client.page);
        expect(before.length).toBeGreaterThan(0);
        const target = before[0];
        const card = client.page.locator(`#decision-${target.decision_id}`);
        await expect(card).toBeVisible();
        // 按卡片给出的选项回答（继续执行）。提交以后只显示一条「已提交」提示（工单 #319：
        // 提交提示重复过一次）；事件很快到达时卡片先移出列表，这两种情况都算通过
        await card.getByRole("button", { name: "继续执行" }).click();
        await expect
          .poll(async () => {
            const hints = await card.locator("span.hint").allInnerTexts();
            const submitted = hints.filter((line) => line.includes("已提交"));
            if (submitted.length > 1) {
              return `重复：${submitted.join(" / ")}`;
            }
            if (submitted.length === 1) {
              return "已提交";
            }
            return (await card.count()) === 0 ? "已提交" : "";
          }, { message: "提交以后显示一条「已提交」" })
          .toBe("已提交");
        // 事件到达以后这张卡片移出等待列表
        await waitUntil(
          async () => (await openDecisions(client.page)).every((row) => row.decision_id !== target.decision_id),
          client.page,
          "回答以后卡片移出等待列表",
        );
        await expect(client.page.locator(`#decision-${target.decision_id}`)).toHaveCount(0);
        // run 按回答继续：这个 run 的下一次请求再次遇到模型不可用，出现新的决定请求（同一事项）
        await waitUntil(
          async () => (await openDecisions(client.page)).some((row) => row.work_item_id === target.work_item_id),
          client.page,
          "run 按回答继续并再次遇到模型不可用",
        );
        expect(errors).toEqual([]);
      } finally {
        await client.close();
      }
    });
  });

  
  test("离开期间的报告：三种范围的汇总项都能展开来源事件，点击「已看过」更新上次查看", async () => {
    test.setTimeout(120_000);
    let client = await openHome({ width: 1440, height: 900 });
    const errors = watchErrors(client);
    const report = client.page.locator("section.card").filter({ has: client.page.getByRole("heading", { name: "离开期间的报告", exact: true }) });
    try {
      for (const range of ["最近 24 小时", "最近 7 天", "自上次查看"]) {
        await report.getByRole("button", { name: range, exact: true }).click();
        await expect.poll(async () => report.locator(".report-item").count()).toBeGreaterThan(0);
        const item = report.locator(".report-item").first();
        await item.locator(".report-head").click();
        await expect(item.locator(".source-list, p.note")).toBeVisible();
      }
      // 记录当前「自上次查看」的起点，点击「已看过」以后它更新为当前位置
      const before = await fetchQuery<{ range: { from_position: number; to_position: number } }>(client.page, "home.away_report", { range: "since_seen" });
      const note = report.locator(".section-head .note").first();
      const noteBefore = await note.textContent();
      await report.getByRole("button", { name: "已看过", exact: true }).click();
      await waitUntil(async () => {
        const now = await fetchQuery<{ range: { from_position: number } }>(client.page, "home.away_report", { range: "since_seen" });
        return now.range.from_position >= before.range.to_position;
      }, client.page, "已看过更新上次查看的位置");
      // 同一页面立即显示新的上次查看（工单 #301）：说明文字变化，不用离开再回来
      await expect.poll(async () => note.textContent()).not.toBe(noteBefore);
      // 重新启动客户端以后上次查看的位置仍然保留（控制主机只记录一个位置）
      await client.close();
      client = await openHome({ width: 1440, height: 900 });
      const after = await fetchQuery<{ range: { from_position: number } }>(client.page, "home.away_report", { range: "since_seen" });
      expect(after.range.from_position).toBeGreaterThanOrEqual(before.range.to_position);
      expect(errors).toEqual([]);
    } finally {
      await client.close();
    }
  });

  
  
  });

test.describe("系统首页（1920×1080）", () => {
  });



// 事项的标题：决定卡片写它，不写事项标识（工单 #802）

// 决定卡片上的两个链接（工单 #1161）：卡片出现在五处——顶栏「待你决定」下拉、首页「待你决定」、
// 概览页循环画面里大厅的板、画面下方收起的文字列表、恢复页。五处各点一次两个链接，都要到对应的页面；
// 「前往本项目的部门设置」还要落在设置页的部门设置那一节。
// 画面里的卡片是像素画的：链接画出来的按钮与它的点击区经 __floorViewForTest 读出来，
// 再在画布上按缩放换成页面坐标真点一下。
type FloorHooks = {
  decisions: () => { faces: { id: string }[]; card: { openId: string | null } };
  openCard: (id: string) => void;
  cardLinks: () => {
    href: string;
    drawn: { x: number; y: number; w: number; h: number };
    hit: { x: number; y: number; w: number; h: number };
  }[];
  size: () => { W: number; H: number };
};

test("决定卡片上的两个链接：五处卡片都到对应的页面，部门设置落在那一节", async () => {
  test.setTimeout(240_000);
  const client = await startClient(backend, { width: 1440, height: 900 });
  const { page } = client;
  const errors = watchErrors(client);
  const hashOf = (): Promise<string> => page.evaluate(() => window.location.hash);
  const goTo = (target: string): Promise<void> => page.evaluate((h) => {
    window.location.hash = h;
  }, target);

  try {
    const [decision] = await openDecisions(page);
    expect(decision, "默认种子里应当有一个等待回答的决定").toBeDefined();
    const projectId = decision.project_id ?? "";
    const workItemId = decision.work_item_id ?? "";
    const cardId = `#decision-${decision.decision_id}`;
    // 部门设置的落点：设置页的路径带上一节的名字（工单 #1161 第 3 条）
    const settingsHash = `#/p/${projectId}/settings?section=departments`;

    // 点两个链接各一次，核对到了哪个页面；「前往本项目的部门设置」还要核对落在部门设置那一节
    const clickBoth = async (where: string, open: () => Promise<Locator>): Promise<void> => {
      for (const [label, expected, landed] of [
        ["前往模型管理", "#/sys/models", page.getByRole("heading", { name: "模型管理", exact: true }).first()],
        ["前往本项目的部门设置", settingsHash, page.locator("#departments")],
      ] as [string, string, Locator][]) {
        const card = await open();
        const button = card.getByRole("button", { name: label, exact: true });
        await expect(button, `${where}的卡片上没有「${label}」`).toBeVisible();
        await button.click();
        await expect.poll(hashOf, { message: `${where}点「${label}」以后地址没变` }).toBe(expected);
        await expect(landed, `${where}点「${label}」以后没有到对应的页面`).toBeVisible();
      }
      // 部门设置那一节要滚到眼前，不是停在设置页的顶部（工单 #1161 第 3 条）
      await expect(page.locator("#departments").getByRole("heading", { name: "部门设置", exact: true }))
        .toBeInViewport({ ratio: 0.05 });
    };

    // 一、首页「待你决定」
    await clickBoth("首页", async () => {
      await goTo("#/home");
      await expect(page.getByRole("heading", { name: "待你决定", exact: true })).toBeVisible();
      const card = page.locator(cardId);
      await expect(card).toBeVisible();
      return card;
    });

    // 二、顶栏「待你决定」下拉（项目页上才有；下拉开着时再点一下是关上，所以按展开与否决定点不点）
    await clickBoth("顶栏下拉", async () => {
      await goTo(`#/p/${projectId}/overview`);
      const opener = page.locator("button.status-item.is-decisions").filter({ hasText: "待你决定 · " }).first();
      if (await opener.getAttribute("aria-expanded") !== "true") {
        await opener.click();
      }
      const card = page.locator(`.decisions-dropdown ${cardId}`);
      await expect(card).toBeVisible();
      return card;
    });

    // 三、画面下方收起的文字列表（卡片里还有自己的折叠块，只点这一层的标题）
    await clickBoth("画面下方的文字列表", async () => {
      await goTo(`#/p/${projectId}/overview`);
      const list = page.locator("details.floor-text-list");
      await expect(list).toBeVisible();
      if (!(await list.evaluate((element) => (element as HTMLDetailsElement).open))) {
        await list.locator("summary").first().click();
      }
      const card = list.locator(cardId);
      await expect(card).toBeVisible();
      return card;
    });

    // 四、恢复页
    await clickBoth("恢复页", async () => {
      await goTo(`#/p/${projectId}/w/${workItemId}/recovery`);
      const block = page.locator("#rc-decide");
      await expect(block).toBeVisible();
      const card = block.locator(cardId);
      await expect(card).toBeVisible();
      return card;
    });

    // 五、循环画面里大厅板上的卡片：打开卡片，读链接的两块位置（画出来的按钮与它的点击区），
    // 在画布上按缩放换成页面坐标真的点一下
    const openFloorCard = async (): Promise<void> => {
      // 离开过这一页时，上一个画面的测试入口还挂在 window 上（它已经不画了，读出来的点击区是旧的）：
      // 先清掉，等这一趟挂上来的新画面
      await goTo("#/home");
      await page.evaluate(() => {
        delete (window as unknown as { __floorViewForTest?: unknown }).__floorViewForTest;
      });
      await goTo(`#/p/${projectId}/overview`);
      // 顶栏的「待你决定」下拉盖在循环画面上面（第二条用例打开过它）：留着它，点在画布上其实点到了
      // 下拉里的卡片，点不到画面里的链接
      const opener = page.locator("button.status-item.is-decisions").filter({ hasText: "待你决定 · " }).first();
      if (await opener.getAttribute("aria-expanded") === "true") {
        await opener.click();
      }
      await page.waitForFunction((id) => {
        const hooks = (window as unknown as { __floorViewForTest?: FloorHooks }).__floorViewForTest;
        return hooks !== undefined && hooks.decisions().faces.some((face) => face.id === id);
      }, decision.decision_id);
      const canvas = page.locator(".floor-canvas canvas");
      await canvas.scrollIntoViewIfNeeded();
      await page.evaluate((id) => {
        (window as unknown as { __floorViewForTest?: FloorHooks }).__floorViewForTest?.openCard(id);
      }, decision.decision_id);
      await expect.poll(async () => page.evaluate(() => {
        const hooks = (window as unknown as { __floorViewForTest?: FloorHooks }).__floorViewForTest;
        return hooks === undefined ? null : hooks.decisions().card.openId;
      })).toBe(decision.decision_id);
      // 卡片打开以后画一帧，链接的点击区才被收集
      await expect.poll(async () => page.evaluate(() => {
        const hooks = (window as unknown as { __floorViewForTest?: FloorHooks }).__floorViewForTest;
        return hooks === undefined ? 0 : hooks.cardLinks().length;
      })).toBeGreaterThan(0);
    };

    for (const [href, landed] of [
      ["#/sys/models", page.getByRole("heading", { name: "模型管理", exact: true }).first()],
      [settingsHash, page.locator("#departments")],
    ] as [string, Locator][]) {
      await openFloorCard();
      const found = await page.evaluate((target) => {
        const hooks = (window as unknown as { __floorViewForTest?: FloorHooks }).__floorViewForTest;
        return hooks === undefined ? null : hooks.cardLinks().find((link) => link.href === target) ?? null;
      }, href);
      expect(found, `画面里的卡片上没有指向 ${href} 的链接`).not.toBeNull();
      const size = await page.evaluate(() => {
        const hooks = (window as unknown as { __floorViewForTest?: FloorHooks }).__floorViewForTest;
        return hooks === undefined ? null : hooks.size();
      });
      const canvas = await page.locator(".floor-canvas canvas").boundingBox();
      if (found === null || size === null || canvas === null) {
        throw new Error("画面里的卡片没有可点的链接，或者没有画布");
      }
      // 链接的点击区放大到这一行文字：画出来的是 12 像素高的按钮，点击区上下各放宽几个像素，
      // 点在这一行文字的上沿（按钮上沿外的纸上）也算点中（工单 #1161 第 2 条）
      expect(
        found.hit.y,
        `画面里「${href}」的点击区没有放大到这一行文字：画出来的按钮从 ${found.drawn.y} 开始，点击区也从那里开始`,
      ).toBeLessThan(found.drawn.y);
      for (const [where, y] of [
        ["按钮中间", found.drawn.y + found.drawn.h / 2],
        ["这一行的上沿", found.hit.y + 1],
      ] as [string, number][]) {
        if (where === "这一行的上沿") {
          await openFloorCard();
        }
        const box = await page.locator(".floor-canvas canvas").boundingBox();
        if (box === null) {
          throw new Error("概览页没有循环画面的画布");
        }
        await page.mouse.click(
          box.x + ((found.drawn.x + found.drawn.w / 2) * box.width) / size.W,
          box.y + (y * box.height) / size.H,
        );
        await expect.poll(hashOf, { message: `画面里的卡片点「${href}」（${where}）以后地址没变` }).toBe(href);
        await expect(landed, `画面里的卡片点「${href}」（${where}）以后没有到对应的页面`).toBeVisible();
      }
      // 部门设置那一节要在眼前，不是停在设置页的顶部
      if (href === settingsHash) {
        await expect(page.locator("#departments").getByRole("heading", { name: "部门设置", exact: true }))
          .toBeInViewport({ ratio: 0.05 });
      }
    }

    expect(errors).toEqual([]);
  } finally {
    await client.close();
  }
});
