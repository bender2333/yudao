"""采纳写回的远端 HTTP 合同（工单 #980，ADR-0034、接入已有项目设计说明「确认以后」）。

这里用真实的组件：一个本机 HTTP 服务按 GitHub 合并请求 API 的最小合同回答创建与列表请求，
并用 `git http-backend` 把同一个主机上的真实裸仓库按 smart HTTP 提供出来；写回的分支经过真实的
Git 传输推到这个裸仓库。测试不用 mock 对象，也不改远端真实 GitHub（那是 #982）。

守 R3（路线图已经走到的阶段写明的行为：接入已有仓库与采纳写回，经合同检查不看内部）：
源目录登记的远端是宿主仓库地址时，推送分支、创建合并请求、结果未知时核实，以及凭据不进事实。
"""

import base64
import gc
import json
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pygit2
import pytest

from harness.models import ProjectEventType
from harness.providers.credentials import CredentialChain
from harness.public_tree import CapturedFile, CapturedTree
from harness.writeback import (
    WritebackOutcomeUnknown, WritebackTargetUnavailable, git_tree_to_captured,
)

from .test_writeback import _setup_yudao_env
from .test_writeback_branch import _PASS_COMMAND, _adopt


CREDENTIAL_REF = "GITHUB_WRITEBACK_TOKEN"
TOKEN = "test-token-980-not-in-facts"
OWNER = "owner"
REPO = "repo"


def _failing_check_command() -> str:
    return f'"{sys.executable}" -c "import sys; sys.exit(1)"'


def _bare_repo(path: Path, files: dict[str, bytes], branch: str = "main") -> pygit2.Oid:
    # 真实裸仓库：写回的分支经 HTTP 推送以后落在这里
    path.parent.mkdir(parents=True, exist_ok=True)
    repo = pygit2.init_repository(str(path), bare=True)
    signature = pygit2.Signature("Yudao Test", "test@yudao.invalid")
    builder = repo.TreeBuilder()
    for name, content in files.items():
        builder.insert(name, repo.create_blob(content), pygit2.enums.FileMode.BLOB)
    tree_oid = builder.write()
    commit_oid = repo.create_commit(f"refs/heads/{branch}", signature, signature, "初始提交", tree_oid, [])
    repo.set_head(f"refs/heads/{branch}")
    # smart HTTP 的接收与读取都打开：服务按 git http-backend 提供这个仓库
    repo.config["http.receivepack"] = True
    repo.config["http.uploadpack"] = True
    del repo
    gc.collect()
    return commit_oid


class _GitHubRemote:
    """本机 HTTP 服务 + 真实裸仓库：GitHub 合并请求 API 的最小合同与 smart HTTP 的 Git。

    故障注入（真实的传输故障，不是 mock）：push_faults 与 create_faults 是按调用次序消费的队列，
    "drop_after_apply" 表示动作已经在服务端完成、回应没有到达调用方；list_faults 决定核实请求列表
    这一次会不会失败。每次调用都记下计数，测试用它核对动作发生了几次。
    """

    def __init__(self, root: Path, files: dict[str, bytes] | None = None) -> None:
        self.remotes_root = root / "remotes"
        self.bare_path = self.remotes_root / OWNER / f"{REPO}.git"
        self.head_commit = _bare_repo(self.bare_path, files or {"app.py": b"print('base')\n"})
        self.token = TOKEN
        self.pull_requests: list[dict] = []
        self.push_calls = 0
        self.create_calls = 0
        self.list_calls = 0
        self.git_requests = 0
        self.api_requests = 0
        self.push_faults: list[str] = []
        self.create_faults: list[str] = []
        self.list_faults: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    # -- 地址与仓库事实 -----------------------------------------------------

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{OWNER}/{REPO}.git"

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v3"

    def branch_commit(self, branch: str) -> pygit2.Commit | None:
        repo = pygit2.Repository(str(self.bare_path))
        try:
            name = f"refs/heads/{branch}"
            if name not in repo.references:
                return None
            return repo.references[name].peel(pygit2.Commit)
        finally:
            del repo
            gc.collect()

    def branch_files(self, branch: str) -> dict[str, bytes]:
        repo = pygit2.Repository(str(self.bare_path))
        try:
            if f"refs/heads/{branch}" not in repo.references:
                return {}
            commit = repo.references[f"refs/heads/{branch}"].peel(pygit2.Commit)
            return {item.path: item.data for item in git_tree_to_captured(repo, commit.tree).files}
        finally:
            del repo
            gc.collect()

    # -- 服务 ---------------------------------------------------------------

    def __enter__(self) -> "_GitHubRemote":
        service = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的接口
                service._handle(self, "GET")

            def do_POST(self) -> None:  # noqa: N802
                service._handle(self, "POST")

            def log_message(self, *args: object) -> None:
                # 服务的日志不进入测试输出：凭据值也不写进日志
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._server = None
        self._thread = None

    def _handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        parsed = urllib.parse.urlsplit(handler.path)
        path = urllib.parse.unquote(parsed.path)
        if path.startswith("/api/v3/repos/"):
            self._api(handler, method, parsed)
        else:
            self._git(handler, method, parsed)

    @staticmethod
    def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
        # push 用 chunked 传输：按块读完，再作为 CGI 的标准输入交给 git http-backend
        if (handler.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            chunks: list[bytes] = []
            while True:
                line = handler.rfile.readline().strip()
                size = int(line.split(b";")[0] or b"0", 16)
                if size == 0:
                    handler.rfile.readline()
                    break
                chunks.append(handler.rfile.read(size))
                handler.rfile.readline()
            return b"".join(chunks)
        length = int(handler.headers.get("Content-Length") or 0)
        return handler.rfile.read(length) if length else b""

    @staticmethod
    def _take(queue: list[str]) -> str:
        return queue.pop(0) if queue else ""

    def _git(self, handler: BaseHTTPRequestHandler, method: str, parsed: urllib.parse.SplitResult) -> None:
        self.git_requests += 1
        expected = "Basic " + base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        if handler.headers.get("Authorization") != expected:
            handler.send_response(401)
            handler.send_header("WWW-Authenticate", 'Basic realm="git"')
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        body = self._read_body(handler)
        is_push = method == "POST" and parsed.path.endswith("/git-receive-pack")
        if is_push:
            self.push_calls += 1
        push_fault = self._take(self.push_faults) if is_push else ""
        if push_fault == "fail_without_apply":
            # 推送没有落到裸仓库，回应也没有给调用方：结果未知，核实以后确认没有推送上去
            handler.send_response(502)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        environment = dict(os.environ)
        environment.update({
            "GIT_PROJECT_ROOT": str(self.remotes_root),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": parsed.path,
            "QUERY_STRING": parsed.query,
            "REQUEST_METHOD": method,
            "CONTENT_TYPE": handler.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(len(body)),
            "REMOTE_USER": "x-access-token",
            "AUTH_TYPE": "Basic",
        })
        completed = subprocess.run(["git", "http-backend"], input=body, capture_output=True, env=environment)
        if is_push and push_fault == "drop_after_apply":
            # 分支已经在裸仓库里更新，回应没有到达调用方：推送的结果未知
            handler.send_response(502)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        header_blob, separator, payload = completed.stdout.partition(b"\r\n\r\n")
        if not separator:
            header_blob, _, payload = completed.stdout.partition(b"\n\n")
        status = "200 OK"
        headers: list[tuple[str, str]] = []
        for line in header_blob.decode("latin-1").splitlines():
            name, _, value = line.partition(":")
            if not name.strip():
                continue
            if name.strip().lower() == "status":
                status = value.strip()
            else:
                headers.append((name.strip(), value.strip()))
        handler.send_response(int(status.split()[0]))
        for name, value in headers:
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    def _api(self, handler: BaseHTTPRequestHandler, method: str, parsed: urllib.parse.SplitResult) -> None:
        self.api_requests += 1
        if handler.headers.get("Authorization") != f"Bearer {self.token}":
            self._respond(handler, 401, {"message": "Bad credentials"})
            return
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) != 6 or parts[:3] != ["api", "v3", "repos"] or parts[5] != "pulls":
            self._respond(handler, 404, {"message": "Not Found"})
            return
        if method == "GET":
            self.list_calls += 1
            if self._take(self.list_faults) == "fail":
                self._respond(handler, 500, {"message": "server error"})
                return
            query = urllib.parse.parse_qs(parsed.query)
            head = query.get("head", [""])[0].split(":", 1)[-1]
            self._respond(handler, 200, [pr for pr in self.pull_requests if pr["head"]["ref"] == head])
            return
        self.create_calls += 1
        body = json.loads(self._read_body(handler) or b"{}")
        fault = self._take(self.create_faults)
        if fault == "drop_without_apply":
            handler.close_connection = True
            return
        if fault in {"server_error", "reject"}:
            status, message = (500, "server error") if fault == "server_error" else (404, "Not Found")
            self._respond(handler, status, {"message": message})
            return
        number = len(self.pull_requests) + 1
        record = {
            "number": number,
            "html_url": f"http://127.0.0.1:{self.port}/{OWNER}/{REPO}/pull/{number}",
            "title": body.get("title"),
            "body": body.get("body"),
            "head": {"ref": body.get("head")},
            "base": {"ref": body.get("base")},
            "state": "open",
        }
        self.pull_requests.append(record)
        if fault == "drop_after_apply":
            # 请求已经在服务端创建，回应没有到达调用方：创建的结果未知
            handler.close_connection = True
            return
        if fault == "already_exists":
            # GitHub 对同一个 head 已有请求的回答：交给核实
            self._respond(handler, 422, {"message": "A pull request already exists for this head"})
            return
        self._respond(handler, 201, record)

    @staticmethod
    def _respond(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
        data = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)


def _setup(tmp_path: Path, remote: _GitHubRemote, *, credential: str | None = TOKEN,
           check_commands: tuple[str, ...] = (_PASS_COMMAND,)):
    credentials = CredentialChain(overrides={CREDENTIAL_REF: credential}) if credential else None
    store, writes, artifacts, projects = _setup_yudao_env(tmp_path, credentials=credentials)
    source_dir = tmp_path / "src"
    source_dir.mkdir(exist_ok=True)
    pid = projects.register("写回远端测试", "把采纳成果写回远端仓库")
    projects.configure_source_directory(
        pid, "default", str(source_dir), base_version=0,
        writeback_enabled=True, remote=remote.url, target_branch="main",
        check_commands=list(check_commands), credential_ref=CREDENTIAL_REF,
    )
    return store, writes, artifacts, projects, pid


def _adopt_one(writes, artifacts, pid, *, base: dict[str, bytes] | None = None,
               adopted: dict[str, bytes] | None = None, check_names: tuple[str, ...] = (_PASS_COMMAND,)):
    base_files = base if base is not None else {"app.py": b"print('base')\n"}
    adopted_files = adopted if adopted is not None else {"app.py": b"print('adopted')\n",
                                                         "added.txt": b"adopted addition\n"}
    base_captured = CapturedTree((), tuple(CapturedFile(path, data) for path, data in sorted(base_files.items())))
    adopted_captured = CapturedTree((), tuple(CapturedFile(path, data) for path, data in sorted(adopted_files.items())))
    _adopt(writes, artifacts, pid, "w1", "r1", "adopt_1", base_captured, adopted_captured,
           check_names=check_names)


def _events(store, pid) -> list:
    return store.list_project_events(pid)


def test_a_writeback_pushes_the_branch_and_creates_a_pull_request(tmp_path):
    # 远端登记成宿主仓库地址：写回分支经真实 Git 推送到达裸仓库，合并请求经 HTTP 接口创建，
    # 完成事件记录请求身份、地址、源分支与目标分支，凭据值不出现在任何事件里
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            event = projects.execute_writeback(pid, "adopt_1")

            assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED
            payload = event.payload
            branch = "writeback/adopt_1"
            assert payload["branch"] == branch

            # 真实裸仓库收到了写回分支：提交基于目标提交，树是最终合并树
            writeback_commit = remote.branch_commit(branch)
            assert writeback_commit is not None
            assert writeback_commit.parents[0].id == remote.head_commit
            assert remote.branch_files(branch) == {
                "app.py": b"print('adopted')\n", "added.txt": b"adopted addition\n"}
            assert payload["final_tree_digest"].startswith("sha256:")

            # 合并请求：身份、地址、源分支、目标分支
            pull_request = payload["pull_request"]
            assert pull_request["identity"] == f"{OWNER}/{REPO}#1"
            assert pull_request["url"] == f"http://127.0.0.1:{remote.port}/{OWNER}/{REPO}/pull/1"
            assert pull_request["branch"] == branch
            assert pull_request["target_branch"] == "main"
            assert pull_request["status"] == "created"
            assert remote.create_calls == 1 and len(remote.pull_requests) == 1

            # 请求的标题与说明携带采纳身份、事项与验收摘要
            created = remote.pull_requests[0]
            assert created["head"]["ref"] == branch and created["base"]["ref"] == "main"
            assert "w1" in created["title"] and "adopt_1" in created["body"]
            assert "验收摘要" in created["body"]
            assert "added.txt" in created["body"] and "已知风险" in created["body"]

            # 凭据只从凭据引用解析、只在控制主机上使用：事件与工件事项里都没有它的值
            dumped = json.dumps([entry.payload for entry in _events(store, pid)], ensure_ascii=False)
            assert TOKEN not in dumped
            assert CREDENTIAL_REF in dumped
        finally:
            store.close()
            gc.collect()


def test_a_missing_credential_is_rejected_before_any_external_action(tmp_path):
    # 凭据引用解析不到：按既有的拒绝边界交回，远端一次也没有被碰到（没有推送、没有创建请求）
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote, credential=None)
        try:
            _adopt_one(writes, artifacts, pid)
            with pytest.raises(WritebackTargetUnavailable) as rejected:
                projects.execute_writeback(pid, "adopt_1")
            assert rejected.value.reason == "credential_missing"
            assert rejected.value.target == CREDENTIAL_REF

            assert remote.git_requests == 0 and remote.api_requests == 0
            assert remote.push_calls == 0 and remote.create_calls == 0
            assert remote.branch_commit("writeback/adopt_1") is None
            assert not any(entry.type == ProjectEventType.WRITEBACK_COMPLETED for entry in _events(store, pid))
        finally:
            store.close()
            gc.collect()


def test_the_writeback_command_explains_the_missing_credential(tmp_path):
    # 命令层按既有的 not_allowed 拒绝并给出中文说明（不新增认证系统）
    import asyncio

    from harness.app.commands import Rejection
    from harness.app.project_and_work_item_commands import WritebackExecute, _execute_writeback
    from harness.event_store import Command

    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote, credential=None)
        try:
            _adopt_one(writes, artifacts, pid)

            class _App:
                def __init__(self, project_service):
                    self.system = type("System", (), {"projects": project_service})()

            command = Command(command_id="00000000-0000-0000-0000-000000000980",
                              name="writeback.execute", digest="d", actor="user")
            with pytest.raises(Rejection) as rejected:
                asyncio.run(_execute_writeback(
                    _App(projects), command,
                    WritebackExecute(command_id="00000000-0000-0000-0000-000000000980", project_id=pid)))
            assert rejected.value.reason == "not_allowed"
            assert "写回的目标凭据缺失" in rejected.value.message
            assert CREDENTIAL_REF in rejected.value.message
            assert TOKEN not in rejected.value.message
        finally:
            store.close()
            gc.collect()


def test_an_unknown_push_outcome_is_verified_before_the_request_is_created(tmp_path):
    # 推送已经在远端完成、回应没有到达调用方：先核实远端分支提交，记下核实事实，再创建合并请求；
    # 同一个采纳只产生一条分支
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            remote.push_faults.append("drop_after_apply")
            event = projects.execute_writeback(pid, "adopt_1")

            assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED
            assert event.payload["verified_external"] is True
            assert event.payload["pull_request"]["identity"] == f"{OWNER}/{REPO}#1"

            verified = [entry for entry in _events(store, pid)
                        if entry.type == ProjectEventType.WRITEBACK_VERIFIED]
            assert [entry.payload["action"] for entry in verified] == ["push"]
            assert verified[0].payload["branch"] == "writeback/adopt_1"
            assert verified[0].payload["verified_fact"]["verified"] is True
            assert remote.push_calls == 1
            assert len(remote.pull_requests) == 1
        finally:
            store.close()
            gc.collect()


def test_an_unknown_create_outcome_records_the_existing_request(tmp_path):
    # 合并请求已经在服务端创建、回应没有到达调用方：核实请求列表，记下已有的身份，不重复创建；
    # 再发起一次也不重复创建
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            remote.create_faults.append("drop_after_apply")
            event = projects.execute_writeback(pid, "adopt_1")

            assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED
            pull_request = event.payload["pull_request"]
            assert pull_request["identity"] == f"{OWNER}/{REPO}#1"
            assert pull_request["status"] == "existing"
            assert remote.create_calls == 1 and len(remote.pull_requests) == 1
            verified = [entry for entry in _events(store, pid)
                        if entry.type == ProjectEventType.WRITEBACK_VERIFIED]
            assert [entry.payload["action"] for entry in verified] == ["pull_request"]
            assert verified[0].payload["verified_fact"]["pull_request"]["identity"] == f"{OWNER}/{REPO}#1"

            again = projects.execute_writeback(pid, "adopt_1")
            assert again is not None and again.type == ProjectEventType.WRITEBACK_COMPLETED
            assert again.payload["pull_request"]["status"] == "existing"
            assert remote.create_calls == 1 and len(remote.pull_requests) == 1
        finally:
            store.close()
            gc.collect()


def test_a_create_confirmed_absent_after_an_unknown_outcome_is_retried_once(tmp_path):
    # 创建请求的结果未知，核实请求列表确认没有创建：按新尝试再创建一次，只留下一个请求
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            remote.create_faults.append("drop_without_apply")
            event = projects.execute_writeback(pid, "adopt_1")

            assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED
            assert event.payload["pull_request"]["status"] == "created"
            assert remote.create_calls == 2 and len(remote.pull_requests) == 1
        finally:
            store.close()
            gc.collect()


def test_an_unverifiable_create_outcome_stays_pending(tmp_path):
    # 创建请求的结果未知、核实请求列表也失败：动作保持待核实，不写完成事件；下一次尝试先核实再创建
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            # 第一次列表是创建之前的核实（成功），第二次列表是结果未知以后的核实（失败）
            remote.list_faults.extend(["", "fail"])
            remote.create_faults.append("drop_without_apply")
            with pytest.raises(WritebackOutcomeUnknown) as pending:
                projects.execute_writeback(pid, "adopt_1")
            assert pending.value.action == "pull_request"

            # 核实以前保持待核实：没有写成完成，也没有请求
            assert not any(entry.type == ProjectEventType.WRITEBACK_COMPLETED for entry in _events(store, pid))
            assert remote.pull_requests == []
            assert remote.branch_commit("writeback/adopt_1") is not None

            event = projects.execute_writeback(pid, "adopt_1")
            assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED
            assert event.payload["pull_request"]["identity"] == f"{OWNER}/{REPO}#1"
            assert len(remote.pull_requests) == 1
        finally:
            store.close()
            gc.collect()


@pytest.mark.parametrize("fault", ["conflict", "verification_failed"])
def test_a_stopped_writeback_never_touches_the_remote(tmp_path, fault):
    # 冲突与写回检查失败都在外部动作之前停止：没有推送分支，也没有创建合并请求
    files = {"app.py": b"print('base')\n"}
    if fault == "conflict":
        files = {"c.txt": b"target side\n"}
    with _GitHubRemote(tmp_path, files=files) as remote:
        base = {"c.txt": b"base side\n"} if fault == "conflict" else {"app.py": b"print('base')\n"}
        adopted = ({"c.txt": b"adopted side\n"} if fault == "conflict"
                   else {"app.py": b"print('adopted')\n"})
        checks = (_failing_check_command(),) if fault == "verification_failed" else (_PASS_COMMAND,)
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote, check_commands=checks)
        try:
            _adopt_one(writes, artifacts, pid, base=base, adopted=adopted, check_names=checks)
            event = projects.execute_writeback(pid, "adopt_1")

            assert event is not None and event.type == ProjectEventType.WRITEBACK_STOPPED
            assert event.payload["reason"] == fault
            assert remote.push_calls == 0
            assert remote.create_calls == 0 and remote.api_requests == 0
            assert remote.branch_commit("writeback/adopt_1") is None
            assert remote.pull_requests == []
        finally:
            store.close()
            gc.collect()


def test_a_branch_already_on_the_remote_with_other_content_is_not_overwritten(tmp_path):
    # 远端已有同名分支、内容不是这一次的结果：不覆盖、不推送、不创建请求，按拒绝边界说明
    with _GitHubRemote(tmp_path) as remote:
        repo = pygit2.Repository(str(remote.bare_path))
        signature = pygit2.Signature("Yudao Test", "test@yudao.invalid")
        head = repo.references["refs/heads/main"].peel(pygit2.Commit)
        builder = repo.TreeBuilder(head.tree)
        builder.insert("app.py", repo.create_blob(b"print('someone else')\n"), pygit2.enums.FileMode.BLOB)
        repo.create_commit("refs/heads/writeback/adopt_1", signature, signature, "别的写回",
                          builder.write(), [head.id])
        del repo
        gc.collect()
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            with pytest.raises(WritebackTargetUnavailable) as rejected:
                projects.execute_writeback(pid, "adopt_1")
            assert rejected.value.reason == "branch_exists"
            assert remote.push_calls == 0
            assert remote.pull_requests == []
            assert remote.branch_files("writeback/adopt_1") == {"app.py": b"print('someone else')\n"}
        finally:
            store.close()
            gc.collect()


def test_a_push_that_did_not_reach_the_remote_is_reported(tmp_path):
    # 推送没有到达远端、错误回应也说明不了结果：核实远端分支确认没有推送上去，按拒绝边界说明
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            remote.push_faults.append("fail_without_apply")
            with pytest.raises(WritebackTargetUnavailable) as rejected:
                projects.execute_writeback(pid, "adopt_1")
            assert rejected.value.reason == "push_failed"
            assert remote.push_calls == 1
            assert remote.pull_requests == [] and remote.create_calls == 0
            assert not any(entry.type == ProjectEventType.WRITEBACK_COMPLETED for entry in _events(store, pid))
        finally:
            store.close()
            gc.collect()


def test_the_remote_reading_failure_is_reported(tmp_path):
    # 远端读不到（服务不在）：按拒绝边界说明，不写完成事件
    with _GitHubRemote(tmp_path) as remote:
        url = remote.url
    store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
    try:
        projects.configure_source_directory(
            pid, "default", str(tmp_path / "src"), base_version=1, writeback_enabled=True,
            remote=url, target_branch="main", check_commands=[_PASS_COMMAND],
            credential_ref=CREDENTIAL_REF,
        )
        _adopt_one(writes, artifacts, pid)
        with pytest.raises(WritebackTargetUnavailable) as rejected:
            projects.execute_writeback(pid, "adopt_1")
        assert rejected.value.reason == "remote_unreachable"
        assert not any(entry.type == ProjectEventType.WRITEBACK_COMPLETED for entry in _events(store, pid))
    finally:
        store.close()
        gc.collect()


@pytest.mark.parametrize("fault, expected_status", [("server_error", "created"), ("already_exists", "existing")])
def test_a_server_error_and_an_already_existing_request_are_both_verified(tmp_path, fault, expected_status):
    # 5xx 与 GitHub 的 422「已有请求」都按结果未知处理：核实请求列表以后记下已有的身份，只留一个请求
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            remote.create_faults.append(fault)
            event = projects.execute_writeback(pid, "adopt_1")

            assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED
            assert event.payload["pull_request"]["status"] == expected_status
            assert event.payload["pull_request"]["identity"] == f"{OWNER}/{REPO}#1"
            assert len(remote.pull_requests) == 1
            # 5xx 的那一次没有创建，核实确认没有以后按新尝试再创建；422 的那一次已经在服务端创建了
            assert remote.create_calls == (2 if fault == "server_error" else 1)
        finally:
            store.close()
            gc.collect()


def test_a_rejected_request_is_reported_without_completing_the_writeback(tmp_path):
    # 合并请求接口明确拒绝（4xx）：按拒绝边界说明，写回不记为完成；分支已经推送上去，重试先核实再创建
    with _GitHubRemote(tmp_path) as remote:
        store, writes, artifacts, projects, pid = _setup(tmp_path, remote)
        try:
            _adopt_one(writes, artifacts, pid)
            remote.create_faults.append("reject")
            with pytest.raises(WritebackTargetUnavailable) as rejected:
                projects.execute_writeback(pid, "adopt_1")
            assert rejected.value.reason == "pull_request_rejected"
            assert "HTTP 404" in rejected.value.target
            assert TOKEN not in rejected.value.target
            assert remote.create_calls == 1 and remote.pull_requests == []
            assert not any(entry.type == ProjectEventType.WRITEBACK_COMPLETED for entry in _events(store, pid))
            # 重试：分支已经核实存在，创建请求成功
            event = projects.execute_writeback(pid, "adopt_1")
            assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED
            assert event.payload["pull_request"]["identity"] == f"{OWNER}/{REPO}#1"
            assert remote.push_calls == 1
        finally:
            store.close()
            gc.collect()


