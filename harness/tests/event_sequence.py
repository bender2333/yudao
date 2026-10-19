import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from harness.definitions import DEFINITIONS
from harness.models import ArtifactRef, EventType
from harness.parameters import initial_version

PARAMETERS_VERSION = initial_version()

# 事件序列对照：把一次 run 的完整事件序列规整成与运行时刻、机器路径无关的形式，与 event_sequences/ 下的基准比较。
# 比较方式（#469）：每个会话内部的事件按顺序比较，会话之间只比较因果关系
# （询问 → 分支开始 → 回答 → 工具结果，提交 → 下一个部门开始），见文件尾的 compare_documents。
#
# 基准文件的结构：
#   scenario   场景名；covers  场景覆盖的行为
#   events     规整后的事件序列，一条事件一项，"event" 是它在序列中的位置 <evt#N>
#   projection 运行结束时的投影（canonical_state）中 PROJECTION_KEY_FIELDS 列出的字段
#   shared     在上面各处重复出现的长文字与大段结构，每份一项，键是 <shared#N>
#
# 规整规则（只去掉随运行变化的部分，其余字段原样保留）：
# 1. 每条事件保留种类、提出者（actor）、部门（department）、状态迁移（state_before/state_after）、停止原因、
#    错误与载荷里的关键字段；去掉事件编号（event_id）、事件在日志中的全局位置、所属的流与流内版本
#    （position、stream、stream_version）、日志为范围读取保存的列（project_id、work_item_id）、
#    写入方的执行权编号（epoch）、run_id 与创建时间。role 在 Stage 5 之前为空，不进入基准。
#    引用其他事件的字段（parent_event_id、载荷中的事件编号）换成被引用事件的位置 <evt#N>。
#    投影的 stream_version 是 run 流的事件数，与运行时刻无关，原样保留。
# 2. 其他随机生成的编号（act_、request_、spec_、ses_pro_ 等前缀加 16 位十六进制）按首次出现的顺序编为 <前缀#N>；
#    sha256 摘要编为 <sha256#N>（「sha256:」开头、单独出现的摘要与工件路径中的摘要都按摘要本身编号），
#    Git 提交号编为 <git#N>。同一个值在各处得到同一个编号，保留相等关系。
# 3. 工件引用（kind、content_hash、path、media_type）换成 <art#N>；工件内容不再写进基准，
#    发出去的部门提示与工具说明集中记在 harness/tests/prompt_snapshot.json。
# 4. 随时间变化的数值：ISO 时间写成 <time>，duration_ms、latency_ms、elapsed_ms 写成 <duration>，
#    运行时间用完的错误文字中的实际用时写成 <elapsed>。
# 5. 流式进度事件在同一次调用尝试中阶段不变时按时间间隔重复记录，只保留每个阶段第一次出现的一条。
# 6. 机器相关的值：测试数据目录写成 <data>；主机 Python 解释器的路径写成 <python>，解释器的文件名
#    （python、python3、python.exe）单独出现或作为带引号的字符串出现时也写成 <python>；
#    场景给出的其他值（例如本机 HTTP 服务的地址）写成场景指定的占位。
# 7. 长度不少于 300 个字符的文字、序列化后不少于 1500 个字符的结构，出现两次及以上时移入 shared，原处写 <shared#N>。
# 8. 定义的版本（definitions_version 字段）是全部定义文件内容的摘要，随定义的内容改变：等于当前加载的定义的版本时
#    写成 <definitions>，其他值（缺少、空或旧的版本）原样保留，与基准不同。
# 9. 参数的版本（parameters_version 字段）是全部参数现值的内容摘要：等于定义的初始参数版本时写成 <parameters>，
#    参数被修改过的值按摘要编号，与基准不同。
# 10. 只保留关键字段：载荷只保留 KEY_FIELDS 按事件种类列出的键，工具回执只保留 receipt 里的四项，
#     投影只保留 PROJECTION_KEY_FIELDS 列出的字段。先筛选、后规整：编号只按保留下来的字段的出现顺序产生。
#     增删表以外的字段不改动基准；表以内的字段变化必须让对应的场景失败。
# 11. prompt_snapshot.json 按 <部门>/<用途>[/guidance|/guidance_only|/request|/ask] 收同一个场景里的请求：
#     工作请求记 department_rules、work_item_guidance、input_handling、professional_completion、
#     collaboration_rules、proposal_contract、allowed_tools 七个提示正文与这次请求带的工具说明；
#     压缩请求只记摘要提示词，其中两个限额写成占位。部门提示与工具说明本身不再逐字进基准。

BASELINE_DIR = Path(__file__).parent / "event_sequences"

_TIME_KEYS = frozenset({"duration_ms", "latency_ms", "elapsed_ms"})
_ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)")
_ELAPSED = re.compile(r"run wall-clock time \d+s")
_GENERATED_ID = re.compile(r"(?<![A-Za-z0-9_])([a-z]+(?:_[a-z]+)*)_([0-9a-f]{16})(?![0-9a-f])")
_SHA256 = re.compile(r"sha256:([0-9a-f]{64})")
# 工件路径 <run>/<摘要前两位>/<摘要> 与单独出现的摘要，按同一个摘要编号
_ARTIFACT_PATH_DIGEST = re.compile(r"(?<![0-9a-f])[0-9a-f]{2}/([0-9a-f]{64})(?![0-9a-f])")
_BARE_DIGEST = re.compile(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])")
_GIT_SHA = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
_ARTIFACT_KEYS = frozenset({"kind", "content_hash", "path", "media_type"})
_EVENT_FIELDS = ("type", "actor", "department", "state_before", "state_after", "parent_event_id", "session_id",
                 "stop_reason", "error", "payload")
_SHARED_TEXT = 300
_SHARED_STRUCTURE = 1500

# 每种事件在基准里保留的载荷字段（第 10 条规整规则）：按事件种类逐行列出，取该种类在基准里实际出现过的键
# 与架构师核对过的白名单的交集（#471、#481、run_check 改命令字符串三次合并在这份表下需要改动的基准为 0 份）。
# 不放进来的是：工件引用（*_ref）、说明与提案正文、token 估算与预算、模型与连接配置、时间、
# 主机提示与调用参数（args、input_item、raw_keys）——它们的变化不改变行为，或由 prompt_snapshot.json 记录。
# 表里列出的字段发生变化必须让对应的场景失败；表以外的字段可以随时增删而不动基准。
KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "run_created": ("definitions_version", "kind", "max_cycles", "parameters_version"),
    "user_input_received": ("id", "kind"),
    "product_input_assigned": ("input_version", ),
    "department_guidance_received": ("department", "id", "status"),
    "department_guidance_applied": ("activation_id", "context_event_id", "guidance_ids", "input_version"),
    "department_guidance_responded": ("content_hash", "department", "guidance_created_event_id", "guidance_id",
                                      "guidance_version", "issuer", "kind", "result_event_ids", "status"),
    "department_activated": ("activation_id", "cycle", "effective_contract_hash", "guidance_ids", "guidance_only",
                             "guidance_version", "input_version", "prompt_version", "request_id"),
    "department_input": ("activation_id", "effective_contract_hash", "guidance_ids", "guidance_only",
                         "input_version", "prompt_version", "request_id", "step_id"),
    "tool_call_required": ("activation_id", "attempt_id", "context_event_id", "count", "effective_contract_hash",
                           "guidance_ids", "guidance_only", "input_version", "limit", "prompt_version",
                           "purpose", "request_id", "step_id"),
    "activation_finished": ("activation_id", "activations", "guidance_ids", "guidance_only", "input_version",
                            "model_steps", "prompt_version", "stop_reason"),
    "context_assembled": ("activation_id", "admitted", "attempt", "attempt_id", "collaboration_request_id",
                          "compaction_event_id", "department", "effective_contract_hash", "guidance_ids",
                          "guidance_only", "input_version", "logical_call_id", "prompt_version", "purpose",
                          "request_id", "retry_of_step_id", "source_event_id", "step_id"),
    "model_request_serialized": ("activation_id", "attempt", "attempt_id", "collaboration_request_id",
                                 "context_event_id", "effective_contract_hash", "guidance_ids", "guidance_only",
                                 "input_version", "logical_call_id", "prompt_version", "purpose", "request_id",
                                 "retry_of_step_id", "step_id"),
    "model_reasoning": ("activation_id", "attempt_id", "collaboration_request_id", "context_event_id",
                        "effective_contract_hash", "guidance_ids", "guidance_only", "input_version",
                        "logical_call_id", "prompt_version", "purpose", "request_id", "step_id"),
    "model_message": ("activation_id", "attempt_id", "collaboration_request_id", "context_event_id",
                      "effective_contract_hash", "guidance_ids", "guidance_only", "input_version",
                      "logical_call_id", "prompt_version", "purpose", "request_id", "step_id", "stop_reason"),
    "model_requested": ("activation_id", "attempt", "attempt_id", "attempted", "collaboration_request_id",
                        "context_event_id", "definitions_version", "effective_contract_hash", "guidance_ids",
                        "guidance_only", "input_version", "logical_call_id", "max_attempts", "parameters_version",
                        "prompt_version", "purpose", "request_id", "retry_of_step_id", "step_id"),
    "model_stream_progress": ("activation_id", "attempt", "attempt_id", "collaboration_request_id",
                              "context_event_id", "guidance_ids", "guidance_only", "input_version",
                              "logical_call_id", "prompt_version", "purpose", "step_id"),
    "model_attempt_finished": ("activation_id", "attempt", "attempt_id", "collaboration_request_id",
                               "context_event_id", "guidance_ids", "guidance_only", "input_version",
                               "logical_call_id", "prompt_version", "purpose", "retry_of_step_id", "status",
                               "step_id"),
    "model_attempt_failed": ("activation_id", "attempt", "attempt_id", "collaboration_request_id",
                             "context_event_id", "effective_contract_hash", "guidance_ids", "guidance_only",
                             "input_version", "logical_call_id", "max_attempts", "prompt_version", "purpose",
                             "reason", "request_id", "retry_of_step_id", "retryable", "status", "step_id",
                             "will_retry"),
    "model_retry_scheduled": ("activation_id", "attempt", "attempt_id", "collaboration_request_id",
                              "context_event_id", "delay_sec", "effective_contract_hash", "guidance_ids",
                              "guidance_only", "input_version", "logical_call_id", "max_attempts", "next_attempt",
                              "next_step_id", "prompt_version", "purpose", "reason", "request_id",
                              "retry_of_step_id", "retryable", "step_id"),
    "compaction_recorded": ("activation_id", "department", "effective_contract_hash", "guidance_ids",
                            "guidance_only", "input_version", "previous_compaction_event_id", "prompt_version",
                            "purpose", "request_id", "step_id"),
    "tool_called": ("activation_id", "attempt_id", "collaboration_request_id", "context_event_id",
                    "effective_contract_hash", "error", "guidance_ids", "guidance_only", "id", "input_version",
                    "logical_call_id", "name", "ok", "prompt_version", "purpose", "request_id", "step_id"),
    "tool_started": ("activation_id", "attempt", "attempt_id", "collaboration_request_id", "context_event_id",
                     "effective_contract_hash", "guidance_ids", "guidance_only", "id", "input_version",
                     "logical_call_id", "name", "prompt_version", "request_id", "step_id"),
    "tool_skipped": ("activation_id", "attempt_id", "collaboration_request_id", "context_event_id",
                     "effective_contract_hash", "error", "guidance_ids", "guidance_only", "id", "input_version",
                     "logical_call_id", "name", "ok", "prompt_version", "purpose", "request_id", "step_id"),
    "action_verified": ("activation_id", "attempt_id", "collaboration_request_id", "context_event_id",
                        "decision_id", "error", "guidance_ids", "guidance_only", "id", "input_version",
                        "logical_call_id", "name", "ok", "prompt_version", "purpose", "request_id", "resolution",
                        "step_id"),
    "proposal_submitted": ("definitions_version", "input_version", "kind", "parameters_version"),
    "proposal_rejected": ("definitions_version", "errors", "input_version", "kind", "parameters_version"),
    "spec_accepted": ("content_hash", "id", "input_version", "issuer", "kind", "parent_hash", "request_id",
                      "revision", "status"),
    "spec_superseded": ("content_hash", "revision", "request_id"),
    "contract_accepted": ("content_hash", "input_version", "product_spec_hash", "request_id", "revision"),
    "collaboration_requested": ("action", "content_hash", "id", "kind", "recipient", "requester", "return_phase",
                                "status"),
    "collaboration_responded": ("content_hash", "id", "kind", "recipient", "request_id", "requester",
                                "result_event_ids", "return_phase", "return_work_valid", "status"),
    "collaboration_closed": ("request_id", "return_phase", "return_work_valid", "status"),
    "ask_started": ("branch_session_id", "question", "recipient", "requester"),
    "ask_answered": ("answer", "revision", "with_spec_revision"),
    "product_decision_accepted": ("content_hash", "id", "kind", "product_spec_hash", "request_id"),
    "delivery_accepted": ("check_names", "code_tree_digest", "content_hash", "effective_contract_hash", "id",
                          "issuer", "kind", "parent_hash", "product_spec_hash", "request_id", "revision", "status"),
    "qa_submitted": ("code_snapshot_hash", "content_hash", "delivery_spec_hash", "effective_contract_hash", "id",
                     "issuer", "kind", "parent_hash", "product_spec_hash", "request_id", "revision", "status",
                     "verdict"),
    "qa_tests_saved": ("activation_id", "content_hash", "version"),
    "structure_accepted": ("content_hash", "code_tree_digest", "id", "issuer", "kind", "parent_hash",
                           "product_spec_hash", "request_id", "revision", "status"),
    "baseline_review_accepted": ("code_snapshot_hash", "content_hash", "id", "issuer", "kind", "parent_hash",
                                 "product_spec_hash", "request_id", "revision", "status", "verdict"),
    "lesson_candidate_recorded": ("delivery_spec_hash", "id", "kind", "product_spec_hash", "source_event_id",
                                  "status"),
    "transition": ("from", "route", "to"),
    "run_done": ("stop_reason", ),
    "run_paused": ("cycle_count", "human_action", "max_cycles", "paused_at_phase", "stop_reason"),
    "run_failed": ("human_action", "stop_reason"),
    "run_resumed": ("acquired_epoch", "previous_epoch"),
    "run_continued": ("decision_id", "resumed_at_phase", "stop_reason"),
    "decision_requested": ("blocks", "department", "kind", "options", "reason", "resumed_at_phase", "stop_reason",
                           "target"),
    "decision_answered": ("base_version", "decision_id", "option"),
    "decision_withdrawn": ("decision_id", "reason"),
}

# 投影在基准里保留的字段；带下划线的四项各自再保留下面列出的键
PROJECTION_KEY_FIELDS = ("phase", "stop_reason", "outcome", "error", "waiting_reason", "active_department",
                         "human_action", "cycle_count", "rework_count", "request_count", "round", "input_version",
                         "processed_input_version", "product_work_input_version", "run_event_version",
                         "stream_version", "definitions_version", "parameters_version")
_PROJECTION_NESTED = {
    "product_spec": ("revision", "status", "content_hash"),
    "delivery_spec": ("revision", "status", "content_hash"),
    "last_review": ("revision", "status", "verdict", "content_hash"),
    "effective_contract": ("revision", "content_hash"),
}
# 工具回执保留的四项：从 output_ref 指向的工件内容里取，工件内容不是 JSON 对象时不记回执
_RECEIPT_KEYS = ("exit_code", "qa_tests_hash", "status", "tree_changed")
_RECEIPT_TYPES = frozenset({"tool_called", "tool_skipped"})


class _Normalizer:
    def __init__(self, system: Any, run_id: str, events: list[Any], replacements: dict[str, str]) -> None:
        self.system = system
        self.run_id = run_id
        self.event_positions = {event.event_id: f"<evt#{index}>" for index, event in enumerate(events, start=1)}
        self.labels: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        data_dir = Path(system.data_dir)
        executable = Path(sys.executable)
        # 同一个路径可能以反斜杠、正斜杠或 JSON 转义后的反斜杠出现
        machine = {str(data_dir): "<data>", str(data_dir.resolve()): "<data>",
                   str(executable): "<python>", str(executable.resolve()): "<python>", **replacements}
        self.replacements = sorted({
            (form, placeholder)
            for path, placeholder in machine.items()
            for form in (path, path.replace("\\", "/"), path.replace("\\", "\\\\"))
        }, key=lambda item: -len(item[0]))
        # 解释器的文件名在各台机器上不同（python.exe、python3），单独出现或作为带引号的 JSON 字符串出现时统一写成 <python>
        names = sorted({"python", "python3", "python.exe", executable.name}, key=len, reverse=True)
        self.python_names = frozenset(names)
        self.quoted_python = re.compile(r'(\\*")(' + "|".join(re.escape(name) for name in names) + r')(\\*")')

    def _label(self, kind: str, value: str) -> str:
        key = f"{kind}:{value}"
        label = self.labels.get(key)
        if label is None:
            self.counters[kind] = self.counters.get(kind, 0) + 1
            label = f"<{kind}#{self.counters[kind]}>"
            self.labels[key] = label
        return label

    def text(self, value: str) -> str:
        if value in self.python_names:
            return "<python>"
        for form, placeholder in self.replacements:
            value = value.replace(form, placeholder)
        value = self.quoted_python.sub(r"\1<python>\3", value)
        value = _ISO_TIME.sub("<time>", value)
        value = _ELAPSED.sub("run wall-clock time <elapsed>s", value)
        def digest(match: re.Match[str]) -> str:
            return self._label("sha256", match.group(1))

        value = _ARTIFACT_PATH_DIGEST.sub(digest, value)
        value = _SHA256.sub(digest, value)
        value = _BARE_DIGEST.sub(digest, value)
        value = _GIT_SHA.sub(lambda match: self._label("git", match.group(0)), value)

        def generated(match: re.Match[str]) -> str:
            known = self.event_positions.get(match.group(0))
            return known if known is not None else self._label(match.group(1), match.group(0))

        return _GENERATED_ID.sub(generated, value)

    def value(self, value: Any, key: str | None = None) -> Any:
        if key in _TIME_KEYS and value is not None:
            return "<duration>"
        if key == "definitions_version" and value == DEFINITIONS.version:
            return "<definitions>"
        if key == "parameters_version" and value == PARAMETERS_VERSION:
            return "<parameters>"
        if isinstance(value, dict):
            return {name: self.value(value[name], name) for name in sorted(value)}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def receipt(self, payload: dict[str, Any], record: dict[str, Any]) -> None:
        # 工具回执：把工件内容里的退出码、状态与公开树是否变化记进 record，工件内容不是 JSON 对象时没有回执
        ref = payload.get("output_ref")
        if not isinstance(ref, dict):
            return
        try:
            content = json.loads(self.system.artifacts.get_for_run(self.run_id, ArtifactRef(**ref)))
        except (TypeError, ValueError):
            return
        if not isinstance(content, dict):
            return
        receipt = {key: self.value(content[key], key) for key in _RECEIPT_KEYS if key in content}
        if receipt:
            record["receipt"] = receipt

    def event(self, event: Any) -> dict[str, Any]:
        keys = KEY_FIELDS.get(event.type)
        if keys is None:
            raise AssertionError(f"event type {event.type} has no KEY_FIELDS entry in harness/tests/event_sequence.py")
        record = {"event": self.event_positions[event.event_id]}
        for field in _EVENT_FIELDS:
            record[field] = self.value(getattr(event, field), field)
        payload = event.payload if isinstance(event.payload, dict) else {}
        # 先筛选、后规整：编号只按保留下来的字段的出现顺序产生
        record["payload"] = {key: self.value(payload[key], key) for key in keys if key in payload}
        if event.type in _RECEIPT_TYPES:
            self.receipt(payload, record)
        return record


def _repeated_progress(event: Any, last_stage: dict[str, str]) -> bool:
    if event.type != EventType.MODEL_STREAM_PROGRESS:
        return False
    attempt, stage = event.payload.get("attempt_id"), event.payload.get("stage")
    repeated = last_stage.get(attempt) == stage
    last_stage[attempt] = stage
    return repeated


def _shared_candidate(value: Any) -> str | None:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False) if len(value) >= _SHARED_TEXT else None
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return text if len(text) >= _SHARED_STRUCTURE else None
    return None


def _count(value: Any, counts: Counter) -> None:
    key = _shared_candidate(value)
    if key is not None:
        counts[key] += 1
    if isinstance(value, dict):
        for item in value.values():
            _count(item, counts)
    elif isinstance(value, list):
        for item in value:
            _count(item, counts)


def _share(value: Any, counts: Counter, shared: dict[str, Any], labels: dict[str, str]) -> Any:
    key = _shared_candidate(value)
    if key is not None and counts[key] > 1:
        label = labels.get(key)
        if label is None:
            label = f"<shared#{len(labels) + 1}>"
            labels[key] = label
            shared[label] = None
            shared[label] = _share_children(value, counts, shared, labels)
        return label
    return _share_children(value, counts, shared, labels)


def _share_children(value: Any, counts: Counter, shared: dict[str, Any], labels: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {name: _share(item, counts, shared, labels) for name, item in value.items()}
    if isinstance(value, list):
        return [_share(item, counts, shared, labels) for item in value]
    return value


def normalized_run(system: Any, run_id: str, replacements: dict[str, str] | None = None) -> dict[str, Any]:
    # replacements：场景自己的机器相关值（例如本机 HTTP 服务的地址）与它的占位写法
    events = system.store.list_events(run_id)
    last_stage: dict[str, str] = {}
    kept = [event for event in events if not _repeated_progress(event, last_stage)]
    normalizer = _Normalizer(system, run_id, kept, dict(replacements or {}))
    document = {
        "events": [normalizer.event(event) for event in kept],
        "projection": _key_fields(system.project(run_id).canonical_state(), PROJECTION_KEY_FIELDS,
                                  _PROJECTION_NESTED, normalizer),
    }
    counts: Counter = Counter()
    _count(document, counts)
    shared: dict[str, Any] = {}
    document = _share_children(document, counts, shared, {})
    document["shared"] = shared
    return document


# 发出去的部门提示与工具说明（#532 步骤 3）：按 <部门>/<用途> 收集每个 context_assembled 事件指向的
# 部门提示正文与这次请求带的工具说明，集中记在 prompt_snapshot.json，事件序列基准里不再出现它们的全文。
PROMPT_PART_SOURCES = ("department_rules", "work_item_guidance", "input_handling", "professional_completion",
                       "collaboration_rules", "proposal_contract", "allowed_tools")


def prompt_entries(system: Any, run_id: str) -> dict[str, dict[str, Any]]:
    events = system.store.list_events(run_id)
    normalizer = _Normalizer(system, run_id, events, {})
    entries: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.type != EventType.CONTEXT_ASSEMBLED:
            continue
        payload = event.payload or {}
        request = _read_json(system, run_id, payload.get("request_ref"))
        if payload.get("purpose") == "compaction":
            # 压缩请求：摘要提示词里的两个限额随窗口变化，写成占位；压缩请求不带工具
            entry = {"parts": {"compaction_request": normalizer.text(_summary_preface(request))}, "tools": []}
        else:
            parts = [part for part in _read_json(system, run_id, payload.get("parts_ref")) if isinstance(part, dict)]
            entry = {"parts": {part["source"]: normalizer.text(part["text"]) for part in parts
                               if part.get("source") in PROMPT_PART_SOURCES},
                     "tools": _tool_entries(request, normalizer)}
        key = f"{payload.get('department')}/{payload.get('purpose')}"
        if payload.get("guidance_only"):
            key += "/guidance_only"
        elif payload.get("guidance_ids"):
            key += "/guidance"
        if payload.get("request_id"):
            key += "/request"
        elif str(payload.get("session_id", "")).startswith("ses_ask_") or any(
            item.get("source") == "pending_ask" for item in payload.get("injected", [])
        ):
            key += "/ask"
        existing = entries.setdefault(key, entry)
        if existing != entry:
            raise AssertionError(f"prompt snapshot key {key} differs between requests in run {run_id}")
    return entries


def _read_json(system: Any, run_id: str, ref: Any) -> Any:
    if not isinstance(ref, dict):
        return None
    try:
        return json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**ref)))
    except (TypeError, ValueError):
        return None


def _tool_entries(request: Any, normalizer: _Normalizer) -> list[dict[str, Any]]:
    tools = request.get("tools") if isinstance(request, dict) else None
    if not isinstance(tools, list):
        return []
    return [{"name": normalizer.text(tool["name"]), "description": normalizer.text(tool["description"]),
             "parameters": normalizer.value(tool["parameters"])}
            for tool in tools if isinstance(tool, dict)]


_SUMMARY_PREFACE = re.compile(r"within \d+ tokens? and \d+ characters")


def _summary_preface(request: Any) -> str:
    # 摘要提示词的第一个 input item 是固定文字，两个限额随窗口与运行变化，换成占位
    items = request.get("input") if isinstance(request, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return ""
    return _SUMMARY_PREFACE.sub("within <n> tokens and <m> characters", str(items[0].get("content", "")))


def _key_fields(state: dict[str, Any], fields: tuple[str, ...], nested: dict[str, tuple[str, ...]],
                normalizer: _Normalizer) -> dict[str, Any]:
    # 先筛选、后规整：编号只按保留下来的字段的出现顺序产生
    record: dict[str, Any] = {}
    for field in fields:
        if field not in state:
            continue
        value = state[field]
        keys = nested.get(field)
        if keys is not None and isinstance(value, dict):
            value = {key: value[key] for key in keys if key in value}
        record[field] = normalizer.value(value, field)
    return record


def baseline_text(name: str, covers: str, run: dict[str, Any]) -> str:
    document = {"scenario": name, "covers": covers, **run}
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


def compare_with_baseline(name: str, covers: str, run: dict[str, Any], *, write: bool) -> None:
    path = BASELINE_DIR / f"{name}.json"
    actual = baseline_text(name, covers, run)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
        return
    assert path.exists(), f"missing event sequence baseline {path.name}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    compare_documents(name, expected, json.loads(actual))


RUN_GROUP = "__run__"

_TOOL_RESULT_TYPES = frozenset({
    "tool_called", "tool_started", "proposal_submitted", "spec_accepted", "contract_accepted",
    "plan_accepted", "delivery_accepted", "qa_submitted",
})


def _inline(value, shared, memo):
    if isinstance(value, str):
        if value in memo:
            return memo[value]
        if value in shared:
            memo[value] = None
            resolved = _inline(shared.get(value), shared, memo)
            memo[value] = resolved
            return resolved
        return value
    if isinstance(value, dict):
        return {name: _inline(item, shared, memo) for name, item in value.items()}
    if isinstance(value, list):
        return [_inline(item, shared, memo) for item in value]
    return value


def _session_groups(events):
    groups = {}
    for event in events:
        groups.setdefault(event.get("session_id") or RUN_GROUP, []).append(event)
    return groups


def _group_records(document):
    shared = document.get("shared") or {}
    events = [_inline(event, shared, {}) for event in document["events"]]
    groups = _session_groups(events)
    positions = {}
    for key, items in groups.items():
        for index, item in enumerate(items, start=1):
            positions[item["event"]] = f"{key}#{index}"
    records = {}
    for key, items in groups.items():
        group_records = []
        for index, item in enumerate(items, start=1):
            record = dict(item)
            record["event"] = index
            parent = item.get("parent_event_id")
            record["parent_event_id"] = positions.get(parent) if parent else None
            group_records.append(record)
        records[key] = group_records
    return records


def _request_ref(payload):
    return str(payload.get("request_id") or payload.get("collaboration_request_id")
               or payload.get("id") or "")


def _event_key(event, group, ordinal):
    payload = event.get("payload") or {}
    return f"{group} {event.get('type')} {_request_ref(payload)} #{ordinal}".replace("  ", " ")


def _causal_edges(events):
    groups = _session_groups(events)
    group_of = [event.get("session_id") or RUN_GROUP for event in events]
    ordinals = {}
    keys = {}
    for position, event in enumerate(events):
        slot = (group_of[position], event.get("type"), _request_ref(event.get("payload") or {}))
        ordinals[slot] = ordinals.get(slot, 0) + 1
        keys[position] = _event_key(event, group_of[position], ordinals[slot])
    edges = set()

    def link(one, other):
        # 边的方向由数组里的先后决定：键本身与顺序无关，方向记录谁在前
        before, after = (one, other) if one < other else (other, one)
        edges.add(f"{keys[before]} -> {keys[after]}")
    activations = [pos for pos, event in enumerate(events) if event.get("type") == "department_activated"]
    if events and events[0].get("type") == "run_created" and activations:
        link(0, activations[0])
    for position, event in enumerate(events):
        payload = event.get("payload") or {}
        if event.get("type") == "collaboration_requested" and payload.get("id"):
            request_id = str(payload["id"])
            starts = [pos for pos in activations
                      if pos > position and str((events[pos].get("payload") or {}).get("request_id")) == request_id]
            answers = [pos for pos, other in enumerate(events)
                       if other.get("type") == "collaboration_responded"
                       and str((other.get("payload") or {}).get("request_id")) == request_id and pos > position]
            if starts and answers:
                link(position, starts[0])
                link(starts[0], answers[0])
                requester = group_of[position]
                stop = next((pos for pos, other in enumerate(events)
                             if pos > answers[0] and group_of[pos] == requester
                             and other.get("type") in {"transition", "run_done"}), len(events))
                for pos in range(answers[0] + 1, stop):
                    if group_of[pos] == requester and events[pos].get("type") in _TOOL_RESULT_TYPES:
                        link(answers[0], pos)
        elif event.get("type") == "transition":
            targets = [pos for pos in activations if pos > position]
            if targets:
                link(position, targets[0])
    return edges


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _diff_lines(expected_lines, actual_lines):
    diff = list(difflib.unified_diff(expected_lines, actual_lines, "baseline", "actual", lineterm="", n=3))
    return "\n".join(diff[:120])


def compare_documents(name, expected, actual):
    for field in ("scenario", "covers"):
        if expected.get(field) != actual.get(field):
            raise AssertionError(f"event sequence of {name} differs from its baseline:\n"
                                 f"{field} differs: {expected.get(field)!r} != {actual.get(field)!r}")
    expected_groups, actual_groups = _group_records(expected), _group_records(actual)
    if set(expected_groups) != set(actual_groups):
        raise AssertionError(f"event sequence of {name} differs from its baseline:\nsessions differ: "
                             f"{sorted(set(expected_groups) - set(actual_groups))} missing, "
                             f"{sorted(set(actual_groups) - set(expected_groups))} unexpected")
    for key in expected_groups:
        wanted = [_canon(record) for record in expected_groups[key]]
        got = [_canon(record) for record in actual_groups[key]]
        if wanted != got:
            for index, (one, other) in enumerate(zip(wanted, got), start=1):
                if one != other:
                    break
            else:
                index = min(len(wanted), len(got)) + 1
            raise AssertionError(f"event sequence of {name} differs from its baseline:\n"
                                 f"session {key} event #{index} differs:\n{_fields_line(expected_groups, actual_groups, key, index)}"
                                 + _diff_lines(wanted, got))
    expected_edges, actual_edges = _causal_edges(expected["events"]), _causal_edges(actual["events"])
    if expected_edges != actual_edges:
        missing = sorted(expected_edges - actual_edges)
        unexpected = sorted(actual_edges - expected_edges)
        raise AssertionError(f"event sequence of {name} differs from its baseline:\ncausal edges differ:\n"
                             f"missing: {missing}\nunexpected: {unexpected}")
    # 投影是事件推出来的结果：事件一致以后才比较投影，差异先写是哪一项再写 diff
    expected_projection, actual_projection = expected.get("projection"), actual.get("projection")
    if _canon(expected_projection) != _canon(actual_projection):
        raise AssertionError(f"event sequence of {name} differs from its baseline:\nprojection differs:\n"
                             + _projection_fields_line(expected_projection, actual_projection)
                             + _diff_lines(_canon(expected_projection).splitlines(),
                                           _canon(actual_projection).splitlines()))


def _projection_fields_line(expected, actual):
    # 指名投影里哪些键不同：嵌套的字典写成 <键>.<子键>，例如 product_spec.revision
    differing = []

    def walk(prefix, one, other):
        if one == other:
            return
        if isinstance(one, dict) and isinstance(other, dict):
            for name in sorted(set(one) | set(other)):
                walk(f"{prefix}.{name}", one.get(name), other.get(name))
            return
        differing.append(prefix)

    for field in sorted(set(expected or {}) | set(actual or {})):
        walk(field, (expected or {}).get(field), (actual or {}).get(field))
    return f"fields: {', '.join(differing)}\n" if differing else ""

def _fields_line(expected_groups, actual_groups, key, index):
    # 指名这一条事件里哪些字段不同：载荷字段写成 payload.<键>，工具回执写成 receipt.<键>
    wanted = expected_groups[key][index - 1] if index <= len(expected_groups[key]) else {}
    got = actual_groups[key][index - 1] if index <= len(actual_groups[key]) else {}
    differing = []
    for field in sorted(set(wanted) | set(got)):
        one, other = wanted.get(field), got.get(field)
        if one == other:
            continue
        if field in {"payload", "receipt"} and isinstance(one, dict) and isinstance(other, dict):
            differing.extend(f"{field}.{name}" for name in sorted(set(one) | set(other))
                             if one.get(name) != other.get(name))
        else:
            differing.append(field)
    return f"type: {wanted.get('type') or got.get('type')}; fields: {', '.join(differing)}\n" if differing else ""
