"""场景 2 的隐藏检查：F2P、P2P 与排除的用例。

F2P 是 8 条新功能测试，按需求条目挂在条目表上，计入完成度与正确性；P2P 是 331 条
原有功能测试，单独报告失败条数（评测场景设计第 4.2 节）。评分器把本目录 tests/ 下的
隐藏测试文件盖到交付上以后，只运行这两个清单里的用例。
"""

import json
import os

F2P_FILE = "f2p.json"
P2P_FILE = "p2p.json"
HIDDEN_FILES_DIR = "tests"
EXCLUDED_FILE = "excluded.json"


def load_list(checks_dir, filename):
    with open(os.path.join(checks_dir, filename), encoding="utf-8") as handle:
        payload = json.load(handle)
    tests = payload["tests"]
    if len(tests) != payload["count"]:
        raise ValueError("count does not match the list in " + filename)
    return tests


def f2p_tests(checks_dir):
    return load_list(checks_dir, F2P_FILE)


def p2p_tests(checks_dir):
    return load_list(checks_dir, P2P_FILE)


def hidden_files_dir(checks_dir):
    return os.path.join(checks_dir, HIDDEN_FILES_DIR)


def excluded_tests(checks_dir):
    with open(os.path.join(checks_dir, EXCLUDED_FILE), encoding="utf-8") as handle:
        return json.load(handle)["tests"]


def requirement_table(table_path):
    """条目表：需求条目与检查的对应，评分目录中有一份副本。"""
    with open(table_path, encoding="utf-8") as handle:
        return json.load(handle)