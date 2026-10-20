"""场景 1（WebGen-Bench 待办清单）在 OpenCode 一侧的运行器专用部分。

起点是材料里的需求原文与接口约定；运行目录、命令行、超时结束
与输出解析由 opencode.py 通用提供。
"""

import os
import shutil

SCENARIO = "scenario-1"
START_FILES = ("requirement.md", "interface-agreement.md")
SCORER_SCRIPT = "scenario1.py"
SCORING_INPUTS = ("checks", "reference", os.path.join("materials", "requirement-table.json"))
SCORING_IGNORES = (".git", ".opencode-config", "node_modules")

# 任务的上游仓库（WebGen-Bench）。运行器在输出里查找对它的访问，与材料目录的路径
# 使用同一条作废处理：找到说明结果可能被上游答案污染。
UPSTREAM_REPOSITORY = "mnluzimu/WebGen-Bench"
UPSTREAM_URLS = (
    "https://github.com/" + UPSTREAM_REPOSITORY,
    "https://huggingface.co/datasets/luzimu/WebGen-Bench",
)


def upstream_urls():
    """任务上游仓库的地址：输出里出现时这次运行作废。"""
    return UPSTREAM_URLS


def scenario_base():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "scenarios", SCENARIO))


def materials_dir():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                        "scenarios", SCENARIO, "materials"))


def scorer_command(python, scoring_dir, delivery_dir):
    """场景 1 的评分命令：在评分目录里启动交付并由界面智能体执行用例。"""
    return [python, os.path.abspath(os.path.join(scenario_base(), "..", "..",
                                                 "scorer", SCORER_SCRIPT)),
            "--delivery", delivery_dir,
            "--checks", os.path.join(scoring_dir, "checks"),
            "--table", os.path.join(scoring_dir, "requirement-table.json")]


def hidden_dirs():
    """隐藏部分：运行目录里不能出现的材料目录。"""
    base = scenario_base()
    return {
        "materials": os.path.join(base, "materials"),
        "checks": os.path.join(base, "checks"),
        "reference": os.path.join(base, "reference"),
    }


def fill_run_dir(run_dir):
    """把材料起点复制进已经新建好的运行目录。"""
    mat = materials_dir()
    for name in START_FILES:
        source = os.path.join(mat, name)
        target = os.path.join(run_dir, name)
        if os.path.exists(source):
            shutil.copy2(source, target)


def message():
    """交给 `opencode run` 的消息。"""
    return ("实现这份需求与接口约定。附件里的 requirement.md 是需求原文，"
            "interface-agreement.md 是接口约定。"
            "按文档实现全部功能，并通过环境变量 PORT 给出端口启动服务。先读完两份文档再动手。")


def message_files(run_dir):
    """随消息附加的材料文件（运行目录中已经有的起点文件）。"""
    return [os.path.join(run_dir, name)
            for name in START_FILES
            if os.path.exists(os.path.join(run_dir, name))]
