# run_check 的持久行为（工单 #480）：任意命令字符串在快照的全新副本中用 bash 运行，
# 质检能运行有依赖的项目的真实测试；副本的改动不绑定原快照；时限缺省与钳位取规则登记；
# 检查结束时副本删除；进程继承完整环境、密钥值脱敏。这些结论 spawn 真实子进程，登记为集成层。
from __future__ import annotations

import subprocess
import sys
import time
import json
from pathlib import Path
from typing import Any



from harness import environment as environment_module
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.models import ArtifactRef, EventType, json_dumps
from harness.proposals import delivery_turn, product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import perform, quality_turns
from harness.workspace import Workspace


def _python() -> str:
    return sys.executable.replace("\\", "/")


def _write_local_wheel(directory: Path) -> str:
    # 手工打一个只含一个模块的纯 Python wheel，作为小项目的依赖：uv 从本地文件安装它，
    # 不需要网络，也不需要机器上的 uv 缓存里碰巧有哪个包
    import zipfile

    name = "minidep-1.0-py3-none-any.whl"
    files = {
        "minidep/__init__.py": "VALUE = 2\n",
        "minidep-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: minidep\nVersion: 1.0\n",
        "minidep-1.0.dist-info/WHEEL": ("Wheel-Version: 1.0\nGenerator: test\n"
                                        "Root-Is-Purelib: true\nTag: py3-none-any\n"),
    }
    files["minidep-1.0.dist-info/RECORD"] = "".join(f"{path},,\n" for path in files) \
        + "minidep-1.0.dist-info/RECORD,,\n"
    with zipfile.ZipFile(directory / name, "w") as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return name


def test_uv_managed_project_pytest_binds_snapshot(tmp_path, monkeypatch):
    # 带依赖的小项目：run_check 在 uv 管理的项目里运行测试成功，回执绑定检查时的快照。
    # 依赖是本地 wheel，uv 缓存用空目录：用例不依赖运行它的机器上缓存里有什么包
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "outside-copy-venv"))
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "empty-uv-cache"))
    workspace = Workspace(tmp_path / "ws")
    wheel = _write_local_wheel(workspace.root)
    workspace.write_file("pyproject.toml",
                         "[project]\nname = \"mini\"\nversion = \"0\"\n"
                         "requires-python = \">=3.11\"\ndependencies = [\"minidep\"]\n"
                         f"[tool.uv]\npackage = false\n[tool.uv.sources]\nminidep = {{ path = \"{wheel}\" }}\n")
    workspace.write_file("test_mini.py",
                         "import unittest\n\nimport minidep\n\n\nclass MiniTest(unittest.TestCase):\n"
                         "    def test_ok(self):\n        self.assertEqual(minidep.VALUE, 2)\n")
    subprocess.run(["uv", "lock", "--offline"], cwd=workspace.root, check=True)  # noqa: S603,S607
    digest = workspace.digest()
    result = perform(LocalEnvironment(workspace), "run_check",
                     {"name": "unittest", "command": "uv run --offline python -m unittest -q"})
    assert result.output["tree_changed"] is False
    receipt = workspace.snapshot().facts.latest_check("engineering", "unittest")
    assert receipt is not None and receipt.exit_code == 0
    assert receipt.snapshot_hash == digest
    assert digest in receipt.summary or "host-executed" in receipt.summary


def test_timeout_default_and_max_come_from_rules(tmp_path, monkeypatch):
    # 不给时限按缺省值执行，超过最长值按最长值执行；缺省 600、最长 3600 取规则登记。
    # 上限用一个很小的值代替以后，真正 spawn 进程验证截断到了替代值
    assert DEFINITIONS.rule_value("check_timeout_sec") == 600
    assert DEFINITIONS.rule_value("check_timeout_max_sec") == 3600
    command = f"\"{_python()}\" -c \"import time;time.sleep(60)\""
    environment = LocalEnvironment(Workspace(tmp_path / "ws"), check_timeout_sec=2)
    started = time.monotonic()
    result = perform(environment, "run_check", {"name": "smoke", "command": command})
    assert time.monotonic() - started < 30
    assert result.status == "timeout" and result.output["exit_code"] == 124
    assert result.output["summary"].splitlines()[1] == "check timed out after 2s"
    monkeypatch.setattr(environment_module, "_CHECK_TIMEOUT_MAX", 2)
    result = perform(LocalEnvironment(Workspace(tmp_path / "clamped")), "run_check",
                     {"name": "smoke", "command": command, "timeout_sec": 10**6})
    assert result.status == "timeout" and result.output["exit_code"] == 124
    assert result.output["summary"].splitlines()[1] == "check timed out after 2s"


def test_run_check_requires_a_command_string(tmp_path):
    # 命令字符串必填；argv 与自报 exit_code 都不是证据
    workspace = Workspace(tmp_path / "ws")
    missing = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "exit_code": 0})
    assert missing.ok is False and "command" in (missing.error or "")
    legacy = perform(LocalEnvironment(workspace), "run_check",
                     {"name": "smoke", "argv": ["python", "ok.py"], "exit_code": 0})
    assert legacy.ok is False and "command" in (legacy.error or "")


RUN_CHECK_TEXT = "python -c \"print('smoke ok')\""


def _tool_call(identity: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _script_with(checks: dict[str, Any]) -> dict[str, list]:
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}, checks=checks)],
        "quality": quality_turns("release", "checks passed on the current snapshot", checks=checks),
    }


def test_delivery_citing_a_run_check_receipt_is_accepted_and_quality_releases_on_it(tmp_path):
    # 事项运行加假模型：工程用 run_check 运行测试，交付引用这条回执被接纳；质检用 run_check
    # 在交付快照上再跑一次项目的测试并放行
    checks = {"smoke": {"command": f"{_python()} -c \"assert True\""}}
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(_script_with(checks)))
    run_id = system.create_run("build an echo CLI")
    system.run_until_stop(run_id)
    projection = system.project(run_id)
    assert projection.status == "done" and projection.stop_reason == "released"
    engineering = [receipt for receipt in system.workspace(run_id).receipts() if receipt.name == "smoke"]
    # 质检在自己的检查工作区里跑，会话结束即删，回执按 #481 的位置从工具事件工件读
    quality = [json.loads(system.artifacts.get(ArtifactRef(**event.payload["output_ref"])).decode("utf-8"))
               for event in system.store.list_events(run_id)
               if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("name") == "run_check"
               and event.department == "quality"]
    # 工程与质检各运行过一次检查：两次都是主机执行的真实进程
    assert len(engineering) == 1 and engineering[0].exit_code == 0
    assert len(quality) == 1 and quality[0]["executor"] == "host" and quality[0]["exit_code"] == 0


def test_delivery_citing_a_bash_result_is_rejected_with_the_check_reason(tmp_path):
    # 交付引用 bash 的动作回执被拒绝，拒绝原因写明要用检查
    from harness.proposals import delivery
    smoke_delivery = dict(delivery("echo CLI", check_names=["smoke"]))
    smoke_delivery.pop("kind", None)
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _tool_call("write-1", "write_file", {"path": "src/echo.py",
                                                     "content": "import sys\nprint(sys.argv[1])\n"}),
                _tool_call("bash-1", "bash", {"command": RUN_CHECK_TEXT}),
                _tool_call("submit-1", "submit_delivery", smoke_delivery),
            ]),
        ],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }))
    run_id = system.create_run("build an echo CLI")
    system.run_until_stop(run_id)
    projection = system.project(run_id)
    assert projection.active_department != "quality" and not projection.delivery_spec, "引用 bash 结果的交付不能被接纳"
    assert projection.rejections, "引用 bash 结果的交付必须被拒绝"
    rejected = projection.rejections
    assert any(item.get("department") == "engineering" for item in rejected), "拒绝项要由工程部门触发"
    assert any("run_check" in json_dumps(item) for item in rejected), "拒绝原因必须写明要用检查回执"
