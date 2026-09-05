"""从诊断文本中去掉凭据，避免日志和回执泄露 provider key。"""

from __future__ import annotations

import os
import re

_SECRET_KEY = re.compile(r"(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTHORIZATION)", re.I)
_MIN_VALUE_LEN = 8


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
