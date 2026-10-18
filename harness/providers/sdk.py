from __future__ import annotations

import importlib
import platform
import threading
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

# SDK 的一次性初始化（D09）：导入 openai 或 anthropic、构建流事件的 pydantic 模型、识别平台，都要几秒。
# 它们不计入单次模型请求的时限，所以放在模型目录用到某个协议时：服务启动读取模型目录时，
# 或者模型目录修改以后，总在第一次请求之前。模型目录没有用到的协议不导入它的 SDK，
# 只用 fake 协议的进程与 harness --version 都不会导入 openai 与 anthropic。
# fake 协议没有 SDK，不在表中。
_PROTOCOL_MODULES = {
    "responses": "responses",
    "chat_completions": "chat",
    "messages": "messages",
}

_lock = threading.Lock()
_prepared: set[str] = set()


def prepare_protocols(protocols: Iterable[str]) -> None:
    # 幂等：已经准备过的协议直接跳过
    wanted = {protocol for protocol in protocols if protocol in _PROTOCOL_MODULES}
    with _lock:
        pending = wanted - _prepared
        if not pending:
            return
        # 两个 SDK 在每个客户端的第一次请求之前识别平台（platform.system 与 platform.platform），
        # 进程内第一次识别要查询系统信息；这里识别一次，之后读取标准库的缓存
        platform.platform()
        for protocol in sorted(pending):
            if protocol == "responses":
                from .responses import prepare_responses_sdk
                prepare_responses_sdk()
            else:
                # chat 与 messages 模块在导入时导入各自的 SDK 并构建流事件的模型
                importlib.import_module(f".{_PROTOCOL_MODULES[protocol]}", __package__)
            _prepared.add(protocol)


def anthropic_base_url(base_url: str) -> str:
    # 服务方案给的是到 /v1 的地址，Anthropic SDK 自己会补 /v1/messages，
    # 这里去掉重复的 /v1，避免出现 /v1/v1/messages
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
