"""场景 2（模型设置透传参数）在 OpenCode 一侧的运行器专用部分。

起点是 openai-agents-python 在任务基准提交的代码（约 1.3 万行），按材料里的
基准提交号从 GitHub 检出，再用仓库自己的锁文件建立 Python 3.13 环境。运行目录
里只留下源码与建立好的环境，不含隐藏检查、条目表、参考实现与基准提交号。
"""

import json
import os
import shutil
import subprocess
import sys

SCENARIO = "scenario-2"
UPSTREAM_URL = "https://github.com/openai/openai-agents-python.git"
SCORER_SCRIPT = "scenario2.py"
SCORING_INPUTS = ("checks", os.path.join("materials", "requirement-table.json"))
# 交付就是整份仓库：复制进评分目录时排除版本控制与运行配置，虚拟环境保留，
# 评分直接用它，不重新建立这份唯一的依赖安装。
SCORING_IGNORES = (".git", ".opencode-config")


def upstream_urls():
    """任务上游仓库的地址：输出里出现时这次运行作废（第 3 节「联网」）。"""
    return (UPSTREAM_URL,)


def scenario_base():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "scenarios", SCENARIO))


def scorer_command(python, scoring_dir, delivery_dir):
    """场景 2 的评分命令：在交付副本上运行 F2P 与 P2P 清单。

    交付副本自带运行器建立的 Python 3.13 虚拟环境，评分直接用它。
    """
    return [sys.executable, os.path.abspath(os.path.join(scenario_base(), "..", "..",
                                                         "scorer", SCORER_SCRIPT)),
            "--delivery", delivery_dir,
            "--checks", os.path.join(scoring_dir, "checks"),
            "--table", os.path.join(scoring_dir, "requirement-table.json"),
            "--work-dir", os.path.join(scoring_dir, "_work")]


def materials_dir():
    return os.path.join(scenario_base(), "materials")


def is_inside(path, parent):
    """运行目录必须在 Yudao 仓库之外（评测场景设计第 3 节）。"""
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent + os.sep)


def base_commit():
    """材料里的基准提交号：Yudao 仓库只记录它，提交号本身不进运行目录。"""
    with open(os.path.join(materials_dir(), "manifest.json"), encoding="utf-8") as handle:
        return json.load(handle)["source"]["base_commit"]


def hidden_dirs():
    """隐藏部分：运行目录里不能出现的材料目录。"""
    base = scenario_base()
    return {
        "materials": os.path.join(base, "materials"),
        "checks": os.path.join(base, "checks"),
        "reference": os.path.join(base, "reference"),
        "repository": os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "..", "..")),
    }


def fill_run_dir(run_dir):
    """检出基准提交并建立环境。

    运行目录就是仓库根：验收标准与 P2P 都在这份交付里跑，建立环境时需要
    GitHub 与 PyPI，评测运行本身不联网。
    """
    commit = base_commit()
    subprocess.run(["git", "init", "--quiet"], cwd=run_dir, check=True,
                   capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", UPSTREAM_URL], cwd=run_dir,
                   check=True, capture_output=True)
    fetched = subprocess.run(
        ["git", "fetch", "--quiet", "--depth", "1", "origin", commit], cwd=run_dir,
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if fetched.returncode != 0:
        raise RuntimeError("cannot fetch base commit " + commit + ": " + fetched.stderr)
    subprocess.run(["git", "checkout", "--quiet", "FETCH_HEAD"], cwd=run_dir,
                   check=True, capture_output=True)
    # 版本控制信息是评分阶段不需要的：留着它，被测方能从上游取回标准答案。
    subprocess.run(["git", "remote", "remove", "origin"], cwd=run_dir,
                   check=True, capture_output=True)
    _remove_git_directory(run_dir)
    build_environment(run_dir)
    shutil.copy2(os.path.join(materials_dir(), "requirement.md"),
                 os.path.join(run_dir, "requirement.md"))


def _remove_git_directory(path):
    shutil.rmtree(os.path.join(path, ".git"), ignore_errors=True)


def build_environment(repo_dir):
    """按仓库自己的锁文件建立 Python 3.13 环境。"""
    command = ["uv", "sync", "--frozen", "--all-extras", "--all-packages",
               "--group", "dev", "--python", "3.13"]
    completed = subprocess.run(command, cwd=repo_dir, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("uv sync failed: " + (completed.stderr or completed.stdout))
    return completed


def message():
    """交给 `opencode run` 的消息。

    需求原文用 `-f` 附加：两边的输入是同一份（评测场景设计第 3 节），但 Windows
    的命令行有长度上限，全文放进命令行会被系统拒绝。环境已经建好，测试用
    `uv run --python 3.13 python -m pytest` 运行。
    """
    return ("实现这份需求。附件里的 requirement.md 是需求原文，"
            "这个目录是一个 Python 仓库，代码是当前的起点。"
            "环境已经按锁文件建好，跑测试用 uv run --python 3.13 python -m pytest。"
            "中途不要问我，按需求实现全部功能。")


def message_files(run_dir):
    """随消息附加的材料文件（运行目录中已经有的需求原文）。"""
    return [os.path.join(run_dir, "requirement.md")]