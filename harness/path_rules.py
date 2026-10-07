# 公开路径的规则：可移植的相对路径、主机私有路径与保留组件的判断。
#
# 裁决（工具许可的计划范围）与执行层（工作区读取、封存、快照）共用同一套规则；
# 规则与需要 libgit2 的公开树采集放在两个模块里，内核因此不导入第三方代码
# （可信内核设计说明第 3 节的导入方向）。

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9\u00b9\u00b2\u00b3]|lpt[1-9\u00b9\u00b2\u00b3]|conin\$|conout\$)", re.IGNORECASE)


class TreeError(ValueError):
    """A tree is incomplete, changed, or cannot be represented without ambiguity."""


def is_private_path(relative: str) -> bool:
    parts = relative.replace("\\", "/").casefold().split("/")
    return parts[0] == ".checks" or ".git" in parts


def is_git_metadata(relative: str) -> bool:
    # 仓库自身的 Git 元数据：公开树排除它（设计第 4.2 节），快照接入不因为它拒绝源目录
    return ".git" in relative.replace("\\", "/").casefold().split("/")


def validate_public_path(relative: str) -> None:
    """Accept an unambiguous portable relative path, never silently normalize it."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise TreeError(f"Invalid public path: {relative!r}")
    if PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).drive:
        raise TreeError(f"Public path must be relative: {relative!r}")
    for part in relative.split("/"):
        if not part or part in {".", ".."} or part.endswith((".", " ")):
            raise TreeError(f"Ambiguous public path: {relative!r}")
        if any(ord(character) < 32 or character in '<>:"|?*' for character in part) or _DEVICE.fullmatch(part.split(".", 1)[0].rstrip(" ")):
            raise TreeError(f"Public path has a reserved component: {relative!r}")
        try:
            part.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise TreeError(f"Public path is not valid UTF-8: {relative!r}") from exc
    if is_private_path(relative):
        raise TreeError(f"Host-private path is not part of a public tree: {relative!r}")