# 事件序列按会话比较的探针（#469 验收 3）：跨会话交错通过，会话内 swap、交接边反向、
# 工具结果提前到回答之前失败并写明差异。比较器见 harness/tests/event_sequence.py 末尾的 compare_documents。
# 前三个探针直接读基准 JSON，在内存里变换事件数组的顺序后调 compare_documents：不重写基准文件，
# 不重新走事件规整，shared 与 artifacts 的标签编号保持稳定，只断言分组比较与因果边的差异点。
# 第四个探针用最小合成文档覆盖询问链（基准里询问链与同组事件交织，单步移动必然先碰到分组比较）；
# 第五、六个探针覆盖投影比较（#541）：只改投影字段、事件与投影同时改两种情况。
# 后面的探针（#892）覆盖事件引用与事项累计数：引用写成被引用事件在它自己会话里的位置，
# 两个会话交错的先后不同不影响比较；会话内引用换了指向要失败并写明会话、第几条与字段名。
# 末尾的探针（#1019）覆盖只为真实变化重写：只差编号数字时通过、同一个值变成两个编号或两个值并成
# 一个编号时失败；投影里的事件版本号不进比对；关键字段等于默认值时与缺失同义，工具调用的 ok 照写。
# 事件版本号当前值的单独核对在 test_event_sequence.py（那个文件在本工单的「只改」清单里）。

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.tests.event_sequence import compare_documents, normalized_run

BASELINE_DIR = Path(__file__).resolve().parent / "event_sequences"

# 编号的写法 <种类#数字>：与 event_sequence.py 的规整规则第 2 条一致
_PLACEHOLDER = re.compile(r"<([a-z][a-z0-9_]*)#(\d+)>")


def _load(name):
    return json.loads((BASELINE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _swap(events, first, second):
    events[first], events[second] = events[second], events[first]


def _index(events, predicate):
    return next(index for index, event in enumerate(events) if predicate(event))


# 因果边由这些事件种类给出：调换它们与别的会话的事件会改变因果边的方向（工单 #556）
_OUTCOME_TYPES = {"spec_accepted", "contract_accepted", "delivery_accepted", "qa_submitted",
                  "baseline_review_accepted", "run_done", "ask_started", "ask_answered"}


def _adjacent_cross_session_pair(events):
    # 相邻的、分属两个会话、且不带因果边的两条事件：调换它们不改变任何会话内部的顺序，
    # 也不改变因果边的方向（工单 #557：同时运行的会话让事件的全局顺序随运行变化，
    # 基准的比较按会话进行，这样的调换应当仍然通过）
    for index in range(len(events) - 1):
        one, other = events[index], events[index + 1]
        if one.get("session_id") == other.get("session_id"):
            continue
        if one["type"] in _OUTCOME_TYPES or other["type"] in _OUTCOME_TYPES:
            continue
        return index, index + 1
    raise AssertionError("no adjacent events from different sessions without a causal edge")


def test_cross_session_interleave_still_passes():
    # 调换两个会话之间事件交错的先后（会话内部顺序与因果关系不变）：两个会话各自收尾与开头的
    # 事件在数组里相邻且分属两组，调换后两组各自的内部顺序不变，成果 → activation 边的方向也不变，
    # 应通过
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    first, second = _adjacent_cross_session_pair(events)
    _swap(events, first, second)
    third, fourth = _adjacent_cross_session_pair(events)
    _swap(events, third, fourth)
    compare_documents("handoff_release", expected, actual)


def test_intra_session_swap_fails_with_diff():
    # 调换工程会话内部两条相邻的同类工具事件：会话内顺序变了，分组比较应失败并点名差异
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    first = _index(events, lambda e: e["session_id"] == "<ses_eng#1>" and e["type"] == "tool_called")
    second = first + 1
    while not (events[second]["session_id"] == "<ses_eng#1>"
               and events[second]["type"] == events[first]["type"]):
        second += 1
    _swap(events, first, second)
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "session <ses_eng#1>" in message, message
    assert "differs" in message, message


def test_handoff_edge_reversed_fails_with_diff():
    # 让交付的接纳落在下一个部门开始之后：把交付以后的质检部门激活搬到交付被接纳之前。
    # 搬家跨过的事件里没有质检组的事件，每个会话内部的相对顺序都不变，分组比较通过；
    # 但成果 → 下一个部门开始的因果边反向，应失败并点名因果边（工单 #556：没有阶段迁移事件，
    # 因果边由正式成果给出）
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    outcome = _index(events, lambda e: e["type"] == "delivery_accepted")
    activation = _index(events, lambda e: e["type"] == "department_activated"
                        and e["session_id"] == "<ses_qua#1>" and e["event"] > events[outcome]["event"])
    assert events[outcome]["type"] == "delivery_accepted"
    assert events[activation]["type"] == "department_activated"
    assert outcome < activation
    assert all(e.get("session_id") != "<ses_qua#1>" for e in events[outcome:activation])
    item = events.pop(activation)
    events.insert(outcome, item)
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "causal edges differ" in message, message


def _ask_documents(moved=False):
    # 最小的询问链文档：工程询问 → 产品分支的第一条事件 → 产品回答 → 工程工具结果
    asked = {"event": "e1", "type": "ask_started", "session_id": "eng",
             "payload": {"branch_session_id": "pro-branch"}}
    start = {"event": "e2", "type": "department_activated", "session_id": "pro-branch",
             "payload": {}}
    answer = {"event": "e3", "type": "ask_answered", "session_id": "pro-branch",
              "payload": {"status": "answered"}}
    tool = {"event": "e4", "type": "tool_called", "session_id": "eng",
            "payload": {"name": "ask"}}
    events = [asked, start, answer, tool]
    if moved:
        events = [asked, start, tool, answer]
    return {"scenario": "ask", "covers": "ask", "projection": {},
            "events": [dict(e) for e in events]}


def test_tool_result_before_response_fails_with_diff():
    # 让工具结果出现在对应的回答之前：工具事件与回答分属两组，移动后每个会话内部的
    # 相对顺序都不变，分组比较通过；但回答 → 工具结果的因果边消失，应失败并点名因果边
    expected = _ask_documents()
    compare_documents("ask", expected, copy.deepcopy(expected))
    with pytest.raises(AssertionError) as raised:
        compare_documents("ask", expected, _ask_documents(moved=True))
    message = str(raised.value)
    assert "causal edges differ" in message, message


def test_projection_difference_fails_with_fields_line():
    # 只改投影的一个字段、事件不动（#541 步骤 3 第 1 项，把放行结果改为未完成）：投影是事件
    # 推出来的结果，事件一致时失败应落在投影上，并在 `fields:` 一行写明是哪个键
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    assert actual["projection"]["status"] == "done"
    actual["projection"]["status"] = "running"
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "handoff_release" in message, message
    assert "projection differs" in message, message
    assert "fields: status" in message, message


def test_event_difference_reported_before_projection():
    # 同时改质检 qa_submitted 事件的 payload.verdict 与投影的 status（#541 步骤 3 第 2 项）：
    # 两边都不一致时，信息先报事件，写明是哪个会话、会话内第几个事件与哪个字段，不报投影
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    index = next(i for i, e in enumerate(actual["events"]) if e["type"] == "qa_submitted")
    actual["events"][index]["payload"]["verdict"] = "rework_engineering"
    actual["projection"]["status"] = "running"
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "handoff_release" in message, message
    assert "session <ses_qua#1>" in message, message
    assert "event #" in message, message
    assert "payload.verdict" in message, message
    assert "projection differs" not in message, message


def test_payload_field_difference_fails_with_fields_line():
    # 只改一条事件的一个载荷字段（质检放行改为退回）：同一会话内同一位置的事件载荷不同，
    # 分组比较应失败，并在 `fields:` 一行点名是哪个字段（#532 步骤 5 第 3 条）
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    index = next(i for i, e in enumerate(events) if e["type"] == "qa_submitted")
    assert events[index]["payload"]["verdict"] == "release"
    events[index]["payload"]["verdict"] = "rework_engineering"
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "handoff_release" in message, message
    assert "session <ses_qua#1>" in message, message
    assert "event #" in message, message
    assert "payload.verdict" in message, message


# 工单 #892：事件引用与事项累计数。
# 两个会话的事件各写一份，交错的先后不同；引用写成被引用事件在它自己会话里的位置，
# 规整以后两份按会话比较相等（不靠运行碰运气，直接构造两份事件序列）。

_ENGINEERING_SESSION = "ses_eng_0123456789abcdef"
_QUALITY_SESSION = "ses_qua_fedcba9876543210"


class _StubStore:
    def __init__(self, events):
        self._events = events

    def list_events(self, run_id):
        return list(self._events)


class _StubSystem:
    # 规整一次事件序列只需要事件、投影与数据目录；合成的事件没有工件引用，用不到工件存储
    def __init__(self, events):
        self.store = _StubStore(events)
        self.data_dir = "C:/yudao-synthetic-data"
        self.artifacts = None

    def project(self, run_id):
        return SimpleNamespace(canonical_state=dict)


def _event(event_id, session_id, type_, department, payload, parent=None):
    return SimpleNamespace(
        event_id=event_id, run_id="run_synthetic", type=type_, role=None, parent_event_id=parent,
        state_before="running", state_after="running", payload=payload, artifact_hashes=[],
        session_id=session_id, actor="system", department=department, stop_reason=None, error=None)


def _session_events(session_id, department, suffix, reference="activation"):
    # 一个会话的三条事件：开始、一次模型请求、结束。模型请求引用开始那条事件；
    # reference 换成 request 时就是「引用换了指向」（指向同会话的另一条）。
    activation = f"evt_{suffix}000000000000001"
    request = f"evt_{suffix}000000000000002"
    finished = f"evt_{suffix}000000000000003"
    return [
        _event(activation, session_id, "department_activated", department,
               {"activation_id": f"act_{suffix}000000000000001", "cycle": 1,
                "effective_contract_hash": None, "guidance_ids": [],
                "guidance_version": 0, "input_version": 1, "prompt_version": 0}),
        _event(request, session_id, "model_requested", department,
               {"activation_id": f"act_{suffix}000000000000001", "attempt": 1,
                "attempt_id": f"att_{suffix}000000000000001", "attempted": True,
                "context_event_id": activation if reference == "activation" else request,
                "effective_contract_hash": None, "guidance_ids": [],
                "input_version": 1, "logical_call_id": f"call_{suffix}000000000000001",
                "max_attempts": 3, "prompt_version": 0, "purpose": "work",
                "retry_of_step_id": None, "step_id": f"step_{suffix}000000000000001"},
               parent=activation),
        _event(finished, session_id, "activation_finished", department,
               {"activation_id": f"act_{suffix}000000000000001", "activations": 2, "model_steps": 3,
                "guidance_ids": [], "input_version": 1, "prompt_version": 0,
                "session_activations": 1, "session_elapsed_ms": 120, "session_model_steps": 1,
                "stop_reason": None},
               parent=activation),
    ]


def _two_sessions(reference="activation"):
    engineering = _session_events(_ENGINEERING_SESSION, "engineering", "a", reference)
    quality = _session_events(_QUALITY_SESSION, "quality", "b", reference)
    return engineering, quality


def _normalized(events):
    return normalized_run(_StubSystem(events), "run_synthetic")


# 事项的累计数不进会话内事件的比较（工单 #892）：会话事件里不再有 activations、model_steps、cycle，
# 会话自己的累计数 session_activations、session_model_steps 保留，事项的总数在投影里比较。
_ITEM_TOTALS = ("activations", "model_steps", "cycle")
_GLOBAL_POSITION = re.compile(r"^<evt#\d+>$")
_SESSION_POSITION = re.compile(r"^(?:<[^>]+>|__run__)#\d+$")


def test_interleaved_sessions_compare_equal():
    # 同一份事件，两个会话交错的先后不同（每个会话内部的事件相同）：
    # 规整以后引用写成会话内的位置，两份按会话比较相等（工单 #892）
    engineering, quality = _two_sessions()
    first = _normalized([engineering[0], quality[0], engineering[1], quality[1],
                         engineering[2], quality[2]])
    second = _normalized([quality[0], engineering[0], quality[1], engineering[1],
                          quality[2], engineering[2]])
    assert first != second, "两份事件记录的交错应当不同"
    compare_documents("synthetic", first, second)


def test_session_reference_change_fails_with_fields_line():
    # 会话内某条事件引用的事件变了（模型请求改为引用同会话的另一条）：
    # 比较失败，信息写明会话、会话内第几条与字段名（工单 #892）
    engineering, quality = _two_sessions()
    expected = _normalized([engineering[0], quality[0], engineering[1], quality[1],
                            engineering[2], quality[2]])
    changed, _ = _two_sessions(reference="request")
    actual = _normalized([changed[0], quality[0], changed[1], quality[1],
                           changed[2], quality[2]])
    with pytest.raises(AssertionError) as raised:
        compare_documents("synthetic", expected, actual)
    message = str(raised.value)
    assert "session <ses_eng#1>" in message, message
    assert "event #" in message, message
    assert "payload.context_event_id" in message, message


def test_normalized_references_are_session_positions():
    # 规整以后引用写成被引用事件在它自己会话里的位置，不写全局位置（工单 #892）
    engineering, quality = _two_sessions()
    document = _normalized([engineering[0], quality[0], engineering[1], quality[1],
                            engineering[2], quality[2]])
    references = [event["parent_event_id"] for event in document["events"]]
    references += [event["payload"].get("context_event_id") for event in document["events"]
                   if "context_event_id" in event["payload"]]
    assert "<ses_eng#1>#1" in references
    assert "<ses_qua#1>#1" in references
    assert all(reference is None or not _GLOBAL_POSITION.match(reference)
               for reference in references), references


# 事项的累计数不进会话内事件的比较（工单 #892）：会话事件里不再有 activations、model_steps、cycle，
# 会话自己的累计数 session_activations、session_model_steps 保留，事项的总数在投影里比较。
# 等于默认值 0 的会话累计数按 #1019 的规则省略：一次在模型调用中途被取消的激活没有模型步，
# session_model_steps 就不写；比对时缺失与 0 同义，所以这里按「缺失即 0」核对，不再要求一定有键。
def test_baselines_keep_session_totals_only():
    steps_recorded = False
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for event in document["events"]:
            payload = event.get("payload") or {}
            if event.get("session_id"):
                for field in _ITEM_TOTALS:
                    assert field not in payload, f"{path.name} 的会话事件里还有事项累计数 {field}"
            if event["type"] == "activation_finished":
                activations = payload.get("session_activations", 0)
                assert activations >= 1, f"{path.name} 的激活结束事件少了 session_activations"
                steps_recorded = steps_recorded or payload.get("session_model_steps", 0) >= 1
    assert steps_recorded, "基准里没有一次模型步被记进会话累计数"


def test_baseline_references_are_session_positions():
    # 基准里的引用写成会话内的位置：父事件与载荷里的事件编号都不写全局位置（工单 #892）
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for event in document["events"]:
            parent = event.get("parent_event_id")
            if parent:
                assert _SESSION_POSITION.match(parent), f"{path.name} 的父事件是全局位置 {parent}"
            for name, value in (event.get("payload") or {}).items():
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if isinstance(item, str) and _GLOBAL_POSITION.match(item):
                        raise AssertionError(f"{path.name} 的 {name} 是全局位置 {item}")


# 工单 #1019：只为真实变化重写。下面覆盖验收的三条：
#   编号按一一对应比较；投影里的事件版本号不进比对；关键字段等于默认值时省略（工具调用的 ok 照写）。


def _shifted(document, shift=1):
    # 各处一致地把编号数字加上 shift：只差编号数字的两份基准
    text = json.dumps(document, ensure_ascii=False)
    return json.loads(_PLACEHOLDER.sub(lambda match: f"<{match.group(1)}#{int(match.group(2)) + shift}>", text))


def _payload_field_with_seen_label(events, field):
    # 找一个载荷字段：它的编号在本文件更早的地方已经出现过（同一个值在各处是同一个编号）
    seen: set[str] = set()
    for event in events:
        value = (event.get("payload") or {}).get(field)
        if not isinstance(value, str):
            continue
        match = _PLACEHOLDER.fullmatch(value)
        if match is None:
            continue
        if match.group(0) in seen:
            return event, match
        seen.add(match.group(0))
    raise AssertionError(f"基准里没有重复出现的 {field} 编号")


def test_documents_differing_only_in_number_digits_pass():
    # 两份基准只差编号的数字（各处一致地替换）：比较通过（工单 #1019 验收 1）
    expected = _load("handoff_release")
    compare_documents("handoff_release", expected, _shifted(expected))


def test_one_value_turned_into_two_numbers_fails():
    # 同一个值在实际里变成两个编号：比较失败并点名该字段（工单 #1019 验收 1）
    expected = _load("handoff_release")
    actual = _shifted(expected)
    event, match = _payload_field_with_seen_label(actual["events"], "activation_id")
    event["payload"]["activation_id"] = f"<{match.group(1)}#9999>"
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "payload.activation_id" in message, message


def test_two_values_merged_into_one_number_fails():
    # 两个本来不同的值在实际里变成同一个编号：比较失败并点名该字段（工单 #1019 验收 1）
    expected = _load("handoff_release")
    actual = _shifted(expected)
    labels = sorted({
        match.group(0)
        for event in actual["events"]
        for value in (event.get("payload") or {}).values()
        if isinstance(value, str)
        for match in [_PLACEHOLDER.fullmatch(value)]
        if match is not None and match.group(1) == "act"
    })
    assert len(labels) >= 2, labels
    merged = json.loads(json.dumps(actual, ensure_ascii=False).replace(labels[1], labels[0]))
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, merged)
    message = str(raised.value)
    assert "payload.activation_id" in message, message


def test_baselines_leave_out_the_run_event_version():
    # 事件版本号不进每个场景的投影比对：基准的投影里不写它（工单 #1019 验收 2）
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert "run_event_version" not in (document.get("projection") or {}), \
            f"{path.name} 的投影还写着 run_event_version"


def test_projection_run_event_version_difference_passes():
    # 两份基准只差投影里的 run_event_version：比较通过（工单 #1019 验收 2）
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    expected["projection"]["run_event_version"] = 10
    actual["projection"]["run_event_version"] = 11
    compare_documents("handoff_release", expected, actual)


def test_default_valued_key_field_equals_missing():
    # 一个关键字段在一份里是默认值、另一份里缺失：比较通过（工单 #1019 验收 3）
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    tool = next(event for event in expected["events"]
                if event["type"] == "tool_called" and "ok" in (event.get("payload") or {}))
    payload = tool["payload"]
    assert "error" not in payload and "guidance_ids" not in payload, payload
    payload["error"] = None
    payload["guidance_ids"] = []
    payload["prompt_version"] = 0
    compare_documents("handoff_release", expected, actual)


def test_tool_call_ok_false_is_written_and_other_defaults_are_omitted():
    # ok 是内核测试按值区分的字段：等于默认值 false 也照写；其余默认值不写进这条事件（验收 3）
    event = _event("evt_00000000000000a1", None, "tool_called", "engineering",
                   {"activation_id": "act_00000000000000a1",
                    "attempt_id": "att_00000000000000a1",
                    "context_event_id": None,
                    "effective_contract_hash": None,
                    "error": None,
                    "guidance_ids": [],
                    "id": "call_00000000000000a1",
                    "input_version": 1,
                    "logical_call_id": "call_00000000000000a1",
                    "name": "bash",
                    "ok": False,
                    "prompt_version": 0,
                    "purpose": "work",
                    "step_id": 1})
    payload = _normalized([event])["events"][0]["payload"]
    assert payload["ok"] is False, payload
    for name in ("context_event_id", "effective_contract_hash", "error", "guidance_ids", "prompt_version"):
        assert name not in payload, f"默认值的 {name} 不应写进这条事件"


def test_baselines_keep_ok_on_every_tool_call_result():
    # 基准里每次工具调用结果都写着 ok，被拒绝的调用写 ok: false（工单 #1019 验收 3、内核测试按值区分）
    denied = 0
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for event in document["events"]:
            if event["type"] not in {"tool_called", "tool_skipped"}:
                continue
            payload = event.get("payload") or {}
            assert "ok" in payload, f"{path.name} 的工具调用结果少了 ok"
            denied += payload["ok"] is False
    assert denied > 0, "基准里没有 ok: false 的工具调用结果"
