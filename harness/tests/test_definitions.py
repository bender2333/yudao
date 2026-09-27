import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, DefinitionError, UnknownStopReason, load_definitions
from harness.event_store import run_stream
from harness.models import EventType
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

REPO_ROOT = Path(__file__).resolve().parents[2]


def _copy(tmp_path: Path) -> Path:
    # 发布的定义文件的一份副本，测试在副本上修改
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        shutil.copyfile(path, directory / path.name)
    return directory


def _read(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def _write(directory: Path, name: str, content) -> None:
    (directory / name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def test_shipped_definitions_are_loaded_once_at_import():
    loaded = load_definitions()
    assert loaded == DEFINITIONS
    assert DEFINITIONS.version.startswith("sha256:") and len(DEFINITIONS.version) == len("sha256:") + 64


def test_version_is_the_digest_of_the_content_and_ignores_the_format(tmp_path):
    directory = _copy(tmp_path)
    limits = _read(directory, "limits.json")
    (directory / "limits.json").write_text(json.dumps(limits, indent=8), encoding="utf-8")
    assert load_definitions(directory).version == DEFINITIONS.version

    _write(directory, "limits.json", {**limits, "max_cycles": limits["max_cycles"] - 1})
    changed = load_definitions(directory)
    assert changed.version != DEFINITIONS.version
    assert changed.limits.max_cycles == DEFINITIONS.limits.max_cycles - 1

    # 键的顺序属于内容（工具参数的顺序会进入请求）
    _write(directory, "limits.json", dict(reversed(list(limits.items()))))
    assert load_definitions(directory).version != DEFINITIONS.version


@pytest.mark.parametrize(("change", "field", "message"), [
    (lambda limits: {**limits, "max_cycles": "many"}, "max_cycles", "valid integer"),
    (lambda limits: {**limits, "max_cycles": 0}, "max_cycles", "greater than 0"),
    (lambda limits: {**limits, "retry_max_delay_sec": True}, "retry_max_delay_sec", "valid number"),
    (lambda limits: {key: value for key, value in limits.items() if key != "run_time_limit_sec"},
     "run_time_limit_sec", "Field required"),
    (lambda limits: {**limits, "max_cycle": 3}, "max_cycle", "Extra inputs"),
])
def test_invalid_definition_names_the_file_and_the_field(tmp_path, change, field, message):
    directory = _copy(tmp_path)
    _write(directory, "limits.json", change(_read(directory, "limits.json")))
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[0] == "limits.json" and issue[1] == field and message in issue[2]
    assert f"limits.json {field}：" in str(raised.value)


def test_invalid_stop_reason_names_the_file_and_the_field(tmp_path):
    directory = _copy(tmp_path)
    reasons = _read(directory, "stop_reasons.json")
    reasons["max_cycles"] = {**reasons["max_cycles"], "outcome": "halted"}
    _write(directory, "stop_reasons.json", reasons)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[:2] == ("stop_reasons.json", "max_cycles.outcome") and "'done', 'paused' or 'failed'" in issue[2]


def test_malformed_json_duplicate_keys_and_missing_files_are_reported(tmp_path):
    directory = _copy(tmp_path)
    (directory / "limits.json").write_text('{\n  "max_cycles": 3,\n  "max_cycles": 4\n}', encoding="utf-8")
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert raised.value.issues == (("limits.json", "max_cycles", "重复的键"),)

    (directory / "limits.json").write_text('{\n  "max_cycles":\n}', encoding="utf-8")
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[0] == "limits.json" and issue[1] == "第 3 行第 1 列" and "不是合法的 JSON" in issue[2]

    (directory / "limits.json").unlink()
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert raised.value.issues == (("limits.json", "（整个文件）", "定义文件不存在"),)


def test_startup_fails_when_a_definition_is_invalid(tmp_path):
    # 在程序的一份副本中把定义改为不合法的内容：命令行启动失败，错误写明文件与字段
    copy = tmp_path / "program"
    shutil.copytree(REPO_ROOT / "harness", copy / "harness",
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
    directory = copy / "harness" / "definitions"
    _write(directory, "limits.json", {**_read(directory, "limits.json"), "max_cycles": -1})
    completed = subprocess.run([sys.executable, "-m", "harness", "--help"], cwd=copy,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                               capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode != 0
    assert "DefinitionError" in completed.stderr and "limits.json max_cycles：" in completed.stderr
    assert "usage" not in completed.stdout


def _terminal(event_type: str, stop_reason: str | None) -> NewEvent:
    return NewEvent(event_type, role="product", state_before="PRODUCT_SPEC", state_after="FAILED",
                    stop_reason=stop_reason, payload={"stop_reason": stop_reason})


def test_stop_reasons_outside_the_definitions_cannot_be_written(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    run_id = system.create_run("build echo")
    before = system.store.list_events(run_id)
    with pytest.raises(UnknownStopReason):
        system.writes.append(run_stream(run_id), _terminal(EventType.RUN_FAILED, "made_up_reason"))
    # 清单中的原因只能由它规定的结束事件承载，结束事件必须带停止原因
    with pytest.raises(ValueError, match="ends a run as paused"):
        system.writes.append(run_stream(run_id), _terminal(EventType.RUN_FAILED, "max_cycles"))
    with pytest.raises(ValueError, match="ends a run as failed"):
        system.writes.append(run_stream(run_id), _terminal(EventType.RUN_DONE, "time_limit"))
    with pytest.raises(ValueError, match="requires a stop reason"):
        system.writes.append(run_stream(run_id), _terminal(EventType.RUN_PAUSED, None))
    with pytest.raises(ValueError, match="cannot be recorded on transition"):
        system.writes.append(run_stream(run_id), _terminal(EventType.TRANSITION, "cancelled"))
    assert system.store.list_events(run_id) == before
    system.close()


def test_a_run_stopping_for_an_unlisted_reason_fails_to_record_the_stop(tmp_path):
    adapter = FakeAdapter([FakeTurn(raise_error=ProviderError("upstream said no", reason="made_up_reason"))])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    with pytest.raises(UnknownStopReason):
        system.run_until_stop(run_id)
    projection = system.project(run_id)
    assert projection.phase == "PRODUCT_SPEC" and projection.stop_reason is None
    assert not [event for event in system.store.list_events(run_id)
                if event.type in {EventType.RUN_FAILED, EventType.RUN_PAUSED, EventType.RUN_DONE}]
    system.close()
