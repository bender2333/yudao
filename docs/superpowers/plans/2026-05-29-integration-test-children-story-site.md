# 集成测试：儿童故事网站闭环验收

> **日期：** 2026-05-29
> **地位：** 这是 v0.1A 的**验收门**。通过即闭环成立，可切 goal 模式自动推进 v0.1B 自举。
> **关联：** 任务实现见 `2026-05-29-v01a-tasks-detailed.md` Task 12；总览见 `2026-05-29-v01a-plan-revised.md`。

## 为什么这份测试是闭环证据

它对应组织类比里的**运维循环**——"运维是真正的物理世界的观察"。这份测试不是 CI 里的一个断言，它是一次真实运行：真部署、真 runner、真生成网站、真在浏览器里观察、真走一轮反馈。跑通它，等于证明"意图 → 规划 → 调度 → 执行 → 产物 → 观察 → 反馈"整条大循环在物理世界里成立。

### 黑盒 + ATDD 定性（核心）

第 2 层是**黑盒验收驱动测试**。立场是"用户"，不是"系统编排者"：

```text
用户做的事（测试只允许做这些）：
  1. 打开 web UI（或打入口 API），提交一句话需求："做一个儿童故事网站"
  2. 选择全自动模式（full_autonomous）
  3. 等待 —— 不点任何"下一步"，不调任何内部接口
  4. 拿到结果：一个能在本地访问的交互式儿童故事网站，自己点开看

系统必须自己做完的事（测试不替它做）：
  规划 → 选模板 → 物化 DAG → 调 runner 生成网站 → 部署启动 → 健康探活 → 自检达标
```

判定原则（ATDD）：

```text
测试通过  = 系统真的能从一句话需求全自动产出可用网站 → 闭环成立
测试不通过 = 系统有缺陷 → 去修系统，不是改测试、不是放宽断言
```

## 两层结构

```text
第 1 层 — 接线冒烟测试（fake runner，确定性，CI/开发期）
  目的：每次提交快速验证 wiring 不破，不烧钱、不依赖 LLM
  地位：开发期保护网，不是验收门
  文件：tests/e2e/childStoryGameMission.e2e.test.ts
  启用：VITE_FAKE_RUNNER=1 pnpm test:e2e
  注：此层允许调内部接口做白盒断言（验证事件流完整）

第 2 层 — 真实部署黑盒全自动测试（验收门）★
  目的：以用户身份，验证系统能从一句话需求全自动产出可用网站
  地位：闭环成立的唯一证据，纯黑盒
  文件：tests/e2e/childStorySiteDeployment.acceptance.test.ts
  启用：ACCEPTANCE=1 + 机器装有 codex 或 claude
  约束：只调"提交意图"和"轮询状态"两类用户端点 + 浏览器验收
```

---

## 用户真实需求（黑盒输入）

这是用户在 web UI 入口框里实际会提交的需求。它有意保持"人话"级别——不含任何技术拆解，因为拆解是系统该做的事。

提交文本（其一即可，测试可用任意一条）：
```text
"做一个儿童故事网站，挑几个经典童话，能在浏览器里一篇篇翻着读。"
"我想要一个本地能跑的儿童故事网站，收录几个经典故事，点开能一页页看。"
```

用户的隐含期望（系统需自行补全为 acceptance criteria）：
```text
- 收录"经典"儿童故事（如小红帽 / 三只小猪 / 龟兔赛跑 / 丑小鸭 / 金发姑娘等，≥3 篇）
- 首页能看到故事列表，一眼挑选
- 点进一篇能逐页阅读，有上一页/下一页
- 适合儿童：字大、配色友好、可加 emoji/插画占位
- 本地就能打开运行，不依赖外部服务
- 纯静态即可（无需后端/数据库）
```

系统应当自动产出的 acceptance criteria（由 exploration 节点写成 artifact，供 GoalCheck 核对）：
```text
AC1 首页展示 ≥3 篇经典故事的入口
AC2 每篇故事 ≥2 页内容，可前后翻页
AC3 站点本地静态可访问（index.html 可直接打开 / 被静态服务器托管）
AC4 儿童友好：可读字号 + 友好配色
AC5 浏览器控制台无 error
```

> 黑盒测试只校验"用户拿到的结果满足 AC1–AC5"，不校验系统内部怎么实现、用了哪几篇故事、文案具体写了什么。

---

## 验收样例规格：静态多页儿童故事站

真实 runner（和 fake runner）应在 mission workspace 生成以下三件套。这是 Playwright 断言的契约。

```text
.mission-workspaces/<missionId>/
  index.html     首页：站点标题 + 故事卡片列表（每个故事一个可点击入口）
  stories.js     故事数据 + 渲染逻辑（至少 3 个故事，每个含 title + 多页 pages[]）
  style.css      基础样式（儿童友好配色）
```

最小行为契约（Playwright 据此断言）：
```text
1. 打开 index.html 显示站点标题（含"故事"字样）
2. 首页可见至少 3 个故事入口（卡片/链接）
3. 点击某个故事入口 → 进入该故事，显示第 1 页内容
4. 存在"下一页"控件，点击后页码/内容前进
5. 整个过程浏览器控制台无 error 级日志
```

stories.js 数据结构约定（供 runner 生成与断言）：
```js
// window.STORIES = [
//   { id: "s1", title: "小熊的森林", cover: "🐻",
//     pages: ["第一页文字...", "第二页文字...", "第三页文字..."] },
//   { id: "s2", title: "月亮上的兔子", cover: "🐰", pages: [...] },
//   { id: "s3", title: "勇敢的小火车", cover: "🚂", pages: [...] }
// ];
```

> 注：runner 生成的具体文案不固定，断言只校验结构与关键字（"故事"、故事数量 ≥ 3、pages 长度 ≥ 2、翻页可前进），不校验具体文本。

---

## 第 1 层：接线冒烟测试（fake runner，CI）

文件：`tests/e2e/childStoryGameMission.e2e.test.ts`
启用：`VITE_FAKE_RUNNER=1 pnpm test:e2e`（或 vitest，视配置）

前置：
```text
- 注册 fake runner 作为 local_cli target（command=node, args=[scripts/fake-local-runner.mjs]）
- 全程不启真实 LLM、不起真实 HTTP 端口（用 app.request 或进程内调用）
- 每个用例后清理 .mission-workspaces 临时目录
```

测试用例与断言：
```text
registers local runner via API
  → POST /api/runtime-targets {kind:local_cli, runnerKind:codex(fake)}
  → 断言 target.kind=local_cli

creates mission and writes MissionCreated
  → POST /api/missions {text:"做一个儿童故事网站"}
  → 断言 mission.state=exploring；timeline 含 MissionCreated；mission.projectId=project_self

planner generates ExplorationWorkflow
  → POST /api/missions/:id/plan-next
  → 断言 workflowIntent.templateId=ExplorationWorkflow
  → 断言 reason.classification=requirement_unclear
  → 断言 planSeed 无 nodeRuns 字段

orchestrator executes DAGRun with fake runner
  → POST /api/dag-runs {planSeed, runtimeTargetId: fakeTarget}
  → 断言 dagRun.status=completed；所有 nodeRun.status=completed

event stream completeness（执行后 timeline 必含）
  → DAGRunScheduled, DAGRunStarted
  → NodeRunStarted×N, NodeRunCompleted×N
  → ArtifactRecorded, RunMessageRecorded
  → DAGRunCompleted, RouteDecided, MissionStateChanged

mission state changes to changing
  → 断言 mission.state=changing

fake runner produced files
  → 断言 workspace 下 index.html / stories.js / style.css 存在
  → 断言 stories.js 含 window.STORIES 且故事数 ≥ 3

run trace shows dagRun messages artifacts
  → GET /api/dag-runs/:id → trace.messages.length>0, trace.artifacts.length>0

feedback triggers second plan-next
  → POST /api/missions/:id/feedback {signalType:requirement_change}
  → POST /api/missions/:id/plan-next
  → 断言 timeline 出现第二条 WorkflowPlanned
  → 断言第二次 templateId=ExplorationWorkflow
```

通过标准：以上全绿即 wiring 完好。这层**不**代表验收通过。

---

## 第 2 层：黑盒全自动验收测试（验收门）★

文件：`tests/e2e/childStorySiteDeployment.acceptance.test.ts`
启用：`ACCEPTANCE=1`，且机器装有 codex（优先）或 claude（兜底）。默认 `describe.skip`，由环境变量解除。

**这一层是真黑盒**：测试只做用户能做的两件事 —— ① 用 `full_autonomous` 模式提交一句话需求，② 轮询 `GET /api/missions/:id/status` 直到出结果。测试**绝不**调用 `plan-next`、`dag-runs`、`feedback` 等编排端点 —— 那些是大循环（Autonomous Mission Driver）在后台自己驱动的。测试只在外面"看结果"，不在里面"递步骤"。

> 失败处理（ATDD 铁律）：若 `outcome` 收敛到 `blocked` / `exhausted`，或 Playwright 断言不过 —— **去修系统，不改测试**。测试是验收规格，不是可调参数。

机器前置（2026-05-29 实测）：
```text
codex --version  → codex-cli 0.134.0
claude --version → 2.1.152 (Claude Code)
```

### 角色：RuntimeTarget 驱动的 ops agent（由大循环调度，非测试编排）

运维由一个 `role: "ops"` 的 local_cli RuntimeTarget 扮演，配套脚本 `scripts/deploy-and-observe.mjs`。它负责真实部署与健康观察，对应"物理世界的观察"。

关键点：ops agent 是**系统的能力**，不是测试的步骤。测试只在跑之前把 worker、ops 两个 RuntimeTarget 注册好（相当于"机器上装好了员工"），之后由 Autonomous Mission Driver 在 deploy 节点把活派给 ops，测试不碰它。

```text
注册（测试 setup 阶段，一次性）：
  POST /api/runtime-targets { name:"Worker", kind:"local_cli", role:"worker",
    command:"node", args:["scripts/run-worker.mjs"] }      # codex 优先 / claude 兜底
  POST /api/runtime-targets { name:"Ops Agent", kind:"local_cli", role:"ops",
    command:"node", args:["scripts/deploy-and-observe.mjs", "<phase>"] }

deploy-and-observe.mjs 阶段（phase，由 driver 在 deploy 节点触发）：
  deploy   → 起静态服务器托管 .mission-workspaces/<missionId>/（故事站）
  health   → 探活故事站首页，产出 deploy_manifest{ url, healthy }
  teardown → 关闭所有起的进程（测试 finally 兜底再调一次）
```

### 完整验收流程（黑盒全自动）

```text
[setup] 注册 worker + ops 两个 RuntimeTarget（测试一次性准备，等价"装好员工"）
[1] 提交意图：POST /api/missions
      { text:"我想要一个本地能跑的儿童经典故事网站，挑几篇经典故事，每篇能翻页阅读",
        autonomyMode:"full_autonomous" }
      → 后端异步启动 Autonomous Mission Driver（driveMission），立刻返回 missionId
[2] 轮询：GET /api/missions/:id/status，每 ~2s 一次，直到
      outcome ∈ {succeeded, blocked, exhausted} 或超时
      —— 测试在这一步什么编排都不做，只读状态
[3] 断言收敛：outcome === "succeeded" 且 status.deployUrl 非空
      （succeeded 的前提是 GoalCheck=achieved：verify 通过 + deploy_manifest.healthy）
[4] Playwright 打开 status.deployUrl，执行渲染断言（AC1–AC5，见下）
[teardown] 调 ops teardown + 清 .mission-workspaces（finally 必跑）

大循环在 [1]→[2] 之间后台自己做的事（测试看不见、也不该看见）：
  plan-next → 物化+执行 DAGRun（worker 产出三件套）→ route → deploy 节点（ops 部署+health）
  → GoalCheck → 未达成则回到 plan-next，直至 achieved / blocked / 到 maxIterations
```

### 第 2 层测试用例与断言

```text
submits a one-sentence intent in full_autonomous mode
  → POST /api/missions {text, autonomyMode:"full_autonomous"} 返回 201 + missionId
  → 立即返回（不阻塞），后台 driver 已启动

system auto-drives the mission to completion (no manual orchestration)
  → 仅轮询 GET /api/missions/:id/status
  → 整个用例中测试不调用 plan-next / dag-runs / feedback（用断言/spy 守住这条边界）

mission reaches outcome=succeeded within timeout
  → 轮询直到 status.outcome === "succeeded"
  → 失败处理：若收敛到 blocked/exhausted → 测试失败 → 修系统（看 timeline 定位卡点）

status exposes a reachable deploy url
  → status.deployUrl 非空，且 driver 内部 GoalCheck 已确认 deploy_manifest.healthy

[AC1] served site shows ≥3 classic story entries (Playwright)
  → page.goto(deployUrl)；标题含"故事"；[data-story] 元素 ≥ 3

[AC2] entering a story shows content and can page back/forward
  → 点第 1 个 [data-story] → [data-page] 可见且有文字
  → 点 [data-next] 后页码/内容前进（≥2 页可翻）

[AC3] site is served locally and reachable
  → deployUrl 为本地地址且 HTTP 可达（已由 health + goto 共同保证）

[AC4] child-friendly rendering
  → 正文字号可读（计算样式 font-size ≥ 阈值）；存在非纯黑白配色

[AC5] no console errors on the served site
  → 收集 console.error + pageerror，断言无 error 级

[降级] falls back to claude when codex unavailable
  → worker runner 探测：codex 不可用则注册 claude，整个黑盒流程用 claude 重跑并通过
```

### Playwright 脚本骨架

```ts
import { test, expect } from "@playwright/test";

// 由黑盒主测试从 GET /api/missions/:id/status 的 deployUrl 写入环境变量后调用
const SITE_URL = process.env.STORY_SITE_URL!;

test.describe(process.env.ACCEPTANCE === "1" ? "story site" : "skipped", () => {
  test.skip(process.env.ACCEPTANCE !== "1", "needs full-auto run + deploy");

  test("home renders with story list and pager, child-friendly, no errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(String(e)));

    await page.goto(SITE_URL);
    await expect(page).toHaveTitle(/故事/);

    // AC1：≥3 篇经典故事入口
    const cards = page.locator("[data-story]");
    expect(await cards.count()).toBeGreaterThanOrEqual(3);

    // AC2：进入故事 → 有内容 → 可翻页
    await cards.first().click();
    const pageEl = page.locator("[data-page]");
    await expect(pageEl).toBeVisible();
    const before = await pageEl.innerText();
    await page.locator("[data-next]").click();
    const after = await pageEl.innerText();
    expect(after).not.toBe(before);

    // AC4：儿童友好（可读字号 + 非纯黑白配色）
    const fontPx = await pageEl.evaluate(
      (el) => parseFloat(getComputedStyle(el).fontSize)
    );
    expect(fontPx).toBeGreaterThanOrEqual(16);
    const bg = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor
    );
    expect(bg).not.toBe("rgb(255, 255, 255)");

    // AC5：无 console error
    expect(errors, errors.join("\n")).toHaveLength(0);
  });
});
```

> data 属性（data-story / data-page / data-next）是 worker 生成 HTML 时应带的钩子。写进 worker 的 prompt 约定里，让真实/fake worker 都产出这些钩子，断言才稳定。
> AC3（本地可达）由 driver 内部 health 探活 + 这里的 `page.goto` 共同保证，不单列脚本。

### 降级与稳健性

```text
runner 选择：codex 优先；codex --version 失败或执行超时 → 切 claude 重跑
超时：单个 DAGRun 给真实 runner 留足超时（建议 ≥ 180s，可配）
非确定性：真实 runner 文案不固定，断言只校验结构/数量/翻页行为，不校验文本
端口冲突：deploy 阶段动态选空闲端口，URL 通过环境变量回传给 Playwright
清理：teardown 必跑（finally），关闭进程 + 清 .mission-workspaces
secrets：runner 的 API key 通过环境变量传入子进程，绝不写入事件/artifact/测试日志
```

---

## 运行命令清单

```bash
# 第 1 层（CI / 开发期，fake runner，确定性）
VITE_FAKE_RUNNER=1 pnpm test:e2e tests/e2e/childStoryGameMission.e2e.test.ts

# 第 2 层（验收门，真实 runner + 真实部署 + Playwright）
# 需机器装有 codex 或 claude，并配好对应 API key 环境变量
ACCEPTANCE=1 pnpm test:e2e tests/e2e/childStorySiteDeployment.acceptance.test.ts

# 全量回归（提交前）
pnpm test && pnpm build
```

## 验收门判定（闭环成立的信号）

```text
[必过] 第 1 层全绿：wiring 完好，事件流完整，fake runner 产出三件套
[必过] 第 2 层在真实机器跑通一次（黑盒全自动）：
        - 测试只提交一句话需求（full_autonomous）+ 轮询 status，全程零编排
        - Autonomous Mission Driver 后台自驱：plan-next→DAGRun→deploy→GoalCheck 直到 achieved
        - worker（codex 或 claude）真实生成静态多页故事站，ops 真实部署 + health ok
        - status.outcome 收敛到 succeeded，status.deployUrl 可达
        - Playwright 在该 URL 上 AC1–AC5 全过（列表/进入故事/翻页/儿童友好/无报错）
[必过] pnpm test 全量绿 + pnpm build 通过
```

三项全过 = v0.1A 闭环成立：**系统真的能从一句话需求、全自动产出一个本地可用的儿童故事网站**。此后可切 goal 模式，自动推进 v0.1B 自举（平台用自己这套 Mission/DAG/Driver/Console 开发自己）。

## 与 v0.1B 的衔接

```text
本测试已证明的能力（v0.1B 可直接复用）：
  - 大循环全自动驱动闭环成立：一句话需求 → driver 自驱 → 可用产物，零人工编排
  - 真实 worker 能在 workspace 真实产出文件
  - ops 角色 runner 能部署 + 观察健康度，GoalCheck 能据此判定达成
  - 黑盒验收范式可复用：提交意图 + 轮询 status + 产物断言

v0.1B 在此之上增量做：
  - workspace 指向 project.repoRoot（让 worker 改平台自己的代码）—— B 档接缝
  - worker 产物落成 openspec/changes/<change>/ 结构 —— B 档接缝
  - gateRequired 真正判定（core/security/runtime 变更触发 gate → driver 暂停 blocked）—— 接缝 3
  - EvaluationRecord 驱动 replay 与 evolution candidate —— 接缝 2
  - 解锁其余 3 种自主模式（human_led / semi / default），driver 按模式插入人工 gate
```





