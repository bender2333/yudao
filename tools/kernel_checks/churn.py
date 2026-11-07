# 近两周改动（docs/design/kernel-quality-gate.md「接口」「方案」4.1）：对内核清单里的每个内核
# 模块（kind 为 module 的路径，不论开关开没开、不论这次改没改到）算从当前提交往前 14 天以内的
# 提交里，这个文件的新增行数与删除行数，再除以它在当前提交上的物理行数（含空行与注释），写成
# 百分数，保留一位小数。
#
# 这一项只是读数：打开开关时用它与 seam-diff 报告核对接入条件，不进结论、不改退出码，也不拿来
# 挡合并（设计说明「接入：按模块，两个开关」：开关打开以后不再重新核对条件）。
#
# 取不到 git 记录（这个文件没有提交过、浅克隆里历史不够）时那个模块的比值留空并写明原因，不算
# 工具出错；git 命令本身失败才按工具出错（退出码 2）处理。
#
# 工具只读文件、起进程（git），不导入 harness/ 里的代码。

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .changes import GitError, _run, show  # _run：与改动识别用同一套 git 调用参数（core.quotepath）

WINDOW_DAYS = 14


def section(root: Path, modules: Iterable[str]) -> dict:
    # 清单里的每个内核模块一项，顺序与清单一致
    window_since = _window_since(root)
    covered = _window_covered(root, window_since)
    return {
        "window_days": WINDOW_DAYS,
        "window_since": window_since,
        "modules": [_module_entry(root, path, window_since, covered) for path in modules],
    }


def _window_since(root: Path) -> str:
    # 窗口是到当前提交为止的 14 天：起点取当前提交的提交时间减 14 天，命令按这个时间过滤提交
    done = _run(root, "log", "-1", "--format=%cI", "HEAD")
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"读不了当前提交的时间（git log -1 失败：{detail}）")
    text = done.stdout.decode("utf-8", "replace").strip()
    if not text:
        raise GitError("读不了当前提交的时间（git log -1 没有给出提交）")
    try:
        committed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GitError(f"读不了当前提交的时间：{text}") from exc
    return (committed - timedelta(days=WINDOW_DAYS)).isoformat()


def _window_covered(root: Path, window_since: str) -> bool:
    # 能不能读到窗口起点以前的历史：浅克隆的边界落在窗口里面时，窗口里的提交可能缺，边界提交还会把
    # 整个文件算成新增，读数不可信。完整的仓库里一律当作能读到（历史本来就短时，全部提交都在窗口里）
    done = _run(root, "rev-parse", "--is-shallow-repository")
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"读不了这个仓库是不是浅克隆：{detail}")
    if done.stdout.decode("utf-8", "replace").strip() != "true":
        return True
    done = _run(root, "rev-list", "--max-count=1", f"--before={window_since}", "HEAD")
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"读不了窗口起点以前的提交：{detail}")
    return bool(done.stdout.strip())


def _module_entry(root: Path, path: str, window_since: str, covered: bool) -> dict:
    text = show(root, "HEAD", path)
    if text is None:
        return _entry(path, 0, 0, None, "当前提交里没有这个文件（没有提交过），取不到 git 记录")
    lines = len(text.splitlines())
    if not covered:
        return _entry(path, 0, 0, lines, "浅克隆里历史不够（窗口起点以前没有能读到的提交），取不到近两周的改动")
    added, deleted = _numstat(root, path, window_since)
    if lines == 0:
        return _entry(path, added, deleted, lines, "模块在当前提交上是空文件，比值没有分母")
    total = added + deleted
    return {
        "module": path,
        "added": added,
        "deleted": deleted,
        "total": total,
        "lines": lines,
        "ratio": round(total / lines * 100, 1),
        "why": None,
    }


def _entry(path: str, added: int, deleted: int, lines: int | None, why: str) -> dict:
    return {
        "module": path,
        "added": added,
        "deleted": deleted,
        "total": added + deleted,
        "lines": lines,
        "ratio": None,
        "why": why,
    }


def _numstat(root: Path, path: str, window_since: str) -> tuple[int, int]:
    # 窗口内这个文件的新增行数合计与删除行数合计；改名按删除加新增算，别的文件的记录不进来
    done = _run(root, "log", f"--since={window_since}", "--numstat", "--format=", "--no-renames", "--", path)
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"读不了 {path} 近两周的改动：{detail}")
    added = 0
    deleted = 0
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 3 or fields[2] != path:
            continue
        added += _count(fields[0])
        deleted += _count(fields[1])
    return added, deleted


def _count(value: str) -> int:
    # 二进制文件的记录是「-」，这个文件是 .py，出现时按 0 行算，不让它把读数整个弄坏
    return int(value) if value.isdigit() else 0
