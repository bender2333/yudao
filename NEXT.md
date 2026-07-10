# NEXT - native-harness 交接

## Current Focus

先修复会污染实验结论的确定性问题，再冻结复杂任务对照协议。当前研究对象是串行角色分工（UNDERSTAND -> PLAN_EXECUTE -> VERIFY）与 solo 的比较，不把它提前泛化成真实并行“多部门”。

## Active Protocol

- 当前历史基线：`docs/native-harness/milestone3-study-protocol.md`
- 下一正式批次：待冻结复杂任务协议；冻结前不得运行正式样本

## Last Action (2026-07-10)

- 完成 current branch review，确认 43 个既有测试通过。
- 发现执行层未强制 tool allowlist、`bash` 可越 workspace、multi 成本重复累计、非法写入会清空旧文件。
- 清理跨分支日志状态并接受 Serena schema 更新：`872e480`。

## Next Action

1. 补复现测试并修复：执行 allowlist、每 loop 成本增量、`write_file` 非法参数、`bash` 退出码/解码。
2. 收紧 fallback 与 PLAN 门禁：空 reason 不得 pass、失败 consult 不晋升、旧文件不能冒充本轮产物。
3. 冻结下一轮复杂任务协议，明确等预算与默认方案是两个不同实验。
4. 只在协议和隔离门通过后申请运行 live pilot。

## Progress

- [x] Milestone 1：solo loop
- [x] Milestone 2：UNDERSTAND -> PLAN_EXECUTE -> VERIFY
- [x] Milestone 3：小任务/鲁棒性初步实验，结论不足
- [ ] R0：实验可信度修复
- [ ] R1：复杂任务协议与题库冻结
- [ ] R2：pilot wiring
- [ ] R3：正式成对批次
- [ ] R4：循环外评分与结论

## Open BLOCKs

- `bash` 尚无机械 workspace 隔离；修复前不能宣称 hidden oracle 对 agent 不可见。
- live batch 的模型额度、题数、重复数和最大 calls 尚未授权。
