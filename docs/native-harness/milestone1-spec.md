# Native Harness — 里程碑 1 spec（solo 可跑通）

> 分支 exp/native-harness。目标：立起 agent_loop 原语，solo 模式端到端可跑。
> multi（理解→计划执行→验证）里程碑 2 复用同一 loop 原语，本里程碑不做。

## 0. 背景约束（照抄，勿自行更改）

- 语言 Python 3.12+。放置目录：仓库根的 `harness/`（全新，勿碰旧 engine/、勿碰 TS 平台）。
- 模型经 **OpenAI 兼容网关**（provider.md），**不是 Anthropic SDK**。用 `openai` 包（已装，2.30.0）。
- 参考骨架 `C:\project\learn-claude-code\s01_agent_loop\code.py` 的 while 循环思路，
  但**协议换成 OpenAI function-calling**（见 §2，已实测通过）。
- gemini-2.5-flash 是 thinking 模型：`message.content` 可能为 ""（正文被 reasoning 挤掉时），
  这不是错误；停止判断**只看有无 tool_calls**，不要只信 finish_reason。

## 1. provider.md 格式（当前真实格式，写匹配它的 loader）

```
key: sk-xxxxx
url: https://penguinapi.vip/
gemini-2.5-flash
```

loader 规则：逐行 strip；`key:` 前缀→key；`url:` 前缀→url；`model:` 前缀或**裸非空行**→model。
base_url = `url.rstrip("/") + "/v1"`。provider.md 已 gitignore，**密钥永不写入日志/事件/summary/代码**。

## 2. OpenAI function-calling 协议（已实测，照此实现）

- 工具定义：`{"type":"function","function":{"name","description","parameters":<JSON Schema>}}`
- 调用请求：`client.chat.completions.create(model, messages, tools, tool_choice="auto", max_completion_tokens=N)`
- 模型要调工具时：`resp.choices[0].finish_reason == "tool_calls"`，
  工具调用在 `resp.choices[0].message.tool_calls`（每个有 `.id`、`.function.name`、`.function.arguments`(JSON字符串)）。
- 回喂协议（**关键**）：
  1. 把 assistant 那条消息原样追加（含 tool_calls）：
     `{"role":"assistant","content":msg.content or None,"tool_calls":[...序列化...]}`
  2. **每个** tool_call 追加一条：`{"role":"tool","tool_call_id":<id>,"content":<工具输出字符串>}`
  - 一个回合可能多个 tool_call，必须全部执行、全部回结果，否则 API 报错。
- 停止：`finish_reason != "tool_calls"`（即没有 tool_calls）→ loop 结束。最后一条 assistant 的 `content` 是终答（可能为空）。
- usage：`resp.usage.prompt_tokens` / `completion_tokens`；reasoning 在 `usage.completion_tokens_details.reasoning_tokens`（单列记录）。

## 3. 模块与接口契约

### harness/provider.py
```python
def load_provider(path="provider.md") -> dict   # {"key","url","model"}；缺 key/url 抛 ValueError
def make_client(cfg: dict) -> OpenAI             # base_url=url+/v1, api_key=key, timeout=300, max_retries=0
```

### harness/llm.py
```python
@dataclass
class CallResult:
    text: str
    tool_calls: list          # 原始 tool_calls（供序列化回喂）
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int

class LlmClient:
    def __init__(self, client, model, max_calls=None): ...   # max_calls=None 不限
    def chat(self, messages: list, tools: list, max_completion_tokens=8000) -> CallResult
    # 累计 calls_made / prompt_tokens_total / completion_tokens_total / reasoning_tokens_total
    # 429/5xx/超时/连接错 → 退避重试最多 3 次；超 max_calls 抛 BudgetExhausted
```

### harness/tools.py
```python
# 每个工具：TOOL_DEFS（OpenAI 格式列表） + TOOL_HANDLERS: dict[str, callable]
# handler 签名 handler(workspace_dir: str, **kwargs) -> str（返回给模型的文本，出错返回 "Error: ..." 不抛）
# 工具集：read_file(path,limit?) / write_file(path,content) / edit_file(path,old,new) / bash(command) / list_dir(path?)
# 全部经 safe_path(workspace_dir, rel)：解析后必须在 workspace_dir 内，越界返回 Error（bash 的 cwd=workspace_dir）
# bash：危险命令黑名单（rm -rf /, sudo, shutdown, reboot, > /dev/, mkfs, :(){）+ 120s 超时 + 输出截断 50k
def dispatch(name: str, args: dict, workspace_dir: str) -> str   # 查表分发，未知工具返回 Error
```

### harness/workspace.py
```python
class Workspace:
    def __init__(self, root: str): ...   # 建目录
    dir: str
    def write_meta(self, name, text): ...  # 写到 root/.harness/ 下（产物区，不算交付物）
    def snapshot_files(self) -> dict[str,int]   # {相对路径: 字节数}，用于 summary
```

### harness/agent_loop.py — 核心原语
```python
@dataclass
class LoopResult:
    final_text: str
    steps: int              # LLM 轮数
    stopped_reason: str     # "natural" | "max_steps"
    tool_invocations: int
    events: list[dict]      # 逐步事件
    calls: int; prompt_tokens: int; completion_tokens: int; reasoning_tokens: int; duration_ms: int

def run_agent_loop(llm: LlmClient, system: str, user: str, tools, handlers_ctx: str,
                   max_steps=40, on_event=None) -> LoopResult:
    # messages=[{system},{user}]；while：llm.chat → 记 assistant → 无 tool_calls 则 stop=natural break
    #   → 否则对每个 tool_call：dispatch(name,args,handlers_ctx) 得输出 → append role:tool
    #   → 每步 emit 事件（llm_call / tool_call(name,args截断,output截断) / stop）
    #   → steps>=max_steps 强停 stop=max_steps
```
> handlers_ctx = workspace_dir（工具执行的根）。事件里**绝不含密钥**。

### harness/run_solo.py — solo 装配
```python
# CLI: python -m harness.run_solo "<任务描述>" [--run-dir runs/<ts>] [--max-steps N] [--max-calls N]
# 1) load_provider + make_client + LlmClient  2) 建 Workspace(run_dir/workspace)
# 3) SOLO_SYSTEM（见 §4）  4) run_agent_loop，on_event 逐行写 run_dir/events.jsonl
# 5) 写 run_dir/summary.json：task, model, stopped_reason, steps, tool_invocations, calls,
#    prompt/completion/reasoning tokens, duration_ms, files(snapshot), final_text
# 6) stdout 打印 summary 摘要
```

## 4. solo 系统提示（起点，可迭代）

> You are a software engineering agent working in an isolated workspace directory.
> You solve the user's task by using the provided tools to read, write, edit files and run commands.
> Work autonomously: investigate, implement, and verify your own work by running it.
> When the task is fully complete and you have verified it works, stop calling tools and give a brief final summary.
> Do not ask questions — make reasonable decisions and proceed.

## 5. 验收门（subagent 必须自测并报告结果）

1. **单测（不联网，mock LlmClient）** `harness/tests/`：
   - provider loader 能解析 §1 格式（含裸模型名行）；缺 key/url 抛错。
   - tools：safe_path 拦截 `../` 越界；write 后 read 一致；edit 命中/未命中；bash 黑名单拦截；未知工具返回 Error。
   - agent_loop：喂一个 mock LlmClient（脚本化返回：先 1 个 write_file tool_call，再无 tool_call），
     断言 loop 执行了工具、写了文件、stopped_reason=="natural"、事件序列正确、max_steps 能触发强停。
   - 全部 `python -m pytest harness/tests -q` 绿。
2. **live smoke（联网，需 provider.md）**：`python -m harness.run_solo "创建 add.py：命令行接两个整数参数，打印其和；然后自己运行 python add.py 2 3 验证输出 5"`
   → 断言 workspace 里有 add.py、summary.json 存在、stopped_reason 合理。**此步 subagent 尽力跑；跑不通如实报错误输出，不得伪造通过。**

## 6. 不做（本里程碑 non-goals）

- 不做 multi / 理解-计划-验证 / 路由 / 承重墙 / skill。
- 不做上下文压缩、subagent、hooks、cron、MCP。
- 不做循环外裁判（那是主线 agent 的活，不进 harness）。
- 不改 provider.md，不碰 engine/、不碰 TS 平台。

