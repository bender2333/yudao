# bash 工具的持久行为：管道与重定向、非零退出码、超时与取消的进程树结束、
# 超时缺省与钳位、环境继承与凭据脱敏、超限截断的游标取回、bash 缺失的报错、
# 以及调用 argv 不带 -l。这些结论 spawn 真实子进程，登记为集成层。
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from harness import environment as environment_module
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.tests.helpers import action, perform, wait_for_file, wait_until_stopped
from harness.workspace import Workspace


def _environment(path, **kwargs) -> LocalEnvironment:
    kwargs.setdefault("session_id", "test-session")
    kwargs.setdefault("jobs", environment_module.BackgroundJobTable())
    return LocalEnvironment(Workspace(path / "ws"), **kwargs)


def _python() -> str:
    return sys.executable.replace("\\", "/")


def test_pipe_redirect_and_exit_code(tmp_path):
    environment = _environment(tmp_path)
    piped = perform(environment, "bash", {"command": "echo hello | tr a-z A-Z"})
    assert piped.ok is True and piped.status == "completed"
    assert piped.output["status"] == "ok" and piped.output["exit_code"] == 0
    assert piped.output["output"] == "HELLO"
    redirected = perform(environment, "bash", {"command": "mkdir -p out && echo DATA > out/data.txt"})
    assert redirected.output["status"] == "ok"
    assert (tmp_path / "ws" / "out" / "data.txt").read_text(encoding="utf-8").strip() == "DATA"
    failed = perform(environment, "bash", {"command": "exit 3"})
    assert failed.ok is True and failed.status == "completed"
    assert failed.output["status"] == "failed" and failed.output["exit_code"] == 3


def _tree_command(marker: str) -> str:
    program = (
        "import subprocess,sys,time,pathlib;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"print('started child=%d' % child.pid,flush=True);"
        f"pathlib.Path(r'{marker}').write_text('running',encoding='utf-8');"
        "time.sleep(60)"
    )
    return f'"{_python()}" -c "{program}"'


def _grandchild(output: str) -> int:
    return int(re.search(r"started child=(\d+)", output).group(1))


def test_timeout_stops_the_process_tree(tmp_path):
    environment = _environment(tmp_path, check_timeout_sec=2)
    marker = (tmp_path / "started").as_posix()
    started = time.monotonic()
    result = perform(environment, "bash", {"command": _tree_command(marker), "timeout_sec": 2})
    assert time.monotonic() - started < 60
    assert result.ok is True and result.status == "timeout"
    assert result.output["exit_code"] == 124 and result.output["status"] == "timeout"
    assert "timed out after 2s" in result.output["output"]
    assert "the process tree was stopped" in result.output["output"]
    assert wait_until_stopped(_grandchild(result.output["output"]))


def test_cancel_stops_the_process_tree(tmp_path):
    environment = _environment(tmp_path)
    marker = tmp_path / "started"
    request = action("bash", {"command": _tree_command(marker.as_posix())})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, environment.perform(request))
        wait_for_file(marker)
        started = time.monotonic()
        environment.cancel(request.action_id)
        result = future.result(timeout=60)
    assert time.monotonic() - started < 30
    assert result.ok is True and result.status == "cancelled"
    assert result.output["exit_code"] == 130 and result.output["status"] == "cancelled"
    assert "the process tree was stopped" in result.output["output"]
    assert wait_until_stopped(_grandchild(result.output["output"]))


def test_timeout_default_and_max_come_from_rules(tmp_path, monkeypatch):
    seen: dict[str, int] = {}
    real_run = environment_module._run_process

    async def spy(argv, workdir, env, timeout_sec, stop):
        seen["timeout_sec"] = timeout_sec
        return await real_run(argv, workdir, env, timeout_sec, stop)

    monkeypatch.setattr(environment_module, "_run_process", spy)
    environment = _environment(tmp_path)
    perform(environment, "bash", {"command": "echo hi"})
    assert seen["timeout_sec"] == DEFINITIONS.rule_value("bash_timeout_default_sec")
    over = DEFINITIONS.rule_value("bash_timeout_max_sec") + 100
    perform(environment, "bash", {"command": "echo hi", "timeout_sec": over})
    assert seen["timeout_sec"] == DEFINITIONS.rule_value("bash_timeout_max_sec")


def test_environment_inherited_and_secrets_redacted(tmp_path, monkeypatch):
    value = secrets.token_hex(8)
    monkeypatch.setenv("MY_SECRET_TOKEN", value)
    environment = _environment(tmp_path)
    inherited = perform(environment, "bash", {"command": "echo $MY_SECRET_TOKEN | wc -c"})
    assert inherited.output["status"] == "ok"
    assert int(inherited.output["output"].strip()) == len(value) + 1
    leaked = perform(environment, "bash", {"command": f"echo prefix-{value}-suffix"})
    assert leaked.output["status"] == "ok"
    assert value not in leaked.output["output"]
    assert "${MY_SECRET_TOKEN}" in leaked.output["output"]


def test_truncated_output_pages_back_exactly(tmp_path):
    environment = _environment(tmp_path)
    command = f'"{_python()}" -c "for i in range(2000): print(\'line-%05d-\' % i + \'x\' * 40)"'
    first = perform(environment, "bash", {"command": command})
    assert first.ok is True and first.status == "completed"
    assert first.output["status"] == "ok" and first.output["truncated"] is True
    assert "use read_output with job_id" in first.output["output"]
    job_id = first.output.get("job_id")
    assert job_id

    rest = perform(environment, "read_output", {"job_id": job_id})
    assert rest.ok is True and rest.status == "completed"
    assert rest.output["status"] == "exited"
    assert rest.output["exit_code"] == 0

    first_page = first.output["output"].split("\n...output truncated")[0]
    full = first_page + rest.output["output"]
    assert len(full) > DEFINITIONS.rule_value("tool_output_limit")
    expected = "\n".join(f"line-{i:05d}-" + "x" * 40 for i in range(2000))
    assert full == expected

def test_missing_bash_reports_the_cause(tmp_path, monkeypatch):
    monkeypatch.setattr(environment_module, "_BASH_PATH", None)
    monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: None)
    real_isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: False if "bash" in str(p).lower() else real_isfile(p))
    result = perform(_environment(tmp_path), "bash", {"command": "echo hi"})
    assert result.ok is False and result.output is None
    assert "bash" in result.error.lower()


def test_bash_does_not_start_a_login_shell(tmp_path, monkeypatch):
    seen: dict[str, list] = {}
    real_run = environment_module._run_process

    async def spy(argv, workdir, env, timeout_sec, stop):
        seen["argv"] = list(argv)
        return await real_run(argv, workdir, env, timeout_sec, stop)

    monkeypatch.setattr(environment_module, "_run_process", spy)
    result = perform(_environment(tmp_path), "bash", {"command": "echo hi"})
    assert result.output["status"] == "ok"
    assert "-l" not in seen["argv"] and "-c" in seen["argv"]


def test_saved_output_stays_outside_the_public_tree(tmp_path):
    environment = _environment(tmp_path)
    command = f'"{_python()}" -c "for i in range(2000): print(\'line-%05d-\' % i + \'x\' * 40)"'
    first = perform(environment, "bash", {"command": command})
    assert first.output["truncated"] is True
    files = perform(environment, "list_files", {"path": "."}).output
    assert not any(name.startswith(".checks") for name in files)
    saved = list((tmp_path / "ws" / ".checks" / "tool-output").glob("*.output"))
    assert len(saved) == 1
    stored = saved[0].read_text(encoding="utf-8")
    expected = "\n".join(f"line-{i:05d}-" + "x" * 40 for i in range(2000))
    assert stored == expected
