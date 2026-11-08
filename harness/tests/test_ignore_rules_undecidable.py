# 工单 #604：忽略规则无法判断（诊断 `Git ignore rules cannot be decided`）时，所有位置统一以
# host_commit_error 停止事项（设计说明 docs/design/local-tools.md「公开树」）。装配请求的位置以前把它
# 记成 context_overflow，工具许可取事实与动作后快照的位置以前记成 provider_error；这两处各有一条用例，
# 从 LoopSystem 整体驱动，用真实的文件系统与真实的 libgit2 判定，只把探测库的打开换成失败
# （TreeError 的构造方式见 harness/public_tree.py 的 excluded_by_ignore_rules）。

import tempfile
from pathlib import Path

import pygit2
import pytest

from harness import public_tree as public_tree_module
from harness.adapters.fake import FakeAdapter
from harness.environment import LocalEnvironment
from harness.models import EventType, json_dumps
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.public_tree import IgnoreRulesUndecidable
from harness.runtime import LoopSystem
from harness.tests.helpers import perform
from harness.workspace import Workspace

DIAGNOSTIC = "Git ignore rules cannot be decided"


def _short_data_dir(tmp_path):
    # 数据目录放在比 tmp_path 更短的路径下：与 test_workspace_unrepresentable.py 同一条环境约定，
    # 探测库的路径长度不随运行机的临时目录变深
    return Path(tempfile.mkdtemp(prefix="d", dir=tmp_path.parent)) / "data"


def _system(tmp_path, engineering_turns):
    # 脚本按部门给出（工单 #557）；这一张工单的两条用例都在工程或产品第一次请求装配时停下
    return LoopSystem.for_testing(_short_data_dir(tmp_path), FakeAdapter({
        "product": [product_spec()],
        "engineering": list(engineering_turns),
        "quality": [],
    }))


def _cannot_decide_the_ignore_rules(monkeypatch):
    # 主机判断不了忽略规则：探测库打不开（真实触发条件是仓库路径太长，见工单 #706 的现场）。
    # 只换这一个函数，忽略规则的判定本身照旧由 libgit2 做
    def refuse(base, probe):
        raise pygit2.GitError("path too long: probe")

    monkeypatch.setattr(public_tree_module, "_probe_repository", refuse)


def _failure(system, run_id):
    return next((event for event in system.store.list_events(run_id)
                 if event.type == EventType.RUN_FAILED), None)


def _failure_message(system, run_id):
    # 失败时把 run_failed 的说明带进断言信息，运行机上的失败才查得出原因
    failed = _failure(system, run_id)
    return "" if failed is None else str(failed.payload.get("message", ""))


def _write_call(identity, path, content):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "write_file",
            "arguments": json_dumps({"path": path, "content": content})}


def test_assembly_stops_with_host_commit_error_when_ignore_rules_cannot_be_decided(tmp_path, monkeypatch):
    # 公开树里已经有忽略规则（.gitignore），主机判断不了它：装配工作请求的那一次读取失败，
    # 事项以 host_commit_error 停止，停止说明带诊断原文，不记成上下文超限。
    # 产品先把规格交出来（这时工作区里还没有忽略规则），随后的工程激活在运行工作区里装配请求
    system = _system(tmp_path, [])
    run_id = system.create_run("Ignore rules cannot be decided while a request is assembled")
    assert system.activate_once(run_id).product_spec is not None
    workspace = system.workspace(run_id)
    (workspace.root / "notes.txt").write_text("hello\n", encoding="utf-8")
    (workspace.root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _cannot_decide_the_ignore_rules(monkeypatch)

    result = system.activate_once(run_id)

    assert (result.status, result.stop_reason) == ("failed", "host_commit_error"), (
        result.status, result.stop_reason, _failure_message(system, run_id))
    assert DIAGNOSTIC in _failure_message(system, run_id)


def test_a_tool_step_stops_with_host_commit_error_when_ignore_rules_cannot_be_decided(tmp_path, monkeypatch):
    # 工程的动作在动作后读公开树（工具许可取事实与动作后快照）：动作写下的 .gitignore 让这一次读取
    # 判断不了忽略规则，事项以 host_commit_error 停止，不再记成 provider_error
    def write_the_ignore_file(request):
        return ModelResponse(output=[_write_call("write-ignore", ".gitignore", "node_modules/\n")])

    system = _system(tmp_path, [write_the_ignore_file])
    run_id = system.create_run("Ignore rules cannot be decided after a tool wrote them")
    _cannot_decide_the_ignore_rules(monkeypatch)

    result = system.run_until_stop(run_id)

    assert (result.status, result.stop_reason) == ("failed", "host_commit_error"), (
        result.status, result.stop_reason, _failure_message(system, run_id))
    assert DIAGNOSTIC in _failure_message(system, run_id)


def test_a_file_action_does_not_turn_undecidable_ignore_rules_into_a_receipt(tmp_path, monkeypatch):
    # 文件工具里遇到同一个错误：以前作为失败回执交还模型（事项接着跑），现在按原样交给步骤驱动，
    # 由它以 host_commit_error 停止事项
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file(".gitignore", "node_modules/\n")
    workspace.write_file("notes.txt", "hello\n")
    environment = LocalEnvironment(workspace)
    _cannot_decide_the_ignore_rules(monkeypatch)

    with pytest.raises(IgnoreRulesUndecidable) as raised:
        perform(environment, "read_file", {"path": "notes.txt"})

    assert DIAGNOSTIC in str(raised.value)


def test_a_check_verification_does_not_turn_undecidable_ignore_rules_into_a_recorded_error(tmp_path, monkeypatch):
    # 检查副本核对里遇到同一个错误：检查的命令写下 .gitignore 以后，主机核对检查副本时判断不了忽略规则。
    # 以前这一条只记进回执的核对失败里（事项接着跑），现在同样交给步骤驱动以 host_commit_error 停止
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("notes.txt", "hello\n")
    environment = LocalEnvironment(workspace)
    _cannot_decide_the_ignore_rules(monkeypatch)

    with pytest.raises(IgnoreRulesUndecidable) as raised:
        perform(environment, "run_check",
                {"name": "write-ignore", "command": "echo node_modules/ > .gitignore"})

    assert DIAGNOSTIC in str(raised.value)
