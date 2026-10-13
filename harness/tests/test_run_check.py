# run_check 的持久行为（工单 #480）：任意命令字符串在快照的全新副本中用 bash 运行，
# 质检能运行有依赖的项目的真实测试；副本的改动不绑定原快照；时限缺省与钳位取规则登记；
# 检查结束时副本删除；进程继承完整环境、密钥值脱敏。这些结论 spawn 真实子进程，登记为集成层。
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import asyncio

import pytest

from harness import environment as environment_module
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.models import EventType, json_dumps
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import action, perform, wait_until_stopped
from harness.workspace import Workspace


def _python() -> str:
    return sys.executable.replace("\\", "/")


def _check_copies() -> set[str]:
    return {item.name for item in Path(tempfile.gettempdir()).glob("yudao-check-*")}


def test_uv_managed_project_pytest_binds_snapshot(tmp_path, monkeypatch):
    # 带依赖的小项目：run_check 运行 uv run pytest 成功，回执绑定检查时的快照
    pytest.importorskip("pytest")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "outside-copy-venv"))
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("pyproject.toml",
                         "[project]\nname = \"mini\"\nversion = \"0\"\n"
                         "requires-python = \">=3.11\"\ndependencies = [\"pytest\"]\n")
    workspace.write_file("test_mini.py", "def test_ok():\n    assert 1 + 1 == 2\n")
    subprocess.run(["uv", "lock", "--offline"], cwd=workspace.root, check=True,  # noqa: S603
                   env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "outside-copy-venv")})
    digest = workspace.digest()
    result = perform(LocalEnvironment(workspace), "run_check",
                     {"name": "pytest", "command": "uv run --offline pytest -q -p no:cacheprovider"})
    assert result.output["tree_changed"] is False
    receipt = workspace.snapshot().facts.latest_check("engineering", "pytest")
    assert receipt is not None and receipt.exit_code == 0
    assert receipt.snapshot_hash == digest
    assert digest in receipt.summary or "host-executed" in receipt.summary


def test_check_copy_mutation_does_not_bind_pass_to_original_snapshot(tmp_path):
    # 检查命令修改副本中的文件：回执写明副本改变，通过结论不绑定原来的快照，工作区不受影响
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("app.py", "BROKEN = True\n")
    original = workspace.digest()
    result = perform(LocalEnvironment(workspace), "run_check", {
        "name": "mutate",
        "command": f"\"{_python()}\" -c \"from pathlib import Path; Path('app.py').write_text('FIXED = True\\n')\"",
    })
    assert result.ok is True and result.output["exit_code"] == 0
    assert result.output["tree_changed"] is True
    assert result.output["snapshot_hash"] != original
    assert workspace.read_file("app.py") == "BROKEN = True\n"
    assert workspace.digest() == original
    assert "pass is not bound to the original snapshot" in result.output["summary"]


def test_check_copy_is_deleted_when_check_finishes(tmp_path):
    # 检查结束时副本删除：运行前后检查副本的目录集合相同
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("app.py", "print('ok')\n")
    before = _check_copies()
    result = perform(LocalEnvironment(workspace), "run_check",
                     {"name": "smoke", "command": "echo hi"})
    assert result.ok is True
    assert _check_copies() == before


def test_check_copy_is_deleted_after_timeout(tmp_path):
    # 超时的检查同样删除副本
    workspace = Workspace(tmp_path / "ws")
    environment = LocalEnvironment(workspace, check_timeout_sec=2)
    before = _check_copies()
    result = perform(environment, "run_check", {
        "name": "hang",
        "command": f"\"{_python()}\" -c \"import time; print('started', flush=True); time.sleep(60)\"",
    })
    assert result.status == "timeout" and result.output["exit_code"] == 124
    assert _check_copies() == before


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


def test_timed_out_check_stops_the_process_tree(tmp_path):
    # 超时结束整个进程树，回执带截至结束时的输出
    workspace = Workspace(tmp_path / "ws")
    environment = LocalEnvironment(workspace, check_timeout_sec=2)
    command = (
        f"\"{_python()}\" -c \"import subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "print('started child=%d' % child.pid,flush=True);time.sleep(60)\""
    )
    started = time.monotonic()
    result = perform(environment, "run_check", {"name": "smoke", "command": command})
    assert time.monotonic() - started < 30
    assert result.ok is True and result.status == "timeout"
    assert result.output["exit_code"] == 124
    assert result.output["summary"].splitlines()[1] == "check timed out after 2s"
    child = int(re.search(r"started child=(\d+)", result.output["summary"]).group(1))
    assert wait_until_stopped(child)


def test_cancel_stops_a_running_check(tmp_path):
    # 运行中取消：结束整个进程树，回执记为已取消，退出码 130
    workspace = Workspace(tmp_path / "ws")
    environment = LocalEnvironment(workspace)
    marker = tmp_path / "started"
    command = (
        f"\"{_python()}\" -c \"import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "print('started child=%d' % child.pid,flush=True);"
        f"pathlib.Path(r'{marker.as_posix()}').write_text('running');time.sleep(60)\""
    )
    request = action("run_check", {"name": "smoke", "command": command})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, environment.perform(request))
        for _ in range(300):
            if marker.exists():
                break
            time.sleep(0.05)
        environment.cancel(request.action_id)
        result = future.result(timeout=30)
    assert result.status == "cancelled" and result.output["exit_code"] == 130
    lines = result.output["summary"].splitlines()
    assert lines[1] == "check cancelled; the process tree was stopped"
    child = int(re.search(r"started child=(\d+)", lines[2]).group(1))
    assert wait_until_stopped(child)


def test_environment_inherited_and_secrets_redacted(tmp_path, monkeypatch):
    # 检查进程得到 Yudao 进程的全部环境变量（与 bash 相同）；输出中密钥的值替换成名字
    value = secrets.token_hex(8)
    monkeypatch.setenv("MY_SECRET_TOKEN", value)
    workspace = Workspace(tmp_path / "ws")
    leaked = perform(LocalEnvironment(workspace), "run_check",
                     {"name": "env", "command": "echo $MY_SECRET_TOKEN"})
    assert leaked.ok is True
    assert value not in leaked.output["summary"]
    assert "${MY_SECRET_TOKEN}" in leaked.output["summary"]


def test_run_check_requires_a_command_string(tmp_path):
    # 命令字符串必填；argv 与自报 exit_code 都不是证据
    workspace = Workspace(tmp_path / "ws")
    missing = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "exit_code": 0})
    assert missing.ok is False and "command" in (missing.error or "")
    legacy = perform(LocalEnvironment(workspace), "run_check",
                     {"name": "smoke", "argv": ["python", "ok.py"], "exit_code": 0})
    assert legacy.ok is False and "command" in (legacy.error or "")


def test_run_check_runs_at_the_copy_root_with_bash(tmp_path):
    # 检查在副本根目录用 bash 运行：管道与重定向可用，工作目录是副本根
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("data.txt", "hello\n")
    result = perform(LocalEnvironment(workspace), "run_check",
                     {"name": "pipe", "command": "cat data.txt | tr a-z A-Z && pwd"})
    assert result.ok is True and result.output["exit_code"] == 0
    assert "HELLO" in result.output["summary"]
    assert "yudao-check-" in result.output["summary"]


RUN_CHECK_TEXT = "python -c \"print('smoke ok')\""


def _tool_call(identity: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _script_with(checks: dict[str, Any]) -> list[dict[str, Any]]:
    return [product_spec(), plan_turn(),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}, checks=checks),
            review_turn("release", "checks passed on the current snapshot", checks=checks)]


def test_delivery_citing_a_run_check_receipt_is_accepted_and_quality_releases_on_it(tmp_path):
    # 事项运行加假模型：工程用 run_check 运行测试，交付引用这条回执被接纳；质检用 run_check
    # 在交付快照上再跑一次项目的测试并放行
    checks = {"smoke": {"command": f"{_python()} -c \"assert True\""}}
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(_script_with(checks)))
    run_id = system.create_run("build an echo CLI")
    system.run_until_stop(run_id)
    projection = system.project(run_id)
    assert projection.phase == "DONE" and projection.stop_reason == "released"
    passed = [receipt for receipt in system.workspace(run_id).receipts() if receipt.name == "smoke"]
    # 工程与质检各运行过一次检查：两次都是主机执行的真实进程
    assert len(passed) == 2 and all(receipt.exit_code == 0 for receipt in passed)


def test_delivery_citing_a_bash_result_is_rejected_with_the_check_reason(tmp_path):
    # 交付引用 bash 的动作回执被拒绝，拒绝原因写明要用检查
    from harness.proposals import delivery
    smoke_delivery = dict(delivery("echo CLI", files=["src/echo.py"], check_names=["smoke"]))
    smoke_delivery.pop("kind", None)
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(),
        ModelResponse(output=[
            _tool_call("write-1", "write_file", {"path": "src/echo.py",
                                                 "content": "import sys\nprint(sys.argv[1])\n"}),
            _tool_call("bash-1", "bash", {"command": RUN_CHECK_TEXT}),
            _tool_call("submit-1", "submit_delivery", smoke_delivery),
        ]),
    ]))
    run_id = system.create_run("build an echo CLI")
    system.run_until_stop(run_id)
    projection = system.project(run_id)
    assert projection.phase != "QUALITY" and not projection.delivery_spec, "引用 bash 结果的交付不能被接纳"
    assert projection.rejections, "引用 bash 结果的交付必须被拒绝"
    rejected = projection.rejections
    assert any(item.get("department") == "engineering" for item in rejected), "拒绝项要由工程部门触发"
    assert any("run_check" in json_dumps(item) for item in rejected), "拒绝原因必须写明要用检查回执"
