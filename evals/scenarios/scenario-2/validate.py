"""核对场景 2 的材料：标准答案通过全部检查，起点一条 F2P 都不通过。

评测场景设计第 2.4 节：参考解法必须通过全部隐藏检查，用来确认检查本身没有写错。
这个脚本按材料里记录的基准提交建立两份交付——原样的与套上参考实现的——分别评分，
两边的结果都符合预期才写出通过。

用法：validate.py --work <工作目录>

每次运行都重新检出并重新建立环境，两份交付互不影响；工作目录必须在 Yudao 仓库之外。
"""

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "runner"))
CHECKS_DIR = os.path.join(HERE, "checks")
for path in (RUNNER_DIR, CHECKS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import run_eval
import scenario2
import pytest_checks


def repository_root():
    return os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def make_delivery(work_dir, name):
    """按材料里的基准提交建立一份交付：原样的，或者套上参考实现的。"""
    run_dir = os.path.join(work_dir, name)
    if os.path.exists(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir)
    scenario2.fill_run_dir(run_dir)
    if name == "reference":
        # 套补丁前先建立版本控制：git apply 需要一个仓库
        subprocess.run(["git", "init", "--quiet"], cwd=run_dir, check=True,
                       capture_output=True)
        patch = os.path.join(scenario2.scenario_base(), "reference", "gold.patch")
        subprocess.run(["git", "apply", "--whitespace=nowarn", patch], cwd=run_dir,
                       check=True, capture_output=True)
    return run_dir


def score_delivery(run_dir, evidence_dir):
    return run_eval.score_delivery(run_dir, evidence_dir, "scenario2")


def summarise(label, scores):
    passed = sum(1 for item in scores["checks"] if item["status"] == "pass")
    print("[%s] 完成度=%.4f 正确性=%.4f F2P 通过 %d/%d P2P 失败 %d/%d" % (
        label, scores["completion"], scores["correctness"], passed,
        len(scores["checks"]), scores["regression"]["failed"],
        scores["regression"]["total"]))
    for name, item in scores["requirements"].items():
        print("    %s %d/%d" % (name, item["passed"], item["total"]))
    for item in scores["checks"]:
        if item["status"] != "pass":
            print("    %s %s %s" % (item["id"], item["status"], item["detail"][:160]))


def check_acceptance(scores, expected_f2p_pass, label):
    """验收标准：完成度、正确定义与 P2P 失败条数。"""
    passed = sum(1 for item in scores["checks"] if item["status"] == "pass")
    total = len(scores["checks"])
    problems = []
    if passed != expected_f2p_pass:
        problems.append("%s: F2P 通过 %d 条，应为 %d 条" % (label, passed, expected_f2p_pass))
    if scores["regression"]["failed"] != 0:
        problems.append("%s: P2P 失败 %d 条，应为 0 条"
                        % (label, scores["regression"]["failed"]))
        for item in scores["regression"]["failures"][:10]:
            problems.append("    " + item["id"] + " " + item["detail"][:160])
    expected_completion = expected_f2p_pass / total
    if abs(scores["completion"] - expected_completion) > 1e-9:
        problems.append("%s: 完成度 %.4f，应为 %.4f"
                        % (label, scores["completion"], expected_completion))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scenario 2 material check")
    parser.add_argument("--work", required=True, help="工作目录，必须在 Yudao 仓库之外")
    args = parser.parse_args(argv)

    work_dir = os.path.abspath(args.work)
    if scenario2.is_inside(work_dir, repository_root()):
        raise SystemExit("the work directory must be outside the Yudao repository")
    os.makedirs(work_dir, exist_ok=True)

    checks_dir = os.path.join(scenario2.scenario_base(), "checks")
    f2p_count = len(pytest_checks.f2p_tests(checks_dir))
    problems = []
    for name, expected in (("reference", f2p_count), ("baseline", 0)):
        delivery = make_delivery(work_dir, name)
        evidence = os.path.join(work_dir, "evidence-" + name)
        scores = score_delivery(delivery, evidence)
        summarise(name, scores)
        problems.extend(check_acceptance(scores, expected, name))
        shutil.rmtree(delivery, ignore_errors=True)

    if problems:
        print("\n不通过：")
        for problem in problems:
            print("  " + problem)
        return 1
    print("\n通过：标准答案 %d 条 F2P 全部通过且 P2P 失败 0 条；"
          "未修改的仓库 %d 条 F2P 全部不通过且 P2P 失败 0 条。"
          % (f2p_count, f2p_count))
    return 0


if __name__ == "__main__":
    sys.exit(main())