# MCP 服务器探测（工单 #1174，网络与 MCP 设计说明第 4.2 节）：把项目设置里的一台服务器
# （#236 校验与保存的非秘密设置文档）变成 #69 客户端的启动参数，在控制主机上临时启动或连接它，
# 读到服务器信息与工具清单以后关闭。探测绑定所提交的非秘密配置及其内容摘要（normalize_mcp_servers
# 归一化时算出的 config_digest），凭据引用按名称在探测开始时解析，凭据值参加脱敏、不参加摘要。
#
# 这里的两个函数都同步完成（探测任务在服务的事件循环里跑，McpClient 的会话自己开事件循环）；
# 失败的原因字符串已经过客户端的凭据替换（mcp_client.failure_reason）。

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from .mcp_client import HttpServer, McpClient, McpStartupError, ServerLaunch, StdioServer, ToolSpec, redact
from .providers.credentials import CredentialChain, CredentialMaterial
from .providers.facade import ProviderFacade

# 服务器标注的提示（SDK 的 ToolAnnotations）进入快照的字段；title 是单独一项
_HINT_FIELDS = ("read_only_hint", "idempotent_hint", "destructive_hint", "open_world_hint")


async def probe(server: dict[str, Any], *, credentials: CredentialChain,
                stderr_log_path: str) -> ProbeOutcome:
    # 启动（或连接）→ 列工具 → 关闭；启动或连接失败交回原因，工具清单成功以后一定关闭会话。
    # 工具清单读取失败同样按失败交回：会话还在时由 close 收尾。
    # 命令处理在服务的事件循环里等待它；同步入口（probe_sync）只给循环之外的调用方用
    try:
        launch = launch_for(server, credentials=credentials, stderr_log_path=stderr_log_path)
    except McpStartupError as failure:
        # 缺凭据等组装阶段的失败：原因已经写明凭据名称，直接按探测失败交回
        return ProbeOutcome(None, [], str(failure))

    async def scenario() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        client = await McpClient.start(launch)
        try:
            assert client.info is not None
            info = {"name": client.info.name, "version": client.info.version,
                    "protocol_version": client.info.protocol_version}
            return info, [_tool_document(tool) for tool in await client.list_tools()]
        finally:
            await client.close()

    try:
        info, tools = await scenario()
    except McpStartupError as failure:
        return ProbeOutcome(None, [], _kept(launch, str(failure)))
    except Exception as failure:  # 工具清单读取或会话关闭失败：原因同样交给事件
        return ProbeOutcome(None, [], _kept(launch, str(failure) or failure.__class__.__name__))
    return ProbeOutcome(info, tools, _kept(launch, ""))


def _kept(launch: ServerLaunch, error: str) -> str:
    # 探测结束以后把标准错误输出日志里的凭据值替换为星号（设计说明第 4.4 节「保存的标准错误输出」）：
    # 日志文件留在数据目录里供诊断，凭据值不出现在保存的内容里
    path = launch.stderr_log_path
    if path and os.path.exists(path) and launch.secrets:
        with open(path, "rb") as log:
            raw = log.read()
        text = redact(raw.decode("utf-8", errors="replace"), launch.secrets)
        with open(path, "w", encoding="utf-8") as log:
            log.write(text)
    return error


def probe_sync(server: dict[str, Any], *, credentials: CredentialChain, stderr_log_path: str) -> ProbeOutcome:
    # 同步入口：调用方不在事件循环里时（脚本、命令行）用它跑一次探测
    return asyncio.run(probe(server, credentials=credentials, stderr_log_path=stderr_log_path))


@dataclass(frozen=True)
class ProbeOutcome:
    # 一次探测的结果：成功带服务器信息与工具清单，失败带原因（已脱敏）
    server_info: dict[str, Any] | None
    tools: list[dict[str, Any]]
    error: str


def _resolve_variable(entry: dict[str, Any], credentials: CredentialChain, server_name: str, where: str) -> str:
    # 一个环境变量或请求头的取值（设计说明第 4.4 节）：固定文本原样，凭据按名称解析；
    # 缺失时启动失败，原因写明凭据名称
    kind = entry.get("kind")
    if kind == "text":
        return str(entry.get("value") or "")
    ref = str(entry.get("credential_ref") or "")
    material: CredentialMaterial | None = credentials.resolve(ref)
    if material is None or not material.secret.strip():
        raise McpStartupError(f"{server_name} 的凭据 {ref or where} 无法解析：凭据来源中没有 {ref} 的值")
    return material.secret


def _tool_document(tool: ToolSpec) -> dict[str, Any]:
    # 一个工具的快照项：名称、说明、参数结构与服务器标注的提示（只供参考，第 4.1 节）
    document: dict[str, Any] = {"name": tool.name, "description": tool.description,
                                "input_schema": dict(tool.input_schema or {}), "hints": None}
    annotations = tool.hints
    if annotations is not None:
        hints = {field: getattr(annotations, field) for field in _HINT_FIELDS
                 if getattr(annotations, field) is not None}
        title = annotations.title
        document["hints"] = {"title": title or "", **hints} if title or hints else None
    return document


def launch_for(server: dict[str, Any], *, credentials: CredentialChain, stderr_log_path: str) -> ServerLaunch:
    # 一台已归一化的服务器设置变成客户端的启动参数（设计说明第 7.1、7.2 节）。
    # secrets 传入已经解析的凭据值：错误文本与标准错误输出在写进事件之前把值替换为星号
    name = str(server.get("name") or "")
    values: list[str] = []
    entries = list((server.get("env") or {}).values()) + list((server.get("headers") or {}).values())
    secrets: list[str] = []
    for entry in entries:
        value = _resolve_variable(entry, credentials, name, "设置中的变量")
        values.append(value)
        if value:
            secrets.append(value)
    common = {"name": name, "startup_timeout_sec": int(server["startup_timeout_sec"]),
              "call_timeout_sec": int(server["call_timeout_sec"]), "stderr_log_path": stderr_log_path,
              "secrets": tuple(secrets)}
    if server["transport"] == "stdio":
        env = {str(key): value for key, value, entry in
               ((key, _resolve_variable(entry, credentials, name, f"环境变量 {key}"), entry)
                for key, entry in (server.get("env") or {}).items())}
        return ServerLaunch(stdio=StdioServer(command=str(server["command"]), args=tuple(server["args"]),
                                              env=env), **common)
    headers = {str(key): _resolve_variable(entry, credentials, name, f"请求头 {key}")
               for key, entry in (server.get("headers") or {}).items()}
    return ServerLaunch(http=HttpServer(url=str(server["url"]), headers=headers), **common)


def stderr_log_path_for(data_dir: str | os.PathLike[str], server_name: str) -> str:
    # 标准错误输出的日志文件（SDK 要求真实文件，设计说明第 7.2 节）：数据目录下的 mcp-logs，
    # 按服务器命名，探测之间追加
    directory = os.path.join(str(data_dir), "mcp-logs")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"{server_name}.log")


def credentials_of(facade: ProviderFacade) -> CredentialChain:
    # 控制主机的凭据来源（进程内存、进程环境、数据目录的 .env，设计说明第 4.4 节）：
    # Provider 模块持有它，探测经这个入口取值
    return facade.credential_chain()
