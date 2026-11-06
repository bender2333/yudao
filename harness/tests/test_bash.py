# bash 工具的持久行为：管道与重定向、非零退出码、环境继承与凭据脱敏、
# 超限截断的回执与按编号取回。这些结论 spawn 真实子进程，登记为集成层。
# 超时与取消结束整棵进程树在 test_bash_process_tree.py（工单 #1215 的准入用例）。
from __future__ import annotations

import secrets
import sys

from harness import environment as environment_module
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.tests.helpers import perform
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


