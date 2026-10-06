"""场景 3（北京地铁票价）在 OpenCode 一侧的运行器专用部分。

起点是材料里的四个文件，消息与附件只与这个场景有关；运行目录、命令行、超时结束
与输出解析由 opencode.py 通用提供。
"""

import os
import shutil

SCENARIO = "scenario-3"
START_FILES = ("PRD.md", "interface_agreement.md", "subway_data.json", "manifest.json")
SCORER_SCRIPT = "scorer.py"
SCORING_INPUTS = ("checks", "reference", os.path.join("materials", "requirement-table.json"))
SCORING_IGNORES = (".git", ".opencode-config")


def scenario_base():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "scenarios", SCENARIO))


def scorer_command(python, scoring_dir, delivery_dir):
    """场景 3 的评分命令：在评分目录里对交付副本运行 24 条检查。"""
    return [python, os.path.abspath(os.path.join(scenario_base(), "..", "..",
                                                 "scorer", SCORER_SCRIPT)),
            "--delivery", delivery_dir,
            "--checks", os.path.join(scoring_dir, "checks")]


def materials_dir():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                        "scenarios", SCENARIO, "materials"))


def start_dir():
    return os.path.join(materials_dir(), "start", "files")


def hidden_dirs():
    """隐藏部分：运行目录里不能出现的材料目录。"""
    base = os.path.dirname(materials_dir())
    return {
        "materials": os.path.join(base, "materials"),
        "checks": os.path.join(base, "checks"),
        "reference": os.path.join(base, "reference"),
        "files": os.path.join(base, "files"),
    }


def fill_run_dir(run_dir):
    """把材料起点复制进已经新建好的运行目录。"""
    for name in START_FILES:
        source = os.path.join(start_dir(), name)
        target = os.path.join(run_dir, name)
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def message():
    """交给 `opencode run` 的消息。

    需求原文与接口约定用 `-f` 附加：两边的输入是同一份（评测场景设计第 3 节），
    但 Windows 的命令行有长度上限，全文放进命令行会被系统拒绝。
    """
    return ("实现这份需求与接口约定。附件里的 PRD.md 是需求原文，"
            "interface_agreement.md 是接口约定，"
            "subway_data.json 是题目提供的北京地铁网络数据，代码放在当前目录的 src/ 下。"
            "先读完两份文档再动手，中途不要问我，按文档实现全部功能。")


def message_files(run_dir):
    """随消息附加的材料文件（运行目录中已经有的起点文件）。"""
    return [os.path.join(run_dir, name)
            for name in ("PRD.md", "interface_agreement.md", "subway_data.json")]