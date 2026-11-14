# 通用命令行、有界事件流与随包运维技能集成测试（docs/design/external-ops-agent.md「有界事件流订阅」「随包运维技能」「验收」）。
# 启动真实本机 Yudao 服务子进程与本机模型桩服务，不打开浏览器，仅通过命令行完成全链路配置、运行、有界等待、导出核查与发布 wheel 验证。

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import psutil

from harness.__main__ import main as cli_main
from harness.event_store import EventStore
from harness.proposals import SUBMIT_COMPLETION
from harness.tests.protocol_helpers import ScriptedProvider, model_test_responder, send_reply, sse

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SEC = 180.0
PORT_PREFIX = "port: "
SECRET_API_KEY = "sk-ops-integration-secret-never-export-73915"


def _utf8_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    merged = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(REPO_ROOT),
    }
    if extra:
        merged.update(extra)
    return merged


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    # 严格按记录的进程号 PID 收集并终止测试启动的服务进程及其全部子孙进程，确认整棵进程树完全退出后再返回
    tracked: list[psutil.Process] = []
    try:
        root = psutil.Process(process.pid)
        tracked = [root, *root.children(recursive=True)]
    except psutil.Error:
        pass

    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    for member in list(tracked):
        try:
            for descendant in member.children(recursive=True):
                if descendant not in tracked:
                    tracked.append(descendant)
        except psutil.Error:
            pass
        try:
            member.kill()
        except psutil.Error:
            pass

    process.wait(timeout=30)
    _gone, alive = psutil.wait_procs(tracked, timeout=30)
    assert not alive, f"服务子进程树未在时限内完全退出：{[proc.pid for proc in alive]}"


def _read_log_lines(log_path: Path) -> list[str]:
    try:
        return log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


@contextmanager
def _running_service_subprocess(workdir: Path, data_dir: Path) -> Iterator[str]:
    log_path = workdir / "yudao-api-service.log"
    spawn_kwargs: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    cmd = [
        sys.executable,
        "-m",
        "harness",
        "api",
        "--data-dir",
        str(data_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--no-browser",
        "--no-fetch",
    ]
    with log_path.open("wb") as log_handle:
        proc = subprocess.Popen(
            cmd,
            cwd=workdir,
            env=_utf8_env(),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            **spawn_kwargs,
        )
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
        bound_port: int | None = None
        while time.monotonic() < deadline:
            assert proc.poll() is None, "\n".join(_read_log_lines(log_path))
            for line in _read_log_lines(log_path):
                if line.startswith(PORT_PREFIX):
                    bound_port = int(line[len(PORT_PREFIX) :].strip())
                    break
            if bound_port is not None:
                break
            time.sleep(0.1)
        if bound_port is None:
            raise TimeoutError(f"服务进程未在时限内输出监听端口：\n" + "\n".join(_read_log_lines(log_path)))

        base_url = f"http://127.0.0.1:{bound_port}"
        while time.monotonic() < deadline:
            assert proc.poll() is None, "\n".join(_read_log_lines(log_path))
            try:
                resp = httpx.get(f"{base_url}/api/capabilities", timeout=2.0, trust_env=False)
                if resp.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        else:
            raise TimeoutError(f"服务进程未在时限内响应能力清单：\n" + "\n".join(_read_log_lines(log_path)))

        yield base_url
    finally:
        _terminate_process_tree(proc)


def _run_cli_subprocess(
    argv: list[str],
    *,
    cwd: Path,
    stdin_text: str = "",
    extra_env: dict[str, str] | None = None,
    timeout: float = 90.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness", *argv],
        cwd=cwd,
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_utf8_env(extra_env),
        timeout=timeout,
        check=False,
    )


def _build_provider_responder() -> Any:
    models = [
        {
            "id": "ops-maker/ops-direct-model",
            "limit": {"context": 128000, "output": 8192},
            "modalities": {"input": ["text"], "output": ["text"]},
        }
    ]

    def respond(_provider: ScriptedProvider, handler: Any) -> None:
        if handler.body is None:
            send_reply(handler, 200, "application/json", json.dumps({"data": models}).encode("utf-8"))
            return
        body = handler.body
        tools = body.get("tools") or []
        tool_names = {
            (item.get("function") or item).get("name")
            for item in tools
            if isinstance(item, dict)
        }
        if SUBMIT_COMPLETION in tool_names:
            completion_args = json.dumps(
                {
                    "summary": "已按直做形态完成命令行全链路验证",
                    "uncertain": [],
                    "known_risks": [],
                },
                ensure_ascii=False,
            )
            chunk = {
                "id": "chat-ops-done",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": body.get("model") or "ops-maker/ops-direct-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-submit-completion",
                                    "type": "function",
                                    "function": {
                                        "name": SUBMIT_COMPLETION,
                                        "arguments": completion_args,
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 24, "completion_tokens": 12, "total_tokens": 36},
            }
            payload = sse(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n", "data: [DONE]\n\n")
            send_reply(handler, 200, "text/event-stream", payload)
            return

        status, content_type, chunks = model_test_responder(
            body,
            protocol="chat_completions",
            actual_model=body.get("model") or "ops-maker/ops-direct-model",
        )
        send_reply(handler, status, content_type, b"".join(chunks))

    return respond


def test_real_service_headless_cli_roundtrip_events_until_run_done_and_secret_isolation(tmp_path: Path) -> None:
    # 守 R1/R3：启动真实 Yudao 服务进程后，仅凭通用命令行走通 capabilities -> describe -> 模型连接与准入 ->
    # project.create -> work_item.create -> events --until-type run_done -> project.overview -> run.export，
    # 服务关闭后执行离线 replay --project 只读核对，并核验明文密钥不出现在任何命令行输出、日志文件、事件库与导出结果中
    upstream = ScriptedProvider([_build_provider_responder()] * 16)
    data_dir = tmp_path / "service-data"
    cli_outputs: list[str] = []

    try:
        with _running_service_subprocess(tmp_path, data_dir) as base_url:
            def cli_subproc(*args: str, stdin_text: str = "") -> subprocess.CompletedProcess[str]:
                res = _run_cli_subprocess(
                    ["--url", base_url, *args],
                    cwd=tmp_path,
                    stdin_text=stdin_text,
                )
                cli_outputs.append(res.stdout)
                cli_outputs.append(res.stderr)
                return res

            def cli_fast(*args: str, stdin_text: str = "") -> tuple[int, str, str]:
                # 经真实 TCP/HTTP 网络访问独立服务子进程（transport=None），免去每步重复冷启动解释器的开销
                out_buf = io.StringIO()
                err_buf = io.StringIO()
                code = cli_main(
                    ["--url", base_url, *args],
                    stdin=io.StringIO(stdin_text),
                    stdout=out_buf,
                    stderr=err_buf,
                    environ={},
                    transport=None,
                )
                out_text = out_buf.getvalue()
                err_text = err_buf.getvalue()
                cli_outputs.append(out_text)
                cli_outputs.append(err_text)
                return code, out_text, err_text

            # 1. capabilities（真实命令行子进程）与 describe（真实 HTTP 网络调用）
            cap_res = cli_subproc("capabilities")
            assert cap_res.returncode == 0, cap_res.stderr
            cap_doc = json.loads(cap_res.stdout)
            assert cap_doc["deployment"]["access"] == "local"

            desc_cmd_code, desc_cmd_out, desc_cmd_err = cli_fast("describe", "work_item.create")
            assert desc_cmd_code == 0, desc_cmd_err
            assert json.loads(desc_cmd_out)["kind"] == "command"

            desc_qry_code, desc_qry_out, desc_qry_err = cli_fast("describe", "project.overview")
            assert desc_qry_code == 0, desc_qry_err
            assert json.loads(desc_qry_out)["kind"] == "query"

            # 2. 连接模型服务与选用模型（密钥经真实命令行子进程 --stdin 传入）
            cat_code, cat_out, cat_err = cli_fast("query", "catalog")
            assert cat_code == 0, cat_err
            cat_init = json.loads(cat_out)
            connect_res = cli_subproc(
                "command",
                "catalog.connect",
                "--stdin",
                stdin_text=json.dumps(
                    {
                        "base_version": cat_init["data"]["revision"],
                        "base_url": f"{upstream.base}/v1",
                        "api_key": SECRET_API_KEY,
                    }
                ),
            )
            assert connect_res.returncode == 0, connect_res.stderr
            connect_accepted = json.loads(connect_res.stdout)
            provider_id = connect_accepted["refs"]["provider_id"]

            ev_col_code, ev_col_out, ev_col_err = cli_fast(
                "events",
                "--after",
                str(connect_accepted["position"]),
                "--until-type",
                "catalog_candidates_collected",
                "--timeout",
                "30",
            )
            assert ev_col_code == 0, ev_col_err
            collected_lines = [json.loads(line) for line in ev_col_out.splitlines() if line.strip()]
            assert collected_lines[-1]["type"] == "catalog_candidates_collected"

            _cat2_code, cat2_out, _cat2_err = cli_fast("query", "catalog")
            cat_after_connect = json.loads(cat2_out)
            sel_code, sel_out, sel_err = cli_fast(
                "command",
                "catalog.model.select",
                "--param",
                f"base_version={cat_after_connect['data']['revision']}",
                "--string-param",
                f"provider_id={provider_id}",
                "--string-param",
                "model=ops-maker/ops-direct-model",
            )
            assert sel_code == 0, sel_err
            select_accepted = json.loads(sel_out)

            ev_adm_code, _ev_adm_out, ev_adm_err = cli_fast(
                "events",
                "--after",
                str(select_accepted["position"]),
                "--until-type",
                "catalog_test_finished",
                "--timeout",
                "30",
            )
            assert ev_adm_code == 0, ev_adm_err

            # 确认目录准入已记录完成
            admit_deadline = time.monotonic() + 30.0
            while time.monotonic() < admit_deadline:
                _cr_code, cr_out, _cr_err = cli_fast("query", "catalog")
                cat_ready = json.loads(cr_out)["data"]
                if any(row.get("admitted") for row in cat_ready.get("admissions", [])):
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("模型选用后未在时限内完成准入记录")

            # 3. project.create -> organization.adopt (single_role_direct) -> work_item.create
            proj_code, proj_out, proj_err = cli_fast(
                "command",
                "project.create",
                "--string-param",
                "name=进程外运维集成项目",
                "--string-param",
                "goal=验证命令行有界事件流直到运行完成",
            )
            assert proj_code == 0, proj_err
            project_id = json.loads(proj_out)["refs"]["project_id"]

            _org_code, org_out, _org_err = cli_fast(
                "query",
                "project.organization",
                "--param",
                f"project_id={project_id}",
            )
            org_snap = json.loads(org_out)
            adopt_code, _adopt_out, adopt_err = cli_fast(
                "command",
                "organization.adopt",
                "--string-param",
                f"project_id={project_id}",
                "--param",
                f"base_version={org_snap['data']['version']}",
                "--string-param",
                "form=single_role_direct",
                "--string-param",
                "reason=集成测试采用单角色直做形态",
            )
            assert adopt_code == 0, adopt_err

            wi_code, wi_out, wi_err = cli_fast(
                "command",
                "work_item.create",
                "--string-param",
                f"project_id={project_id}",
                "--string-param",
                "text=完成一次直做交付并结束事项",
            )
            assert wi_code == 0, wi_err
            wi_accepted = json.loads(wi_out)
            wi_pos = wi_accepted["position"]
            work_item_id = wi_accepted["refs"]["work_item_id"]
            run_id = wi_accepted["refs"]["run_id"]

            # 4. 真实命令行子进程执行 events --after <位置> --until-type run_done
            ev_run = cli_subproc(
                "events",
                "--after",
                str(wi_pos),
                "--work-item",
                work_item_id,
                "--until-type",
                "run_done",
                "--timeout",
                "60",
            )
            assert ev_run.returncode == 0, ev_run.stderr
            run_events = [json.loads(line) for line in ev_run.stdout.splitlines() if line.strip()]
            assert len(run_events) >= 1
            assert run_events[-1]["type"] == "run_done"
            assert run_events[-1]["run_id"] == run_id

            # 5. project.overview 与真实命令行子进程执行 run.export
            ov_code, ov_out, ov_err = cli_fast("query", "project.overview", "--param", f"project_id={project_id}")
            assert ov_code == 0, ov_err
            overview = json.loads(ov_out)["data"]
            items = [item for item in overview["work_items"] if item["work_item_id"] == work_item_id]
            assert len(items) == 1
            assert items[0]["status"] == "adopted"

            export_res = cli_subproc("query", "run.export", "--param", f"run_id={run_id}")
            assert export_res.returncode == 0, export_res.stderr
            export_doc = json.loads(export_res.stdout)
            assert export_doc["data"]["run_id"] == run_id
            assert SECRET_API_KEY not in export_res.stdout

        # 6. 服务关闭后立即运行离线 replay --project 只读核对，并核对全部命令行输出、日志目录与 SQLite 事件库均不含明文密钥
        replay_res = _run_cli_subprocess(
            ["--data-dir", str(data_dir), "replay", "--project", project_id],
            cwd=tmp_path,
        )
        cli_outputs.append(replay_res.stdout)
        cli_outputs.append(replay_res.stderr)
        assert replay_res.returncode == 0, replay_res.stderr
        replay_doc = json.loads(replay_res.stdout)
        assert replay_doc["data"]["consistent"] is True

        for text_chunk in cli_outputs:
            assert SECRET_API_KEY not in text_chunk

        logs_dir = data_dir / "logs"
        if logs_dir.is_dir():
            for log_file in logs_dir.rglob("*"):
                if log_file.is_file():
                    assert SECRET_API_KEY not in log_file.read_text(encoding="utf-8", errors="replace")

        service_stdout_log = tmp_path / "yudao-api-service.log"
        assert SECRET_API_KEY not in service_stdout_log.read_text(encoding="utf-8", errors="replace")

        sqlite_file = data_dir / "events.sqlite"
        assert SECRET_API_KEY.encode("utf-8") not in sqlite_file.read_bytes()
        store = EventStore(sqlite_file, read_only=True)
        try:
            all_events = store.read(0, limit=10000)
            assert len(all_events) >= 5
            assert SECRET_API_KEY not in json.dumps([ev.payload for ev in all_events], ensure_ascii=False)
        finally:
            store.close()
    finally:
        upstream.close()


def _ignore_for_wheel_copy(_directory: str, names: list[str]) -> set[str]:
    skipped = {"__pycache__", "tests", "release_assets", ".pytest_cache"}
    return {name for name in names if name in skipped or name.endswith(".egg-info")}


def test_release_wheel_packages_ops_skill_and_loads_from_packaged_wheel(tmp_path: Path) -> None:
    # 守 R1/R3：构建发布 wheel 后核对归档内含 harness/ops_skill/SKILL.md，且从解包的 wheel 目录加载时 skill show 与 skill install 正常工作
    pkg_src = tmp_path / "pkg-src"
    pkg_src.mkdir()
    shutil.copy2(REPO_ROOT / "pyproject.toml", pkg_src / "pyproject.toml")
    shutil.copytree(REPO_ROOT / "harness", pkg_src / "harness", ignore=_ignore_for_wheel_copy)

    dist_dir = tmp_path / "dist"
    build_res = subprocess.run(
        ["uv", "build", "--wheel", "--no-build-isolation", "--out-dir", str(dist_dir)],
        cwd=pkg_src,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_utf8_env(),
        timeout=120,
        check=False,
    )
    if build_res.returncode != 0:
        # 当前环境未预装 setuptools 时回退到标准 uv build --wheel
        build_res = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
            cwd=pkg_src,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_utf8_env(),
            timeout=180,
            check=False,
        )
    assert build_res.returncode == 0, build_res.stdout + "\n" + build_res.stderr

    wheels = list(dist_dir.glob("yudao_harness-*.whl"))
    assert len(wheels) == 1
    wheel_path = wheels[0]

    source_skill_text = (REPO_ROOT / "harness" / "ops_skill" / "SKILL.md").read_text(encoding="utf-8")
    wheel_extract_dir = tmp_path / "wheel-site"
    with zipfile.ZipFile(wheel_path) as archive:
        members = set(archive.namelist())
        assert "harness/ops_skill/SKILL.md" in members
        assert "harness/ops_skill/__init__.py" in members
        assert "harness/cli_client.py" in members
        assert archive.read("harness/ops_skill/SKILL.md").decode("utf-8").replace("\r\n", "\n") == source_skill_text
        archive.extractall(wheel_extract_dir)

    isolated_cwd = tmp_path / "run-cwd"
    isolated_cwd.mkdir()
    wheel_env = _utf8_env({"PYTHONPATH": str(wheel_extract_dir)})

    verify_origin = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import harness.ops_skill as m; print(Path(m.__file__).resolve())",
        ],
        cwd=isolated_cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=wheel_env,
        timeout=30,
        check=True,
    )
    loaded_module_path = Path(verify_origin.stdout.strip())
    assert wheel_extract_dir.resolve() in loaded_module_path.parents

    show_res = subprocess.run(
        [sys.executable, "-m", "harness", "skill", "show"],
        cwd=isolated_cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=wheel_env,
        timeout=30,
        check=False,
    )
    assert show_res.returncode == 0, show_res.stderr
    assert show_res.stdout == source_skill_text

    install_target = tmp_path / "installed-agent-skill"
    inst_res = subprocess.run(
        [sys.executable, "-m", "harness", "skill", "install", str(install_target)],
        cwd=isolated_cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=wheel_env,
        timeout=30,
        check=False,
    )
    assert inst_res.returncode == 0, inst_res.stderr
    assert (install_target / "SKILL.md").read_text(encoding="utf-8") == source_skill_text

    refuse_res = subprocess.run(
        [sys.executable, "-m", "harness", "skill", "install", str(install_target)],
        cwd=isolated_cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=wheel_env,
        timeout=30,
        check=False,
    )
    assert refuse_res.returncode == 1
