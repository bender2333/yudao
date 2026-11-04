# 浏览器工具的执行（浏览器与 computer use 设计说明第 4 章「浏览器工具（Playwright MCP）」、第 7 章
# 「截图作为证据」与第 9 章「恢复契约」；总图第四节「动作」缝的 browser 类别）。
#
# 每个网页种类的试用会话一个 Playwright MCP 进程（stdio，`--browser chromium --headless --isolated
# --viewport-size 1280x800 --caps testing --image-responses allow --snapshot-mode full --output-dir <会话目录>`）。
# 一次浏览器动作是：地址与路径的拒绝（导航目标用取回那一套服务地址规则，本地文件限试用副本内）→ 调用 MCP →
# 只读标注为否的工具再截一张图并把它存成工件 → 结果带页面的可访问性结构。工具失败（is_error）交回错误文本，
# 动作记为完成；MCP 进程退出、调用超时或取消时会话记为中断，动作按失败交回（第 9 节）。
#
# 执行层的代码：只导入标准库、同一层的工作树与客户端模块、定义与工件存储，不导入控制核心与应用层。

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .artifacts import ArtifactStore
from .definitions import DEFINITIONS
from .fetch import FetchFailed, FetchRefused, _refuse_service_address
from .mcp_client import (McpCallError, McpClient, McpStartupError, ServerLaunch, StdioServer,
                         terminate_legacy_process)
from .models import ArtifactRef, new_id

# 试用需要的程序（设计说明第 3.2 节）：Playwright MCP 0.0.83 与它依赖的 Playwright 装出来的 Chromium。
# 内核之外的这一层只负责找到并启动，版本由试用会话的程序核对负责报出
MCP_PACKAGE = "@playwright/mcp"
MCP_VERSION = "0.0.83"
NODE = "node"
# 问 npm 全局根目录（`npm root -g`）的时限（秒）：一次探测，结果缓存在 _CLI_CACHE 里
NPM_QUERY_TIMEOUT_SEC = 30

# 浏览器工具的名称（定义里动作类别是 browser 的那一组，工单 #147 从 Playwright MCP 的 tools/list 生成）：
# 恢复按它判断一个结果未知的动作是不是浏览器动作
BROWSER_TOOL_NAMES = frozenset(name for name, tool in DEFINITIONS.tools.items() if tool.action == "browser")

# 启动参数（设计说明第 4.1 节的表）：--browser chromium 在 0.0.83 里落到 Playwright 自带的 Chromium
# （chrome-for-testing 渠道），--caps testing 多出四个 browser_verify_* 断言工具。没有取值的开关写成 None
BROWSER_ARGUMENTS: tuple[tuple[str, str | None], ...] = (
    ("--browser", "chromium"),
    ("--headless", None),
    ("--isolated", None),
    ("--viewport-size", "1280x800"),
    ("--caps", "testing"),
    ("--image-responses", "allow"),
    ("--snapshot-mode", "full"),
)
# 会话目录里的输出子目录：工具以文件名保存的内容留在这里，会话结束时删除（设计说明第 4.1 节）
OUTPUT_DIR_NAME = "mcp-output"

# 截图与结构的两个工具
SCREENSHOT_TOOL = "browser_take_screenshot"
SNAPSHOT_TOOL = "browser_snapshot"
# 关闭浏览器的工具：它执行以后没有页面可以截图，会话本身还在（下一次导航会重新启动浏览器）
CLOSE_TOOL = "browser_close"
# 可以带本地文件路径的两个工具（设计说明第 4.2 节）：路径按试用副本解析，副本之外的拒绝
FILE_PATH_TOOLS = frozenset({"browser_file_upload", "browser_drop"})
# 导航类工具：目标地址在执行之前按服务自己的地址规则检查（第 4.1 节「来源限制」）
NAVIGATION_TOOLS = frozenset({"browser_navigate"})
# 一次调用最多等这么久（规则登记 browser.call_timeout_sec）：Playwright MCP 自己的动作时限 5 秒、
# 导航时限 60 秒，这里是它们之外的上限
CALL_TIMEOUT_SEC = int(DEFINITIONS.rule_value("browser.call_timeout_sec"))
# 启动最多等这么久：node 冷启动、Chromium 第一次启动都在这一段里
STARTUP_TIMEOUT_SEC = 120.0
# 页面结构的摘录上限（字符）：与工具输出的上限同一做法
STRUCTURE_LIMIT = int(DEFINITIONS.rule_value("tool_output_limit"))
# MCP 结果里指向会话目录的页面结构文件（`- [Snapshot](<path>)`）
_SNAPSHOT_LINK = re.compile(r"\[Snapshot\]\(([^)]+)\)")
# 轮询取消信号的间隔（秒）
_CANCEL_POLL_SEC = 0.1


class BrowserRefused(Exception):
    """这次浏览器动作被拒绝：导航目标指向服务自己，或本地文件路径在试用副本之外。"""


class BrowserSessionFailed(Exception):
    """浏览器会话没有建立、已经中断，或执行这次动作时 Playwright MCP 退出。"""

    def __init__(self, message: str, *, output: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.output = dict(output or {})


@dataclass
class BrowserSession:
    # 一个浏览器会话：身份、部门、试用副本与它的树摘要、MCP 的输出目录、客户端与状态。
    # 关闭与截图可以在别的线程上发生（动作取消、会话结束），状态只在锁里改
    session_id: str
    run_id: str | None
    department: str
    copy_root: Path
    tree_digest: str
    output_dir: Path
    started_at: str
    client: McpClient
    status: str = "running"
    ended_reason: str | None = None
    last_url: str | None = None
    screenshots: int = 0
    _lock: Lock = field(default_factory=Lock)

    def record(self) -> dict[str, Any]:
        # 会话记录：身份、部门、状态、试用副本的树摘要与输出目录。回执与核实记录都用这一份
        with self._lock:
            info = self.client.info
            return {
                "session_id": self.session_id,
                "department": self.department,
                "status": self.status,
                "tree_digest": self.tree_digest,
                "copy": str(self.copy_root),
                "output_dir": str(self.output_dir),
                "started_at": self.started_at,
                "ended_reason": self.ended_reason,
                "last_url": self.last_url,
                "screenshots": self.screenshots,
                "server": {"name": None if info is None else info.name,
                           "version": None if info is None else info.version},
                "server_pid": self.client.pid,
            }

    def minimal_record(self) -> dict[str, Any]:
        # 回执里的会话身份与树摘要（设计说明第 7.1 节）：每一步都带，不重复整份记录
        with self._lock:
            return {"session_id": self.session_id, "status": self.status,
                    "tree_digest": self.tree_digest}

    def mark_interrupted(self, reason: str) -> None:
        with self._lock:
            if self.status == "running":
                self.status = "interrupted"
                self.ended_reason = reason

    def mark_ended(self, reason: str) -> None:
        with self._lock:
            self.status = "ended"
            self.ended_reason = reason


@dataclass(frozen=True)
class BrowserProgram:
    # 启动 Playwright MCP 需要的两样：可执行文件与它的入口
    node: str
    cli: str


_CLI_CACHE: BrowserProgram | None = None


def _package_version(cli: Path) -> str | None:
    try:
        data = json.loads((cli.parent / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else None


def _cli_candidates() -> list[Path]:
    # 全局安装（CI 与用户按设计说明的装法）与 npx 缓存（只运行过一次、没有全局安装的机器）
    node, npm = shutil.which(NODE), shutil.which("npm")
    candidates = [root / MCP_PACKAGE / "cli.js" for root in _node_module_roots(node, npm, _npm_global_root(npm))]
    cache_roots = [Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "npm" / "_npx"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cache_roots.append(Path(local) / "npm-cache" / "_npx")
    for root in cache_roots:
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/node_modules/@playwright/mcp/cli.js")))
    return candidates


def _npm_global_root(npm: str | None) -> Path | None:
    """全局安装的根目录，由 npm 自己给出（`npm root -g`）。

    不能只按目录猜：GitHub Actions 的 Windows 宿主把全局前缀放在 `C:\\npm\\prefix`，不在 `%APPDATA%\\npm`，
    按目录猜会漏掉 CI 上按设计说明 `npm install --global` 装的那一份（工单 #1184 的分支集成层就是这么红的）。
    """
    if npm is None:
        return None
    try:
        finished = subprocess.run([npm, "root", "-g"], capture_output=True, text=True,
                                  timeout=NPM_QUERY_TIMEOUT_SEC)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = finished.stdout.strip().splitlines() if finished.returncode == 0 else []
    return Path(lines[-1]) if lines else None


def _node_module_roots(node: str | None, npm: str | None, npm_root: Path | None) -> list[Path]:
    """全局装的那份 `node_modules` 可能在哪，按可信程度排：npm 报出的全局根目录、node 与 npm 所在的目录
    （Windows 的宿主把全局前缀与 node 放在一起）、各系统的默认前缀。"""
    roots: list[Path] = []
    if npm_root is not None:
        roots.append(npm_root)
    for executable in (node, npm):
        if executable is not None:
            roots.append(Path(executable).parent / "node_modules")
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "npm" / "node_modules")
    else:
        for prefix in ("/usr/local/lib", "/usr/lib", str(Path.home() / ".local" / "lib")):
            roots.append(Path(prefix) / "node_modules")
    return list(dict.fromkeys(roots))


def find_program() -> BrowserProgram:
    """找到 Playwright MCP 0.0.83 的入口，与启动它的 node。找不到时抛 BrowserSessionFailed。"""
    global _CLI_CACHE
    if _CLI_CACHE is not None:
        return _CLI_CACHE
    node = shutil.which(NODE)
    if node is None:
        raise BrowserSessionFailed("Node.js was not found on PATH; the browser tools need Node.js 24")
    npm = shutil.which("npm")
    roots = _node_module_roots(node, npm, _npm_global_root(npm))
    seen: list[str] = []
    for candidate in _cli_candidates():
        if not candidate.is_file():
            continue
        version = _package_version(candidate)
        seen.append(f"{candidate} ({version or 'unknown version'})")
        if version == MCP_VERSION:
            _CLI_CACHE = BrowserProgram(node=node, cli=str(candidate))
            return _CLI_CACHE
    found = ", ".join(seen) or "nothing"
    looked = ", ".join(str(root) for root in roots) or "no global root"
    raise BrowserSessionFailed(
        f"Playwright MCP {MCP_VERSION} was not found; looked for a global install ({looked}) and in the npx "
        f"cache and found: {found}")


def launch_arguments(output_dir: str | Path) -> tuple[str, ...]:
    # 启动参数（设计说明第 4.1 节）：输出目录放这次会话的文件，其余按表
    arguments: list[str] = []
    for name, value in BROWSER_ARGUMENTS:
        arguments.append(name)
        if value is not None:
            arguments.append(value)
    arguments.extend(("--output-dir", str(output_dir)))
    return tuple(arguments)


def is_read_only(tool: str) -> bool:
    """这个浏览器工具的只读标注（设计说明第 4.2 节）：定义里按 Playwright 的标注生成，
    只读标注为是的工具核实方法为 none（工单 #147）。"""
    definition = DEFINITIONS.tools.get(tool)
    if definition is None or definition.action != "browser":
        raise BrowserSessionFailed(f"{tool} is not a browser tool")
    return definition.verification == "none"


def check_navigation(url: Any) -> str:
    """导航目标的来源限制（设计说明第 4.1、10 节）：与取回同一个函数检查服务自己的地址与端口。

    MCP 的 --blocked-origins 只按字面来源匹配，挡不住指向本机的域名别名，所以动作层再查一次实际地址。
    指向服务自己的地址与端口时抛 BrowserRefused，其余地址（含回环与内网）照常访问。
    """
    if not isinstance(url, str) or not url.strip():
        raise BrowserRefused("browser_navigate requires a url")
    value = url.strip()
    if not value.lower().startswith(("http://", "https://")):
        raise BrowserRefused(f"the browser navigates to http and https addresses only: {value}")
    try:
        _refuse_service_address(value)
    except FetchRefused as refusal:
        raise BrowserRefused(str(refusal)) from refusal
    except FetchFailed as failure:
        raise BrowserRefused(f"the browser cannot check the target address {value}: {failure}") from failure
    return value


def resolve_paths(session: BrowserSession, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """browser_file_upload 与 browser_drop 的路径（设计说明第 4.2 节）：相对路径按试用副本解析，
    副本之外的拒绝。交回替换成执行位置上的绝对路径的参数。"""
    if tool not in FILE_PATH_TOOLS:
        return dict(args)
    raw = args.get("paths")
    if raw is None:
        return dict(args)
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item for item in raw):
        raise BrowserRefused(f"{tool} takes a list of file paths")
    root = session.copy_root.resolve()
    resolved: list[str] = []
    for item in raw:
        candidate = Path(item)
        target = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if target != root and root not in target.parents:
            raise BrowserRefused(
                f"{tool} takes paths inside the trial copy only; {item} is outside {root}")
        resolved.append(str(target))
    return {**args, "paths": resolved}


def _remove_tree(root: Path) -> None:
    # 会话结束时删掉 MCP 的输出目录：Windows 上句柄可能还没放开，重试几次，删不掉时留下目录不报错
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


def _clip(text: str, limit: int = STRUCTURE_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


async def _cancel_when_stopped(client: McpClient, stop: Any) -> None:
    # 取消信号到达：交给客户端的 cancel（它取消 SDK 的调用任务、发出取消通知）。会话随后的关闭
    # 发生在调用所在的任务里，这里不取消那个任务
    while not stop.is_set():
        await asyncio.sleep(_CANCEL_POLL_SEC)
    await client.cancel()


class BrowserSessions:
    """一个进程里全部 run 的浏览器会话：每个 run 的每个部门同一时刻最多一个。

    会话由试用会话建立（网页种类的 `trial_start`/`trial_open`）时交给这里启动，`trial_stop` 关闭；
    动作按（run、部门）找到会话，找不到时按失败交回。截图存进这个 run 的工件库（种类 screenshot）。
    """

    def __init__(self, artifacts: ArtifactStore | None = None, *,
                 program: BrowserProgram | None = None) -> None:
        self._sessions: dict[tuple[str | None, str], BrowserSession] = {}
        self._lock = Lock()
        self._artifacts = artifacts
        self._program = program

    # ---- 会话 ----
    def session_of(self, run_id: str | None, department: str) -> BrowserSession | None:
        with self._lock:
            return self._sessions.get((run_id, department))

    def record(self, run_id: str | None, department: str) -> dict[str, Any] | None:
        # 这个部门当前会话的记录；没有会话时为空（恢复时据此把会话记为中断）
        session = self.session_of(run_id, department)
        return None if session is None else session.record()

    async def start(self, *, run_id: str | None, department: str, copy_root: str | Path,
                    tree_digest: str, ready_url: str, output_dir: str | Path | None = None) -> dict[str, Any]:
        # 结束本部门原来的会话，再按启动参数起 Playwright MCP，打开就绪地址并截一张图（设计说明第 3.4 节）
        await self.stop(run_id, department, reason="replaced by a new browser session")
        if self._artifacts is None or run_id is None:
            raise BrowserSessionFailed(
                "a browser session requires an environment with an artifact store")
        root = Path(copy_root)
        directory = Path(output_dir) if output_dir is not None else root.parent / OUTPUT_DIR_NAME / new_id("mcp")
        directory.mkdir(parents=True, exist_ok=True)
        program = self._program or find_program()
        launch = ServerLaunch(
            name="playwright",
            stdio=StdioServer(command=program.node,
                              args=(program.cli, *launch_arguments(directory)),
                              cwd=str(root)),
            startup_timeout_sec=STARTUP_TIMEOUT_SEC,
            call_timeout_sec=CALL_TIMEOUT_SEC,
            stderr_log_path=str(directory / "mcp-stderr.log"),
        )
        try:
            client = await McpClient.start(launch)
        except McpStartupError as failure:
            _remove_tree(directory)
            raise BrowserSessionFailed(f"the Playwright MCP server did not start: {failure}",
                                       output={"session": None}) from failure
        session = BrowserSession(
            session_id=new_id("browser"), run_id=run_id, department=department, copy_root=root,
            tree_digest=tree_digest, output_dir=directory,
            started_at=datetime.now(timezone.utc).isoformat(), client=client,
        )
        try:
            page = await self._open(session, check_navigation(ready_url))
        except BaseException:
            await self._discard(session, "the browser session could not open the ready url")
            raise
        with self._lock:
            self._sessions[(run_id, department)] = session
        return page

    async def _open(self, session: BrowserSession, url: str) -> dict[str, Any]:
        # 打开就绪地址：导航的结果已经带页面的可访问性结构，再截一张图作为会话开始的证据
        result = await self._call_mcp(session, "browser_navigate", {"url": url})
        session.last_url = url
        text = await self._with_structure(session, result["text"])
        image = await self._screenshot(session)
        return {"session": session.record(), "accessibility": text, "images": [] if image is None else [image]}

    async def call(self, *, run_id: str | None, department: str, tool: str, args: dict[str, Any],
                   structure_limit: int = STRUCTURE_LIMIT, stop: Any = None) -> dict[str, Any]:
        """执行一次浏览器动作，交回回执的输出：可访问性结构、截图引用与会话身份。"""
        session = self.session_of(run_id, department)
        if session is None:
            raise BrowserSessionFailed(
                "there is no browser session for this department; start a trial session first")
        if session.status != "running":
            raise BrowserSessionFailed(
                f"the browser session is {session.status}; start a new trial session",
                output={"session": session.record()})
        is_read_only(tool)
        prepared = resolve_paths(session, tool, args)
        if tool in NAVIGATION_TOOLS:
            prepared = {**prepared, "url": check_navigation(prepared.get("url"))}
        result = await self._call_mcp(session, tool, prepared, stop=stop)
        text = result["text"]
        images: list[dict[str, Any]] = []
        if tool == SCREENSHOT_TOOL:
            # 模型自己调的截图（设计说明第 4.3 节）：返回的图像同样保存为证据
            image = await self._save_image(session, result.get("image"))
            if image is not None:
                images.append(image)
        elif not is_read_only(tool) and tool != CLOSE_TOOL:
            # 只读标注为否的工具：同一个动作里再截一张图，每一步都有截图作为证据
            image = await self._screenshot(session, stop=stop)
            if image is not None:
                images.append(image)
            text = await self._with_structure(session, text, stop=stop)
        if tool in NAVIGATION_TOOLS:
            session.last_url = prepared["url"]
        clipped, truncated = _clip(text, structure_limit)
        output: dict[str, Any] = {"accessibility": clipped, "images": images,
                                  "session": session.minimal_record()}
        if truncated:
            output["structure_truncated"] = True
        if result["is_error"]:
            output["tool_error"] = True
        return output

    async def verify(self, run_id: str | None, department: str) -> dict[str, Any] | None:
        """结果未知的浏览器动作的核实依据（设计说明第 9 节）：会话仍然存在时取当前页面结构与截图。"""
        session = self.session_of(run_id, department)
        if session is None or session.status != "running":
            return None
        snapshot = await self._call_mcp(session, SNAPSHOT_TOOL, {})
        image = await self._screenshot(session)
        text, truncated = _clip(snapshot["text"])
        return {"accessibility": text, "session": session.record(), "screenshot": image,
                "structure_truncated": truncated}

    async def stop(self, run_id: str | None, department: str, *, reason: str = "stopped") -> dict[str, Any]:
        # 关闭 MCP 与浏览器（客户端关闭时结束整棵进程树），删掉会话目录
        with self._lock:
            session = self._sessions.pop((run_id, department), None)
        if session is None:
            return {"session": None, "ended": False, "reason": reason}
        session.mark_ended(reason)
        record = session.record()
        await self._discard(session, reason)
        return {"session": record, "ended": True, "reason": reason}

    async def close_all(self, reason: str = "stopped") -> None:
        # 持有会话的进程结束前关掉全部会话：run 结束与进程退出都走这里
        with self._lock:
            sessions = list(self._sessions.items())
            self._sessions.clear()
        for (_run_id, _department), session in sessions:
            session.mark_ended(reason)
            await self._discard(session, reason)

    # ---- 内部 ----
    async def _discard(self, session: BrowserSession, reason: str) -> None:
        session.mark_interrupted(reason)
        client = session.client
        pid, created = client.pid, client.process_create_time
        try:
            await client.close()
        except Exception:  # noqa: BLE001 - 换一个任务关闭时 SDK 的取消范围不允许，进程树自己结束
            # 与 `McpSessions.close` 的处理相同（网络与 MCP 设计说明第 7.2 节）：关闭失败不挡住会话结束。
            # 客户端建立时记下的进程标识与创建时间在这里结束整棵进程树；它打开的标准错误输出日志文件
            # 也没有关（关闭在 SDK 的退出之后），这里一并关掉，否则会话目录删不掉
            if pid is not None and created is not None:
                terminate_legacy_process(int(pid), float(created))
            log = getattr(client, "_stderr_log", None)
            if log is not None:
                try:
                    log.close()
                except OSError:
                    pass
        finally:
            _remove_tree(session.output_dir)

    async def _call_mcp(self, session: BrowserSession, tool: str, args: dict[str, Any],
                        stop: Any = None) -> dict[str, Any]:
        # 一次 MCP 调用：进程退出、协议错误与取消都让会话不能再使用，按中断交回（设计说明第 9 节）。
        # 取消信号到达时交给客户端的 cancel（它取消 SDK 的调用任务、发取消通知），本任务等取消结果
        watcher = None if stop is None else asyncio.ensure_future(_cancel_when_stopped(session.client, stop))
        try:
            result = await session.client.call_tool(tool, args)
        except McpCallError as failure:
            session.mark_interrupted(f"the Playwright MCP server failed during {tool}")
            raise BrowserSessionFailed(
                f"the Playwright MCP server failed during {tool}: {failure}",
                output={"session": session.record()}) from failure
        except Exception as failure:  # 传输层断开：进程已经退出
            session.mark_interrupted(f"the Playwright MCP server ended during {tool}")
            raise BrowserSessionFailed(
                f"the Playwright MCP server ended during {tool}: {failure}",
                output={"session": session.record()}) from failure
        finally:
            if watcher is not None and not watcher.done():
                watcher.cancel()
        if result.cancelled:
            session.mark_interrupted(f"{tool} was cancelled or timed out")
            raise BrowserSessionFailed(
                f"{tool} was cancelled or timed out; the browser session is interrupted",
                output={"session": session.record()})
        image = next((block for block in result.content if block.kind == "image"), None)
        return {"text": result.text, "is_error": bool(result.is_error), "image": image}

    async def _with_structure(self, session: BrowserSession, text: str, stop: Any = None) -> str:
        # 结果里的可访问性结构：MCP 把它存成会话目录里的文件时读出来接在结果后面（设计说明第 4.3 节）；
        # 结果里没有结构时（例如输入文字不改变页面结构的那一步）再取一次页面结构
        match = _SNAPSHOT_LINK.search(text)
        if match is not None:
            path = Path(match.group(1).strip())
            if not path.is_absolute():
                path = session.copy_root / path
            try:
                structure = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                structure = ""
            if structure.strip():
                clipped, truncated = _clip(structure)
                note = "\n（结构已截断）" if truncated else ""
                return f"{text}\n\n### Accessibility structure{note}\n{clipped}"
        snapshot = await self._call_mcp(session, SNAPSHOT_TOOL, {}, stop=stop)
        clipped, truncated = _clip(snapshot["text"])
        note = "\n（结构已截断）" if truncated else ""
        return f"{text}\n\n### Accessibility structure{note}\n{clipped}"

    async def _screenshot(self, session: BrowserSession, stop: Any = None) -> dict[str, Any] | None:
        # 同一个动作里的截图（视口，PNG）：MCP 把图像作为内容返回，这里存成这个 run 的工件
        result = await self._call_mcp(session, SCREENSHOT_TOOL, {"scale": "css"}, stop=stop)
        return await self._save_image(session, result.get("image"))

    async def _save_image(self, session: BrowserSession, block: Any) -> dict[str, Any] | None:
        # 把 MCP 返回的图像块存成工件（种类 screenshot）：回执带工件引用，摘要就是内容摘要
        if block is None or getattr(block, "data", None) is None:
            return None
        if self._artifacts is None or session.run_id is None:
            raise BrowserSessionFailed("a screenshot requires an environment with an artifact store")
        try:
            raw = base64.b64decode(block.data)
        except (ValueError, TypeError) as failure:
            raise BrowserSessionFailed(f"the screenshot was not base64 png: {failure}") from failure
        ref: ArtifactRef = self._artifacts.put(session.run_id, "screenshot", raw,
                                               media_type=block.media_type or "image/png")
        with session._lock:
            session.screenshots += 1
        return {"kind": ref.kind, "content_hash": ref.content_hash, "path": ref.path,
                "media_type": ref.media_type}
