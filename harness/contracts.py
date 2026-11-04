"""有效合同的身份与公开路径的规范写法（结构说明这类材料的渲染在接纳的一侧，见 submissions.py）。"""

from __future__ import annotations

from typing import Any

from .path_rules import validate_public_path


def artifact_hash(artifact: Any) -> str | None:
    # 当前成果的版本摘要：最小投影里的成果与应用侧运行状态投影里的成果都读同名的字段
    return None if artifact is None else getattr(artifact, "content_hash", None)


def normalize_scope(value: str) -> str:
    relative = value.replace("\\", "/")
    if relative == ".":
        return relative
    validate_public_path(relative[:-1] if relative.endswith("/") else relative)
    return relative
