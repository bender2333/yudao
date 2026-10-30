# 动作合同的共用契约测试（工单 #1170；执行环境服务设计说明第 4 节「执行环境的合同」；总图第四节「动作」缝）。
#
# 立缝的样子：两个实际的环境实现（本机的 `LocalEnvironment` 与测试用的 `SecondEnvironment`）接受同一份动作合同
# （`harness/actions.py` 的 `Action` 与 `ActionReceipt`），不按实现的名字分派，也不读请求里的部门与阶段。
# 这个文件查六件事：
# 1. 写入与读取都是真的：写入以后按同一个合同读回内容，公开树摘要有对应的变化（回执可核对）；
# 2. 旧合同（没有核实方法与能否取消）与写明这两项的请求都照常执行；
# 3. 两个实现对同一个动作给出同样的回执；
# 4. 取消先于动作到达时记下、动作到达时不执行；实现不在合同之外保存跨步状态（新起一个实现读到同样的结果）；
# 5. 本机执行环境不执行的类别与不在这一类里的工具立刻失败；合同与实现的连接不写部门与阶段的名字；
# 6. 工具许可拒绝在工具一侧发生：回执带被拒绝标记与原因，执行环境没有被调用。
#
# 层：模块层（工作区文件、一个实现与它的真实依赖、一次部门激活）。守 R2（动作合同的交换字段与类别）与
# R3（文件动作的回执可核对；工具调用先有许可）。

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable

import pytest

from harness.actions import Action, ActionReceipt, FactsQuery
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.models import EventType
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests import second_environment

REPO_ROOT = Path(__file__).resolve().parents[2]
ORGANIZATION = REPO_ROOT / "harness" / "definitions" / "organization.json"
CONTRACT_TEST = Path(__file__).resolve()

# 组织定义里的部门按顺序排列，第一个部门是一轮工作的起点（一层定义，测试不写部门的名字）
FIRST_DEPARTMENT = json.loads(ORGANIZATION.read_text(encoding="utf-8"))["departments"][0]["id"]

# 两个实际的环境实现：交给它们一个工作区目录，取到同一个合同上的实现
IMPLEMENTATIONS: dict[str, Callable[[Path], Any]] = {
    "local": LocalEnvironment.open,
    "second": second_environment.SecondEnvironment,
}

# 请求里的部门是上报进事实的一个字段：环境实现不按它分派。契约测试用一个不属于任何部门的值，
# 连接处因此不写部门的名字
REQUESTER = "contract-test"

# 阶段的名字只在路线图里：合同两侧的代码不写它们（路线图的五个阶段，以及已归档计划里的编号）
STAGE_PATTERN = re.compile(r"(阶段[一二三四五六七八九]|Stage\s*\d|\b\d\.\d[A-Z]\b)")


def _action(tool: str, kind: str, tool_input: dict[str, Any], **declared: Any) -> Action:
    return Action(action_id=f"{REQUESTER}:{tool}", kind=kind, tool=tool,
                  department=REQUESTER, input=tool_input, **declared)


def _perform(implementation: Any, action: Action) -> ActionReceipt:
    # 两个实现的执行都是异步的；这一步没有同时进行的事，直接跑完
    return asyncio.run(implementation.perform(action))


@pytest.fixture(params=sorted(IMPLEMENTATIONS))
def implementation(request, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return request.param, root, IMPLEMENTATIONS[request.param](root)


def test_a_written_file_is_read_back_through_the_same_contract(implementation):
    name, _root, environment = implementation
    action = _action("write_file", "write", {"path": "notes/a.txt", "content": "hello\n"})

    written = _perform(environment, action)

    assert written.action_id == action.action_id
    assert written.status == "completed" and written.ok and written.error is None
    assert written.refused is False and written.refused_reason is None
    read = _perform(environment, _action("read_file", "read", {"path": "notes/a.txt"}))
    assert read.status == "completed" and read.output == "hello\n", name


def test_a_write_changes_the_public_tree_the_contract_reports(implementation):
    _name, _root, environment = implementation
    before = environment.query(FactsQuery(tree=True)).tree
    assert before is not None and "notes/a.txt" not in before.files

    _perform(environment, _action("write_file", "write", {"path": "notes/a.txt", "content": "hello\n"}))

    after = environment.query(FactsQuery(tree=True)).tree
    assert after is not None
    assert after.digest != before.digest, "写入以后公开树的摘要没有变化"
    assert "notes/a.txt" in after.files
    assert len(after.hashes) == len(after.files)
    assert after.hashes[after.files.index("notes/a.txt")].startswith("sha256:")


@pytest.mark.parametrize("declared", [
    {},
    {"verification": "snapshot", "cancellable": True},
])
def test_an_old_contract_and_a_declared_contract_are_both_executed(implementation, declared):
    # 旧合同里没有这两项（缺了按动作类别的既定值解释）；写明的请求照常执行，行为不因此改变
    _name, _root, environment = implementation
    written = _perform(environment, _action("write_file", "write", {"path": "a.txt", "content": "x"}, **declared))

    assert written.status == "completed" and written.ok and written.error is None


def test_both_implementations_answer_the_same_file_actions_the_same_way(tmp_path):
    receipts: dict[str, tuple[ActionReceipt, ActionReceipt]] = {}
    for name, open_environment in IMPLEMENTATIONS.items():
        root = tmp_path / name
        root.mkdir()
        environment = open_environment(root)
        write = _action("write_file", "write", {"path": "src/echo.py", "content": "print(1)\n"})
        receipts[name] = (
            _perform(environment, write),
            _perform(environment, _action("read_file", "read", {"path": "src/echo.py"})),
        )

    assert receipts["local"] == receipts["second"], "两个实现给同一个动作的回执不相同"


def test_cancelling_before_the_action_arrives_keeps_it_unexecuted(implementation):
    _name, _root, environment = implementation
    action = _action("write_file", "write", {"path": "a.txt", "content": "x"})
    environment.cancel(action.action_id)

    cancelled = _perform(environment, action)

    assert cancelled.status == "cancelled" and cancelled.ok is False and cancelled.error
    missing = _perform(environment, _action("read_file", "read", {"path": "a.txt"}))
    assert missing.status == "failed" and missing.output is None, "取消的动作被写出了文件"


def test_a_new_instance_over_the_same_workspace_reads_the_written_file(implementation):
    # 实现不在合同之外保存跨步状态：结果留在工作区，新起一个实现对同一个工作区读到同样的内容与摘要
    name, root, environment = implementation
    _perform(environment, _action("write_file", "write", {"path": "a.txt", "content": "hello\n"}))
    digest = environment.query(FactsQuery(tree=True)).tree.digest

    fresh = IMPLEMENTATIONS[name](root)

    assert _perform(fresh, _action("read_file", "read", {"path": "a.txt"})).output == "hello\n"
    assert fresh.query(FactsQuery(tree=True)).tree.digest == digest


def test_an_action_the_implementation_does_not_execute_fails(implementation):
    _name, _root, environment = implementation
    # 新的动作类别由各自的处理分支提供：本机执行环境还没有取回的处理分支
    with pytest.raises(ValueError, match="does not execute fetch"):
        _perform(environment, _action("fetch_url", "fetch", {"url": "https://example.invalid"},
                                      verification="none", cancellable=True))
    # 工具不在它声明的动作类别里：按类别分派时立刻失败，不换一个动作执行
    with pytest.raises(ValueError, match="is not a read action"):
        _perform(environment, _action("write_file", "read", {"path": "a.txt", "content": "x"}))


def test_the_connection_to_the_contract_names_no_department_or_stage():
    # 合同两侧的代码不带部门与阶段的名字：部门标识取自组织定义，阶段名是路线图里的那几个
    departments = [item["id"] for item in json.loads(ORGANIZATION.read_text(encoding="utf-8"))["departments"]]
    assert departments, "组织定义里没有部门"
    offenders: list[str] = []
    for source in (Path(second_environment.__file__), CONTRACT_TEST):
        text = source.read_text(encoding="utf-8")
        for department in departments:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(department)}(?![A-Za-z0-9_])", text):
                offenders.append(f"{source.name}: {department}")
        for stage in STAGE_PATTERN.findall(text):
            offenders.append(f"{source.name}: {stage}")
    assert offenders == [], "合同与实现的连接里出现了部门或阶段的名字：\n" + "\n".join(offenders)


def _function_call(identity: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json.dumps(arguments)}


def test_a_tool_permission_refusal_is_a_receipt_and_the_environment_is_not_called(tmp_path):
    # 拒绝发生在工具一侧的执行前检查（工具许可）：回执带被拒绝标记与原因，工具结果照常记录，
    # 执行环境没有被调用，工作区没有变化
    department = FIRST_DEPARTMENT
    allowed = set(DEFINITIONS.tools_for(department))
    denied = next(name for name, tool in DEFINITIONS.tools.items()
                  if tool.kind == "environment" and name not in allowed)
    call = _function_call("denied", denied, {"path": "src/echo.py", "content": "x"})
    adapter = FakeAdapter({department: [ModelResponse(output=[call]), product_spec()]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("print the argument in uppercase")
    workspace = system.workspace(run_id)
    workspace.write_file("src/echo.py", "original\n")

    system.activate_once(run_id)

    events = system.store.list_events(run_id)
    called = next(event for event in events
                  if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == "denied")
    result = json.loads(called.payload["input_item"]["output"])
    assert result["refused"] is True, "被拒绝的调用没有带回被拒绝标记"
    assert result["refused_reason"] == called.payload["error"] and called.payload["ok"] is False
    assert not any(event.type == EventType.TOOL_STARTED and (event.payload or {}).get("id") == "denied"
                   for event in events), "被拒绝的调用有工具开始事件"
    assert workspace.read_file("src/echo.py") == "original\n", "被拒绝的写入改动了工作区"
