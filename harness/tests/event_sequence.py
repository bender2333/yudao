import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from harness.definitions import DEFINITIONS
from harness.models import ArtifactRef, EventType

# 事件序列对照：把一次 run 的完整事件序列规整成与运行时刻、机器路径无关的形式，与 event_sequences/ 下的基准比较。
# 基准记录的是行为：之后任何提交使基准改变，说明行为改变，必须修正代码，不能更新基准。
#
# 基准文件的结构：
#   scenario   场景名；covers  场景覆盖的行为
#   events     规整后的事件序列，一条事件一项，"event" 是它在序列中的位置 <evt#N>
#   projection 运行结束时的投影（canonical_state）
#   artifacts  事件与投影引用的工件内容，每个工件一份，键是 <art#N>
#   shared     在上面各处重复出现的长文字与大段结构，每份一项，键是 <shared#N>
#
# 规整规则（只去掉随运行变化的部分，其余字段原样保留）：
# 1. 每条事件保留种类、提出者（actor）、部门（department）、状态迁移（state_before/state_after）、停止原因、
#    错误与载荷中的全部字段；去掉事件编号（event_id）、事件在日志中的全局位置、所属的流与流内版本
#    （position、stream、stream_version）、日志为范围读取保存的列（project_id、work_item_id）、
#    写入方的执行权编号（epoch）、run_id 与创建时间。role 在 Stage 5 之前为空，不进入基准。
#    引用其他事件的字段（parent_event_id、载荷与工件中的事件编号）换成被引用事件的位置 <evt#N>。
#    投影的 stream_version 是 run 流的事件数，与运行时刻无关，原样保留。
# 2. 其他随机生成的编号（act_、request_、spec_、ses_pro_ 等前缀加 16 位十六进制）按首次出现的顺序编为 <前缀#N>；
#    sha256 摘要编为 <sha256#N>（「sha256:」开头、工件路径中的摘要与单独出现的摘要都按摘要本身编号），
#    Git 提交号编为 <git#N>。同一个值在各处得到同一个编号，保留相等关系。
# 3. 工件按内容比较：工件引用（kind、content_hash、path、media_type）换成 <art#N>，内容放在 artifacts 中：
#    JSON 工件解析后按同样规则规整，JSON Lines 逐行解析，文本按字符串规整，无法按 UTF-8 解码的内容记它的摘要编号。
# 4. 随时间变化的数值：ISO 时间写成 <time>，duration_ms、latency_ms、elapsed_ms 写成 <duration>，
#    运行时间用完的错误文字中的实际用时写成 <elapsed>。
# 5. 流式进度事件在同一次调用尝试中阶段不变时按时间间隔重复记录，只保留每个阶段第一次出现的一条。
# 6. 机器相关的值：测试数据目录写成 <data>；主机 Python 解释器的路径写成 <python>，解释器的文件名
#    （python、python3、python.exe）单独出现或作为带引号的字符串出现时也写成 <python>；
#    场景给出的其他值（例如本机 HTTP 服务的地址）写成场景指定的占位。
# 7. 长度不少于 300 个字符的文字、序列化后不少于 1500 个字符的结构，出现两次及以上时移入 shared，原处写 <shared#N>。
# 8. 定义的版本（definitions_version 字段）是全部定义文件内容的摘要，随定义的内容改变：等于当前加载的定义的版本时
#    写成 <definitions>，其他值（缺少、空或旧的版本）原样保留，与基准不同。

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
                 "provider", "model", "context_digest", "stop_reason", "error", "artifact_hashes", "payload")
_SHARED_TEXT = 300
_SHARED_STRUCTURE = 1500


class _Normalizer:
    def __init__(self, system: Any, run_id: str, events: list[Any], replacements: dict[str, str]) -> None:
        self.system = system
        self.run_id = run_id
        self.event_positions = {event.event_id: f"<evt#{index}>" for index, event in enumerate(events, start=1)}
        self.labels: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.artifacts: dict[str, Any] = {}
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
        if isinstance(value, dict):
            if set(value) == _ARTIFACT_KEYS and isinstance(value.get("content_hash"), str):
                return self.artifact(value)
            return {name: self.value(value[name], name) for name in sorted(value)}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def artifact(self, ref: dict[str, Any]) -> str:
        label = self._label("art", ref["content_hash"])
        if label in self.artifacts:
            return label
        self.artifacts[label] = None
        raw = self.system.artifacts.get_for_run(self.run_id, ArtifactRef(**ref))
        media_type = ref["media_type"]
        if media_type == "application/json":
            content = self.value(json.loads(raw))
        elif media_type == "application/x-ndjson":
            content = [self.value(json.loads(line)) for line in raw.decode("utf-8").splitlines() if line.strip()]
        else:
            try:
                content = self.text(raw.decode("utf-8"))
            except UnicodeDecodeError:
                content = {"binary": self.text(ref["content_hash"])}
        self.artifacts[label] = {"kind": ref["kind"], "media_type": media_type, "content": content}
        return label

    def event(self, event: Any) -> dict[str, Any]:
        record = {"event": self.event_positions[event.event_id]}
        for field in _EVENT_FIELDS:
            record[field] = self.value(getattr(event, field), field)
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
        "projection": normalizer.value(system.project(run_id).canonical_state()),
    }
    document["artifacts"] = normalizer.artifacts
    counts: Counter = Counter()
    _count(document, counts)
    shared: dict[str, Any] = {}
    document = _share_children(document, counts, shared, {})
    document["shared"] = shared
    return document


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
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = list(difflib.unified_diff(expected.splitlines(), actual.splitlines(),
                                         "baseline", "actual", lineterm="", n=3))
        shown = "\n".join(diff[:120])
        raise AssertionError(f"event sequence of {name} differs from its baseline:\n{shown}")
