# NEXT — 跨 Session 交接

> 每次 session 结束更新本文件。下一个 session 从这里续上，不靠记忆。
> 目标看 `NORTH_STAR.md`，循环协议看 `LOOP.md`，决策看 `docs/decision.md`。

---

## Current Focus
NS-1：v0.1A 骨架与流程闭环。长任务控制文件已搭好，准备进入实现循环。

## Last Action（2026-05-29）
搭建完长任务自动闭环的控制文件：NORTH_STAR.md / LOOP.md / 重写 AGENTS.md / docs/decision.md / docs/journal/2026-05-29.md。

## Next Action
启动实现循环（按 LOOP.md）：
1. 自动模式首步：切到工作分支 `work/v01a`（不存在则建），`git push -u origin work/v01a`。
2. 开始 **Task 1**（脚手架 + 共享契约），见 `docs/superpowers/plans/2026-05-29-v01a-tasks-detailed.md`。
   - 该 Task 的"验收门槛"即它的 done；通过即 commit + push，再进 Task 2。
3. 沿 Task 1 → 12 顺序推进，直到 NS-1 三项验收门全绿。

## 当前进度（Task 维度）
- [ ] Task 1  脚手架 + 共享契约
- [ ] Task 2 / 2B  契约增量 + 自举接缝预埋
- [ ] Task 3  事件存储
- [ ] Task 4  WorkflowTemplate 注册表（8 个模板，含 DeployWorkflow）
- [ ] Task 5 / 5B  Planner / Orchestrator
- [ ] Task 6A–6C  Runtime 适配器（Mock / LocalCli / Router）
- [ ] Task 6D  Autonomous Mission Driver + GoalCheck（全自动大循环）
- [ ] Task 7  DAGRun 物化 / NodeRun 执行 + deploy 节点
- [ ] Task 8  API（含 `GET /api/missions/:id/status` 黑盒轮询端点）
- [ ] Task 9–11  前端 Console（NewMission 入口 / MissionDetail / 时间线）
- [ ] Task 12  集成测试两层（第 1 层 wiring + 第 2 层黑盒验收门）

## Open BLOCKs
_（无）_

## 备注
- 设计稿与 4 份计划文档已成体系且自洽（设计-zh / plan-revised / tasks-detailed / 集成测试）。
- v0.1A 只实装 `full_autonomous` 一种自主模式。
- 仓库根有大量未跟踪的 .superpowers/ 与 node_modules/ 等——提交前用具体路径 add，别 `git add .`。
