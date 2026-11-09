"""从诊断文本中去掉凭据，避免日志和回执泄露 provider key。"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

_SECRET_KEY = re.compile(r"(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTHORIZATION)", re.I)
_MIN_VALUE_LEN = 8

# 只被记录、不构成这次调用的一项参数（工作过程的任务与动作标题设计说明「动作标题」「接口」，工单 #1659）：
# 运行命令的一句话。它和命令原文一样是模型写的文字，所以与它同处一份模块；交给执行环境的输入、
# 收敛的调用标识与失败清单的「同样的参数」比较都先用 call_arguments 去掉这一项
INTENT_ARGUMENT = "intent"


def secret_env_names() -> list[str]:
    names = []
    for key, value in os.environ.items():
        if not value or len(value) < _MIN_VALUE_LEN:
            continue
        if _SECRET_KEY.search(key):
            names.append(key)
    return names


def sanitized_env(source: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    for key in list(env):
        if _SECRET_KEY.search(key):
            env.pop(key, None)
    return env


def redact_text(text: str, *, extra_values: list[str] | None = None) -> str:
    if not text:
        return text
    redacted = text
    values: list[tuple[str, str]] = []
    for key in secret_env_names():
        value = os.environ.get(key) or ""
        if len(value) >= _MIN_VALUE_LEN:
            values.append((value, f"${{{key}}}"))
    for value in extra_values or []:
        if value and len(value) >= _MIN_VALUE_LEN:
            values.append((value, "<redacted>"))
    values.sort(key=lambda item: len(item[0]), reverse=True)
    for value, replacement in values:
        redacted = redacted.replace(value, replacement)
    return redacted


def redact_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    # 动作参数里的命令按 ADR-0038 只留凭据的名称：保存的内容里不出现密钥原文，
    # 命令输出里的同一规则（redact_text）也适用于命令本身。
    # 运行命令的那一句话与命令原文是同一条规则（工作过程的任务与动作标题设计说明「动作标题」，工单 #1659）
    command = args.get("command")
    redacted = args if not isinstance(command, str) or not command else {**args, "command": redact_text(command)}
    sentence = redacted.get(INTENT_ARGUMENT)
    if isinstance(sentence, str) and sentence:
        redacted = {**redacted, INTENT_ARGUMENT: redact_text(sentence)}
    return redacted


def call_arguments(args: Any) -> Any:
    """一次工具调用里构成这次调用的参数：去掉只被记录的那一项（运行命令的一句话）。

    动作执行、收敛的调用标识与失败清单的「同样的参数」比较都用这一份，所以同一条命令写了不同的一句话
    仍算同一次调用；参数不是对象时原样交回。
    """
    if not isinstance(args, Mapping):
        return args
    return {key: value for key, value in args.items() if key != INTENT_ARGUMENT}

