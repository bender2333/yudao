"""场景 2 评分器：在评分目录里对交付运行 8 条 F2P 与 331 条 P2P。

交付是 openai-agents-python 在任务基准提交上被改过的仓库。评分器先把隐藏检查的
测试文件盖到交付的副本上，再只用 Python 3.13 运行两个清单里的用例：F2P 按需求条目
计入完成度与正确性，P2P 单独报告失败条数（评测场景设计第 4.2 节）。

Python 3.13 的虚拟环境由运行器在运行目录里按锁文件建立，这份环境是这套依赖唯一的
安装，评分阶段直接用它，不重新建立。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

SCENARIO = "scenario-2"
MATERIAL_VERSION = "scenario-2@1"
SCORER_VERSION = "scorer-2@1"
PYTHON_VERSION = "3.13"
TEST_COMMAND = ("uv run --python " + PYTHON_VERSION + " --project <交付> --no-sync "
                "python -m pytest")

# 判定「没有做」的异常类型：模块、类、函数或入口不存在，单元层属于这一类
# （评测场景设计第 4.1 节）。其余失败都是「做了但结果不对」。
NOT_DONE_TYPES = ("AttributeError", "ImportError", "ModuleNotFoundError",
                  "NameError", "CollectionError", "ImportFileMismatchError")
# 隐藏检查以文件的形态随材料走：评分时直接盖掉交付里的同名文件，不依赖版本控制。
# 被测方可能改过同一处代码，用补丁套上去会被当作已经应用而跳过，评分就落在被测方
# 自己写的测试上。
HIDDEN_FILES_DIR = "tests"

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKS_DIR = os.path.join(HERE, "..", "scenarios", SCENARIO, "checks")
MATERIALS_DIR = os.path.join(HERE, "..", "scenarios", SCENARIO, "materials")


def load_checks(checks_dir):
    """从评分目录导入隐藏检查模块。

    模块名用 pytest_checks：场景 3 的隐藏检查也叫 checks，同一个进程里两个都导入
    时会撞上，模块名分开才不会互相顶掉。
    """
    path = os.path.abspath(checks_dir)
    if path not in sys.path:
        sys.path.insert(0, path)
    import pytest_checks
    return pytest_checks


def apply_hidden_files(delivery_dir, checks_dir):
    """把隐藏检查的测试文件盖到交付上。

    隐藏检查的内容只由材料决定：被测方改过同一个文件也按材料里的版本评分，
    否则被测方可以改测试来让自己通过。
    """
    source_root = os.path.join(checks_dir, HIDDEN_FILES_DIR)
    if not os.path.isdir(source_root):
        raise ValueError("no hidden test file directory: " + source_root)
    shutil.copytree(source_root, os.path.join(delivery_dir, HIDDEN_FILES_DIR),
                    dirs_exist_ok=True)


def registered_files(tests):
    """清单里出现过的文件路径：junit 的模块名只能还原成这些路径之一。"""
    return sorted({test.split("::")[0] for test in tests})


def run_tests(delivery_dir, tests, junit_path):
    """按登记的测试命令运行用例清单，结果写到 junit。

    `--project` 指向交付自己：环境由运行器在建好之后放在交付里，评分直接用它，
    不让 uv 向上找到 Yudao 仓库的环境。
    """
    command = ["uv", "run", "--python", PYTHON_VERSION, "--project", delivery_dir,
               "--no-sync", "python", "-m", "pytest",
               "-p", "no:cacheprovider", "-q", "--junit-xml", junit_path] + tests
    return subprocess.run(command, cwd=delivery_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def parse_junit(junit_path, file_paths):
    """读 pytest 自带的 junit 输出：{去掉参数后的用例标识: (状态, 详情)}。

    junit 的 classname 是点分隔的模块名，带测试类的再接一段类名，清单里写的是
    带 .py 的文件路径。登记过的文件路径就是全部可能的模块，按它还原标识。
    """
    modules = sorted((path[:-3].replace("/", "."), path) for path in file_paths)
    cases = {}
    for testcase in ET.parse(junit_path).iter("testcase"):
        dotted = testcase.get("classname")
        for module, path in modules:
            if dotted == module or dotted.startswith(module + "."):
                break
        else:
            raise ValueError("junit output holds an unregistered module: " + dotted)
        tail = dotted[len(module):].lstrip(".")
        prefix = path + ("::" + tail if tail else "")
        nodeid = "%s::%s" % (prefix, testcase.get("name"))
        status, detail = "pass", ""
        for child in testcase:
            if child.tag in ("failure", "error"):
                status = "fail"
                detail = " ".join(("%s %s" % (child.get("type") or "",
                                              child.get("message") or "")).split())
            elif child.tag == "skipped":
                status = "skip"
                detail = child.get("message") or ""
        key = nodeid.split("[", 1)[0]
        # 同一函数有几个参数化用例：任一失败就记失败
        if key in cases and cases[key][0] != "pass":
            continue
        cases[key] = (status, detail[:400])
    return cases


def classify(status, detail):
    """返回 ('pass' | 'not_done' | 'wrong', 详情)。"""
    if status == "pass":
        return "pass", ""
    if status == "skip":
        return "not_done", "the test was skipped: " + detail
    if any(name in detail for name in NOT_DONE_TYPES):
        return "not_done", detail
    if status == "missing":
        return "not_done", detail
    return "wrong", detail


def score(delivery_dir, checks_dir, table_path, work_dir):
    """对一份交付评分，返回场景 2 的结果字典。"""
    checks_dir = os.path.abspath(checks_dir)
    checks = load_checks(checks_dir)
    f2p = checks.f2p_tests(checks_dir)
    p2p = checks.p2p_tests(checks_dir)

    with open(table_path, encoding="utf-8") as handle:
        table = json.load(handle)
    requirement_names = [entry["id"] for entry in table["requirements"]]
    requirement_of = {check: entry["id"]
                      for entry in table["requirements"] for check in entry["checks"]}
    unregistered = sorted(set(f2p) - set(requirement_of))
    if unregistered:
        raise ValueError("the requirement table does not map these checks: "
                         + ", ".join(unregistered))

    os.makedirs(work_dir, exist_ok=True)
    f2p_junit = os.path.join(work_dir, "f2p-junit.xml")
    p2p_junit = os.path.join(work_dir, "p2p-junit.xml")
    apply_hidden_files(delivery_dir, checks_dir)
    f2p_run = run_tests(delivery_dir, f2p, f2p_junit)
    p2p_run = run_tests(delivery_dir, p2p, p2p_junit)

    f2p_cases = parse_junit(f2p_junit, registered_files(f2p)) if os.path.exists(f2p_junit) else {}
    p2p_cases = parse_junit(p2p_junit, registered_files(p2p)) if os.path.exists(p2p_junit) else {}

    records = []
    for test in f2p:
        status, detail = f2p_cases.get(test, ("missing", "the test was not collected"))
        outcome, text = classify(status, detail)
        records.append({"id": test, "requirement": requirement_of[test],
                        "status": outcome, "detail": text})

    regression = {"passed": 0, "failed": 0, "total": len(p2p), "failures": []}
    for test in p2p:
        status, detail = p2p_cases.get(test, ("fail", "the test was not collected"))
        if status == "pass":
            regression["passed"] += 1
        else:
            regression["failed"] += 1
            regression["failures"].append({"id": test, "detail": detail[:200]})

    return aggregate(records, requirement_names, regression,
                     {"f2p": f2p_run.returncode, "p2p": p2p_run.returncode})


def aggregate(records, requirement_names, regression, exit_codes):
    by_requirement = {name: [] for name in requirement_names}
    for record in records:
        by_requirement[record["requirement"]].append(record)

    requirement_scores = {}
    for name in requirement_names:
        items = by_requirement[name]
        passed = sum(1 for item in items if item["status"] == "pass")
        requirement_scores[name] = {
            "passed": passed,
            "total": len(items),
            "score": passed / len(items) if items else 0.0,
        }

    completion = (sum(item["score"] for item in requirement_scores.values())
                  / len(requirement_names)) if requirement_names else 0.0
    attempted = [item for item in records if item["status"] != "not_done"]
    passed_attempts = sum(1 for item in attempted if item["status"] == "pass")
    correctness = passed_attempts / len(attempted) if attempted else 0.0

    not_done = [item["id"] for item in records if item["status"] == "not_done"]
    wrong = [item["id"] for item in records if item["status"] == "wrong"]

    return {
        "scenario": SCENARIO,
        "material_version": MATERIAL_VERSION,
        "scorer_version": SCORER_VERSION,
        "python": PYTHON_VERSION,
        "test_command": TEST_COMMAND,
        "completion": completion,
        "correctness": correctness,
        "not_done_count": len(not_done),
        "wrong_count": len(wrong),
        "not_done": not_done,
        "wrong": wrong,
        "requirements": requirement_scores,
        "checks": records,
        "regression": regression,
        "test_exit_codes": exit_codes,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scenario 2 scorer")
    parser.add_argument("--delivery", required=True,
                        help="交付目录：基准提交的仓库")
    parser.add_argument("--checks", default=CHECKS_DIR)
    parser.add_argument("--table", default=os.path.join(MATERIALS_DIR,
                                                        "requirement-table.json"))
    parser.add_argument("--result", help="写机器可读结果的路径")
    parser.add_argument("--work-dir", help="放 junit 结果的目录，默认在交付目录旁边")
    args = parser.parse_args(argv)

    delivery_dir = os.path.abspath(args.delivery)
    work_dir = os.path.abspath(args.work_dir or os.path.join(
        os.path.dirname(delivery_dir), "_work"))
    result = score(delivery_dir, os.path.abspath(args.checks),
                   os.path.abspath(args.table), work_dir)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result:
        with open(args.result, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())