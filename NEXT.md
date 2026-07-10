# NEXT — 跨 Session 交接

> 每次 session 结束更新本文件。下一个 session 从这里续上，不靠记忆。
> 目标看 `NORTH_STAR.md`，循环协议看 `LOOP.md`，决策看 `docs/decision.md`。

---

## Current Focus
当前 checkout 为 `exp/native-harness`。本 session 已完成该分支的代码审查；它是 Python agent harness 实验分支，不是 NORTH_STAR 所述 Mission 平台主实现。

## Last Action（2026-07-10）
- `python -m pytest harness/tests -q`：43 passed。
- 确认高风险问题：工具白名单未在执行层生效、bash 可越 workspace、multi 成本重复累计、非法 `write_file` 会先清空旧文件。
- 标准 pnpm 验收命令均失败；对应 Mission 平台实现和配置已存在于本地 `work/v01a`，不在当前分支。

## Next Action
1. 先确认目标分支：审查/推进 Mission 平台应切到 `work/v01a`；继续 native harness 才留在当前分支。
2. 若继续 harness，依次修复：执行层工具 allowlist 与 workspace 隔离 → 成本统计 → 写入参数/原子性 → bash 退出码；每项补最小回归测试。
3. 修正统计后重算 `docs/native-harness/` 中的 calls/token/墙钟结论。

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
- 目标分支不一致：`NORTH_STAR.md` 指向 Mission 平台，当前 checkout 是 `exp/native-harness`；实现前需明确选择。

## 备注
- Review 详情见 `docs/journal/2026-07-10.md` 与本 session 最终报告。
- `work/v01a` 相对当前分支有完整 API、Vitest 配置和两层 E2E 验收文件。
- 工作区已有 `.serena/project.yml` 与 `docs/journal/codex/` 改动；提交时继续使用具体路径，别 `git add .`。
