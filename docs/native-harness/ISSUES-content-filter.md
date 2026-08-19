# 已记录问题：content_filter 空响应被误判为 natural stop

> 记录日期：2026-07-10
> 数据来源：`runs/aider/pilot-001/`（Aider polyglot pilot，5 题 × S/P × 1 rep，真模型 gemini-2.5-flash）
> 状态：**已确证根因，未修复**

## 现象（用户观察）
- multi(P) 比 solo(S) 更不稳：多题 escalated。
- list-ops P 在 UNDERSTAND 阶段几乎没产出（2 calls / 5 秒就 escalated）。
- 唯一 PASS 在 solo（pig-latin），P 同题 escalated。

## 根因（已确证，有据）
被拦步的原始 events 显示 `finish_reason="content_filter"`、`text=""`、`has_tool_calls=false`：

- `list-ops/P_r1` UNDERSTAND step2：`{"finish_reason":"content_filter","text":"","completion_tokens":18}`
- `pig-latin/P_r1` PLAN step1：`{"finish_reason":"content_filter","text":"","completion_tokens":0,"duration_ms":42199}`

**harness 缺陷**：`harness/agent_loop.py` 的停止判断只看"有无 tool_calls"，不看 `finish_reason`。
于是 `content_filter`（输出被网关内容审查拦截 = 异常）被当成 `natural`（模型主动说完 = 正常）处理：
→ 阶段被判自然结束 → 撞门闩（UNDERSTAND extract 抽不出四字段 / PLAN 无交付物）→ escalated。

## finish_reason 分布（5 个 P run，已统计）
| 题 | 分布 | 结果 |
|---|---|---|
| list-ops P | tool_calls×1, **content_filter×1** | escalated（UNDERSTAND 死） |
| grade-school P | tool_calls×18 | done（无 content_filter） |
| wordy P | tool_calls×12, **content_filter×1** | escalated |
| phone-number P | tool_calls×31, **content_filter×1** | escalated |
| pig-latin P | tool_calls×4, **content_filter×1** | escalated |

**4/5 的 P run 命中 content_filter。**

## 为什么专打 multi、不打 solo
multi 有多阶段 + 门闩：任一阶段撞 content_filter → 被判自然停止 → 门闩 escalate。
solo 单 loop 无门闩：即使某步被过滤，循环仍可继续。
→ content_filter 的伤害被 multi 结构放大。**本轮"multi 更差"很大程度是此 bug 制造的假象，非 multi 本质更差。**

## 已排除
- content_filter **不是被任务内容触发**：list-ops 被拦步的完整送入上下文（列表操作编程题 + 一次 list_dir 目录返回）完全无害。倾向"网关偶发拦截"。

## 待查（未臆测，需单独验证）
1. **transcript 里的中文乱码**：`sessions/understand.jsonl` 的 system/user 中文显示为 `���`。尚不确定是 GBK/UTF-8 显示问题，还是真的把乱码写进了 prompt。若是后者，是独立 bug，且可能与 content_filter 触发相关。
2. content_filter 触发规律：是否与某类内容/长度/时序相关（需横向对比 4 个被拦 run 的送入上下文）。

## 结论对实验的影响
- 本轮 pilot-001 的 solo vs multi 对比**数据无效**：multi 被 content_filter × harness 误判系统性拖垮，未公平跑起来。
- 修复方向候选（未定）：agent_loop 遇 `finish_reason=content_filter`（空输出）时，不当 natural stop —— 要么 retry，要么记为独立失败终态（不喂给门闩当"没交卷"）。

## 相关文件
- `harness/agent_loop.py`：停止判断逻辑（只看 tool_calls，未看 finish_reason）
- `harness/llm.py`：CallResult 已含 finish_reason 字段（数据在，只是没被 loop 用于停止判断）
- 证据：`runs/aider/pilot-001/tasks/*/P_r1/harness_run/{events,sessions/*}.jsonl`
