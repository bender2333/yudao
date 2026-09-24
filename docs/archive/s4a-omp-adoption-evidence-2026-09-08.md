# S4-A OMP 采用项到实现/测试对应

日期：2026-09-08。审查底本：[omp-stage2-system-review.md](research/omp-stage2-system-review.md)，OMP 固定提交 `e3106be`。被测应用提交：`cdcdce5`。不重开无边界研究。本表只关联已选择采用的最小机制；未采用项保持归档。

阶段状态仍为 PARTIAL：本表是源码与局部测试对应，不能代替 S3 联合验收。

## 采用项

| 采用项 | Yudao 实现入口 | 验证报告 | 边界 |
| --- | --- | --- | --- |
| 请求/响应/工具/usage 稳定身份 | `observability.py` 尝试级查询；`MODEL_REQUESTED` / `MODEL_REQUEST_SERIALIZED` / attempt payload 含 `logical_call_id`、`attempt_id`、requested/actual | `test_observability.py::test_fake_run_exposes_attempt_identity_and_keeps_missing_usage_null`；`test_web_ui.js` 请求/返回身份 | 实际模型未返回时保持 unknown，不回填配置 |
| 失败可见 | `ProviderError.diagnostics`；`model_attempt_failed`；部分流失败保留 stream 工件、不进部门历史 | `test_observability.py::test_failed_partial_output_is_observation_only_but_detail_keeps_it`；`test_generic_adapter_failure_closes_raw_capture_and_keeps_stream_evidence`；S2 `aef3178` 有界 HTTP code/type/param | 不保存错误原文或凭据 |
| 查询不推进 | 观测 API 只读；导出不触发模型或工具 | `test_observability.py::test_observability_routes_are_run_scoped_and_query_only`；`test_observability_export_contains_attempt_context_and_usage_without_mutating_run` | Web 不能执行部门循环 |
| 压缩不切断工具回合 | `compaction.py` 切点排除未完成 tool 回合 | `test_compaction.py::test_unpaired_tool_history_has_no_valid_compaction_boundary`；`test_compaction_preserves_originals_then_resumes_work_with_summary` | 失败摘要不进有效历史 |
| 只读历史/Context 来源 | `context.py` parts；观测 Context 跳转到精确尝试 | `test_observability.py::test_context_parts_are_verified_and_missing_current_parts_do_not_fallback`；`test_web_ui.js` Context 精确 attempt id | 查询不重跑摘要 |
| 取消与迟到结果 | 取消尝试可筛选；迟到结果不推进已关闭激活 | `test_observability.py::test_cancelled_attempt_is_independently_filterable`；`test_web_ui.js` 取消标签与筛选；`test_department_guidance.py::test_cancel_during_pending_guidance_does_not_mark_processed` | 已开始工具保留真实结果 |
| 用量缺失与费用 | `reported=False` 不进上报小计；不可合计不填零 | `test_observability.py` usage totals 三例；`test_web_ui.js` 费用总计 | 覆盖率与来源必须可见 |
| 部门指导结果合同 | `collaboration.py` `explained`/`completed`；宿主绑定采用后结果 | `test_department_guidance.py` F1/F2 与 explained 回归；`fcb06ab` | 模型引用不能扩大宿主结果集 |

## 未采用（保持归档）

| 项 | 不采用理由 |
| --- | --- |
| OAuth / 自动发现 / 认证政策运行时 | 首批只要宿主凭据解析和 Responses |
| 适配器内部重试、key 轮换、strict-tools/reasoning fallback、`previous_response_id` | D17 由内核计数；适配器 `max_retries=0` |
| 远端压缩回退、Snapcompact、分支摘要、append-only KV | 会掩盖协议不支持并另立事实源 |
| 复杂并行 Agent / steering / IRC | 超出当前单循环部门权限 |
| 独立 Stats 库、OTEL 作为领域事实、数字 row id | 事件/工件是唯一事实；查询只派生 |

## 验收缺口

S3 浏览器矩阵、连续输入、小窗压缩到最终 QA、真实指导闭环仍未关闭。上表局部测试通过不能关闭这些项。
