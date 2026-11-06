# 试用会话（本机版的执行位置）：核对试用需要的程序、建立试用副本、分配端口、按系统选用启动命令、
# 启动交付的软件并等到就绪，以及读输出与结束会话（浏览器与 computer use 设计说明「试用会话」
# 「试用工具」与「恢复契约」；总图第四节「动作」缝的 trial 类别）。
#
# 会话记录（身份、部门、种类、启动方式、端口、试用副本、各进程的进程号与启动时间）与动作记录保存在一起：
# 本模块交回的记录随 tool_called 的载荷写入事件。会话的开始与结束各写一条应用事件
# （`trial_session_started`、`trial_session_ended`，设计说明「事件、决定请求与查询」）；run 进入终态时由 run 的收尾
# 结束全部会话，持有会话的进程重新启动时由启动扫描按会话记录里的进程号与创建时间结束遗留的进程树
# （工单 #1183）。
#
# 执行层的代码：只导入标准库与本层的工作树、进程树与凭据遮蔽，不导入控制核心与应用层。
# 事件的写入方由装配一方（薄驱动）交进来（`bind_events`），与 MCP 会话的生命周期事件同一个做法。

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

import psutil

from .definitions import DEFINITIONS
from .models import EventType, new_id
from .process_tree import STOP_LIMIT_SEC, ProcessTree, spawn_options
from .public_tree import CapturedTree, capture_public_tree, materialize_tree
from .redact import redact_text

# 试用副本与输出放在这个 run 的工作区旁边，与检查工作区同一种摆法（docs/design/browser-and-computer-use.md「试用的位置」）
TRIALS_DIR = "trials"
OUTPUT_DIR = "outputs"

# 本机进程是控制主机：系统按 Python 的 sys.platform 取值。其他系统没有启动命令的约定
_PLATFORM_SYSTEMS = {"win32": "windows", "linux": "linux"}

# 就绪时限的默认值与界限取自规则登记
READINESS_TIMEOUT_SEC = int(DEFINITIONS.rule_value("execution.readiness_timeout_sec"))

# 试用需要的程序与版本（docs/design/browser-and-computer-use.md「执行位置上的程序」）
NODE_MAJOR_MIN = 24
PLAYWRIGHT_MCP_VERSION = "0.0.83"

# 就绪的轮询间隔（秒）：每次轮询先看进程是否还在，再对就绪地址发一次请求
READY_POLL_SEC = 0.2
# 就绪地址的一次请求最多等这么久（秒）
READY_REQUEST_TIMEOUT_SEC = 2.0
# 程序探测的命令最多等这么久（秒）：npm 在 Windows 上第一次运行较慢
PROBE_TIMEOUT_SEC = 90

# 一条工具结果带回来的输出上限（字符）：取自规则登记里的 tool_output_limit，与执行环境按同一条规则
# 截断（读输出、结束会话与失败回执带回来的启动输出都走这个上限）
DEFAULT_OUTPUT_LIMIT = int(DEFINITIONS.rule_value("tool_output_limit"))

# 会话的结束方式（docs/design/browser-and-computer-use.md「事件、决定请求与查询」 `trial_session_ended` 的取值）：停止、被新会话替换、中断（持有会话的
# 进程重新启动）、用户停止（停止使用桌面，本机版的桌面会话还没有接上，取值先留着）、run 结束
END_STOPPED = "stopped"
END_REPLACED = "replaced"
END_INTERRUPTED = "interrupted"
END_USER_STOPPED = "user_stopped"
END_RUN_ENDED = "run_ended"

# 会话事件写到 run 流的接口：装配一方（薄驱动）给出，参数是 run 身份、事件种类与载荷
EventSink = Callable[[str, str, dict[str, Any]], None]


class TrialStartFailed(Exception):
    """试用会话没有建立：原因与截至失败时的启动输出一起交回动作回执。"""

    def __init__(self, message: str, *, output: dict[str, Any] | None = None,
                 cancelled: bool = False) -> None:
        super().__init__(message)
        self.output = dict(output or {})
        self.cancelled = cancelled


@dataclass
class TrialSession:
    # 一个试用会话：身份、部门、种类与启动方式、端口与就绪地址、试用副本、树摘要、进程与输出。
    # 进程的结束与输出的读取可以在另一条线程上发生（读输出、停止、动作取消），状态只在锁里改
    session_id: str
    run_id: str | None
    department: str
    kind: str
    launch_name: str
    launch: dict[str, Any]
    system: str
    port: int
    ready_url: str
    copy_root: Path
    tree_digest: str
    source: str
    output_path: Path
    process: subprocess.Popen[Any] | None
    tree: ProcessTree | None
    file_handle: Any
    started_at: str
    # 直接子进程的创建时间（psutil，秒）：与进程号一起记进会话记录。持有会话的进程重新启动时按这两项
    # 核对并结束遗留的进程树——进程号可能已经被别的进程复用（工单 #1183）
    process_create_time: float | None = None
    status: str = "running"
    ended_reason: str | None = None
    exit_code: int | None = None
    _lock: Lock = field(default_factory=Lock)

    def record(self) -> dict[str, Any]:
        # 会话记录：身份、部门、种类、端口、试用副本、各进程的进程号与启动时间（docs/design/browser-and-computer-use.md「试用工具」）
        with self._lock:
            return {
                "session_id": self.session_id,
                "department": self.department,
                "kind": self.kind,
                "launch_name": self.launch_name,
                "system": self.system,
                "port": self.port,
                "ready_url": self.ready_url,
                "tree_digest": self.tree_digest,
                "copy_source": self.source,
                "copy": str(self.copy_root),
                "process_id": None if self.process is None else self.process.pid,
                "process_create_time": self.process_create_time,
                "started_at": self.started_at,
                "status": self.status,
                "ended_reason": self.ended_reason,
                "exit_code": self.exit_code,
            }

    def mark_ended(self, reason: str) -> None:
        # 会话没有建立时的记录：只改状态，进程与副本由调用方结束
        with self._lock:
            if self.exit_code is None and self.process is not None:
                self.exit_code = self.process.poll()
            self.status = "ended"
            self.ended_reason = reason

    def end(self, reason: str) -> bool:
        # 结束交付软件的整棵进程树。可以重复调用：状态已经是结束时不再动已经放掉的资源。
        # 返回这一次是否结束了仍然在的进程树（启动扫描据此写 `ended`：进程已经不在了也是正常结束）
        with self._lock:
            if self.status == "ended":
                return False
            was_running = self.tree is not None
            if self.process is not None and self.exit_code is None:
                ret = self.process.poll()
                if ret is not None:
                    self.exit_code = ret
            if self.tree is not None:
                self.tree.stop()
                self.tree.wait_stopped(STOP_LIMIT_SEC)
                if self.process is not None and self.process.poll() is None:
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                self.tree.close()
                self.tree = None
            if self.file_handle is not None:
                try:
                    self.file_handle.close()
                finally:
                    self.file_handle = None
            self.status = "ended"
            self.ended_reason = reason
            return was_running


_PORT_LOCK = Lock()
_ALLOCATED_PORTS: set[int] = set()


def _free_port() -> int:
    # 取得一个空闲的 TCP 端口：bind(("127.0.0.1", 0)) 以后记下端口并关掉套接字，
    # 端口留在进程内的已分配集合里直到会话结束
    with _PORT_LOCK:
        for _ in range(64):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            if port not in _ALLOCATED_PORTS:
                _ALLOCATED_PORTS.add(port)
                return port
    raise TrialStartFailed("no free TCP port could be taken on 127.0.0.1")


def _release_port(port: int) -> None:
    with _PORT_LOCK:
        _ALLOCATED_PORTS.discard(port)


def current_system() -> str | None:
    # 执行位置的系统：本机是控制主机，取 Python 的 sys.platform。其他系统返回 None
    return _PLATFORM_SYSTEMS.get(sys.platform)


# 建立试用会话的两个工具：工程用 trial_start（给出启动方式），质检用 trial_open（给出交付说明中的名称）
TRIAL_TOOLS = frozenset({"trial_start", "trial_open"})


def resolve_trial_call(name: str, args: dict[str, Any], delivery_spec: Any,
                       system: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """工具许可对 trial_start 与 trial_open 的核对：交回启动方式或拒绝原因。

    质检的 trial_open 按当前交付说明（`delivery_spec.launch`）里的名称解析；工程与执行环境按启动方式
    列表解析时用 `resolve_trial_launch`（交付说明没有时按空清单处理）。
    """
    methods = [item for item in (getattr(delivery_spec, "launch", None) or [])
               if isinstance(item, dict)]
    return resolve_trial_launch(name, args, methods, system=system)


def resolve_trial_launch(name: str, args: dict[str, Any], methods: list[dict[str, Any]],
                         system: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """交回这次调用要用的启动方式，或者拒绝的原因（工具许可与执行之前是同一套核对）。

    工程的 trial_start 用这次调用给出的启动方式；质检的 trial_open 只接受当前交付说明里的名称，
    名称不存在时原因写明交付说明中已有的名称，没有启动方式时写明交付说明没有写启动方式。
    两者都按执行位置的系统选用命令：没有这个系统的命令时拒绝，原因写明缺少哪个系统的命令。
    桌面试用会话在本机版还没有接上（屏幕工具属于 computer use 专题），先拒绝并写明原因。
    """
    if name == "trial_start":
        launch = args.get("launch")
        if not isinstance(launch, dict):
            return None, "trial_start requires a launch method object"
    elif name == "trial_open":
        if not methods:
            return None, "the DeliverySpec has no launch method"
        wanted = args.get("launch_name")
        matches = [item for item in methods if item.get("name") == wanted]
        if not matches:
            names = ", ".join(str(item.get("name")) for item in methods)
            return None, (f"the DeliverySpec has no launch method named {wanted!r}; "
                          f"it carries: {names}")
        launch = matches[0]
    else:
        return None, f"{name} does not start a trial session"
    problem = _launch_shape_problem(launch)
    if problem is not None:
        return None, problem
    system = system or current_system()
    commands = launch.get("commands") or {}
    if system is None:
        return None, (f"this execution location runs {sys.platform}; "
                      f"launch commands are defined for windows and linux only")
    if system not in commands:
        covered = ", ".join(sorted(commands)) or "nothing"
        return None, f"the launch method has no command for {system}; commands cover: {covered}"
    if launch.get("kind") == "desktop":
        return None, "desktop trial sessions are not available in this build"
    return dict(launch), None


def _launch_shape_problem(launch: dict[str, Any]) -> str | None:
    # 启动方式的形状（docs/design/browser-and-computer-use.md「启动方式」）：交付说明由提案校验，trial_start 的启动方式由这里核对
    kind = launch.get("kind")
    if kind not in {"web", "desktop"}:
        return "kind must be web or desktop"
    name = launch.get("name")
    if not isinstance(name, str) or not name.strip():
        return "name must be a non-empty string"
    commands = launch.get("commands")
    if not isinstance(commands, dict) or not commands:
        return "commands must map at least one system to an argv list"
    for system, argv in commands.items():
        if system not in {"windows", "linux"}:
            return f"commands keys must be windows or linux, not {system!r}"
        if not isinstance(argv, list) or not argv or any(
                not isinstance(part, str) or not part for part in argv):
            return f"commands.{system} must be a non-empty list of non-empty strings"
    if kind == "web":
        ready_url = launch.get("ready_url")
        if not isinstance(ready_url, str) or "{port}" not in ready_url:
            return "a web app requires a ready_url containing {port}"
    return None


def trial_root(run_root: str | Path) -> Path:
    # 这个 run 的试用目录：放在运行工作区旁边，与检查工作区同一种摆法
    path = Path(run_root)
    return path.parent / TRIALS_DIR / path.name


def trial_session_root(run_root: str | Path, session_id: str) -> Path:
    return trial_root(run_root) / session_id


def _run_probe(argv: list[str], timeout: float = PROBE_TIMEOUT_SEC) -> tuple[int, str]:
    # 程序探测的一条命令：输出与错误一起取回，找不到程序、超时都按失败交回
    try:
        finished = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                  env={**os.environ, "npm_config_yes": "false"})
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return finished.returncode, "\n".join(part for part in (finished.stdout, finished.stderr) if part)


def _node_status() -> dict[str, str] | None:
    # Node.js 24 LTS（docs/design/browser-and-computer-use.md「执行位置上的程序」）：找不到或版本不是 24 时算缺少
    executable = shutil.which("node")
    if executable is None:
        return {"program": "Node.js 24", "detail": "node was not found on PATH"}
    code, output = _run_probe([executable, "--version"])
    text = output.strip().splitlines()[-1] if output.strip() else ""
    match = re.match(r"v(\d+)\.", text)
    if code != 0 or match is None:
        return {"program": "Node.js 24", "detail": f"node --version failed: {text or 'no output'}"}
    if int(match.group(1)) != NODE_MAJOR_MIN:
        return {"program": "Node.js 24", "detail": f"found {text}"}
    return None


def _installed_mcp_version(output: str) -> str | None:
    try:
        data = json.loads(output)
    except ValueError:
        return None
    dependencies = data.get("dependencies") if isinstance(data, dict) else None
    item = dependencies.get("@playwright/mcp") if isinstance(dependencies, dict) else None
    if not isinstance(item, dict):
        return None
    version = item.get("version")
    return version if isinstance(version, str) else None


def _playwright_mcp_status() -> dict[str, str] | None:
    # Playwright MCP 0.0.83：先看全局安装（CI 与用户按设计说明的装法），再看 npx 的缓存
    # （只运行过一次、没有全局安装的机器）。都没有时算缺少
    npm = shutil.which("npm")
    if npm is not None:
        code, output = _run_probe([npm, "ls", "-g", "--depth=0", "--json", "@playwright/mcp"])
        if code == 0:
            version = _installed_mcp_version(output)
            if version == PLAYWRIGHT_MCP_VERSION:
                return None
            if version is not None:
                return {"program": f"Playwright MCP {PLAYWRIGHT_MCP_VERSION}",
                        "detail": f"found {version}"}
    npx = shutil.which("npx")
    if npx is not None:
        code, output = _run_probe([npx, "--no-install", f"@playwright/mcp@{PLAYWRIGHT_MCP_VERSION}",
                                   "--version"])
        if code == 0 and PLAYWRIGHT_MCP_VERSION in output:
            return None
    return {"program": f"Playwright MCP {PLAYWRIGHT_MCP_VERSION}",
            "detail": "neither a global install nor the npx cache carries this version"}


def _playwright_browsers_dir() -> Path:
    # Playwright 安装的 Chromium 默认在这个目录下（Windows：%LOCALAPPDATA%\ms-playwright）
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base / "ms-playwright"


def _chromium_status() -> dict[str, str] | None:
    # Chromium 由 Playwright 自带命令安装（docs/design/browser-and-computer-use.md「执行位置上的程序」）：有 chromium 或无界面的
    # chromium_headless_shell 都算装好。修订号是否与 Playwright 版本对得上，由真正启动浏览器时核对
    root = _playwright_browsers_dir()
    installed: list[str] = []
    if root.is_dir():
        installed = sorted(item.name for item in root.iterdir()
                           if item.is_dir() and (item.name.startswith("chromium-")
                                                 or item.name.startswith("chromium_headless_shell-")))
    if not installed:
        return {"program": "Chromium (Playwright)", "detail": f"no Chromium under {root}"}
    return None


def missing_programs() -> list[dict[str, str]]:
    # 试用需要的程序（docs/design/browser-and-computer-use.md「执行位置上的程序」）：Node.js 24、Playwright MCP 0.0.83、Chromium。
    # 缺一个就交回一项，回执按它写明缺少的程序，会话不建立
    missing = [item for item in (_node_status(), _playwright_mcp_status(), _chromium_status()) if item]
    return [dict(item) for item in missing]


def normalize_launch(raw: Any) -> dict[str, Any]:
    # 一个启动方式的形状（docs/design/browser-and-computer-use.md「启动方式」）。交付说明由提案校验核对过；这里再核一次，
    # 因为 trial_start 的启动方式是模型在这次调用里给出的
    if not isinstance(raw, dict):
        raise ValueError("a launch method must be an object")
    kind = raw.get("kind")
    if kind not in {"web", "desktop"}:
        raise ValueError("kind must be web or desktop")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    commands = raw.get("commands")
    if not isinstance(commands, dict) or not commands:
        raise ValueError("commands must map at least one system to an argv list")
    normalized_commands: dict[str, list[str]] = {}
    for system, argv in commands.items():
        if system not in {"windows", "linux"}:
            raise ValueError(f"commands keys must be windows or linux, not {system!r}")
        if not isinstance(argv, list) or not argv or any(not isinstance(part, str) or not part for part in argv):
            raise ValueError(f"commands.{system} must be a non-empty list of non-empty strings")
        normalized_commands[str(system)] = list(argv)
    ready_url = raw.get("ready_url")
    if kind == "web":
        if not isinstance(ready_url, str) or "{port}" not in ready_url:
            raise ValueError("a web app requires a ready_url containing {port}")
    elif ready_url is not None:
        raise ValueError("a desktop program has no ready_url")
    timeout = raw.get("ready_timeout_sec")
    if timeout is None:
        timeout = READINESS_TIMEOUT_SEC
    low, high = DEFINITIONS.rule("execution.readiness_timeout_sec").bounds
    if type(timeout) is not int or not low <= timeout <= high:
        raise ValueError(f"ready_timeout_sec must be an integer between {int(low)} and {int(high)}")
    return {"name": name.strip(), "kind": kind, "commands": normalized_commands,
            "ready_url": ready_url, "ready_timeout_sec": timeout}


def select_command(launch: dict[str, Any], system: str | None) -> list[str]:
    # 按执行位置的系统选用命令（docs/design/browser-and-computer-use.md「启动方式」）：没有这个系统的命令时按缺少启动方式处理
    commands = launch.get("commands") or {}
    if system is None:
        raise ValueError("this execution location has no system from which to choose a launch command")
    if system not in commands:
        raise ValueError(f"the launch method has no command for {system}; "
                         f"commands cover: {', '.join(sorted(commands)) or 'nothing'}")
    return list(commands[system])


def _process_create_time(pid: int) -> float | None:
    # 进程的创建时间（psutil）：与进程号一起记进会话记录。读不到时为空，遗留进程的结束因此找不到它，
    # 不按只剩进程号去杀进程（进程号可能已经被别的进程复用）
    try:
        return float(psutil.Process(pid).create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _http_ready(url: str) -> bool:
    # 就绪条件：对替换端口以后的地址的请求得到任何 HTTP 响应
    try:
        with urllib.request.urlopen(url, timeout=READY_REQUEST_TIMEOUT_SEC) as response:
            response.read(64)
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _read_output(path: Path, limit: int = DEFAULT_OUTPUT_LIMIT) -> str:
    # 失败回执带截至结束时的启动输出：按工具输出上限取末尾，避免刷屏的程序把回执撑大
    return _tail(path, limit)[0]


def _tail(path: Path, limit: int) -> tuple[str, bool]:
    # 取输出的末尾部分：limit 是字节数，按它截取以后再解码
    if not path.exists():
        return "", False
    data = path.read_bytes()
    if len(data) <= limit:
        return redact_text(data.decode("utf-8", errors="replace")), False
    return redact_text(data[-limit:].decode("utf-8", errors="replace")), True


def _head(path: Path, limit: int) -> tuple[str, bool]:
    if not path.exists():
        return "", False
    data = path.read_bytes()
    if len(data) <= limit:
        return redact_text(data.decode("utf-8", errors="replace")), False
    return redact_text(data[:limit].decode("utf-8", errors="replace")), True


def _remove_tree(root: Path) -> None:
    # Windows 上进程句柄可能还没放开：按固定次数与递增退避重试，仍删不掉时留下目录不报错，
    # 由会话结束的记录与后续的清理接住
    if not root.exists():
        return
    for attempt in range(3):
        try:
            shutil.rmtree(root)
            return
        except OSError:
            if attempt == 2:
                return
            time.sleep(0.1 * (attempt + 1))


class TrialSessionTable:
    """一个进程里全部 run 的试用会话：每个 run 的每个部门同一时刻最多一个。

    会话记录与动作记录一起保存（docs/design/browser-and-computer-use.md「试用工具」）：`start` 交回会话记录与启动输出的开头，
    `read_output` 与 `stop` 交回同一个记录与输出。程序探测可以注入，测试用它模拟缺少某个程序。
    会话开始与结束时经装配一方交来的写入方（`bind_events`）写一条应用事件；run 进入终态时由
    `stop_run` 结束这个 run 的全部会话，结束事件排在 `flush` 里写（工单 #1183）。
    """

    def __init__(self, probe: Callable[[], list[dict[str, str]]] | None = None,
                 *, events: EventSink | None = None) -> None:
        self._sessions: dict[tuple[str | None, str], TrialSession] = {}
        self._lock = Lock()
        self._probe = probe or missing_programs
        # 写会话事件的写入方（装配一方给出）；没有给时只维护会话表，不写事件（单一模块的用例）
        self._events = events
        # run 结束时会话已经结束、结束事件还没有写的记录（工单 #1183）：run 进入终态的事件正在提交时
        # 不能再写一条事件（事件的位置会乱序），由调用方在安全的时候 flush
        self._pending: list[tuple[str, str, dict[str, Any]]] = []

    def bind_events(self, events: EventSink | None) -> None:
        # 交入写入方：会话开始与结束时经它写一条应用事件（装配的一方在构造它以后接上）
        self._events = events

    def _record(self, run_id: str | None, event_type: str, payload: dict[str, Any], *,
                defer: bool = False) -> None:
        # 一条会话事件：没有 run 身份（直接构造执行环境的用例）时不写；defer 时排队等 flush
        if run_id is None:
            return
        if defer:
            with self._lock:
                self._pending.append((run_id, event_type, payload))
            return
        if self._events is not None:
            self._events(run_id, event_type, payload)

    def flush(self, run_id: str | None = None) -> int:
        """写排队的会话结束事件（run 的终态事件已经提交以后调用）；交回写了几条。

        还没有接上写入方时队列留着，不等（装配之前不会有会话）。
        """
        if self._events is None:
            return 0
        with self._lock:
            if run_id is None:
                queued, self._pending = self._pending, []
            else:
                queued = [item for item in self._pending if item[0] == run_id]
                self._pending = [item for item in self._pending if item[0] != run_id]
        for item_run, event_type, payload in queued:
            self._events(item_run, event_type, payload)
        return len(queued)

    async def start(self, *, run_id: str | None, department: str, launch: dict[str, Any],
                    source_tree: CapturedTree, run_root: Path, source: str,
                    output_limit: int = DEFAULT_OUTPUT_LIMIT, stop: Any = None) -> dict[str, Any]:
        # 结束本部门原来的会话（docs/design/browser-and-computer-use.md「试用工具」），再建立新的会话
        self.stop(run_id, department, reason=END_REPLACED)
        missing = self._probe()
        if missing:
            names = ", ".join(item["program"] for item in missing)
            raise TrialStartFailed(f"trial programs are missing: {names}",
                                   output={"missing_programs": missing, "session": None})
        try:
            launch = normalize_launch(launch)
            system = current_system()
            argv = select_command(launch, system)
        except ValueError as exc:
            raise TrialStartFailed(str(exc), output={"session": None}) from exc
        if launch["kind"] != "web":
            raise TrialStartFailed("desktop trial sessions are not available in this build",
                                   output={"session": None})
        return await self._start_web(run_id=run_id, department=department, launch=launch, argv=argv,
                                     system=str(system), source_tree=source_tree, run_root=Path(run_root),
                                     source=source, output_limit=output_limit, stop=stop)

    async def _start_web(self, *, run_id: str | None, department: str, launch: dict[str, Any],
                         argv: list[str], system: str, source_tree: CapturedTree, run_root: Path,
                         source: str, output_limit: int, stop: Any) -> dict[str, Any]:
        session_id = new_id("trial")
        copy_root = trial_session_root(run_root, session_id)
        copy_root.parent.mkdir(parents=True, exist_ok=True)
        materialize_tree(source_tree, copy_root)
        try:
            digest = capture_public_tree(copy_root).digest
        except Exception as exc:
            _remove_tree(copy_root)
            raise TrialStartFailed(f"the trial copy could not be read back: {exc}",
                                   output={"session": None}) from exc
        if digest != source_tree.digest:
            _remove_tree(copy_root)
            raise TrialStartFailed("the trial copy does not match the source tree", output={"session": None})
        port = _free_port()
        ready_url = str(launch["ready_url"]).replace("{port}", str(port))
        output_path = trial_root(run_root) / OUTPUT_DIR / f"{session_id}.output"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        file_handle = open(output_path, "wb")
        process: subprocess.Popen[Any] | None = None
        tree: ProcessTree | None = None
        session: TrialSession | None = None
        try:
            process = subprocess.Popen(
                argv, cwd=str(copy_root), env={**os.environ, "PORT": str(port)},
                stdin=subprocess.DEVNULL, stdout=file_handle, stderr=subprocess.STDOUT,
                **spawn_options(),
            )
            tree = ProcessTree()
            try:
                tree.attach(process.pid)
            except BaseException:
                tree.stop()
                tree.close()
                raise
            session = TrialSession(
                session_id=session_id, run_id=run_id, department=department, kind=str(launch["kind"]),
                launch_name=str(launch["name"]), launch=launch, system=system, port=port,
                ready_url=ready_url, copy_root=copy_root, tree_digest=digest, source=source,
                output_path=output_path, process=process, tree=tree, file_handle=file_handle,
                started_at=datetime.now(timezone.utc).isoformat(),
                process_create_time=_process_create_time(process.pid),
            )
            await self._wait_ready(session, int(launch["ready_timeout_sec"]), stop, output_limit)
        except TrialStartFailed as exc:
            if session is not None:
                session.mark_ended(str(exc))
                exc.output["session"] = session.record()
            self._discard(process, tree, file_handle, copy_root, port)
            raise
        except BaseException:
            self._discard(process, tree, file_handle, copy_root, port)
            raise
        with self._lock:
            self._sessions[(run_id, department)] = session
        # 会话建立以后写一条开始事件（docs/design/browser-and-computer-use.md「事件、决定请求与查询」）：身份、部门、种类、启动方式、选用命令的系统、
        # 端口与就绪地址、试用副本的树摘要与清单来源，以及进程号与创建时间（启动扫描按这两项结束遗留进程）
        self._record(run_id, EventType.TRIAL_SESSION_STARTED, _started_payload(session))
        head, truncated = _head(output_path, output_limit)
        return {"session": session.record(), "output": head, "truncated": truncated}

    async def _wait_ready(self, session: TrialSession, timeout_sec: int, stop: Any,
                          output_limit: int) -> None:
        # 失败回执带回来的启动输出按工具结果的上限截断（与规则登记 tool_output_limit）
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_sec
        while True:
            if stop is not None and stop.is_set():
                raise TrialStartFailed("the trial session was cancelled before it was ready",
                                       output={"session": None}, cancelled=True)
            if session.process is not None:
                code = session.process.poll()
                if code is not None:
                    session.exit_code = code
                    raise TrialStartFailed(
                        f"the launch command exited with code {code} before the trial session was ready",
                        output={"session": session.record(),
                                "output": _read_output(session.output_path, output_limit)})
            if await asyncio.to_thread(_http_ready, session.ready_url):
                return
            if loop.time() >= deadline:
                raise TrialStartFailed(
                    f"the trial session did not become ready within {timeout_sec}s at {session.ready_url}",
                    output={"session": session.record(),
                            "output": _read_output(session.output_path, output_limit)})
            await asyncio.sleep(READY_POLL_SEC)

    def _discard(self, process: subprocess.Popen[Any] | None, tree: ProcessTree | None,
                 file_handle: Any, copy_root: Path, port: int) -> None:
        # 没有建立的会话：结束进程树、关掉输出、删掉副本、放掉端口，不留半成品
        if tree is not None:
            tree.stop()
            tree.wait_stopped(STOP_LIMIT_SEC)
            tree.close()
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        if file_handle is not None:
            try:
                file_handle.close()
            finally:
                file_handle = None
        _remove_tree(copy_root)
        _release_port(port)

    # ---- 读输出与结束 ----
    def session_of(self, run_id: str | None, department: str) -> TrialSession | None:
        with self._lock:
            return self._sessions.get((run_id, department))

    def read_output(self, run_id: str | None, department: str, limit: int) -> dict[str, Any]:
        # 交付软件到目前为止的标准输出与标准错误的末尾部分
        session = self.session_of(run_id, department)
        if session is None:
            return {"session_id": None, "output": "", "truncated": False, "status": "ended"}
        output, truncated = _tail(session.output_path, limit)
        return {"session_id": session.session_id, "output": output, "truncated": truncated,
                "status": session.status}

    def stop(self, run_id: str | None, department: str, *, reason: str = END_STOPPED,
             limit: int = DEFAULT_OUTPUT_LIMIT) -> dict[str, Any]:
        # 结束会话：结束交付软件的进程树、删掉试用副本、放掉端口；交回结束方式与输出的末尾部分。
        # 这一条在工具执行里调用（trial_stop，或开始新会话时结束原来的会话），没有事务正在进行，
        # 结束事件在这里直接写
        with self._lock:
            session = self._sessions.pop((run_id, department), None)
        if session is None:
            return {"session": None, "ended": False, "reason": reason, "output": "", "truncated": False}
        ended = session.end(reason)
        output, truncated = _tail(session.output_path, limit)
        _remove_tree(session.copy_root)
        _release_port(session.port)
        self._record(run_id, EventType.TRIAL_SESSION_ENDED,
                     _ended_payload(session, reason, ended=ended))
        return {"session": session.record(), "ended": True, "reason": reason,
                "output": output, "truncated": truncated}

    def stop_run(self, run_id: str | None, *, reason: str = END_RUN_ENDED) -> list[dict[str, Any]]:
        """结束这个 run 的全部会话（run 进入终态时由 run 的收尾调用，工单 #1183）。

        结束交付软件的进程树、删掉试用副本、放掉端口，交回结束时的会话记录。结束事件在这里排队，
        由调用方在安全的时候用 `flush` 写：这条路径在 run 的终态事件提交之后的效果里运行，
        那时再写一条事件会让订阅方先看到后面那条，终态事件被当成旧位置丢掉。
        """
        with self._lock:
            keys = [key for key in self._sessions if key[0] == run_id]
            sessions = [self._sessions.pop(key) for key in keys]
        records: list[dict[str, Any]] = []
        for session in sessions:
            ended = session.end(reason)
            _remove_tree(session.copy_root)
            _release_port(session.port)
            records.append(session.record())
            self._record(run_id, EventType.TRIAL_SESSION_ENDED,
                         _ended_payload(session, reason, ended=ended), defer=True)
        return records


# ---------------------------------------------------------------------------
# 会话事件的载荷（docs/design/browser-and-computer-use.md「事件、决定请求与查询」 `trial_session_started`、`trial_session_ended`）


def _started_payload(session: TrialSession) -> dict[str, Any]:
    # 开始时的事实：身份、部门、种类、启动方式的名称、选用命令的系统、端口与就绪地址、试用副本的树摘要
    # 与清单来源，以及进程号与创建时间（启动扫描按后两项结束遗留进程）。
    # 完整的启动方式不在这里重复记一份：它是模型给出的工具参数，已经按 ADR-0038 脱敏记在工具事件里
    record = session.record()
    return {
        "session_id": record["session_id"],
        "department": record["department"],
        "kind": record["kind"],
        "launch_name": record["launch_name"],
        "system": record["system"],
        "port": record["port"],
        "ready_url": record["ready_url"],
        "tree_digest": record["tree_digest"],
        "source": record["copy_source"],
        "pid": record["process_id"],
        "create_time": record["process_create_time"],
    }


def _ended_payload(session: TrialSession, reason: str, *, ended: bool) -> dict[str, Any]:
    # 结束时的事实：与开始事件按（run、会话身份）配对；reason 是结束方式，ended 说明这一次是否真的
    # 结束了仍然存活的进程（进程已经不在了也是 False）
    record = session.record()
    return {
        "session_id": record["session_id"],
        "department": record["department"],
        "kind": record["kind"],
        "reason": reason,
        "pid": record["process_id"],
        "create_time": record["process_create_time"],
        "ended": bool(ended),
        "exit_code": record["exit_code"],
    }


# ---------------------------------------------------------------------------
# 遗留的会话（工单 #1183）：Yudao 启动时结束没有结束记录的会话留下的进程树，
# 补写 trial_session_ended。进程号与创建时间都取自会话记录（开始事件的载荷）


@dataclass(frozen=True)
class LeftoverSession:
    # 一条没有结束记录的开始：哪个 run 的哪个会话，部门的种类，以及它记录的进程号与创建时间
    run_id: str
    session_id: str
    department: str
    kind: str
    pid: int | None
    create_time: float | None


# 按（run、会话身份）配对的两类事件：开始与结束。结束记录一到就配成一对
_LEFTOVER_TYPES = (EventType.TRIAL_SESSION_STARTED, EventType.TRIAL_SESSION_ENDED)
# 一次读多少条：按种类过滤、按位置翻页，不把全部事件读进内存
_LEFTOVER_PAGE = 1000


def leftover_sessions(store, *, limit: int = _LEFTOVER_PAGE) -> list[LeftoverSession]:
    """有开始记录、没有结束记录的会话（按（run、会话身份）配对，先开始先配对）。

    Yudao 启动时用这份清单结束遗留的进程树并补写结束事件：
    进程崩溃时结束事件没有写下来，交付软件的进程树可能还活着。
    """
    open_starts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    after = 0
    while True:
        batch = store.read(after, types=_LEFTOVER_TYPES, limit=limit)
        if not batch:
            break
        for event in batch:
            after = max(after, int(event.position))
            payload = event.payload or {}
            key = (str(event.run_id or ""), str(payload.get("session_id") or ""))
            if event.type == EventType.TRIAL_SESSION_STARTED:
                open_starts.setdefault(key, []).append(payload)
                continue
            pending = open_starts.get(key)
            if pending:
                pending.pop(0)
    return [LeftoverSession(run_id=run_id, session_id=session_id,
                            department=str(payload.get("department") or ""),
                            kind=str(payload.get("kind") or "web"),
                            pid=payload.get("pid"), create_time=payload.get("create_time"))
            for (run_id, session_id), pending in open_starts.items() for payload in pending]


def end_leftover_session(leftover: LeftoverSession) -> bool:
    """按进程号与创建时间结束遗留的进程树；两项都对得上才结束（进程号可能已经被别的进程复用）。

    交回这一次是否真的结束了仍然存活的进程。
    """
    if leftover.pid is None or leftover.create_time is None:
        return False
    return terminate_process_tree(int(leftover.pid), float(leftover.create_time))


def terminate_process_tree(pid: int, create_time: float) -> bool:
    # 结束一棵进程树（先子进程、后它自己），等它们真的停下；进程不在、没有权限或对不上时交回 False
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - create_time) > 1.0:
            return False
        tree = process.children(recursive=True)
        for child in tree:
            child.kill()
        process.kill()
        psutil.wait_procs([*tree, process], timeout=5)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
        return False
    return True


def remove_trial_copy(run_root: str | Path, session_id: str) -> None:
    # 删掉一个会话的试用副本（启动扫描结束遗留会话时用：结束事件没有写下来的会话，副本也还在）
    _remove_tree(trial_session_root(run_root, session_id))
