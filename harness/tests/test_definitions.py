import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, DefinitionError, UnknownStopReason, load_definitions
from harness.event_store import run_stream
from harness.models import EventType, ProjectEventType
from harness.providers.presets import PRESET_TABLE_SOURCE, PRESET_TABLE_VERSION, get_preset, list_presets
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.tools import tool_definitions
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


def test_departments_and_roles_must_refer_to_each_other(tmp_path):
    directory = _copy(tmp_path)
    organization = _read(directory, "organization.json")
    organization["departments"][0]["roles"] = ["manager"]
    _write(directory, "organization.json", organization)
    roles = _read(directory, "roles.json")
    roles["quality"]["tools"].append("read_file")
    _write(directory, "roles.json", roles)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert raised.value.issues == (
        ("organization.json", "departments[0].roles", "每个部门现在只有一个角色，角色编号与部门编号相同"),
        ("roles.json", "manager", "组织中的角色没有定义"),
        ("roles.json", "product", "角色不属于任何部门"),
        ("roles.json", "quality.tools", "重复的工具 read_file"),
    )


def test_tool_categories_and_references_are_checked(tmp_path):
    directory = _copy(tmp_path)
    tools = _read(directory, "tools.json")
    tools["submit_plan"]["action"] = "write"
    tools["submit_delivery"]["proposal"] = "engineering_plan"
    del tools["run_command"]
    _write(directory, "tools.json", tools)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[:2] == ("tools.json", "submit_plan") and "a host tool requires proposal and has no action" in issue[2]

    tools["submit_plan"].pop("action")
    _write(directory, "tools.json", tools)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert raised.value.issues[:2] == (
        ("roles.json", "engineering.tools[9]", "工具 run_command 没有定义"),
        ("tools.json", "submit_delivery.proposal", "提案种类 engineering_plan 已经由 submit_plan 提交"),
    )
    # 工程部门的提案合同仍然说明 delivery_spec，与提交工具的种类不再相符
    assert raised.value.issues[2][:2] == ("proposal_contracts.json", "roles.engineering.kinds")


def test_proposal_contracts_must_match_the_submit_tools_of_each_role(tmp_path):
    directory = _copy(tmp_path)
    contracts = _read(directory, "proposal_contracts.json")
    contracts["roles"]["engineering"]["submit_tools"] = ["submit_delivery"]
    del contracts["roles"]["quality"]["kinds"]["qa_review"]
    del contracts["roles"]["product"]
    _write(directory, "proposal_contracts.json", contracts)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert [issue[:2] for issue in raised.value.issues] == [
        ("proposal_contracts.json", "roles.product"),
        ("proposal_contracts.json", "roles.engineering.submit_tools"),
        ("proposal_contracts.json", "roles.quality.kinds"),
    ]


def test_a_role_and_the_shared_part_cannot_describe_the_same_proposal_kind(tmp_path):
    directory = _copy(tmp_path)
    contracts = _read(directory, "proposal_contracts.json")
    contracts["roles"]["product"]["kinds"]["collaboration_request"] = {"required": ["recipient"]}
    _write(directory, "proposal_contracts.json", contracts)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert raised.value.issues == (
        ("proposal_contracts.json", "roles.product.kinds", "与共同部分重复说明 collaboration_request"),)


def test_loaded_definitions_are_read_only_and_hand_out_plain_copies(tmp_path):
    # 映射是只读映射、列表是元组，改不到；请求与界面用的是普通 JSON 结构的副本
    review = DEFINITIONS.tools["submit_review"]
    assert isinstance(review.parameters["properties"]["verdict"]["enum"], tuple)
    with pytest.raises(TypeError):
        review.parameters["properties"]["verdict"]["enum"][0] = "approve"
    with pytest.raises(TypeError):
        del review.parameters["properties"]["defects"]
    with pytest.raises(TypeError):
        DEFINITIONS.tools["fetch_url"] = review
    with pytest.raises(TypeError):
        del DEFINITIONS.stop_reasons["max_cycles"]
    [definition] = tool_definitions(["submit_review"])
    definition["parameters"]["properties"].clear()
    contract = DEFINITIONS.proposal_contract("quality")
    contract["kinds"]["qa_review"]["verdict"].append("approve")
    contract["submit_tools"].clear()
    assert list(review.parameters["properties"]["verdict"]["enum"]) == ["rework_product", "rework_engineering", "release"]
    assert DEFINITIONS.proposal_contract("quality")["kinds"]["qa_review"]["verdict"] == [
        "rework_product", "rework_engineering", "release"]
    assert load_definitions() == DEFINITIONS


@pytest.mark.parametrize(("change", "field", "message"), [
    (lambda limits: {**limits, "retry_max_delay_sec": float("inf")}, "retry_max_delay_sec", "finite number"),
    (lambda limits: {**limits, "retry_initial_delay_sec": 90.0}, "（整个文件）", "retry_initial_delay_sec cannot exceed"),
    (lambda limits: {**limits, "check_timeout_sec": 900}, "（整个文件）", "check_timeout_sec cannot exceed"),
])
def test_limits_are_finite_and_consistent(tmp_path, change, field, message):
    directory = _copy(tmp_path)
    _write(directory, "limits.json", change(_read(directory, "limits.json")))
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[0] == "limits.json" and issue[1] == field and message in issue[2]


def test_a_definition_file_that_is_not_utf8_names_the_file(tmp_path):
    directory = _copy(tmp_path)
    (directory / "roles.json").write_bytes('{"product": "café"}'.encode("latin-1"))
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert raised.value.issues == (("roles.json", "第 16 个字节", "不是 UTF-8 编码的文本"),)


def test_service_presets_keep_their_revision_and_are_checked(tmp_path):
    assert (PRESET_TABLE_VERSION, PRESET_TABLE_SOURCE) == (
        DEFINITIONS.service_presets.revision, DEFINITIONS.service_presets.source)
    [preset] = list_presets()
    preset["base_urls"].clear()
    assert get_preset("opencode-go")["base_urls"]["responses"] == "https://opencode.ai/zen/go/v1"

    directory = _copy(tmp_path)
    table = _read(directory, "service_presets.json")
    # 预置表只含接入规则，不带模型（#84）
    assert "known_models" not in table["presets"][0]
    table["presets"][0]["base_urls"]["responses"] = 7
    _write(directory, "service_presets.json", table)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[:2] == ("service_presets.json", "presets[0].base_urls.responses")
    table = _read(directory, "service_presets.json")
    table["presets"][0]["base_urls"]["responses"] = "https://opencode.ai/zen/go/v1"
    table["presets"].append(table["presets"][0])
    _write(directory, "service_presets.json", table)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert raised.value.issues == (("service_presets.json", "presets[1].id", "重复的服务方案 opencode-go"),)


def test_role_visibility_is_a_closed_list(tmp_path):
    directory = _copy(tmp_path)
    roles = _read(directory, "roles.json")
    roles["product"]["visibility"] = ["other_department_transcript"]
    _write(directory, "roles.json", roles)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[:2] == ("roles.json", "product.visibility[0]")


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


def _without_quality(directory: Path) -> None:
    organization = _read(directory, "organization.json")
    organization["departments"] = organization["departments"][:2]
    _write(directory, "organization.json", organization)
    for name, key in (("roles.json", None), ("proposal_contracts.json", "roles")):
        content = _read(directory, name)
        del (content if key is None else content[key])["quality"]
        _write(directory, name, content)


def _with_unimplemented_tool(directory: Path) -> None:
    tools = _read(directory, "tools.json")
    tools["fetch_url"] = {**tools["read_file"], "description": "Fetch one registered URL."}
    _write(directory, "tools.json", tools)
    roles = _read(directory, "roles.json")
    roles["product"]["tools"].append("fetch_url")
    _write(directory, "roles.json", roles)


@pytest.mark.parametrize(("change", "expected"), [
    (lambda directory: _write(directory, "limits.json", {**_read(directory, "limits.json"), "max_cycles": -1}),
     "limits.json max_cycles："),
    # 控制核心的阶段迁移只为产品、工程、质检写了阶段
    (_without_quality, "organization.json departments：控制核心的阶段迁移按顺序支持部门 product、engineering、quality"),
    # 执行环境没有实现的环境工具
    (_with_unimplemented_tool, "tools.json fetch_url：执行环境没有这个环境工具的实现"),
])
def test_startup_fails_when_a_definition_is_invalid(tmp_path, change, expected):
    # 在程序的一份副本中把定义改为不合法的内容：命令行启动失败，错误写明文件与字段
    copy = tmp_path / "program"
    shutil.copytree(REPO_ROOT / "harness", copy / "harness",
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
    change(copy / "harness" / "definitions")
    completed = subprocess.run([sys.executable, "-m", "harness", "--help"], cwd=copy,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                               capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode != 0
    assert "DefinitionError" in completed.stderr and expected in completed.stderr
    assert "usage" not in completed.stdout


def _terminal(event_type: str, stop_reason: str | None) -> NewEvent:
    return NewEvent(event_type, actor="system", department="product", state_before="PRODUCT_SPEC",
                    state_after="FAILED",
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
    # 结束事件的终态与载荷中的停止原因都要与事件的停止原因一致
    paused = NewEvent(EventType.RUN_PAUSED, actor="system", department="product", state_before="PRODUCT_SPEC",
                      state_after="FAILED",
                      stop_reason="max_cycles", payload={"stop_reason": "max_cycles"})
    with pytest.raises(ValueError, match="must end in PAUSED"):
        system.writes.append(run_stream(run_id), paused)
    with pytest.raises(ValueError, match="same stop reason in its payload"):
        system.writes.append(run_stream(run_id), NewEvent(
            EventType.RUN_FAILED, actor="system", department="product", state_before="PRODUCT_SPEC",
            state_after="FAILED",
            stop_reason="cancelled", payload={"stop_reason": "made_up_reason"}))
    assert system.store.list_events(run_id) == before
    system.close()


def test_work_item_creation_model_requests_and_proposal_decisions_record_the_definitions_version(tmp_path):
    invalid_spec = {"kind": "product_spec", "goal": "", "requirements": ["print"], "acceptance_criteria": ["prints"]}
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([invalid_spec, *happy_script()]))
    project_id = system.projects.register("定义版本", "做一个命令行回显工具。")
    work_item_id, run_id = system.projects.start_work_item(project_id, "回显参数")
    assert system.run_until_stop(run_id).phase == "DONE"

    [created] = [event for event in system.store.list_project_events(project_id)
                 if event.type == ProjectEventType.WORK_ITEM_CREATED]
    assert created.payload["work_item_id"] == work_item_id
    assert created.payload["definitions_version"] == DEFINITIONS.version
    events = system.store.list_events(run_id)
    recorded = {EventType.RUN_CREATED, EventType.MODEL_REQUESTED, EventType.PROPOSAL_SUBMITTED,
                EventType.PROPOSAL_REJECTED}
    counts = {kind: 0 for kind in recorded}
    for event in events:
        if event.type in recorded:
            counts[event.type] += 1
            assert event.payload["definitions_version"] == DEFINITIONS.version, event.type
    assert counts == {EventType.RUN_CREATED: 1, EventType.MODEL_REQUESTED: 5,
                      EventType.PROPOSAL_SUBMITTED: 5, EventType.PROPOSAL_REJECTED: 1}
    system.close()


@pytest.mark.parametrize("names", [
    ("handoff_release", "quality_rework", "collaboration_request_answer", "guidance_response_explained",
     "tool_denied_guidance_only", "compaction_success", "proposal_rejected"),
    ("http_responses_handoff", "http_chat_handoff", "http_messages_handoff"),
])
def test_no_code_path_changes_the_loaded_definitions(tmp_path, names):
    # 走完交接、退回、协作请求、指导、压缩与三种协议的真实请求以后，已加载的定义与重新读取文件的结果相同
    from harness.tests.test_event_sequence import SCENARIOS

    for name in names:
        system, _run_id, _ = SCENARIOS[name].run(tmp_path / name)
        system.close()
    assert DEFINITIONS == load_definitions()
    with pytest.raises(ValidationError):
        DEFINITIONS.limits.max_cycles = 1


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
