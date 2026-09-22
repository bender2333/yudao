# 决策记录

## 2026-09-22 - 运行时间限制替代计数限制作为主要收敛保证

- 用户指令：「不用限额。进行时间限制即可，尽可能放开限制，确定收敛即可」。
- 事实：真实验收运行因计数限制（`max_cycles=12`、`MAX_MODEL_STEPS=32`）在模型提交前被暂停（`PAUSED / model_steps_exhausted`、`PAUSED / max_cycles`），无法完成交付。
- 决策：
  - 新增 `run_time_limit_sec`（默认 7200 秒）作为运行级挂钟时间限制，使用单调时钟在每次激活准备和每步之间检查，达到上限进入 `FAILED`（停止原因为 `time_limit`）。
  - `max_cycles` 默认值从 8 放宽至 999999，`MAX_MODEL_STEPS` 默认值从 32 放宽至 999999，实际运行中不再成为有效约束。
  - 保留计数限制的完整机制：调用方仍可显式配置较小值以恢复旧行为，达到上限时仍进入 `PAUSED`。
  - 终态选择 `FAILED` 而非 `PAUSED`：时间限制是系统强制停止，与取消、provider 错误等同类，不属于「暂停后可继续」的语义。
- 变更文件：`harness/models.py`、`harness/engine.py`、`harness/orchestrator.py`、`harness/projection.py`、`harness/projects.py`、`harness/web/server.py`、`harness/tests/test_run_time_limit.py`、`harness/tests/test_orchestrator.py`、`README.md`、`docs/requirements/execution-limits.md`。

## 2026-09-05 - 从基础 Harness 重启

- 新分支从 `origin/exp/native-harness` 开始，因为其中的三部门协议与目标一致。
- 当前只保留需求、开发、质检三个角色的确定性状态机；provider、任意 shell、旧实验 runner 和前端不进入基础层。
- 三部门职责固定为：需求形成验收合同，开发实现并提交证据，质检独立验证并返工或放行。

## 2026-09-21 - 压缩在推理型模型上的失败形态与待决方向

- 事实：`mimo-v2.5`（推理型）在真实运行中多次进入 `FAILED / compaction_failed`，两种形态：`Compaction summary exceeds its output limit`（12000 窗两次，场景 C）与 `Compaction returned an empty summary`（32000 窗一次，3.2A 登记命令验收 `run_4280c207b68248cd`）。压缩调用在上游侧记录为 success，但正文为空或超限；两次压缩调用分别耗时 47s / 23s。
- 机制：`harness/compaction.py` 的 `response_reserve` 取 `max(窗口 15%, min(模型声明输出上限, 窗口/2))`；32000 窗且声明输出上限 4096 时预留 4800、摘要上限 4096。推理模型的 reasoning 与摘要正文共享该预算。
- 现状与设计一致（压缩失败 fail-closed，不静默截断），因此不按缺陷直接修改。
- 待决方向（需人确认，涉及 D10 压缩语义与 D17 重试边界）：
  1. 提高模型声明的 `max_output_tokens`。本机 4096 是验收发送上限而非服务商标称；需确认模型真实上限，不猜容量。
  2. 把"空摘要"归为可重试的模型输出畸形，走现有每次激活的重试额度（与"未声明工具却返回 function_call 归为可重试"同类先例）。
  3. 压缩请求抑制推理，需要协议或服务商级参数支持，属能力变更。
  4. 摘要改用非推理模型。部门绑定为单模型，属设计变更。
- 推荐：先做第 2 项（最小改动，不改变 fail-closed 与重试类别），同时确认第 1 项的真实上限；若仍不足以覆盖长工程会话，再评估第 3 或第 4 项。

## 2026-09-21 - 压缩请求输出预算固定为 4096，空/超限摘要不终止任务

- 参考实现：`sst/opencode` `packages/core/src/session/compaction.ts`（commit `70a24697ea0028e19f22712fd63059538cb4bee7`）。
- 新策略：
  - `SUMMARY_OUTPUT_TOKENS = 4096`：摘要请求的 `max_output_tokens` 固定为 4096，与模型声明的输出上限无关。推理模型的 reasoning 输出与摘要正文共享该预算，固定上限避免摘要被 reasoning 挤占。
  - 摘要请求发送 `tools: []`，不携带推理/provider 特殊参数（已确认 `assemble_compaction` 和 provider 适配器层均不发送）。
  - 摘要仅从可见文本 delta 收集；reasoning 类型的输出被忽略。
  - 预检：估算的摘要提示词 token 数超过 `context_window - SUMMARY_OUTPUT_TOKENS` 时不发送请求，返回"未压缩"。
  - 空摘要或超限摘要不终止任务（返回 None），部门继续工作，后续激活重试压缩。
  - 序列化历史时，工具输出截断为 `TOOL_OUTPUT_MAX_CHARS = 2000` 字符。
  - 真正的"无法容纳"场景（固定原文与当前工作超出窗口）仍然明确停止。
- 变更文件：`harness/compaction.py`（新增常量、截断、预检、非致命空/超限）、`harness/orchestrator.py`（`_finish_compaction` 处理 None 返回值）。
- 现有 `test_three_undeclared_tool_calls_fail_compaction` 测试不变：适配器级的协议畸形（未声明工具却返回 function_call）仍走引擎重试→耗尽→FAILED 路径，与 `finish_compaction` 的非致命处理是不同的错误路径。
