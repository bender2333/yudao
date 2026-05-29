# NORTH_STAR — 终极目标（只读，禁止修改）

> 这是项目的北极星。任何 session 都不得修改本文件的 NS 条目。
> 它定义"做完了没有"，是自动循环的唯一终止裁判。
> 若你认为某条 NS 需要变更，写进 `docs/decision.md` 提请人确认，不要自己改。

## 一句话使命

打造一个 AI/Agent 原生的任务平台：用户给一句话需求，系统自动分解、规划、执行、部署、自检，闭环产出可用结果。
设计全文见 `docs/superpowers/specs/2026-05-27-ai-agent-native-mission-platform-design-zh.md`。

---

## NS-1 — v0.1A 骨架与流程闭环 ★当前唯一目标

**done 的定义（不是"我觉得差不多"，是这条验收门）：**

`docs/superpowers/plans/2026-05-29-integration-test-children-story-site.md` 的三项必过全绿：

1. **第 1 层**（fake runner，确定性）：`VITE_FAKE_RUNNER=1 pnpm test:e2e` 全绿——wiring 完好、事件流完整、产出三件套。
2. **第 2 层**（黑盒全自动验收门）：`ACCEPTANCE=1 pnpm test:e2e` 在装有 codex/claude 的机器跑通一次——
   黑盒提交一句话需求（`full_autonomous`）+ 只轮询 `GET /api/missions/:id/status`，
   系统自驱到 `outcome=succeeded`、`deployUrl` 可达，Playwright 在该 URL 上 AC1–AC5 全过。
3. **全量回归**：`pnpm test` 全绿 + `pnpm build` 通过。

三项全过 = NS-1 达成 = v0.1A 闭环成立。

**实现路线**：按 `docs/superpowers/plans/2026-05-29-v01a-tasks-detailed.md` 的 Task 1 → 12 顺序推进。
每个 Task 的"验收门槛"是它自己的 done；所有 Task 的 done 累加 = NS-1 的 done。

---

## NS-2 — v0.1B 自举式开发（NS-1 达成后才解锁）

平台用自己这套 Mission/DAG/Driver/Console 来开发自己。
增量接上 B 档接缝（workspace 指向 repoRoot、产物落 openspec 结构、gateRequired、EvaluationRecord）。
**在 NS-1 未达成前，不要碰 NS-2。**

---

## 不变量（任何时候都不能破坏）

- 大循环（Driver）只管流程节奏与观察，不替业务做决定。
- Mission Planner 只选下一个 workflow，不创建/执行 DAGRun、不分解任务。
- 黑盒验收测试是验收规格：测不过 → 修系统，**绝不改测试、不放宽断言**。
- v0.1A 只实装 `full_autonomous` 一种自主模式，其余三种留配置位、不实装逻辑。
- 确定性的事用代码做，不用 LLM（路由、重试、状态码判定）。
