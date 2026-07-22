# 三部门工单闭环 Harness 核心实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成已批准设计的 P0–P2：用五类机械工单、三个长期私有会话、受限本机工具、显式 Solo 完成协议和 Windows 外层 supervisor，干净取代旧 U/P/V 运行时。

**Architecture:** 保留现有 `LlmClient`、function-calling loop、增量计量和 fresh workspace 习惯；新增合同账本、角色会话、工单状态机、命名检查与原子产物层。模型只提交语义 payload；ticket ID、版本、父链、哈希、代码树和检查证据全部由控制层生成。旧 `orchestrator/run_multi/stage_tools/tools` 与 Aider runner 在新入口和测试通过后一次性删除，不留别名或兼容路由。

**Tech Stack:** Python 3.14、标准库（`dataclasses`、`enum`、`hashlib`、`json`、`pathlib`、`tempfile`、`subprocess`、`signal`、`shutil`）、OpenAI-compatible Python client、pytest。

---

## 0. 范围、后续计划与禁止事项

本计划只实施设计文档 `docs/native-harness/three-department-work-order-validation-design.md` 的 P0–P2，并交付可离线测试的 S/T 核心。以下工作不塞进同一计划：

1. **P3 development 校准题与新 experiment runner**：核心入口稳定后，先单独设计两道校准题的真实业务合同，再写 `scripts/work_order_experiment.py`。
2. **P4 12 道 formal 题库**：需要逐题设计、独立复核和 oracle 冻结，不能在没有具体题目规格时写空泛实施任务。
3. **P5 72 次 live 批次与报告**：必须等 P3/P4 通过并由 `NEXT.md` 明确授权模型与费用。

这不是缩减范围，而是按依赖关系拆成四个可独立验收的计划。本计划完成后，下一步是 P3 的 fixture brainstorming/spec，而不是直接调用 live 模型。

实施期间禁止：

- 调用真实 provider；所有测试使用 scripted/fake client。
- 新增第三方依赖。
- 让模型计算 ticket/hash/check receipt 等控制字段。
- 保留 `run_multi_cli`、cold/persistent、natural-stop router 或旧 terminal 工具兼容层。
- 使用 `shell=True`、命令字符串、路径黑名单或危险词黑名单替代能力边界。
- 暂存用户已有的 `docs/journal/2026-07-10.md` 与 `docs/native-harness/ISSUES-content-filter.md`。

## 1. Phase 0：已核实的实现依据

### 1.1 允许复用的现有 API

| API | 当前来源 | 复用方式 |
|---|---|---|
| `LlmClient.chat(messages, tools, max_completion_tokens=8000, accounting_role=None)` | `harness/llm.py:89-169` | 保留响应解析、calls/token/per-role 计量；增加 typed provider failure 与 retry 计数 |
| `LlmClient.check_budget(before_call=False)` | `harness/llm.py:65-87` | 保留 200 calls / 5400 秒协作式保险丝；不冒充外层强杀 |
| `LoopResult`、tool-call re-feed、allowed-tools gate、delta 计量 | `harness/agent_loop.py:56-68,119-321` | 保留；修 finish_reason，终端后跳过剩余 calls，最终改为显式 dispatcher |
| `AgentSession` 长期 messages 习惯 | `harness/agent_loop.py:71-116` | 迁移为 `harness/role_session.py::RoleSession`；删除 cold reset |
| `Workspace(root)` 与 deterministic snapshots 思路 | `harness/workspace.py:9-53` | 改成 chunked file hash、规范树哈希、拒绝 symlink/junction/special file |
| `seed_workspace(seed_dir, dest_dir)` fresh-copy 习惯 | `harness/seed.py:9-29` | 保留签名，改成只复制 regular files 且拒绝链接/特殊文件 |
| provider 装配与 fake response 形态 | `harness/provider.py:21-61`、`harness/tests/test_provider.py:20-80` | 新 S/T CLI 共用；密钥不写 summary/env |
| JSONL 每条 flush 与 session 紧凑序列化 | `harness/run_solo.py:57-62`、`harness/run_multi.py:33-38` | 收入 `harness/artifacts.py`，summary 改原子最后写 |
| FakeLLM 私有历史和 per-role 计量模式 | `harness/tests/test_agent_loop.py:13-85`、`test_orchestrator.py:30-145` | 移入 `harness/tests/fakes.py`，供所有新测试共享 |

### 1.2 已证实必须删除的边界

- `harness/orchestrator.py`：旧 U/P/V prompt、natural extract/router、consult、cold/persistent、自由文本 handoff 全部删除。
- `harness/run_multi.py`：由 `harness/run_team.py` 取代，不保留 re-export。
- `harness/stage_tools.py`：旧 terminal 和 import-time 全局 handler 注册删除。
- `harness/tools.py`：任意 `bash` 与全局 dispatcher 由 `local_tools.py` 取代。
- `scripts/aider_polyglot_runner.py`、`harness/tests/test_aider_runner.py`、`harness/tests/fixtures/mini_exercise/`：旧 S/P/C runner 及专属 fixture 删除；历史文档保留并标注 superseded。

### 1.3 新文件职责

| 文件 | 职责 |
|---|---|
| `harness/contracts.py` | 五类 ticket + Solo done payload 校验、控制头部、规范 JSON、SHA-256、账本与 terminal tool schema |
| `harness/role_session.py` | 单角色长期私有 messages、激活计数、loop 调用，不做路由 |
| `harness/local_tools.py` | 相对路径文件工具、protected paths、搜索、命名检查镜像、check receipt |
| `harness/process_control.py` | 参数数组子进程、真实墙钟、跨平台进程树终止；供命名检查与 supervisor 共用 |
| `harness/work_order_loop.py` | S/T 无关的 Team 状态机、工单 collector、返工、卡死、per-role/transition 计量 |
| `harness/artifacts.py` | JSON/JSONL 原子写入、流式 events、ticket/session/final tree 落盘 |
| `harness/run_team.py` | provider + workspace + runtime + Team loop 的单 run CLI |
| `harness/run_solo.py` | 重写为同工具边界、一个长期会话、显式 `submit_done` 的单 run CLI |
| `harness/supervisor.py` | 子进程监督、真实墙钟、Windows/POSIX 进程树终止、summary 完整性 |

---

## Task 1：修正 provider 停止语义与重试归类

**Files:**
- Modify: `harness/llm.py:13-195`
- Modify: `harness/agent_loop.py:156-229`
- Modify: `harness/tests/test_agent_loop.py`
- Modify: `harness/tests/test_provider.py`

- [ ] **Step 1: 写 finish_reason 与 transient failure 红灯测试**

在 `test_agent_loop.py` 复用现有 `_cr` helper（分别传入 `finish="content_filter"`、`finish="stop"` 和 `finish="length"`）与 `MockLlmClient`，新增：

```python
def test_content_filter_retries_same_context_without_recording_empty_assistant(tmp_path):
    llm = MockLlmClient([
        _cr(text="", finish="content_filter"),
        _cr(text="done", finish="stop"),
    ])
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm=llm,
        system="system",
        user="task",
        tools=[],
        handlers_ctx=str(tmp_path),
        messages=messages,
    )

    assert result.stopped_reason == "natural"
    assert result.calls == 2
    assert result.content_filter_retries == 1
    assert llm.message_snapshots[0] == llm.message_snapshots[1]
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert sum(e["type"] == "llm_call" for e in result.events) == 2
    assert any(e["type"] == "provider_retry" for e in result.events)


def test_repeated_content_filter_stops_as_provider_blocked(tmp_path):
    llm = MockLlmClient([
        _cr(text="", finish="content_filter"),
        _cr(text="", finish="content_filter"),
    ])

    result = run_agent_loop(
        llm=llm,
        system="system",
        user="task",
        tools=[],
        handlers_ctx=str(tmp_path),
    )

    assert result.stopped_reason == "provider_blocked"
    assert result.calls == 2
    assert result.content_filter_retries == 1
    assert all(e.get("reason") != "natural" for e in result.events)


def test_length_finish_is_not_natural(tmp_path):
    result = run_agent_loop(
        llm=MockLlmClient([_cr(text="partial", finish="length")]),
        system="system",
        user="task",
        tools=[],
        handlers_ctx=str(tmp_path),
    )
    assert result.stopped_reason == "output_truncated"
```

在 `test_provider.py` 用 monkeypatch 把 `_RETRYABLE` 临时设为 `(RuntimeError,)`，断言四次失败后抛 `ProviderUnavailable`，且 `retry_attempts == 3`。再为 bad request classifier 增加两个测试：provider code 精确等于 `context_length_exceeded` 时抛 `ContextOverflow`；thinking signature、普通 400 或未知 code 抛 `ProviderProtocolError`，不能误归因成任务失败。

- [ ] **Step 2: 运行红灯测试**

Run:

```bash
python -m pytest harness/tests/test_agent_loop.py harness/tests/test_provider.py -q
```

Expected: FAIL；当前 `content_filter` 被标成 `natural`，三个 typed provider exception 尚不存在。

- [ ] **Step 3: 最小实现 typed provider failure 与 finish_reason 分支**

在 `llm.py` 增加：

```python
class ProviderUnavailable(Exception):
    """Transient provider retries were exhausted."""


class ProviderProtocolError(Exception):
    """The provider rejected or malformed the request protocol."""


class ContextOverflow(Exception):
    """The provider explicitly reported context_length_exceeded."""


@dataclass
class LlmClient:
    # existing fields stay unchanged
    retry_attempts: int = field(default=0, init=False)
```

`_create_with_retry` 仅在确实准备再次请求时增加 `retry_attempts`；最后一次失败包装为：

```python
raise ProviderUnavailable(
    f"{type(last_exc).__name__}: {last_exc}"
) from last_exc
```

在 `run_agent_loop`：

1. 捕获 `ProviderUnavailable`，发 `provider_error` 和 `stop(provider_unavailable)`；
2. 捕获 `ContextOverflow` 为 `context_overflow`，捕获 `ProviderProtocolError` 为 `provider_protocol_error`；
3. `result.stopped_reason` 预算门优先；
4. 在 append assistant 之前处理 `content_filter`；第一次只记事件并原上下文重试，第二次 `provider_blocked`；
5. 无 tool calls 时仅 `finish_reason in {"stop", ""}` 可为 natural；`length` 为 `output_truncated`，其他值为 `provider_protocol_error`。

`LoopResult` 新增 `content_filter_retries: int`，每个 outbound context 最多计一次；后续成功工具回执形成新 context 后重置 retry allowance。

- [ ] **Step 4: 运行定向测试**

Run:

```bash
python -m pytest harness/tests/test_agent_loop.py harness/tests/test_provider.py -q
```

Expected: PASS；无 live provider 调用。

- [ ] **Step 5: 提交**

```bash
git add harness/llm.py harness/agent_loop.py harness/tests/test_agent_loop.py harness/tests/test_provider.py
git commit -m "fix(harness): classify provider stops explicitly" -m "Verified-By: python -m pytest harness/tests/test_agent_loop.py harness/tests/test_provider.py -q"
```

---

## Task 2：保证 terminal 后不再执行剩余工具

**Files:**
- Modify: `harness/agent_loop.py:231-307`
- Modify: `harness/tests/test_agent_loop.py`

- [ ] **Step 1: 写 terminal 顺序红灯测试**

构造一个 response，依次包含 `write_file`、合法 terminal、第二个 `write_file`。断言第一个写入执行，terminal 被接受，第二个写入被跳过，但 transcript 为所有 tool call 都补齐 tool response：

```python
def test_terminal_acceptance_skips_later_calls_and_completes_protocol(tmp_path):
    calls = [
        _tc("1", "write_file", {"path": "before.txt", "content": "ok"}),
        _tc("2", "submit_done", {"changed_files": ["before.txt"], "check_names": []}),
        _tc("3", "write_file", {"path": "after.txt", "content": "bad"}),
    ]
    terminal = lambda **_: "done recorded"
    result = run_agent_loop(
        llm=MockLlmClient([_cr(tool_calls=calls, finish="tool_calls")]),
        system="system",
        user="task",
        tools=TOOL_DEFS + [{"type": "function", "function": {"name": "submit_done", "description": "record completion", "parameters": {"type": "object", "properties": {"changed_files": {"type": "array", "items": {"type": "string"}}, "check_names": {"type": "array", "items": {"type": "string"}}}, "required": ["changed_files", "check_names"]}}],
        handlers_ctx=str(tmp_path),
        terminal_tools={"submit_done"},
        extra_handlers={"submit_done": terminal},
    )

    assert result.stopped_reason == "terminal"
    assert (tmp_path / "before.txt").read_text() == "ok"
    assert not (tmp_path / "after.txt").exists()
    assert any(e["type"] == "tool_call_skipped" for e in result.events)
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_agent_loop.py -q`

Expected: FAIL；当前 for-loop 会继续执行 terminal 后的调用。

- [ ] **Step 3: 实现终端短路但补齐 tool responses**

terminal 成功后：

- 保存 `terminal_call`；
- 对后续 tool calls 不 dispatch；
- 每个后续 call append `{"role":"tool", "tool_call_id":"该 call 的真实 ID", "content":"Skipped: terminal tool already accepted"}`；
- 发 `tool_call_skipped` 事件；
- 退出本轮。

非法 terminal 仍返回 `Error:` 并继续后续调用。

- [ ] **Step 4: 运行定向测试**

Run: `python -m pytest harness/tests/test_agent_loop.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/agent_loop.py harness/tests/test_agent_loop.py
git commit -m "fix(harness): stop dispatch after terminal ticket" -m "Verified-By: python -m pytest harness/tests/test_agent_loop.py -q"
```

---

## Task 3：实现控制层工单账本与规范哈希

**Files:**
- Create: `harness/contracts.py`
- Create: `harness/tests/test_contracts.py`

- [ ] **Step 1: 写 canonical hash、revision、parent chain 红灯测试**

```python
from harness.contracts import TicketLedger, TicketValidationError, validate_payload, verify_ticket

def _valid_acceptance(summary="summary"):
    return {
        "summary": summary,
        "requirements": [{"id": "R-001", "behavior": "write VALUE=42", "evidence": "public_tests"}],
        "edge_cases": [{"id": "E-001", "behavior": "module imports cleanly", "evidence": "public_tests"}],
        "regressions_to_avoid": [{"id": "G-001", "behavior": "existing files remain importable", "evidence": "public_tests"}],
        "fatal_conditions": [{"id": "F-001", "behavior": "tests are not modified", "evidence": "tree manifest"}],
        "constraints": ["standard library only"],
        "non_goals": ["no CLI"],
        "clarification_responses": [],
    }


def test_ledger_owns_header_revision_parent_and_hash():
    ledger = TicketLedger(task_id="task-1")
    first = ledger.issue(
        kind="acceptance",
        issuer="requirements",
        payload=_valid_acceptance(),
        parent_hash=None,
    )
    second = ledger.issue(
        kind="acceptance",
        issuer="requirements",
        payload=_valid_acceptance(summary="revised"),
        parent_hash=first["content_hash"],
    )

    assert first["ticket_id"] == "A-0001"
    assert second["ticket_id"] == "A-0002"
    assert second["revision"] == 2
    assert second["parent_hash"] == first["content_hash"]
    verify_ticket(first)
    verify_ticket(second)


def test_hash_is_key_order_independent_and_tampering_fails():
    ledger = TicketLedger("task-1")
    ticket = ledger.issue("acceptance", "requirements", _valid_acceptance(), None)
    reordered = json.loads(json.dumps(ticket, sort_keys=False))
    verify_ticket(reordered)
    reordered["payload"]["summary"] = "tampered"
    with pytest.raises(TicketValidationError, match="content_hash"):
        verify_ticket(reordered)
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_contracts.py -q`

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现最小账本**

核心 API 固定为：

```python
SCHEMA_VERSION = 1
ROLE_BY_KIND = {
    "acceptance": "requirements",
    "clarification": "engineering",
    "delivery": "engineering",
    "defect": "quality",
    "release": "quality",
    "solo_done": "solo",
}
PREFIX_BY_KIND = {
    "acceptance": "A",
    "clarification": "C",
    "delivery": "L",
    "defect": "D",
    "release": "R",
    "solo_done": "S",
}


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass
class TicketLedger:
    task_id: str
    tickets: list[dict] = field(default_factory=list)
    revisions: dict[str, int] = field(default_factory=dict)

    def issue(self, kind, issuer, payload, parent_hash, bindings=None) -> dict:
        validated = validate_payload(kind, payload)
        if ROLE_BY_KIND[kind] != issuer:
            raise TicketValidationError("issuer does not own ticket kind")
        revision = self.revisions.get(kind, 0) + 1
        body = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "ticket_id": f"{PREFIX_BY_KIND[kind]}-{revision:04d}",
            "task_id": self.task_id,
            "issuer": issuer,
            "revision": revision,
            "parent_hash": parent_hash,
            "bindings": bindings or {},
            "payload": validated,
        }
        ticket = {**body, "content_hash": content_hash(body)}
        verify_ticket(ticket)
        self.revisions[kind] = revision
        self.tickets.append(ticket)
        return ticket
```

`verify_ticket` 重算 hash，并校验 schema/kind/issuer/ticket prefix/revision/parent 字段类型。不要在此模块读文件或执行检查。

`TicketLedger.verify_chain()` 逐张重验 hash、revision 和 parent：`parent_hash` 必须为账本中已存在的直接触发 ticket 或初始 acceptance 的 `None`；issue 时也执行同一检查，不能先写坏链再事后发现。

- [ ] **Step 4: 运行定向测试**

Run: `python -m pytest harness/tests/test_contracts.py -q`

Expected: canonical、tamper、revision、issuer 测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/contracts.py harness/tests/test_contracts.py
git commit -m "feat(harness): add controlled work-order ledger" -m "Verified-By: python -m pytest harness/tests/test_contracts.py -q"
```

---

## Task 4：实现五类 payload 与 Solo done 的显式校验

**Files:**
- Modify: `harness/contracts.py`
- Modify: `harness/tests/test_contracts.py`

- [ ] **Step 1: 写完整 validator 矩阵红灯测试**

对每种 kind 至少覆盖一条成功和每个非平凡分支：

| kind | 必填规则 |
|---|---|
| acceptance | summary 非空；R/E/G/F 四组各至少一项；ID 前缀正确且全局唯一；behavior/evidence 非空；constraints/non_goals/clarification_responses 为 list |
| clarification | blocked IDs 非空；question/why_blocking 非空；interpretations 至少两项且 choice 唯一 |
| delivery | changed_files 为相对路径列表（允许一次合法空列表）；requirement_mapping、check_names 非空；mapping ID 存在于当前 acceptance（由 loop 再校验） |
| defect | route 仅 requirements/engineering；defects 非空；severity 仅 fatal/major/minor；复现、expected、actual、evidence names 非空 |
| release | verified_requirements、check_names 为非空唯一列表；decision 必须 release |
| solo_done | changed_files、check_names 非空；known_risks 为字符串列表 |

使用参数化测试：

`test_contracts.py` 同时定义以下完整有效 payload helper，供参数化测试只改一个字段：

```python
def _valid_clarification():
    return {"blocked_requirement_ids": ["R-001"], "question": "Which value?", "interpretations": [{"choice": "A", "observable_result": "41"}, {"choice": "B", "observable_result": "42"}], "why_blocking": "outputs differ"}

def _valid_delivery():
    return {"changed_files": ["answer.py"], "requirement_mapping": [{"requirement_id": "R-001", "files": ["answer.py"]}], "check_names": ["public_tests"], "known_risks": []}

def _valid_defect():
    return {"route": "engineering", "defects": [{"requirement_ids": ["R-001"], "severity": "major", "reproduction": ["run public_tests"], "expected": "exit 0", "actual": "exit 1", "evidence_check_names": ["public_tests"]}]}

def _valid_release():
    return {"verified_requirements": ["R-001", "E-001", "G-001", "F-001"], "check_names": ["public_tests"], "closed_defects": [], "decision": "release"}

def _valid_done():
    return {"changed_files": ["answer.py"], "check_names": ["public_tests"], "known_risks": []}
```

```python
@pytest.mark.parametrize(
    ("kind", "payload", "error"),
    [
        ("acceptance", {**_valid_acceptance(), "summary": ""}, "summary"),
        ("clarification", {**_valid_clarification(), "interpretations": [{}]}, "interpretations"),
        ("delivery", {**_valid_delivery(), "changed_files": ["../x.py"]}, "relative"),
        ("defect", {**_valid_defect(), "route": "both"}, "route"),
        ("release", {**_valid_release(), "decision": "pass"}, "decision"),
        ("solo_done", {**_valid_done(), "check_names": []}, "check_names"),
    ],
)
def test_invalid_payloads_fail_loudly(kind, payload, error):
    with pytest.raises(TicketValidationError, match=error):
        validate_payload(kind, payload)
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_contracts.py -q`

Expected: FAIL，validator 尚未覆盖矩阵。

- [ ] **Step 3: 实现显式 validator 与 terminal tool defs**

使用小型普通函数 `_required_text`、`_string_list`、`_unique_ids`、`_relative_paths`，不要引入 JSON Schema/Pydantic 依赖。新增常量：

```python
SUBMIT_ACCEPTANCE = "submit_acceptance"
SUBMIT_CLARIFICATION = "submit_clarification"
SUBMIT_DELIVERY = "submit_delivery"
SUBMIT_DEFECT = "submit_defect"
SUBMIT_RELEASE = "submit_release"
SUBMIT_DONE = "submit_done"

TERMINAL_TO_KIND = {
    SUBMIT_ACCEPTANCE: "acceptance",
    SUBMIT_CLARIFICATION: "clarification",
    SUBMIT_DELIVERY: "delivery",
    SUBMIT_DEFECT: "defect",
    SUBMIT_RELEASE: "release",
    SUBMIT_DONE: "solo_done",
}
```

为六个 terminal 工具提供 OpenAI function schema，但显式 Python validator 才是信任边界。工具 schema 只暴露语义 payload，绝不暴露 header/hash/exit code/result digest。

- [ ] **Step 4: 运行定向测试**

Run: `python -m pytest harness/tests/test_contracts.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/contracts.py harness/tests/test_contracts.py
git commit -m "feat(harness): validate work-order payloads" -m "Verified-By: python -m pytest harness/tests/test_contracts.py -q"
```

---

## Task 5：加固 workspace 树哈希与 visible seed

**Files:**
- Modify: `harness/workspace.py`
- Modify: `harness/seed.py`
- Create: `harness/tests/test_workspace.py`
- Create: `harness/tests/test_seed.py`

- [ ] **Step 1: 写链接、特殊文件与确定性树哈希红灯测试**

测试：相同内容不同创建顺序得到同一 tree hash；内容/路径变化改变 hash；`.harness/` 不计入；file symlink、directory symlink、Windows junction（`os.path.isjunction` 可用时）被拒绝；seed 源和目标中的链接/非 regular file 被拒绝。

```python
def test_tree_hash_is_order_independent_and_content_sensitive(tmp_path):
    a = Workspace(str(tmp_path / "a"))
    b = Workspace(str(tmp_path / "b"))
    (Path(a.dir) / "z.txt").write_text("z", encoding="utf-8")
    (Path(a.dir) / "a.txt").write_text("a", encoding="utf-8")
    (Path(b.dir) / "a.txt").write_text("a", encoding="utf-8")
    (Path(b.dir) / "z.txt").write_text("z", encoding="utf-8")
    assert a.tree_manifest() == b.tree_manifest()
    assert a.tree_hash() == b.tree_hash()
    (Path(b.dir) / "z.txt").write_text("changed", encoding="utf-8")
    assert a.tree_hash() != b.tree_hash()
```

- [ ] **Step 2: 运行红灯测试**

Run:

```bash
python -m pytest harness/tests/test_workspace.py harness/tests/test_seed.py -q
```

Expected: FAIL，API 和边界尚不存在。

- [ ] **Step 3: 实现 chunked hash 与安全 walk**

新增：

```python
def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_link_or_junction(path: str) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    return os.path.islink(path) or is_junction(path)


class Workspace:
    def tree_manifest(self) -> list[dict]:
        result = []
        for dirpath, dirnames, filenames in os.walk(self.dir, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name != ".harness")
            for dirname in dirnames:
                full_dir = os.path.join(dirpath, dirname)
                if _is_link_or_junction(full_dir):
                    raise ValueError(f"workspace directory link is not allowed: {full_dir}")
            for filename in sorted(filenames):
                full = os.path.join(dirpath, filename)
                if _is_link_or_junction(full):
                    raise ValueError(f"workspace file link is not allowed: {full}")
                mode = os.lstat(full).st_mode
                if not stat.S_ISREG(mode):
                    raise ValueError(f"workspace special file is not allowed: {full}")
                relative = os.path.relpath(full, self.dir).replace(os.sep, "/")
                result.append({
                    "path": relative,
                    "size": os.path.getsize(full),
                    "sha256": _sha256_file(full),
                })
        return result

    def tree_hash(self) -> str:
        return "sha256:" + hashlib.sha256(
            json.dumps(
                self.tree_manifest(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def diff_manifests(before: list[dict], after: list[dict]) -> list[str]:
    before_by_path = {item["path"]: (item["size"], item["sha256"]) for item in before}
    after_by_path = {item["path"]: (item["size"], item["sha256"]) for item in after}
    return sorted(
        path
        for path in before_by_path.keys() | after_by_path.keys()
        if before_by_path.get(path) != after_by_path.get(path)
    )
```

删除零调用方 `write_meta`，并让旧 `snapshot_files` / `snapshot_fingerprints` 临时从新 manifest 派生，Task 14 再删除旧名字。

同时修改 `Workspace.__init__`：只创建 workspace root，不再创建 `.harness/`；audit/check/ticket 全部位于 run 目录的 workspace 外。这样 fresh seed 的 destination 可机械要求为空。

`seed_workspace` 必须要求 destination 已存在但为空，仅复制 regular files；源包含 symlink/junction/special file 或目标已含同名路径时抛 `ValueError`。

- [ ] **Step 4: 运行定向测试**

Run:

```bash
python -m pytest harness/tests/test_workspace.py harness/tests/test_seed.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/workspace.py harness/seed.py harness/tests/test_workspace.py harness/tests/test_seed.py
git commit -m "feat(harness): harden workspace snapshots and seeds" -m "Verified-By: python -m pytest harness/tests/test_workspace.py harness/tests/test_seed.py -q"
```

---

## Task 6：实现受限文件工具与 protected paths

**Files:**
- Create: `harness/local_tools.py`
- Create: `harness/tests/test_local_tools.py`

- [ ] **Step 1: 写文件能力红灯测试**

覆盖：绝对路径、drive-relative、UNC、`..`、symlink/junction、protected file/dir 拒绝；read/write/edit/list/search 正常；list/search 不跟随链接；未知工具与坏参数大声失败；tool defs 中永远没有 `bash`。

```python
def test_runtime_rejects_escape_and_protected_paths(tmp_path):
    ws = Workspace(str(tmp_path / "workspace"))
    runtime = LocalToolRuntime(
        workspace=ws,
        checks={},
        protected_paths=("TASK.md", "tests/public"),
        audit_dir=tmp_path / "audit",
    )
    Path(ws.dir, "TASK.md").write_text("task", encoding="utf-8")

    assert runtime.dispatch("write_file", {"path": "../escape", "content": "x"}).startswith("Error:")
    assert runtime.dispatch("write_file", {"path": "C:escape", "content": "x"}).startswith("Error:")
    assert runtime.dispatch("edit_file", {"path": "TASK.md", "old": "task", "new": "x"}).startswith("Error:")
    assert runtime.dispatch("write_file", {"path": "tests/public/x.py", "content": "x"}).startswith("Error:")
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_local_tools.py -q`

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现 LocalToolRuntime 文件能力**

固定 API：

```python
READ_TOOL_NAMES = frozenset({"read_file", "list_files", "search_text", "run_check"})
WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})


@dataclass(frozen=True)
class CheckSpec:
    argv: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True)
class CheckReceipt:
    name: str
    tree_hash: str
    exit_code: int | None
    timed_out: bool
    stdout_digest: str
    stderr_digest: str
    duration_ms: int


@dataclass
class LocalToolRuntime:
    workspace: Workspace
    checks: dict[str, CheckSpec]
    protected_paths: tuple[str, ...]
    audit_dir: Path
    receipts: dict[tuple[str, str], CheckReceipt] = field(default_factory=dict)
    check_sequence: int = 0
```

实现以下三个公开方法，名称和返回类型固定：`tool_defs(writable: bool) -> list[dict]`、`handlers() -> dict[str, Callable]`、`dispatch(name: str, args: dict) -> str`。路径解析必须先拒绝空路径、`os.path.isabs(path)`、`os.path.splitdrive(path)[0]`、UNC 和任何 `..` component，再 realpath containment；每次操作拒绝 path chain 中的 symlink/junction。`search_text` 使用 literal substring，不把模型输入当 regex；只读 regular UTF-8 text，单文件最多 1 MiB，最多返回 200 行。`list_files` 返回最多 1000 个 sorted POSIX relative paths。

`protected_paths` 对 write/edit 使用“等于或位于目录下”判定。错误统一返回包含具体原因的 `Error:` 回执，不抛到模型 loop。

- [ ] **Step 4: 运行定向测试**

Run: `python -m pytest harness/tests/test_local_tools.py -q`

Expected: 文件能力、边界、权限矩阵 PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/local_tools.py harness/tests/test_local_tools.py
git commit -m "feat(harness): add restricted local file tools" -m "Verified-By: python -m pytest harness/tests/test_local_tools.py -q"
```

---

## Task 7：实现预登记检查与一次性镜像

**Files:**
- Modify: `harness/local_tools.py`
- Create: `harness/process_control.py`
- Modify: `harness/tests/test_local_tools.py`

- [ ] **Step 1: 写命名检查红灯测试**

覆盖：manifest argv 必须是非空字符串数组；timeout 为有限正数；Agent 只能传 name；检查在镜像中运行且真实 workspace 不变；receipt 绑定调用前 tree hash；代码变化后旧 receipt 不可查询；child env 不含测试注入的 `PROVIDER_KEY`；timeout、非零、不可解码输出都有结构化 receipt；超时检查启动的后代进程也被终止，不能在稍后写 sentinel。

```python
def test_run_check_uses_disposable_mirror_and_sanitized_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER_KEY", "must-not-leak")
    ws = Workspace(str(tmp_path / "workspace"))
    Path(ws.dir, "value.txt").write_text("before", encoding="utf-8")
    script = (
        "import os,pathlib;"
        "assert 'PROVIDER_KEY' not in os.environ;"
        "pathlib.Path('value.txt').write_text('inside-mirror')"
    )
    runtime = LocalToolRuntime(
        workspace=ws,
        checks={"public_tests": CheckSpec((sys.executable, "-c", script), 5.0)},
        protected_paths=(),
        audit_dir=tmp_path / "audit",
    )

    output = runtime.dispatch("run_check", {"name": "public_tests"})
    tree_hash = ws.tree_hash()
    receipt = runtime.receipt("public_tests", tree_hash)

    assert "exit=0" in output
    assert receipt is not None and receipt.exit_code == 0
    assert Path(ws.dir, "value.txt").read_text() == "before"
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_local_tools.py -q`

Expected: FAIL，check API 尚未实现。

- [ ] **Step 3: 实现 manifest loader、receipt lookup 与 run_check**

复用 Task 6 已定义的 `CheckSpec` / `CheckReceipt`，不要重复声明类型。`load_check_manifest` 完成 argv、timeout、protected paths 校验；`receipt(name, tree_hash)` 只返回精确当前证据。

`harness/process_control.py` 定义：

```python
@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    timed_out: bool
    duration_ms: int
```

`harness/process_control.py` 提供 `run_process_tree(argv, *, cwd, env, timeout_seconds, stdout_path, stderr_path) -> ProcessResult`：只接受参数数组，并把 stdout/stderr 直接流入指定文件，禁止在内存中无限累积输出；Windows 使用 `CREATE_NEW_PROCESS_GROUP`，超时时调用 `%SystemRoot%\\System32\\taskkill.exe /PID <pid> /T /F`，POSIX 使用 `start_new_session=True` 与 `os.killpg`，随后等待直接进程退出并返回 returncode/timed_out/duration。`run_check` 固定执行：tree manifest/hash → `TemporaryDirectory` → 复制 regular workspace tree → `self.check_sequence += 1` 并令 `sequence = self.check_sequence` → 定义 `audit_stdout = audit_dir / f"{sequence:04d}-{name}.stdout.log"` 与 `audit_stderr = audit_dir / f"{sequence:04d}-{name}.stderr.log"` → `run_process_tree(list(spec.argv), cwd=mirror, env=_safe_env(), timeout_seconds=spec.timeout_seconds, stdout_path=audit_stdout, stderr_path=audit_stderr)` → 从日志计算 digest 和截断回执 → 删除镜像 → 保存 `(name, tree_hash)` receipt。环境 allowlist 仅保留 `PATH/PATHEXT/SYSTEMROOT/WINDIR/TEMP/TMP` 中存在的项，并显式设 `PYTHONUTF8=1`；不复制任意 `*_KEY`。

`load_check_manifest(path)` 接受：

```json
{
  "protected_paths": ["TASK.md", "tests/public"],
  "checks": {
    "public_tests": {
      "argv": ["python", "-m", "pytest", "tests/public", "-q"],
      "timeout_seconds": 120
    }
  }
}
```

禁止额外 Agent 参数；receipt lookup 只按精确 name + 当前 tree hash。

- [ ] **Step 4: 运行定向测试**

Run: `python -m pytest harness/tests/test_local_tools.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/local_tools.py harness/process_control.py harness/tests/test_local_tools.py
git commit -m "feat(harness): run checks in disposable mirrors" -m "Verified-By: python -m pytest harness/tests/test_local_tools.py -q"
```

---

## Task 8：抽取长期私有 RoleSession

**Files:**
- Create: `harness/role_session.py`
- Create: `harness/tests/fakes.py`
- Create: `harness/tests/test_role_session.py`
- Modify: `harness/tests/test_agent_loop.py`（迁出 session 专属测试）

- [ ] **Step 1: 写长期重入与会话隔离红灯测试**

```python
def test_role_session_reentry_keeps_private_history(tmp_path):
    session = RoleSession(role="engineering", system="engineering system", tools=[])
    llm = ScriptedLlm([text_stop("first"), text_stop("second")])

    first = session.activate("handoff one", llm=llm, handlers_ctx=str(tmp_path))
    first_len = len(session.messages)
    second = session.activate("handoff two", llm=llm, handlers_ctx=str(tmp_path))

    assert first.stopped_reason == "natural"
    assert second.stopped_reason == "natural"
    assert len(session.messages) > first_len
    assert sum(m["role"] == "system" for m in session.messages) == 1
    assert "first" in json.dumps(llm.message_snapshots[1])


def test_role_sessions_never_share_message_lists():
    requirements = RoleSession("requirements", "r", [])
    engineering = RoleSession("engineering", "e", [])
    requirements.messages.append({"role": "assistant", "content": "PRIVATE_R"})
    assert "PRIVATE_R" not in json.dumps(engineering.messages)
    assert requirements.messages is not engineering.messages
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_role_session.py -q`

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现 RoleSession**

```python
@dataclass
class RoleSession:
    role: str
    system: str
    tools: list[dict]
    messages: list[dict] = field(default_factory=list, init=False)
    activates: int = 0

    def __post_init__(self) -> None:
        self.messages.append({"role": "system", "content": self.system})

    def activate(
        self,
        user_turn: str,
        *,
        llm: LlmClient,
        handlers_ctx: str,
        max_steps: int = 40,
        on_event=None,
        terminal_tools: set[str] | None = None,
        extra_handlers: dict | None = None,
    ) -> LoopResult:
        self.activates += 1
        return run_agent_loop(
            llm=llm,
            system=self.system,
            user=user_turn,
            tools=self.tools,
            handlers_ctx=handlers_ctx,
            max_steps=max_steps,
            on_event=on_event,
            terminal_tools=terminal_tools,
            extra_handlers=extra_handlers,
            accounting_role=self.role,
            messages=self.messages,
        )
```

不提供 `keep_history` 参数，不允许替换/共享 messages。把通用 scripted fake 从旧测试复制到 `harness/tests/fakes.py`，不要让生产代码依赖 test helper。

`harness/tests/fakes.py` 从 `test_agent_loop.py:13-85` 和 `test_orchestrator.py:30-100` 复制 SDK-shaped `_Fn/_ToolCall` 与 scripted client，统一导出：`call(name, args)`、`text_stop(text)`、`tool_result(name, args)`、`multi_tool_result(calls)`、`ScriptedLlm(script)`。`ScriptedLlm.chat` 必须 deepcopy 每次 messages、累计 calls/token/`usage_by_role`，并暴露 `message_snapshots`；不得包含任何生产分支。

- [ ] **Step 4: 运行相关测试**

Run:

```bash
python -m pytest harness/tests/test_role_session.py harness/tests/test_agent_loop.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/role_session.py harness/tests/fakes.py harness/tests/test_role_session.py harness/tests/test_agent_loop.py
git commit -m "feat(harness): add private persistent role sessions" -m "Verified-By: python -m pytest harness/tests/test_role_session.py harness/tests/test_agent_loop.py -q"
```

---

## Task 9：实现 Team happy path 与机械工单绑定

**Files:**
- Create: `harness/work_order_loop.py`
- Create: `harness/tests/test_work_order_loop.py`

- [ ] **Step 1: 写 Requirements → Engineering → Quality → Done 集成红灯测试**

使用真实 `LocalToolRuntime`、临时 Python public check 和 scripted LLM。脚本顺序必须包含：acceptance；write + run_check + delivery；QA 自己 run_check + release。

在 Task 8 的 `harness/tests/fakes.py` 增加以下真实 runtime 与 payload helpers，`test_work_order_loop.py` 与后续 `test_solo_loop.py` 都从该模块导入：

```python
def make_runtime_with_public_check(tmp_path):
    workspace = Workspace(str(tmp_path / "workspace"))
    check = CheckSpec((sys.executable, "-c", "import answer; assert answer.VALUE == 42"), 5.0)
    runtime = LocalToolRuntime(workspace, {"public_tests": check}, (), tmp_path / "audit")
    return workspace, runtime

def valid_acceptance_payload():
    return _valid_acceptance()

def valid_delivery_payload():
    return {"changed_files": ["answer.py"], "requirement_mapping": [{"requirement_id": "R-001", "files": ["answer.py"]}], "check_names": ["public_tests"], "known_risks": []}

def valid_release_payload():
    return {"verified_requirements": ["R-001", "E-001", "G-001", "F-001"], "check_names": ["public_tests"], "closed_defects": [], "decision": "release"}
```

把 Task 4 的 `_valid_acceptance` 内容复制为 `harness.tests.fakes.valid_acceptance_payload`，避免测试模块互相 import；其余 helpers 也由 fakes 模块导出。

```python
def test_team_happy_path_binds_tickets_to_real_tree_and_receipts(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm([
        tool_result("submit_acceptance", valid_acceptance_payload()),
        multi_tool_result([
            call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
            call("run_check", {"name": "public_tests"}),
            call("submit_delivery", valid_delivery_payload()),
        ]),
        multi_tool_result([
            call("run_check", {"name": "public_tests"}),
            call("submit_release", valid_release_payload()),
        ]),
    ])

    result = run_team(
        llm=llm,
        workspace=workspace,
        runtime=runtime,
        task_id="task-1",
        task="implement VALUE",
    )

    assert result.outcome == "done"
    assert [t["kind"] for t in result.tickets] == ["acceptance", "delivery", "release"]
    assert result.tickets[1]["bindings"]["code_tree_hash"] == workspace.tree_hash()
    assert result.tickets[2]["bindings"]["checks"][0]["exit_code"] == 0
    assert result.transitions == [
        "requirements->engineering",
        "engineering->quality",
        "quality->done",
    ]
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_work_order_loop.py -q`

Expected: FAIL，Team loop 尚不存在。

- [ ] **Step 3: 实现系统 prompt、collector 与 happy path**

固定 role/accounting keys：`requirements`、`engineering`、`quality`。状态枚举：

```python
class TeamState(str, Enum):
    REQUIREMENTS = "requirements"
    ENGINEERING = "engineering"
    QUALITY = "quality"
    DONE = "done"
```

三个 system prompt 固定为以下职责合同；实现可用相邻字符串拼接，文字不得在测试后按结果调优：

```python
REQUIREMENTS_SYSTEM = (
    "You are the Requirements department. Keep your own private history. "
    "The immutable user request and the newest validated ticket in each handoff "
    "override older memories. Investigate with read-only tools, never edit code, "
    "and end each activation with submit_acceptance."
)
ENGINEERING_SYSTEM = (
    "You are the Engineering department. Keep your own private history and never "
    "assume you can see another department's transcript. The immutable user request "
    "and newest validated acceptance ticket override older memories. Implement and "
    "run registered checks, then end with submit_delivery or submit_clarification."
)
QUALITY_SYSTEM = (
    "You are the Quality department. Keep your own private history and independently "
    "inspect the current code. Do not edit files and do not trust delivery claims "
    "without running registered checks. End with submit_defect or submit_release. "
    "The immutable user request and newest validated tickets override older memories."
)
```

固定 API：

```python
@dataclass
class TeamResult:
    outcome: str
    stopped_reason: str
    sessions: dict[str, RoleSession]
    tickets: list[dict]
    transitions: list[str]
    reworks: int
    calls: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int
    tool_invocations: int
    transient_retry_attempts: int
    content_filter_retries: int
    per_role: dict
```


`run_team` 的固定签名为：

```text
run_team(llm, workspace: Workspace, runtime: LocalToolRuntime, task_id: str, task: str, *, max_reworks: int = 8, max_steps: int = 40, on_event=None, on_ticket=None) -> TeamResult
```

函数内部使用显式 while/state branches，不创建通用 workflow engine。每次激活的 handoff 必含原始 L0、当前验收单、触发 ticket、当前 tree hash 和文件列表；绝不含其他会话 messages。

`TicketCollector` 只接受当前角色允许的 terminal：

- requirements：`submit_acceptance`
- engineering：`submit_clarification | submit_delivery`
- quality：`submit_defect | submit_release`

collector 调 `validate_payload`，从 runtime 读取当前 tree 的 receipts，控制层注入 bindings，再由 ledger issue；校验失败返回包含字段名和原因的 `Error:` 回执，不停止 loop。Engineering 每次接单时冻结 before manifest，提交 delivery 时用 `diff_manifests` 计算真实 changed files，并要求与 payload 集合精确一致（包含新增、修改和删除）；空集合可接受一次。release 要求所有验收 ID 精确覆盖、所有未关闭 defect 均列入 closed_defects、所有 check receipt 当前且 exit 0。

- [ ] **Step 4: 运行 happy-path 测试**

Run: `python -m pytest harness/tests/test_work_order_loop.py::test_team_happy_path_binds_tickets_to_real_tree_and_receipts -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/work_order_loop.py harness/tests/test_work_order_loop.py
git commit -m "feat(harness): run work-order team happy path" -m "Verified-By: python -m pytest harness/tests/test_work_order_loop.py::test_team_happy_path_binds_tickets_to_real_tree_and_receipts -q"
```

---

## Task 10：完成澄清、两类返工、格式纠错与卡死收口

**Files:**
- Modify: `harness/work_order_loop.py`
- Modify: `harness/tests/test_work_order_loop.py`

- [ ] **Step 1: 写完整状态与失败矩阵红灯测试**

新增独立行为测试：

1. engineering clarification → requirements acceptance revision 2 → engineering；
2. QA defect(route=engineering) → engineering 修复 → QA release；
3. QA defect(route=requirements) → requirements revision → engineering → QA；
4. 第一次 natural/非法 payload 在同一私有 session 收到纠错 handoff，第二次合法 ticket 可继续；
5. 连续两次无合法 ticket → `role_incomplete`；
6. QA write attempt 返回 unavailable error，真实 workspace 不变；
7. release 引用非当前 check、check 非零、验收 ID 不全或漏掉 open defect 均拒绝；
8. 相同 acceptance/tree/normalized defects 连续两次 → `stalled`；
9. 一次无代码变化 delivery 可用于纯规格澄清；连续两次无变化 delivery → `stalled`；
10. 第 9 个 QA defect 不再路由，结果 `max_reworks`；
11. provider_blocked/provider_unavailable/budget/context overflow 原样传播，不能改写成角色不完整；
12. per-role calls 求和等于 total，events 中 llm_call 数等于 calls。

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_work_order_loop.py -q`

Expected: FAIL，只有 happy path 已实现。

- [ ] **Step 3: 实现状态分支与机械卡死 fingerprint**

核心规则：

```python
def defect_fingerprint(ticket: dict) -> str:
    normalized = {
        "route": ticket["payload"]["route"],
        "defects": [
            {key: value for key, value in defect.items() if key != "defect_id"}
            for defect in ticket["payload"]["defects"]
        ],
    }
    return content_hash(normalized)
```

- clarification 和 route=requirements 的 defect 都进入 requirements；新 acceptance parent 为触发 ticket hash。
- route=engineering defect 进入 engineering；delivery parent 为 defect hash。
- release/defect parent 为当前 delivery hash。
- 没有合法 terminal 时，只对 `natural|terminal` 做一次纠错激活；provider/budget/length 类停止直接失败。
- reworks 只在 QA 接受 DefectTicket 时增加。
- per-role 使用 `llm.usage_by_role` before/after，记录 activates/message_count/message_chars/LLM duration。
- 所有 transition/ticket accepted/rejected/role activation/stop 都写事件，不写 private transcript、judge path 或 provider key。

- [ ] **Step 4: 运行完整 Team 测试**

Run: `python -m pytest harness/tests/test_work_order_loop.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/work_order_loop.py harness/tests/test_work_order_loop.py
git commit -m "feat(harness): close work-order rework loops" -m "Verified-By: python -m pytest harness/tests/test_work_order_loop.py -q"
```

---

## Task 11：重写 Solo 为同工具边界与显式 submit_done

**Files:**
- Modify: `harness/run_solo.py`
- Create: `harness/tests/test_solo_loop.py`

- [ ] **Step 1: 写 Solo 核心红灯测试**

把纯 loop 与 provider/文件装配分开，测试：合法 write + run_check + submit_done 才 outcome done；natural stop 纠错一次后仍无 submit_done 则 role_incomplete；done 缺当前 check receipt 被拒绝；同 runtime 没有 ticket/QA；metrics 使用 `solo` accounting role。

`test_solo_loop.py` 从 `harness.tests.fakes` 导入 `make_runtime_with_public_check`、`ScriptedLlm`、`multi_tool_result` 和 `call`；只在本文件新增 Solo payload helper：

```python
def valid_done_payload():
    return {"changed_files": ["answer.py"], "check_names": ["public_tests"], "known_risks": []}


def test_solo_requires_explicit_done_with_current_check(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm([
        multi_tool_result([
            call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
            call("run_check", {"name": "public_tests"}),
            call("submit_done", valid_done_payload()),
        ])
    ])

    result = run_solo_loop(
        llm=llm,
        workspace=workspace,
        runtime=runtime,
        task_id="task-1",
        task="implement VALUE",
    )

    assert result.outcome == "done"
    assert result.stopped_reason == "completed"
    assert result.completion["bindings"]["code_tree_hash"] == workspace.tree_hash()
```

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_solo_loop.py -q`

Expected: FAIL，`run_solo_loop` 尚不存在。

- [ ] **Step 3: 实现 SoloResult 与 run_solo_loop**

```python
@dataclass
class SoloResult:
    outcome: str
    stopped_reason: str
    session: RoleSession
    completion: dict | None
    calls: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int
    tool_invocations: int
    transient_retry_attempts: int
    content_filter_retries: int
    per_role: dict
```

一个长期 `RoleSession(role="solo")`，工具为 writable local defs + `submit_done`。run 开始时冻结 initial manifest；done collector 复用 contracts validator，以 `diff_manifests(initial, current)` 计算真实 changed files并要求与 payload 精确一致，再绑定 current tree/current receipts。natural/非法 payload 只纠错一次；provider/budget stop 原样失败。`SOLO_SYSTEM` 明确最新原始任务和公开工具为真源，不提三部门。

保留 `run_solo` 名称给 CLI 装配，但其实现留到 Task 12 完成；本 Task 先提供可注入 fake 的 `run_solo_loop`。

- [ ] **Step 4: 运行 Solo 与 Team 核心测试**

Run:

```bash
python -m pytest harness/tests/test_solo_loop.py harness/tests/test_work_order_loop.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/run_solo.py harness/tests/test_solo_loop.py
git commit -m "feat(harness): require explicit solo completion" -m "Verified-By: python -m pytest harness/tests/test_solo_loop.py harness/tests/test_work_order_loop.py -q"
```

---

## Task 12：统一原子产物并提供 run_team/run_solo 入口

**Files:**
- Create: `harness/artifacts.py`
- Create: `harness/run_team.py`
- Modify: `harness/run_solo.py`
- Create: `harness/tests/test_runners.py`
- Modify: `harness/tests/test_provider.py`

- [ ] **Step 1: 写产物与入口红灯测试**

使用 `test_provider.py:20-80` 的 scripted OpenAI client/monkeypatch 形态。分别运行 S/T，断言：

- 已存在 run dir 在读取 provider 前 fail-fast；
- `events.jsonl`、`checks/`、`sessions/`、`final_tree.json` 存在；
- T 只有 requirements/engineering/quality transcripts，S 只有 solo；
- tickets 每张独立 JSON，哈希可重新验证；
- `summary.json` 是最后原子产物并等于返回 dict；
- common summary 字段一致；
- 全部文本产物不含 fake provider key、checks manifest 绝对路径或字符串 `judge/`；
- missing usage + max_tokens 仍 `budget_accounting_error`；
- calls == llm_call event count，per-role calls 守恒。

- [ ] **Step 2: 运行红灯测试**

Run:

```bash
python -m pytest harness/tests/test_runners.py harness/tests/test_provider.py -q
```

Expected: FAIL，artifacts/run_team/new summary 尚不存在。

- [ ] **Step 3: 实现原子 writer 与两个 CLI**

`artifacts.py` 固定 API：

```python
def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


class EventWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("x", encoding="utf-8", newline="\n")
        self._seq = 0

    def append(self, event: dict) -> None:
        self._seq += 1
        record = {"seq": self._seq, **event}
        self._file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
```

同目录 temp + `os.replace`。session/ticket/final tree 在 summary 前写；summary 最后写。发生受控失败仍写完整 summary；未捕获崩溃由 supervisor 判缺 summary。

入口签名固定：

```text
run_team_cli(task: str, task_id: str, run_dir: str, seed_dir: str, checks_file: str, max_steps: int = 40, max_reworks: int = 8, max_calls: int = 200, max_tokens: int | None = None, max_seconds: float = 5400, provider_path: str = "provider.md") -> dict

run_solo(task: str, task_id: str, run_dir: str, seed_dir: str, checks_file: str, max_steps: int = 200, max_calls: int = 200, max_tokens: int | None = None, max_seconds: float = 5400, provider_path: str = "provider.md") -> dict
```

common summary 至少包含：schema_version、task_id、treatment、model、outcome、stopped_reason、limits、calls、三类 tokens、transient_retry_attempts、content_filter_retries、tool_invocations、duration_ms、llm_duration_ms、final_tree_hash、final_tree、per_role。T 额外 tickets/reworks/transitions；S 额外 completion。不得写 provider path/key。

- [ ] **Step 4: 运行入口测试**

Run:

```bash
python -m pytest harness/tests/test_runners.py harness/tests/test_provider.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add harness/artifacts.py harness/run_team.py harness/run_solo.py harness/tests/test_runners.py harness/tests/test_provider.py
git commit -m "feat(harness): add atomic solo and team runners" -m "Verified-By: python -m pytest harness/tests/test_runners.py harness/tests/test_provider.py -q"
```

---

## Task 13：实现外层 supervisor 与进程树强杀

**Files:**
- Create: `harness/supervisor.py`
- Create: `harness/tests/test_supervisor.py`

- [ ] **Step 1: 写成功、缺 summary、超时后代红灯测试**

低层 API 允许测试任意 argv；高层只构造 `python -m harness.run_solo|run_team`。测试 helper 启动一个 child，child 延迟写 sentinel；supervisor 超时后 sentinel 永不出现，证明杀的是进程树而非只杀直接进程。

```python
def test_timeout_kills_descendants_and_records_failure(tmp_path):
    sentinel = tmp_path / "child-survived.txt"
    code = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c',"
        f"\"import time,pathlib;time.sleep(1);pathlib.Path(r'{sentinel}').write_text('bad')\"]);"
        "time.sleep(60)"
    )
    result = supervise_command(
        [sys.executable, "-c", code],
        run_dir=tmp_path / "run",
        timeout_seconds=0.2,
        env={},
    )
    time.sleep(1.2)
    assert result.timed_out is True
    assert result.stop_reason == "hard_timeout"
    assert not sentinel.exists()
```

另测 child exit 0 + valid summary、exit 0 缺 summary、半写 JSON、nonzero exit。

- [ ] **Step 2: 运行红灯测试**

Run: `python -m pytest harness/tests/test_supervisor.py -q`

Expected: FAIL，模块尚不存在。

- [ ] **Step 3: 实现跨平台进程树监督**

```python
@dataclass(frozen=True)
class SupervisorResult:
    returncode: int | None
    timed_out: bool
    stop_reason: str
    duration_ms: int
    summary: dict | None
```


`supervise_command` 的固定签名为：

```text
supervise_command(argv: list[str], *, run_dir: Path, timeout_seconds: float, env: dict[str, str]) -> SupervisorResult
```

`supervise_command` 调用 Task 7 的 `run_process_tree`，不再实现第二套终止逻辑；`taskkill` 只存在于 `process_control.py` 控制面，不暴露给 Agent。

始终写原子 `supervisor.json`。只有 child returncode 0、未超时、`summary.json` 存在且 JSON 对象有效，stop_reason 才是 completed；其余分别为 hard_timeout/process_failed/summary_missing/summary_invalid。

高层 CLI 提供 `team` 与 `solo` 两个 subcommand；两者都要求 task、task-id、run-dir、seed-dir 和 checks-file，并把其余安全上限原样传给对应 child module。

- [ ] **Step 4: 运行 supervisor 测试**

Run: `python -m pytest harness/tests/test_supervisor.py -q`

Expected: PASS；Windows 后代 sentinel 不出现。

- [ ] **Step 5: 提交**

```bash
git add harness/supervisor.py harness/tests/test_supervisor.py
git commit -m "feat(harness): supervise run process trees" -m "Verified-By: python -m pytest harness/tests/test_supervisor.py -q"
```

---

## Task 14：干净切换、删除旧链并完成全量回归

**Files:**
- Modify: `harness/agent_loop.py`
- Modify: `harness/role_session.py`
- Modify: `harness/run_team.py`
- Modify: `harness/run_solo.py`
- Modify: `harness/tests/test_agent_loop.py`
- Modify: `harness/tests/test_role_session.py`
- Modify: `harness/tests/test_work_order_loop.py`
- Modify: `harness/tests/test_solo_loop.py`
- Delete: `harness/orchestrator.py`
- Delete: `harness/run_multi.py`
- Delete: `harness/stage_tools.py`
- Delete: `harness/tools.py`
- Delete: `harness/tests/test_orchestrator.py`
- Delete: `harness/tests/test_tools.py`
- Delete: `harness/tests/test_aider_runner.py`
- Delete: `harness/tests/fixtures/mini_exercise/`
- Delete: `scripts/aider_polyglot_runner.py`
- Modify: `AGENTS.md`
- Modify: `LOOP.md`
- Modify: `docs/native-harness/aider-polyglot-protocol.md`
- Modify: `docs/native-harness/aider-polyglot-tasklist.md`
- Modify: `docs/native-harness/milestone4-complex-study-protocol.md`
- Modify: `docs/native-harness/milestone3-study-protocol.md`
- Modify: `docs/native-harness/role-persistent-sessions-design.md`
- Modify: `NEXT.md`
- Modify: `docs/journal/2026-07-22.md`（追加验证记录，不替换已批准设计记录）

- [ ] **Step 1: 用符号引用检查锁定所有旧调用方**

执行实现时必须先用 LSP references（可用时）查询：`run_multi_cli`、`run_multi`、`AgentSession`、`activate`、`TOOL_DEFS`、`dispatch`、旧 terminal 常量。随后用字面搜索确认运行时代码中的旧标识。历史 markdown 可保留旧命令，但顶部必须明确 superseded。

Expected runtime references before deletion：只有旧模块、旧测试、旧 Aider runner；不得遗漏隐藏调用方。

- [ ] **Step 2: 将 agent_loop 改为唯一显式 dispatcher**

最终签名：

```text
run_agent_loop(llm: LlmClient, system: str, user: str, tools: list, dispatch_tool: Callable[[str, dict], str], max_steps: int = 40, on_event=None, terminal_tools: set[str] | None = None, *, accounting_role: str | None = None, messages: list[dict] | None = None) -> LoopResult
```

删除 `handlers_ctx`、`extra_handlers`、`on_stop`、`.tools.dispatch` import、`AgentSession`、`activate`、cold reset。`RoleSession.activate` 传入组合 dispatcher：terminal collector 优先，否则 `LocalToolRuntime.dispatch`。不保留 optional fallback。

- [ ] **Step 3: 删除旧运行时代码和迁移测试**

删除上表旧文件。把仍有价值的 allowed-tools、bad JSON、multi-tool、budget、event tests 留在 `test_agent_loop.py`，全部改为显式 dispatcher。旧 U/P/V、cold、consult、natural router、Aider S/P/C 测试直接删除，不翻译成新名字。

历史文档顶部加：

```markdown
> 状态：**SUPERSEDED / HISTORICAL**  
> 新方案：`three-department-work-order-validation-design.md`  
> 旧命令仅用于解释历史结果，当前运行时已移除。
```

`AGENTS.md` 与 `LOOP.md` 把真实入口改为 `harness.run_team`；仍保留“live 必须冻结且 NEXT 授权”。`NEXT.md` 仅在全量测试通过后把 W1–W3 标完成，并把下一步设为 P3 development fixture 设计。

- [ ] **Step 4: 运行无 live 的完整验证**

Run:

```bash
python -m pytest harness/tests -q
python -m harness.run_solo --help
python -m harness.run_team --help
python -m harness.supervisor --help
```

Expected:

- pytest 全部 PASS，0 skipped；
- 三个入口 `--help` exit 0；
- 无 provider 调用；
- 运行时代码无 `run_multi|UNDERSTAND|PLAN_EXECUTE|VERIFY|submit_understanding|submit_ready|submit_verdict|consult_understanding|session_model|shell=True`；
- `summary.json` 原子最后写、content_filter 测试、后代强杀测试均在全量套件中执行。
随后按仓库要求调用语言专项 reviewer，修完 blocker 后重跑同一验证。

- [ ] **Step 5: 更新 journal、精确暂存、提交并 push**

journal 记录命令、通过数、skip 数、无 live、删除边界和已知软隔离限制。只暂存本计划明确路径，不暂存用户已有变更。

```bash
git add AGENTS.md LOOP.md NEXT.md harness/agent_loop.py harness/role_session.py harness/run_team.py harness/run_solo.py harness/tests/test_agent_loop.py harness/tests/test_role_session.py harness/tests/test_work_order_loop.py harness/tests/test_solo_loop.py docs/native-harness/aider-polyglot-protocol.md docs/native-harness/aider-polyglot-tasklist.md docs/native-harness/milestone3-study-protocol.md docs/native-harness/milestone4-complex-study-protocol.md docs/native-harness/role-persistent-sessions-design.md docs/journal/2026-07-22.md
git add harness/orchestrator.py harness/run_multi.py harness/stage_tools.py harness/tools.py harness/tests/test_orchestrator.py harness/tests/test_tools.py harness/tests/test_aider_runner.py harness/tests/fixtures/mini_exercise/mini.py harness/tests/fixtures/mini_exercise/mini_suite.py harness/tests/fixtures/mini_exercise/.meta/config.json harness/tests/fixtures/mini_exercise/.meta/example.py harness/tests/fixtures/mini_exercise/.docs/instructions.md scripts/aider_polyglot_runner.py
git commit -m "feat(harness): cut over to work-order departments" -m "Verified-By: python -m pytest harness/tests -q"
git push origin exp/native-harness
```

暂存前必须用 `git status --short --branch` 核对路径；若任何明确路径包含计划外用户改动，先停下并拆分该文件，不能扩大暂存范围。

---

## 2. 完成定义

本计划完成时必须同时成立：

1. S 与 T 都通过同一个 `LocalToolRuntime`，没有 Agent 任意 shell。
2. Team 三个长期会话私有且不串线；最新有效 ticket 高于旧记忆。
3. 五类 ticket 和 Solo done 的控制字段全部由控制层生成、可重验哈希。
4. 只有合法 release/done 能自报完成；natural/空回复/content_filter 都不能放行。
5. 检查只按 manifest 名执行，在一次性镜像运行，receipt 绑定当前代码树。
6. 绝对路径、drive/UNC、`..`、symlink、junction、特殊文件与 protected path 被拒绝。
7. summary 最后原子写；外层 supervisor 能杀整个进程树并分类缺 summary。
8. 旧 U/P/V、cold/persistent、consult、Aider S/P/C 运行时和测试已删除，无 shim。
9. `python -m pytest harness/tests -q` 全绿且 0 skipped；三个 CLI `--help` 可运行。
10. 没有 live 调用；下一步明确是 P3 两道 development fixture 的独立设计与计划。

## 3. 后续计划入口

本计划验证通过后，按以下顺序重新走 brainstorming → spec → plan：

1. **P3：两道 development fixture + `scripts/work_order_experiment.py`**：同时锁定 manifest/score schema、attempt 目录、paired infrastructure retry 和离线 fake S/T dry-run。
2. **P4：12 道 formal fixture catalog**：逐题给出 task/visible/judge/reference/incomplete patches，独立复核后冻结 realized schedule。
3. **P5：72 runs 与报告**：只在 `NEXT.md` 明确授权模型、费用和冻结 commit 后执行。
