# 对外合同里的部门是字符串，取值由定义给出（工单 #1389；形态与核验角色设计说明「形态随事项冻结」；
# 总图第四节「接口」「定义」缝）：事件载荷与成果的作者部门不把部门收窄成三个固定的名字，
# 换一份把质检改了名的定义，载荷的类型校验照样接受新的名字；命令收到这份定义里没有的部门时照旧拒绝，
# 错误写明可用的部门。
#
# 守的是 R2（对外合同的字段：部门是字符串、合同的版本）与 R3（形态随事项冻结：换一份定义不改代码）。
# 改名的那份定义要落在临时目录里（load_definitions 读文件），所以整个文件属于模块层。

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.commands import execute
from harness.app.contracts import Rejected
from harness.app.payloads import PAYLOADS
from harness.app.project_and_work_item_commands import DepartmentSettingsSave, GuidanceSend, MaterialRecord
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.models import EventType
from harness.runtime import LoopSystem

# 改名后的质检：不是默认定义里的任何一个名字
RENAMED = "inspection"


def _renamed(value: Any, old: str, new: str) -> Any:
    # 定义文件里表示部门的那个字符串全部换掉，其余内容照旧。规则登记的条目名带着部门（roles.<部门>.…），
    # 它也是按部门写的，一起换
    if isinstance(value, dict):
        return {_renamed_key(key, old, new): _renamed(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item, old, new) for item in value]
    return new if value == old else value


def _renamed_key(key: Any, old: str, new: str) -> Any:
    # 键本身是部门名，或者按部门分段的规则条目名（roles.<部门>.visible）：按段换，其余照旧
    if not isinstance(key, str):
        return key
    return ".".join(new if part == old else part for part in key.split("."))


def _definitions_with_a_renamed_department(tmp_path: Path) -> Any:
    # 发布的那份定义的一份副本，质检改叫另一个名字
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        renamed = _renamed(content, "quality", RENAMED)
        (directory / path.name).write_text(json.dumps(renamed, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _validate(event_type: str, payload: dict[str, Any]) -> Any:
    return TypeAdapter(PAYLOADS[event_type]).validate_python(payload)


def test_the_payload_contract_takes_the_department_name_from_the_definition(tmp_path):
    # 验收第 3 条：一份改名质检的测试定义下，事件载荷的类型校验接受改名后的部门。
    # 事件载荷里的部门是字符串，取值由定义给出：合同里没有「只有这三个名字」这一条
    definitions = _definitions_with_a_renamed_department(tmp_path)
    assert definitions.departments == ("product", "engineering", RENAMED)
    assert RENAMED not in DEFINITIONS.departments

    guidance = _validate(EventType.DEPARTMENT_GUIDANCE_RECEIVED, {
        "id": "guidance-1", "department": RENAMED, "version": 1, "text": "改一下",
        "guidance_ref": {"kind": "guidance", "content_hash": "sha256:00", "path": "guidance/1",
                         "media_type": None},
        "status": "received",
    })
    assert guidance.department == RENAMED

    asked = _validate(EventType.ASK_STARTED, {
        "requester": RENAMED, "recipient": "engineering", "question": "这两条要求冲突吗",
        "branch_session_id": "session-1",
    })
    assert (asked.requester, asked.recipient) == (RENAMED, "engineering")


def test_a_review_issuer_is_a_department_name_not_one_fixed_name():
    # 验收第 1 条的另一半：质检结论的作者部门与结论的种类不同，它是写这份成果的部门的名字，
    # 所以合同里不再固定为某个部门的名字
    issuer = TypeAdapter(PAYLOADS[EventType.QA_SUBMITTED]).json_schema()["properties"]["issuer"]
    assert issuer["type"] == "string" and "const" not in issuer


@pytest.mark.parametrize(("name", "command_request"), [
    ("material.record", MaterialRecord(
        command_id=str(uuid.uuid4()), project_id="project-1", text="一段原文", department=RENAMED)),
    ("guidance.send", GuidanceSend(
        command_id=str(uuid.uuid4()), work_item_id="item-1", department=RENAMED, text="按新的要求做")),
    ("department_settings.save", DepartmentSettingsSave(
        command_id=str(uuid.uuid4()), base_version=0, project_id="project-1", department=RENAMED)),
])
def test_a_command_with_a_department_outside_the_definition_names_the_available_ones(tmp_path, name, command_request):
    # 验收第 2 条：命令带定义里没有的部门时被拒绝，错误写明可用的部门。
    # 走的是真实的命令登记与命令处理，不直接调用处理函数
    application = Application(LoopSystem.for_testing(tmp_path, FakeAdapter([])))
    try:
        result = asyncio.run(execute(application, application.registry.commands[name], command_request,
                                     actor="user:local"))
    finally:
        application.close()
    assert isinstance(result, Rejected)
    assert result.reason == "not_allowed"
    assert RENAMED in result.message
    for department in DEFINITIONS.departments:
        assert DEFINITIONS.department_labels[department] in result.message
        assert department in result.message
