# NEXT - native-harness 交接

## Current Focus

用户已批准放弃旧 `UNDERSTAND -> PLAN_EXECUTE -> VERIFY` 三臂主方案。下一研究对象改为两臂：单 Agent（S）与需求/开发/质检工单闭环（T），回答“各自跑到完成时，T 是否更容易交付正确结果”。

三个部门各自保留 run 级完整私有会话，跨部门只传带版本与内容哈希的正式工单；隐藏评分始终在循环外。

## Active Protocol

- 当前已批准设计：`docs/native-harness/three-department-work-order-validation-design.md`（APPROVED / 待实施）
- 当前核心实施计划：`docs/superpowers/plans/2026-07-22-three-department-work-order-harness-core.md`（P0–P2，14 个可独立验证任务）
- 历史协议：`milestone3-study-protocol.md`、`milestone4-complex-study-protocol.md`、`role-persistent-sessions-design.md` 与 `aider-polyglot-protocol.md` 仅供追溯，不再定义下一轮主方案。
- 已知历史缺陷：`docs/native-harness/ISSUES-content-filter.md`；旧 Aider pilot 因异常停止误判而无效，不进入新方案证据。

## Last Action (2026-07-22)

- 完成并批准三部门工单闭环重设计。
- 决策：S/T 各自跑到完成；同模型、同工具和相同宽松保险丝，但不强制等 calls/token/墙钟。
- 决策：五类工单、确定性路由、三个私有会话、质检唯一放行、循环外隐藏评分。
- 决策：移除任意 shell，改为相对路径文件工具与预登记 `run_check`；暂不引入容器，因此结果只称本机软隔离工程证据。
- 预注册规模：12 道自建复杂题 × S/T × 3 次 = 72 个正式 run；支持门槛为 T 赢至少 10/12、平均有效分至少 +5、fatal 与 false-complete 均不增加。
- 已完成设计与 P0–P2 详细实施计划；未改 harness 代码、未调用 live 模型、未运行实验。

## Next Action

1. 选择执行方式并按 `docs/superpowers/plans/2026-07-22-three-department-work-order-harness-core.md` 从 Task 1 开始实施；全部测试使用 fake/scripted provider。
2. 核心计划依次完成 provider 停止分类、工单合同、workspace/工具边界、私有会话、S/T loop、原子产物和进程树 supervisor。
3. 全量 `python -m pytest harness/tests -q` 与三个 CLI `--help` 通过后，删除旧 U/P/V 链并更新 W1–W3。
4. P0–P2 完成后另走 brainstorming/spec/plan 设计两道 development 校准题与 experiment runner。
5. 任何 live 调用仍需 `NEXT.md` 单独授权。

## Progress

- [x] 历史：solo loop、旧 U/P/V 三阶段、常驻会话与三臂消融
- [x] W0：新工单闭环与 S/T 验证设计获批
- [x] W0b：P0–P2 核心详细实施计划完成
- [ ] W1：工单合同与确定性状态机
- [ ] W2：私有会话、角色权限与 Solo 对照
- [ ] W3：受限本机工具与外层 supervisor
- [ ] W4：两道 development 校准题
- [ ] W5：12 道 formal 题与冻结
- [ ] W6：72 次正式运行、循环外评分与结论

## Open BLOCKs

- 当前 `bash` 与 Agent 生成代码都没有 OS 级沙箱；新工具边界完成前不得运行新协议样本。即使完成，本机结果也只能称软隔离工程证据。
- `content_filter` 仍会被旧 agent loop 误判；新底座必须将它与 natural stop 分开并留下回归测试。
- 外层 Windows 进程树硬超时尚未实现。
- 两道 development 题、12 道 formal 题、隐藏评分与冻结哈希均未创建。
- live batch 的模型、费用上限和计划 run 数尚未授权。
