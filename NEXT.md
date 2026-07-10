# NEXT - native-harness 交接

## Current Focus

三角色常驻会话重构已完成。当前研究对象是同一 U -> P -> V 拓扑下的三臂比较：solo（S）、cold multi（C）与 persistent multi（P）；主问题仍是 P 是否优于 S，C 只用于识别角色内记忆的贡献。

## Active Protocol

- 当前历史基线：`docs/native-harness/milestone3-study-protocol.md`
- 下一正式批次：`docs/native-harness/milestone4-complex-study-protocol.md`（DRAFT / BLOCKED）
- 会话设计与验收：`docs/native-harness/role-persistent-sessions-design.md`（P0-P3 已实现）
- **无 Docker 公开题对比（Aider Polyglot）**：`docs/native-harness/aider-polyglot-protocol.md` + `scripts/aider_polyglot_runner.py`（dry-run 已通；live pilot 待额度）

## Last Action (2026-07-10)

- 设计三角色常驻会话：`59db10d`。
- P0 三角色私有 AgentSession + activate：`5a49438`。
- P1 常驻 consult、per-role 计量与预算耗尽收口：`1646903`。
- P2 sessions/handoffs 审计落盘与 reason/context 边界：`87ccd6d`。
- P3 cold/persistent 消融、共享 calls/token/协作式墙钟预算与三臂协议：`b15794e`。
- harness 全量：80 passed，0 skipped。

## Next Action

1. 为 S/C/P 三臂补 pilot runner wiring 与外层 300 秒进程硬超时；先用 development fixture 验证，不计正式样本。
2. 创建并审查 8 个复杂 fixture + hidden oracle；提交 SHA-256 后冻结协议。
3. 评估 persistent 的 `message_count/message_chars` 与 token 成本，再决定是否另立角色内压缩任务；当前不自动压缩。
4. Docker/Podman 暂不推进；正式 hidden-oracle 批次前再完成机械隔离并取得 live 额度授权。

## Progress

- [x] Milestone 1：solo loop
- [x] Milestone 2：UNDERSTAND -> PLAN_EXECUTE -> VERIFY
- [x] Milestone 3：小任务/鲁棒性初步实验，结论不足
- [x] R0：确定性实验可信度修复（不含 OS 级隔离）
- [x] P0：三角色常驻 session + 私有 transcript
- [x] P1：常驻 consult + per-role + run budget 收口
- [x] P2：session/handoff 审计与 context 指标
- [x] P3：cold/persistent 消融开关与三臂协议
- [ ] R1：复杂任务协议与题库冻结
- [ ] R2：pilot wiring
- [ ] R3：正式成对批次
- [ ] R4：循环外评分与结论

## Open BLOCKs

- `bash` 尚无机械 workspace 隔离；修复前不能宣称 hidden oracle 对 agent 不可见。
- `max_seconds` 是协作式门闩；外层进程硬超时未实现，不能保证强杀在途 API/shell。
- live batch 的模型额度、题数、重复数和最大 calls 尚未授权。
