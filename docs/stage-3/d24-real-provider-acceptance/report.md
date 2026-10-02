# D24 真实 Provider 验收报告（工单 #96）

日期：2026-10-03。模型：`claude-opus-4-6`（本报告的写入者 ID，见各证据文件的生成运行）。工单：[#96](https://github.com/bender2333/yudao/issues/96)，父工单 [#83](https://github.com/bender2333/yudao/issues/83)。判断标准：[模型管理设计说明](../design/model-management.md)第 4 至 7 节。术语以 [CONTEXT.md](../../CONTEXT.md) 为准。

## 1. 范围与身份

| 项目 | 内容 |
| --- | --- |
| 应用代码起点 | `6f674ce8`（合入 `origin/main` 之后的 HEAD，见本工单的 DELIVERY 评论） |
| 模型服务 | 9router，同一地址提供三种协议，只返回流式回复 |
| 地址与凭据 | 用户环境变量 `YUDAO_EVAL_BASE_URL`、`YUDAO_EVAL_API_KEY`；连接的凭据引用写这两个变量名，Key 不进入仓库、工单、事件与日志 |
| 首选模型 | `ag/claude-opus-4-6-thinking`：三种协议的连接测试、模型测试与 Messages 工具往返 |
| 推理内容模型 | `cbcn/deepseek-v4.1-flash`：推理内容的核对与回放 |
| 证据位置 | [evidence/](evidence/)，每份是本次运行的原始 JSON |

上游模型列表（`GET {BASE_URL}/models`，2026-10-02 采集）确认两个模型都在：`ag/claude-opus-4-6-thinking`（contextWindow 200000、maxOutput 64000、tools 与 reasoning 为真、vision 为真）、`cbcn/deepseek-v4.1-flash`（contextWindow 1000000、maxOutput 128000、tools 与 reasoning 为真、vision 为真）。

## 2. 三种协议的连接测试与模型测试

证据：[evidence/step1_connection_and_model_tests.json](evidence/step1_connection_and_model_tests.json)。对 Responses、Chat Completions、Anthropic Messages 各建一份连接，每份连接两条模型访问定义（Claude 与 DeepSeek），容量取上游模型列表的窗口与输出上限。

| 协议 | 连接测试 | Claude 模型测试 | DeepSeek 模型测试 |
| --- | --- | --- | --- |
| responses | ok（读模型列表） | ok，admitted，实际返回 `ag/claude-opus-4-6-thinking`，usage 已回报 | ok，admitted，实际返回 `cbcn/deepseek-v4.1-flash` |
| chat_completions | ok | ok，admitted，实际返回 `claude-opus-4-6-thinking` | ok，admitted，实际返回 `deepseek-v4.1-flash` |
| messages | ok | ok，admitted，实际返回 `claude-opus-4-6-thinking` | ok，admitted，实际返回 `deepseek-v4.1-flash` |

连接测试按该连接协议的认证方式读取模型列表地址，不改变准入；模型测试发一次真实最小推理请求，通过且容量已确认时写入准入记录。三份连接的六条定义都进入准入。

## 3. 各协议至少一个声明推理档位的模型：实际发送的推理参数与上游返回的推理内容

证据：[evidence/step2_reasoning_params_and_content.json](evidence/step2_reasoning_params_and_content.json)。每个协议的两个模型都声明支持档位 low、medium、high，默认档位 medium；按第 7.4 节映射发送，实际发送档位就是 medium。

| 协议 | 实际发送的推理参数 | 上游返回的推理内容 |
| --- | --- | --- |
| responses | `reasoning.effort = medium` | DeepSeek 返回 `reasoning` 条目，`summary[0].text` 为推理摘要（该线路 Claude 在 Responses 上不返回推理内容） |
| chat_completions | `reasoning_effort = medium` | DeepSeek 返回 `reasoning_content`：`{"items": [{"type": "reasoning", "reasoning_content": "..."}]}` |
| messages | `thinking.type = adaptive`、`output_config.effort = medium` | DeepSeek 返回 thinking 块：`{"items": [{"type": "reasoning", "call_id": "", "blocks": [{"type": "thinking", "thinking": "..."}]}]}` |

按工单正文，`ag` 线路的 Claude 在三种协议上都不返回推理内容，DeepSeek V4.1 Flash 在三种协议上都返回，与本次实测一致。

## 4. Anthropic Messages 的连接完成一次带工具往返的请求

证据：[evidence/step3_messages_tool_round_trip.json](evidence/step3_messages_tool_round_trip.json)。用 `ag/claude-opus-4-6-thinking`，工具 `get_weather`。请求体（第 3 节记录的实际发送参数据此核对）：

```json
{"model": "ag/claude-opus-4-6-thinking", "max_tokens": 1024, "stream": true,
 "tools": [{"name": "get_weather", "description": "Look up the weather for a city",
            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}],
 "tool_choice": {"type": "any"},
 "thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"},
 "messages": [{"role": "user", "content": "Use get_weather to look up Paris, then report the result."}]}
```

第一次真实响应返回 `function_call`：`{"name": "get_weather", "arguments": "{\"city\":\"Paris\"}"}`，call_id 为 `toolu_vrtx_...`。回传工具结果以后，第二次请求的 `messages` 是「assistant 文本 + assistant `tool_use` + user `tool_result`」，`tool_use` 与 `tool_result` 按 call_id 成对；第二次真实响应是最终回答。往返完成。

身份头证据：[evidence/step4_identity_headers.json](evidence/step4_identity_headers.json)。经本机记录代理转发三种协议的真实请求，代理只记认证头的名称与取值长度，不记取值。

| 协议 | 请求路径 | 认证头 |
| --- | --- | --- |
| responses | `/v1/responses` | `authorization: <42 chars>`（Bearer 前缀加 Key） |
| chat_completions | `/v1/chat/completions` | `authorization: <42 chars>` |
| messages | `/v1/messages` | `x-api-key: <35 chars>` 与 `anthropic-version: 2023-06-01` |

Messages 用 `x-api-key` 加 `anthropic-version` 头，与第 4.2 节的认证方式一致；地址去掉末尾 `/v1` 再拼 `/v1/messages`，路径不出现 `/v1/v1`。

## 5. 运行一个事项：运行中更换模型与推理档位

证据：[evidence/step6_switch_and_replay.json](evidence/step6_switch_and_replay.json)、[evidence/step8_switch_no_replay.json](evidence/step8_switch_no_replay.json)。部门默认绑定 Messages 上的 Claude（档位 high）；事项新建后产品一步用部门默认。请求事件里的调用目标（字段来自事件载荷的公开部分）：

| 阶段 | model_id | protocol | selection_source | requested_tier | sent_tier |
| --- | --- | --- | --- | --- | --- |
| 产品（部门默认） | claude-messages | messages | department_default | high | high |
| 工程（更换以后） | claude-chat_completions | chat_completions | project_department_setting | low | low |
| 工程（再换成 DeepSeek） | deepseek-chat_completions | chat_completions | project_department_setting | medium | medium |

运行中通过 `department_settings.save` 更换工程部门的模型与推理档位，下一次请求（工程部门）使用新的调用目标，选择来源为项目部门设置；请求档位与模型分别继承，档位按新模型的支持范围限制（第 5.3、7.3 节）。这与部门工作间按第 9.3 节显示的调用目标同一来源。

同一模型的连续请求回放推理内容：第一轮请求不带推理内容，同一模型在部门的第二轮请求带上第一轮的推理内容（evidence/step7_run_replay.json 中 chat 协议 `replayed_reasoning_messages: 1`，样例是上一轮 DeepSeek 的 `reasoning_content`）。更换模型以后请求不被上游拒绝：工程部门换成 Messages 上的 Claude 后，Messages 的请求不带上一个模型的推理内容，运行照常推进（evidence/step8_switch_no_replay.json 中 `phase_after_switch` 为 `ENGINEERING`，无停止原因，`messages_thinking_in_second_turn` 为 false）。

## 6. 修改凭据引用使准入作废、恢复与继续

证据：[evidence/step9_credential_recovery.json](evidence/step9_credential_recovery.json)。步骤：

1. 产品一步留下已完成的工作与限额。
2. 按外部修改目录文件的路径重写连接 `eval-messages` 的 `credential_ref`（改为另一个变量名）并 `reload()`。该连接下全部定义的准入作废（`stale: true`）。
3. 下一次激活：该部门的模型请求不发送，事项进入待恢复。决定请求 `model_unavailable` 写明「部门 engineering 的模型 ag/claude-opus-4-6-thinking 无法使用：模型 claude-messages 的准入已作废，请重新执行模型测试」，选项为「继续执行」与「停止事项」。决定请求事件在位置 31。
4. 修复凭据引用并重新执行模型测试，准入恢复（`stale: false`）。
5. 回答「继续执行」，决定请求的回答事件在位置 33；运行从这次请求接着进行，最终到 `DONE`。

已完成的工作与已用限额保留：继续以前的限额 7143 token，继续以后 67541 token（只增不减）；事项从这次请求接着进行，没有重建。

事件编号作为证据：`decision_requested` 位置 31、`decision_answered` 位置 33，同一 run 的事件日志中。

## 7. 导出以后重放一致，重放不发出模型请求

证据：[evidence/step10_export_replay.json](evidence/step10_export_replay.json)。从运行的数据目录复制一份独立副本，删掉原目录的依赖，从副本复核。

- 导出：`run.export` 交回投影、事件、尝试与用量，共 185 条事件。
- 重放：`replay.check` 交回 `consistent: true`，无差异。
- 重放不发模型请求：把副本的 Provider 模块指向空凭据（`use_env=False`，无覆盖），重放仍然 `consistent: true`。重放路径只读事件、工件与 Git 历史，没有任何调用目标解析或模型调用。

## 8. 事件、工件、日志与导出副本中没有 API Key

证据：[evidence/step10_export_replay.json](evidence/step10_export_replay.json)。以 35 个字符的真实 Key 为模式，扫描：

- 导出结构（投影、事件、尝试、用量）：`secret_hits_export` 为空。
- 数据目录的全部文件：`secret_hits_files` 为空。
- 导出中出现的 `api_key` 字样全部是 `credential_ref: "YUDAO_EVAL_API_KEY"`（凭据引用的变量名，设计第 4.6 节要求目录文档不含 Key、事件记录凭据引用），没有 Key 的取值。

## 9. 验收中发现并修正的实现缺陷

真实运行在 Anthropic Messages 协议上跨多轮工具时，上游返回 HTTP 400 `invalid_request_error`：`unexpected tool_use_id found in tool_result blocks`。原因是 `harness/providers/messages.py` 的 `_messages_input` 把历史里每个工具调用翻译成一条独立的 assistant 消息、每个工具结果翻译成一条独立的 user 消息，跨轮次时 role 不交替，违反 Messages 的要求。修正为把连续的同 role 回合合并成一条消息（多个 `tool_use` 或多个 `tool_result` 块），文本与紧随的工具调用合并进同一个 assistant 回合。同一处一并修正两处边界：assistant 回合里 thinking 块排到文本与工具调用之前（与上游返回的顺序一致，Anthropic 要求本轮思考块按原顺序回显）；空文本不产生文本块、不单独占一条消息（Anthropic 的 `TextBlockParam.text` 至少一个字符）。新增单元层测试 `harness/tests/test_protocol_history_replay.py` 的三项：`test_messages_history_merges_consecutive_turns_into_alternating_roles`、`test_messages_history_places_thinking_before_text_and_tool_use`、`test_messages_history_skips_empty_text_blocks`。已登记在 [architecture-issues.md](../architecture-issues.md)。

修正以后，第 6 节的真实事项运行在 Messages 协议上跨多轮工具到 `DONE`。两个 Messages 事件序列场景（`http_messages_handoff` 与 `http_messages_credential_rejected_then_continue`）的基准按修正后的请求形状重写，差异只在 Messages 请求体里工具结果与文本的块形状，事件种类、顺序与工具身份不变；这条有意改变已登记，请架构师核对。

## 10. 逐条验收核对

| 验收标准 | 结果 | 证据 |
| --- | --- | --- |
| 三种协议的连接测试与模型测试都有真实请求与响应的证据 | 通过 | 第 2 节；step1 |
| 使用 Anthropic Messages 连接的部门完成一次带工具往返的请求，记录请求体、身份头与真实响应 | 通过 | 第 4 节；step3、step4 |
| 请求事件中的调用目标、选择来源、请求档位与实际发送的档位和界面显示一致 | 通过 | 第 5 节；step6、step8 |
| 待恢复与继续执行的过程有事件编号作为证据 | 通过 | 第 6 节；step9（位置 31、33） |
| 事件、工件、日志与导出副本中没有 API Key | 通过 | 第 8 节；step10 |
| 事件导出以后重放一致，重放不发出模型请求 | 通过 | 第 7 节；step10 |
| 验收报告链接到本工单，并更新当前验收基线 | 通过 | 本报告第 1 节链接 #96；[当前验收基线](../../current-baseline.md) |

## 11. 复现方式

证据由 `.tmp/d24accept/` 下的脚本生成（中间结果目录已被 git 忽略）。脚本：`run_step1.py` 至 `run_step10.py` 与共享装配 `harness/tests/d24_acceptance_provider.py`。运行需要环境变量 `YUDAO_EVAL_BASE_URL` 与 `YUDAO_EVAL_API_KEY`；脚本不把 Key 写入任何文件。
