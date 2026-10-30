# MCP 客户端模块（网络与 MCP 设计说明第 7.1 至 7.3 节；执行环境服务设计说明第 5 节的分层与职责）。
#
# 这一份不导入 Yudao 的其他模块：只用官方 MCP Python SDK、psutil、pydantic 与标准库，
# 由 pyproject.toml 的 import-linter 合同守住（工单 #69）。阶段四搬进执行代码包时只改导入路径。
#
# 一次会话的生命周期：start（stdio 启动子进程或连接 HTTP）→ list_tools / call_tool（可取消、有调用时限）
# → close（stdio 先关标准输入、等 2 秒，再结束整个进程树；HTTP 关闭会话）。
# 不声明 roots、sampling、elicitation：服务器发来这三类请求时由 SDK 回错误，本模块不注册回调。

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from contextlib import AsyncExitStack
from typing import Any, Literal
from urllib.parse import quote

import httpx2
import psutil
from pydantic import BaseModel, ConfigDict, Field

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp_types import REQUEST_TIMEOUT

# 标准错误输出读末尾这么多字符（设计说明第 7.2 节「读取末尾部分用于诊断」）
STDERR_TAIL_CHARS = 4000
# 超时或取消以后等服务器应答的最长时间。这个数取自设计说明第 8 节的两处：
# 「stdio：发取消通知，等服务器应答最多 10 秒，随后结束进程树」与「MCP 调用超时的处理顺序」。
# 不够用的情况：服务器在收到取消通知之前正要开始一次慢操作（冷启动一个 npx 包、一次大结果的序列化），
# 应答会晚于 10 秒——这时按设计说明的顺序直接结束进程树（stdio 已能确认停止），HTTP 一侧本来就无法确认
CANCEL_ACK_TIMEOUT_SEC = 10.0
# 子进程需要的系统变量：SDK 默认已给 APPDATA、LOCALAPPDATA、PATH、PATHEXT、SYSTEMROOT、TEMP、USERPROFILE 等，
# 少了 Windows 上命令行程序自己再起子进程时用的 COMSPEC 与 WINDIR（设计说明第 7.2 节，工单 #69）
EXTRA_ENVIRONMENT = ("COMSPEC", "WINDIR", "PATH", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP")
REDACTED = "***"


class StdioServer(BaseModel):
    # stdio 传输：命令与参数、已经取值的环境变量与工作目录；不经过 shell
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["stdio"] = "stdio"
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class HttpServer(BaseModel):
    # streamable HTTP 传输：地址与已经取值的请求头
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class ServerLaunch(BaseModel):
    # 启动或连接一个服务器：传输参数、已经取值的环境变量与请求头、启动时限、标准错误日志文件，
    # 以及调用方要求从错误文本与结果里隐去的值（凭据）
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    stdio: StdioServer | None = None
    http: HttpServer | None = None
    startup_timeout_sec: float = 60.0
    call_timeout_sec: float = 120.0
    stderr_log_path: str | None = None
    secrets: tuple[str, ...] = ()

    @property
    def transport(self) -> str:
        return "stdio" if self.stdio is not None else "http"


class ServerInfo(BaseModel):
    # 服务器信息与协议版本（initialize 的结果）
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str
    protocol_version: str


class ToolSpec(BaseModel):
    # 一个工具的清单项：名称、说明与参数结构；服务器自己的提示只作参考
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ContentBlock(BaseModel):
    # 工具结果的一块内容，各自的类型保留下来（设计说明第 7.3 节）：
    # 文本、图像（base64 与媒体类型）、嵌入资源（原文或二进制与地址）、音频（base64 与媒体类型）
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["text", "image", "resource", "audio"]
    text: str | None = None
    media_type: str | None = None
    data: str | None = None
    uri: str | None = None


class ToolCallResult(BaseModel):
    # 一次工具调用：内容块、structuredContent、是否工具错误、错误码，
    # 以及超时或取消时取消能否确认停止（stdio 结束时可以确认，HTTP 关闭会话时无法确认）
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: tuple[ContentBlock, ...] = ()
    structured_content: Any = None
    is_error: bool = False
    error_code: str | None = None
    cancelled: bool = False
    cancel_confirmed: bool | None = None
    stderr_tail: str = ""
    elapsed_ms: int = 0

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.content if block.text)


def redact(text: str, secrets: tuple[str, ...] | list[str]) -> str:
    """把需要隐去的值（及其 URL 编码形式）换成星号。"""
    for secret in secrets:
        if not secret:
            continue
        for form in {secret, quote(secret, safe="")}:
            text = text.replace(form, REDACTED)
    return text


def server_environment(values: dict[str, str]) -> dict[str, str]:
    """子进程的环境变量：只有传入的变量与操作系统运行所需的基础变量（设计说明第 7.2 节）。"""
    environment = get_default_environment()
    for key in EXTRA_ENVIRONMENT:
        value = os.environ.get(key)
        if value and key not in environment:
            environment[key] = value
    environment.update(values)
    return environment


def read_stderr_tail(path: str | None, *, secrets: tuple[str, ...] | list[str] = (),
                     limit: int = STDERR_TAIL_CHARS) -> str:
    """标准错误输出日志的末尾部分，凭据值替换为星号。"""
    if not path or not os.path.exists(path):
        return ""
    with open(path, "rb") as log:
        log.seek(0, os.SEEK_END)
        size = log.tell()
        log.seek(max(0, size - limit * 4))
        raw = log.read()
    return redact(raw.decode("utf-8", errors="replace")[-limit:], secrets)


def terminate_legacy_process(pid: int, create_time: float) -> bool:
    """按进程标识与进程创建时间结束遗留的服务器进程；两项都对得上才结束（设计说明第 7.2 节）。"""
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


class McpClient:
    """一个 MCP 服务器的一次会话：启动、列工具、调工具、取消与关闭。"""

    def __init__(self, launch: ServerLaunch) -> None:
        self.launch = launch
        self.info: ServerInfo | None = None
        self.pid: int | None = None
        self.process_create_time: float | None = None
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._stderr_log: Any = None
        self._call: asyncio.Task[Any] | None = None
        self._cancel_requested = False
        self._closed = False

    @classmethod
    async def start(cls, launch: ServerLaunch) -> "McpClient":
        client = cls(launch)
        try:
            await client._open()
        except BaseException as exc:
            await client.close()
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            raise McpStartupError(client.failure_reason(exc)) from exc
        return client

    async def _open(self) -> None:
        launch = self.launch
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        if launch.stdio is not None:
            if launch.stderr_log_path:
                os.makedirs(os.path.dirname(os.path.abspath(launch.stderr_log_path)), exist_ok=True)
                self._stderr_log = open(launch.stderr_log_path, "a", encoding="utf-8", buffering=1)
            server = StdioServerParameters(command=launch.stdio.command,
                                           args=list(launch.stdio.args),
                                           env=server_environment(launch.stdio.env),
                                           cwd=launch.stdio.cwd)
            read_stream, write_stream = await self._stack.enter_async_context(
                stdio_client(
                    server, errlog=self._stderr_log if self._stderr_log is not None else sys.stderr))
        else:
            assert launch.http is not None
            http_client = httpx2.AsyncClient(headers=launch.http.headers or None, timeout=None)
            await self._stack.enter_async_context(http_client)
            # SDK 的 HTTP 传输交出两条或三条流（版本不同）：只取前两条使用
            streams = await self._stack.enter_async_context(
                streamable_http_client(launch.http.url, http_client=http_client, terminate_on_close=True))
            read_stream, write_stream = streams[0], streams[1]
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream, read_timeout_seconds=launch.call_timeout_sec))
        # 启动时限包住握手（同任务内取消，不换任务）
        async with asyncio.timeout(launch.startup_timeout_sec):
            result = await self._session.initialize()
        self.info = ServerInfo(name=result.server_info.name, version=result.server_info.version,
                               protocol_version=result.protocol_version)
        if launch.stdio is not None:
            self._remember_process()

    def _remember_process(self) -> None:
        # 子进程标识与创建时间：SDK 不交出进程句柄，按当前进程的子进程与命令核对
        if self.launch.stdio is None:
            return
        command = os.path.basename(self.launch.stdio.command).lower()
        started = time.time()
        for child in psutil.Process().children():
            try:
                cmdline = " ".join(child.cmdline()).lower()
                if command in cmdline and started - child.create_time() < self.launch.startup_timeout_sec:
                    self.pid, self.process_create_time = child.pid, child.create_time()
                    return
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    async def list_tools(self) -> list[ToolSpec]:
        session = self._require_session()
        try:
            result = await session.list_tools()
        except MCPError as exc:
            raise McpCallError(self.failure_reason(exc), code=_error_code(exc)) from exc
        return [ToolSpec(name=tool.name, description=tool.description or "",
                         input_schema=dict(tool.input_schema or {})) for tool in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        session = self._require_session()
        started = time.monotonic()
        self._cancel_requested = False
        self._call = asyncio.ensure_future(
            session.call_tool(name, arguments or {}, read_timeout_seconds=self.launch.call_timeout_sec))
        try:
            result = await self._call
        except asyncio.CancelledError:
            result = None
        except MCPError as exc:
            if _error_code(exc) == str(REQUEST_TIMEOUT):
                result = None
            else:
                raise McpCallError(self.failure_reason(exc), code=_error_code(exc),
                                   stderr_tail=self.stderr_tail()) from exc
        finally:
            call, self._call = self._call, None
        if result is None:
            return await self._cancelled_result(started, call)
        if not isinstance(result, types.CallToolResult):
            raise McpCallError("the server answered the tool call with a non-result", code="invalid_result")
        elapsed = int((time.monotonic() - started) * 1000)
        return ToolCallResult(content=tuple(_content_blocks(result.content)),
                              structured_content=_redact_value(result.structured_content, self.launch.secrets),
                              is_error=bool(result.is_error), elapsed_ms=elapsed,
                              error_code="tool_error" if result.is_error else None)

    async def _cancelled_result(self, started: float, call: asyncio.Future | None) -> ToolCallResult:
        # 超时或取消：SDK 已经发出取消通知，这里等服务器应答最多 10 秒。stdio 随后结束进程树
        # （进程已结束，可以确认停止）；HTTP 关闭会话（无法确认服务器停止）
        if call is not None:
            await asyncio.wait([call], timeout=CANCEL_ACK_TIMEOUT_SEC)
        confirmed = self.launch.stdio is not None
        tail = self.stderr_tail()
        elapsed = int((time.monotonic() - started) * 1000)
        result = ToolCallResult(cancelled=True, cancel_confirmed=confirmed, error_code="cancelled",
                                stderr_tail=tail, elapsed_ms=elapsed,
                                content=(ContentBlock(kind="text", text=self._message(confirmed)),))
        await self.close()
        return result

    async def cancel(self) -> bool:
        """取消正在进行的调用；没有正在进行的调用时返回 False。"""
        if self._call is None or self._call.done():
            return False
        self._cancel_requested = True
        self._call.cancel()
        return True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # 先记下服务器起的整棵进程树：SDK 关掉服务器以后这些进程就找不到父进程了，
        # 而设计说明第 7.2 节要求关闭时整个进程树都结束
        tree = self._process_tree()
        # stdio：SDK 关闭时先关标准输入、等 2 秒，再结束它起的子进程；HTTP：终止会话
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._session = None
        for process in tree:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        # Windows 上结束进程是异步的：等到整棵树真的结束，关闭以后调用方看到的状态才是最终的
        if tree:
            psutil.wait_procs(tree, timeout=5)
        if self._stderr_log is not None:
            self._stderr_log.close()
            self._stderr_log = None

    def _process_tree(self) -> list[psutil.Process]:
        if self.pid is None:
            return []
        try:
            return psutil.Process(self.pid).children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    def stderr_tail(self) -> str:
        return read_stderr_tail(self.launch.stderr_log_path, secrets=self.launch.secrets)

    def failure_reason(self, error: BaseException) -> str:
        """启动或调用失败的原因，带标准错误输出的末尾部分；凭据值替换为星号。"""
        detail = redact(str(error) or error.__class__.__name__, self.launch.secrets)
        tail = self.stderr_tail()
        return f"{detail}\n{tail}".strip() if tail else detail

    def _message(self, confirmable: bool) -> str:
        return f"工具调用被取消（{'能' if confirmable else '不能'}确认服务器已停止）"

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise McpCallError("the MCP session is not open", code="session_closed")
        return self._session


class McpStartupError(RuntimeError):
    """服务器启动或连接失败：原因带标准错误输出的末尾部分。"""


class McpCallError(RuntimeError):
    """一次调用失败：协议错误、错误码与标准错误输出的末尾部分。"""

    def __init__(self, message: str, *, code: str = "protocol_error", stderr_tail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.stderr_tail = stderr_tail


def _error_code(error: MCPError) -> str:
    # 错误码是 JSON-RPC 的整数码或字符串；超时用 SDK 的 REQUEST_TIMEOUT 判断
    code = getattr(error, "code", None)
    return str(code) if code is not None else "protocol_error"


def _content_blocks(content: list[Any]) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    for item in content:
        kind = getattr(item, "type", None)
        if kind == "text":
            blocks.append(ContentBlock(kind="text", text=item.text))
        elif kind == "image":
            blocks.append(ContentBlock(kind="image", media_type=item.mime_type, data=item.data))
        elif kind == "audio":
            blocks.append(ContentBlock(kind="audio", media_type=item.mime_type, data=item.data))
        elif kind == "resource":
            resource = item.resource
            uri = str(getattr(resource, "uri", ""))
            if isinstance(getattr(resource, "blob", None), str):
                blocks.append(ContentBlock(kind="resource", data=base64.b64encode(resource.blob.encode()).decode(),
                                           media_type=getattr(resource, "mime_type", None), uri=uri))
            else:
                blocks.append(ContentBlock(kind="resource", text=getattr(resource, "text", ""),
                                           media_type=getattr(resource, "mime_type", None), uri=uri))
        else:
            blocks.append(ContentBlock(kind="resource", text=json.dumps(_plain(item), ensure_ascii=False)))
    return blocks


def _plain(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    return model_dump(mode="json") if callable(model_dump) else str(value)


def _redact_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {key: _redact_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    return value
