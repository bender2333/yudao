# NEXT - native-harness 交接

## Current Focus

用户已批准放弃旧 `UNDERSTAND -> PLAN_EXECUTE -> VERIFY` 三臂主方案。下一研究对象改为两臂：单 Agent（S）与需求/开发/质检工单闭环（T），回答“各自跑到完成时，T 是否更容易交付正确结果”。

三个部门各自保留 run 级完整私有会话，跨部门只传带版本与内容哈希的正式工单；隐藏评分始终在循环外。

## Active Protocol

- 当前已批准设计：`docs/native-harness/three-department-work-order-validation-design.md`（APPROVED / 已实现 P0–P2）
- 当前核心实施计划：`docs/superpowers/plans/2026-07-22-three-department-work-order-harness-core.md`（14/14 完成）
- 历史协议：`milestone3-study-protocol.md`、`milestone4-complex-study-protocol.md`、`role-persistent-sessions-design.md` 与 `aider-polyglot-protocol.md` 仅供追溯，不再定义下一轮主方案。
- 已知历史缺陷：`docs/native-harness/ISSUES-content-filter.md`；旧 Aider pilot 因异常停止误判而无效，不进入新方案证据。

## Last Action (2026-07-22)

- P0–P2 核心底座完成：工单合同与哈希、确定性 Team 状态机、三个长期私有会话、Solo 对照、受限文件工具、预登记检查、原子产物和外层进程树 supervisor。
- Windows 子进程以 `CREATE_SUSPENDED` 启动，加入 Job Object 后才恢复；assignment 延迟竞态回归通过。
- 旧 U/P/V、cold/persistent、consult、任意 shell 工具、`run_multi` 与 Aider S/P/C runner 已干净删除，无兼容 shim。
- `content_filter` 与 natural stop 已分离；意外 dispatcher 异常 fail closed 为脱敏 `system_error`，不能继续形成 terminal 完成。
- 最终无 live 回归为 `python -m pytest harness/tests -q` 490 passed、0 skipped；`run_solo`、`run_team`、`supervisor` 三个 `--help` 均 exit 0。
- 未运行 live 模型或实验；当前证据只证明本机软隔离底座按合同工作，不证明 T 优于 S。

## Next Action

1. 重新走 brainstorming → spec → plan，设计两道 P3 development fixture 与 `scripts/work_order_experiment.py`。
2. 同时锁定 manifest/score schema、attempt 目录、paired infrastructure retry 和离线 fake S/T dry-run。
3. P3 通过后再独立设计 12 道 formal fixture；正式样本继续要求协议、题库、oracle、预算和评分先冻结。
4. 任何 live 调用仍需 `NEXT.md` 单独授权模型、费用、题数、重复数和最大调用预算。

## Progress

- [x] 历史：solo loop、旧 U/P/V 三阶段、常驻会话与三臂消融
- [x] W0：新工单闭环与 S/T 验证设计获批
- [x] W0b：P0–P2 核心详细实施计划完成
- [x] W1：工单合同与确定性状态机
- [x] W2：私有会话、角色权限与 Solo 对照
- [x] W3：受限本机工具与外层 supervisor
- [ ] W4：两道 development 校准题
- [ ] W5：12 道 formal 题与冻结
- [ ] W6：72 次正式运行、循环外评分与结论

## Open BLOCKs

- 本机仍无 OS 级 Agent 沙箱；任意 shell 已从 Agent 工具删除，但进程内 Python 不是容器边界，因此当前只能称软隔离工程证据。
- 两道 development 题、12 道 formal 题、隐藏评分与冻结哈希均未创建。
- live batch 的模型、费用上限和计划 run 数尚未授权。
