# Native Harness — 里程碑 2 spec（multi 编排：理解 → 计划执行 → 验证）

> 分支 exp/native-harness。目标：在里程碑 1 的 agent_loop 原语之上，实现 multi 模式——
> 三条独立 agent_loop 按「理解 → 计划执行 → 验证」事件驱动循环，直到验证判通过。
> solo 与 multi 共享同一 loop 原语、同一工具集、同一 summary schema，以保证可对比性。

## 0. 前置与约束（照抄，勿改）

- 复用里程碑 1：`harness/{provider,llm,tools,workspace,agent_loop,run_solo}.py`。**不得重写这些的既有行为**。
- 里程碑 1 的 solo 单测（21个）在本里程碑结束时**仍须全绿**（回归门）。
- 模型/协议/密钥纪律同里程碑 1（见 milestone1-spec.md §0-§2）。不重复。
- 语言 Python 3.12+，Windows。不引入新第三方依赖。

## 1. 对里程碑 1 的唯一扩展：terminal_tools（向后兼容）

`run_agent_loop` 增加可选参数 `terminal_tools: set[str] | None = None`：
- 当模型调用名字在 `terminal_tools` 里的工具时：**照常执行该工具的 handler**（拿到其结构化参数），
  记录该次调用的 args 到 `LoopResult.terminal_call`（新增字段：`dict | None`），
  执行完该工具后**立即停止 loop**，`stopped_reason="terminal"`。
- `terminal_tools=None`（solo 用）→ 行为与里程碑 1 **完全一致**（自然停 / max_steps）。
- 若到 max_steps 仍未调用终止工具 → `stopped_reason="max_steps"`，`terminal_call=None`（编排层据此判为该阶段失败）。
- 新增回归测试：solo 路径（不传 terminal_tools）事件序列/停止行为不变。

## 2. 状态机（编排核心）

```
state = UNDERSTAND ; round = 0
while round < MAX_ROUNDS:
  UNDERSTAND      → 跑理解 loop，产出 understanding（str）→ state = PLAN_EXECUTE
  PLAN_EXECUTE    → 跑计划执行 loop，落地实现文件      → state = VERIFY
  VERIFY          → 跑验证 loop，得 verdict：
                      pass                → state = DONE，break
                      reject_understanding→ state = UNDERSTAND ; round += 1
                      reject_execution    → state = PLAN_EXECUTE ; round += 1
超过 MAX_ROUNDS → state = ESCALATED（未收敛，记录），break
```

- 验证是**唯一**路由裁判；理解/计划执行不决定去向。
- 任一阶段 loop 以 `max_steps`/无 terminal_call 收场（该拿的产出没拿到）→ 记 `ESCALATED`，break。
- `MAX_ROUNDS` 默认 4（CLI 可调）。round 只在验证打回时 +1。

## 3. 阶段终止工具（新增，仅 multi 用）

三个终止工具放 `harness/stage_tools.py`（OpenAI function 格式 + handler）。handler 只做**记录/校验并回执**，
不改文件系统（产物由普通工具在阶段内写好）。它们与普通工具一起进 tools 列表传给对应阶段。

- `submit_understanding(summary, requirements, constraints, done_criteria)`
  - 四个必填字符串。handler 校验非空 → 回 `"understanding recorded"`；空字段 → 回 `"Error: <字段> is required"`（不终止，让模型补）。
  - UNDERSTAND 阶段终止工具。产出 = 四段拼成的 `understanding` 文本（编排层组装）。
- `submit_ready(notes)`
  - PLAN_EXECUTE 阶段终止工具，`notes`=实现要点/自测摘要（必填）。
- `submit_verdict(status, reason)`
  - VERIFY 阶段终止工具。`status` ∈ `{"pass","reject_understanding","reject_execution"}`（非法→`"Error: invalid status"` 不终止）；`reason` 必填。

> 终止工具只有被对应阶段列入 `terminal_tools` 才生效；跨阶段误用 → 该工具不在其 tools 列表，模型根本调不到。

## 4. 上下文封装：各阶段看得到什么（承重墙：验证独立）

编排层为每阶段**组装初始 user 消息**——"阶段独立"的结构性落点，不靠 prompt 自律。

- **UNDERSTAND**：`原始任务` + `工作区文件清单`（打回时附上一轮 verify 的 reject reason）。**不含**旧实现全文。
- **PLAN_EXECUTE**：`understanding 文本` + `文件清单`（打回时附 reject reason；它能读自己的现有实现去改）。
- **VERIFY**：`understanding 文本`（判据来源）+ `文件清单`。拿 understanding 当"应满足什么"的标准，独立跑功能测试判定。

> 验证阶段技术上能调 write/edit（工具集相同，符合"每阶段全套工具"设计）。本里程碑**不**从工具层禁它改代码；
> 靠 system prompt 明确其职责=验证+交 verdict，且其产出不被采信为交付物（交付物是 PLAN_EXECUTE 写的）。
> 更强的机械承重墙留待后续里程碑，此处登记为已知张力。

## 5. 阶段 system prompt（起点，可迭代；均在隔离工作区、可用全套工具）

**UNDERSTAND**:
> You are the UNDERSTANDING stage. Investigate the task and the existing workspace using tools.
> Your job is NOT to implement — it is to deeply understand WHAT must be true when the task is done.
> When ready, call submit_understanding with a crisp summary, the concrete requirements, the constraints,
> and the observable done-criteria. Do not write solution code.

**PLAN_EXECUTE**:
> You are the PLAN & EXECUTE stage, given the upstream understanding. Plan and implement it for real using
> tools (write/edit files, run commands to check your work). Realize every done-criterion as actually-working
> behavior. When complete and you have run it to confirm, call submit_ready with a brief note of what you
> built and how you verified it.

**VERIFY**:
> You are the VERIFICATION stage, given the upstream understanding (source of truth for "done") and the
> workspace. Independently verify whether the implementation satisfies the done-criteria: read delivered
> files and RUN functional checks (write/execute test scripts, invoke the program, inspect outputs). Judge
> from real execution evidence, not code reading alone. Then call submit_verdict: status="pass" if every
> criterion is met with evidence; "reject_execution" if the implementation fails a criterion (cite observed
> vs expected); "reject_understanding" if the understanding itself is wrong/insufficient (cite why).
> Do not modify the implementation; your role is to judge and route.

## 6. 模块与接口

### harness/stage_tools.py
```python
UNDERSTAND_TERMINAL="submit_understanding"; PLAN_TERMINAL="submit_ready"; VERIFY_TERMINAL="submit_verdict"
STAGE_TOOL_DEFS: dict[str, list]          # stage -> 该阶段终止工具 def（追加到普通 TOOL_DEFS）
STAGE_TOOL_HANDLERS: dict[str, callable]  # name -> handler(workspace_dir, **kwargs)->str
def parse_understanding(call_args: dict) -> str   # 四段 → 组装文本
```

### harness/orchestrator.py
```python
@dataclass
class StageRun: stage: str; loop: LoopResult; terminal_call: dict | None
@dataclass
class MultiResult:
    outcome: str            # "done" | "escalated"
    rounds: int
    stages: list[StageRun]
    understanding: str | None
    verdict: dict | None    # 最后一次 verify {status,reason}
    # 聚合成本（所有阶段累加）：calls/prompt/completion/reasoning tokens/duration_ms/tool_invocations
def run_multi(llm, workspace, task, max_rounds=4, max_steps=40, on_event=None) -> MultiResult
# 复用 run_agent_loop（传对应 tools + terminal_tools + 组装 system/user）；
# 每阶段发 stage_start/stage_end 事件（含 stage/round/terminal_call 摘要）。
```

### harness/run_multi.py
```python
# CLI: python -m harness.run_multi "<任务>" [--run-dir ...] [--max-rounds N] [--max-steps N] [--max-calls N]
# 装配同 run_solo，调 run_multi；写 events.jsonl + summary.json。
# summary 与 solo 同构 + 追加 mode="multi"/outcome/rounds/per-stage 成本/verdict。
# run_solo 的 summary 补 mode="solo"，两模式可直接对比。
```

## 7. 验收门（subagent 必须自测并如实报告）

1. **回归**：`python -m pytest harness/tests -q` 全绿，含里程碑 1 的 21 个（solo 行为未变）。
2. **新单测**（mock LlmClient，不联网）`harness/tests/test_orchestrator.py`：
   - terminal_tools：mock 调 submit_verdict 的 loop → stopped_reason=="terminal"、terminal_call 记录正确；solo 路径回归不变。
   - 三条边各一测：脚本化 mock 使 verify 依次返回 pass / reject_execution / reject_understanding，断言状态转移与 round 计数（reject_execution→PLAN_EXECUTE、reject_understanding→UNDERSTAND）。
   - MAX_ROUNDS 用尽 → outcome=="escalated"。
   - 阶段 loop 无 terminal_call（max_steps）→ outcome=="escalated"。
   - stage_tools：submit_understanding 空字段 Error 不终止；submit_verdict 非法 status Error。
3. **live smoke**（联网）：`python -m harness.run_multi "创建 fizzbuzz.py：接整数 N，逐行打印 1..N，3 的倍数打印 Fizz，5 的倍数 Buzz，15 的倍数 FizzBuzz；自己运行验证"`
   → 断言：走完≥1 轮三阶段、workspace 有 fizzbuzz.py、summary.json 的 outcome 合理、verdict 存在。
   **尽力跑；跑不通如实贴错误与诊断，绝不伪造通过。**

## 8. 不做（non-goals）

- 不做循环外裁判/隐藏 oracle（主线 agent 的活，不进 harness）。
- 不做独立 skill 抽象（验证用通用工具自己跑测试即可）。
- 不做上下文压缩/subagent/hooks/MCP。
- 不做「验证阶段工具层禁写」的强承重墙（靠 prompt+产物归属，张力已在 §4 登记）。
- 不改 provider.md、不碰 engine/、不碰 TS 平台、不动里程碑 1 既有行为。
