# 仓库概况（docs/design/existing-project-onboarding.md 第 4.1 节）：建档事项里部门读取的第一项材料。
# 只由快照的公开树清单与定义中的模式表确定生成：同一份快照生成同一份文字，不含文件内容，不含主机绝对路径。
# 属于控制核心，不导入应用层与接口层。

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from .definitions import DEFINITIONS, OverviewCategory
from .public_tree import CapturedFile, CapturedTree

DIRECTORY_LIMIT = 50  # 顶层目录一节最多列出的目录数


def repository_overview(tree: CapturedTree) -> str:
    # 生成仓库概况的 Markdown 文字：规模、顶层目录、按定义模式表匹配的类别清单
    files = sorted(tree.files, key=lambda item: item.path)
    total = sum(len(item.data) for item in files)
    lines: list[str] = [
        "# 仓库概况",
        "",
        "本节由控制核心按快照的公开树清单与定义中的模式表确定生成，只含路径、数量与扩展名，"
        "不含文件内容与主机绝对路径；需要内容时用 list_files 与 read_file 读取。",
        "",
        f"## 规模：共 {len(files)} 个文件，{total} 字节",
        "",
        *_directories(files),
        "",
        "## 类别",
    ]
    for name, category in DEFINITIONS.work_items.repository_overview.items():
        lines.extend(_category(name, category, files))
    return "\n".join(lines).rstrip() + "\n"


def _directories(files: list[CapturedFile]) -> list[str]:
    # 顶层目录与各目录的文件数、主要扩展名；仓库根目录下的散文件单列一条
    groups: dict[str, list[str]] = {}
    for item in files:
        segments = item.path.split("/")
        key = segments[0] + "/" if len(segments) > 1 else ""
        groups.setdefault(key, []).append(item.path)
    rows = sorted(groups.items(), key=lambda entry: (entry[0] != "", entry[0]))
    shown, hidden = rows[:DIRECTORY_LIMIT], rows[DIRECTORY_LIMIT:]
    lines = [f"- {key or '（仓库根目录的文件）'}：{len(paths)} 个文件，主要扩展名 {_extensions(paths)}"
             for key, paths in shown]
    lines.extend(f"- {key}：{len(paths)} 个文件，未列出（顶层目录数超过 {DIRECTORY_LIMIT} 个）"
                 for key, paths in hidden)
    return lines


def _category(name: str, category: OverviewCategory, files: list[CapturedFile]) -> list[str]:
    # 一个类别：写清匹配模式，匹配的清单按上限列出，超出的数量写明
    lines: list[str] = ["", f"### {name}（匹配模式：{'、'.join(category.patterns)}）", ""]
    matched = [item.path for item in files if _matches(item.path, category)]
    if not matched:
        lines.append("（快照中没有匹配的文件）")
        return lines
    lines.extend(f"- {path}" for path in matched[:category.limit])
    if len(matched) > category.limit:
        lines.append(f"- 另有 {len(matched) - category.limit} 个匹配文件未列出（本类上限 {category.limit} 个）")
    return lines


def _matches(path: str, category: OverviewCategory) -> bool:
    # 目录形式（以 / 结尾，可多级）匹配该目录下的文件；带 / 的模式匹配路径；不带 / 的模式匹配文件名
    segments = path.split("/")
    for pattern in category.patterns:
        if pattern.endswith("/"):
            head = pattern[:-1]
            if "/" in head:
                if path.startswith(head + "/"):
                    return True
            elif any(fnmatch(segment, head) for segment in segments[:-1]):
                return True
        elif "/" in pattern:
            head, tail = pattern.rsplit("/", 1)
            if path.startswith(head + "/") and fnmatch(path[len(head) + 1:], tail):
                return True
        elif fnmatch(segments[-1], pattern):
            return True
    return False


def _extensions(paths: list[str]) -> str:
    # 一个目录里数量最多的三种扩展名，以「扩展名(文件数)」列出；无扩展名的文件记作「无」
    counts: dict[str, int] = {}
    for path in paths:
        key = _extension(path)
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    return ", ".join(f"{name or '无'}({count})" for name, count in ranked[:3])


def _extension(path: str) -> str:
    name = PurePosixPath(path).name
    if name.startswith("."):
        return name.lower()
    return name.rsplit(".", 1)[1].lower() if "." in name else ""
