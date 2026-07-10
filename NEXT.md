# NEXT - native-harness 交接

## Current Focus

先修复会污染实验结论的确定性问题，再冻结复杂任务对照协议。当前研究对象是串行角色分工（UNDERSTAND -> PLAN_EXECUTE -> VERIFY）与 solo 的比较，不把它提前泛化成真实并行“多部门”。

## Active Protocol

- 当前历史基线：`docs/native-harness/milestone3-study-protocol.md`
- 下一正式批次：`docs/native-harness/milestone4-complex-study-protocol.md`（DRAFT / BLOCKED）

## Last Action (2026-07-10)

- 清理工作区与长任务控制面：`872e480`、`7b74ecb`。
- 修复执行 allowlist、成本增量、破坏性写入、bash 退出码与解码：`331b593`。
- 收紧 PLAN、VERIFY fallback、consult 和 stage 参数门禁：`dfcf7ab`。
- 禁止复用 run 目录并提高默认目录唯一性：`35828e9`。
- harness 全量：54 passed。

## Next Action

1. 选择并实现 agent 文件系统/网络隔离；当前机器无 Docker/Podman/可用 WSL。
2. 实现 run 级 token 与 300 秒墙钟硬预算，并让已存在 run_dir 大声失败。
3. 创建并审查 8 个复杂 fixture + hidden oracle；提交哈希后冻结协议。
4. 只在隔离、预算和额度授权全部通过后运行 live pilot。

## Progress

- [x] Milestone 1：solo loop
- [x] Milestone 2：UNDERSTAND -> PLAN_EXECUTE -> VERIFY
- [x] Milestone 3：小任务/鲁棒性初步实验，结论不足
- [x] R0：确定性实验可信度修复（不含 OS 级隔离）
- [ ] R1：复杂任务协议与题库冻结
- [ ] R2：pilot wiring
- [ ] R3：正式成对批次
- [ ] R4：循环外评分与结论

## Open BLOCKs

- `bash` 尚无机械 workspace 隔离；修复前不能宣称 hidden oracle 对 agent 不可见。
- live batch 的模型额度、题数、重复数和最大 calls 尚未授权。
