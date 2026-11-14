# 随包分发的进程外运维技能加载与安装入口（docs/design/external-ops-agent.md「接口」「随包运维技能」）。
# 位于总图第四节「接口」的缝外侧，只使用 Python 标准库，不导入 harness 内的其他模块（由 pyproject.toml 的 import-linter 合同守卫）。

from __future__ import annotations

import argparse
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any, TextIO

SKILL_FILENAME = "SKILL.md"
EXIT_SKILL_OK = 0
EXIT_SKILL_CONFLICT = 1


class SkillTargetExistsError(FileExistsError):
    # 目标技能文件已存在且调用方未传入 --force 时触发（对应退出码 1）
    pass


def read_skill_text() -> str:
    return files(__package__).joinpath(SKILL_FILENAME).read_text(encoding="utf-8")


def install_skill(target_dir: str | Path, *, force: bool = False) -> Path:
    destination_dir = Path(target_dir)
    destination_file = destination_dir / SKILL_FILENAME
    if destination_file.exists() and not force:
        raise SkillTargetExistsError(
            f"目标技能文件已存在：{destination_file}（如需覆盖请显式传入 --force）"
        )
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_file.write_text(read_skill_text(), encoding="utf-8")
    return destination_file


def register_skill_subcommands(subparsers: Any) -> None:
    skill = subparsers.add_parser("skill", help="show or install the bundled Yudao operations skill")
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    skill_sub.add_parser("show", help="print the bundled SKILL.md to standard output")
    install = skill_sub.add_parser("install", help="copy SKILL.md into a target skill directory")
    install.add_argument("target_dir", help="target directory where SKILL.md will be written")
    install.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="overwrite existing SKILL.md in target directory",
    )


def execute_skill_command(
    args: argparse.Namespace,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out_stream = sys.stdout if stdout is None else stdout
    err_stream = sys.stderr if stderr is None else stderr

    if args.skill_command == "show":
        content = read_skill_text()
        out_stream.write(content if content.endswith("\n") else f"{content}\n")
        out_stream.flush()
        return EXIT_SKILL_OK

    if args.skill_command == "install":
        try:
            written_path = install_skill(args.target_dir, force=bool(args.force))
        except SkillTargetExistsError as exc:
            print(str(exc), file=err_stream)
            return EXIT_SKILL_CONFLICT
        print(str(written_path), file=out_stream)
        return EXIT_SKILL_OK

    print(f"未知技能子命令：{args.skill_command}", file=err_stream)
    return EXIT_SKILL_CONFLICT
