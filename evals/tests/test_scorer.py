"""Tests for the scenario 3 scorer.

They run the scorer against the reference implementation, against an empty
delivery and against a delivery with a wrong fare rule, and check the
completion, correctness and failure classification of each. No mock is used:
the scorer runs the real reference code.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORER_DIR = os.path.join(EVALS_DIR, "scorer")
SCORER = os.path.join(SCORER_DIR, "scorer.py")
REFERENCE_SRC = os.path.join(EVALS_DIR, "scenarios", "scenario-3", "reference", "src")
FIXTURES = os.path.join(EVALS_DIR, "scenarios", "scenario-3", "checks", "fixtures")


def make_delivery(root, copy_reference=True):
    """按被测方交付的形状搭一个目录：参考实现的代码连同它自带的数据文件。

    接口约定写明数据文件放在源码旁边，所以数据文件属于参考实现自己。这里整目录
    复制、不再从别处补一份，否则参考实现缺数据文件时这个测试仍会通过。
    """
    delivery = os.path.join(root, "delivery")
    os.makedirs(delivery, exist_ok=True)
    if copy_reference:
        shutil.copytree(REFERENCE_SRC, os.path.join(delivery, "src"))
    return delivery


def run_scorer(delivery, result_path):
    completed = subprocess.run(
        [sys.executable, SCORER, "--delivery", delivery, "--result", result_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert completed.returncode == 0, completed.stderr
    with open(result_path, encoding="utf-8") as handle:
        return json.load(handle)


CHECKS_PARENT = os.path.join(EVALS_DIR, "scenarios", "scenario-3")

def load_checks():
    """按评分器加载隐藏检查的方式导入检查包，并取回评分器使用的文件比对检查与依赖登记。"""
    if CHECKS_PARENT not in sys.path:
        sys.path.insert(0, CHECKS_PARENT)
    if SCORER_DIR not in sys.path:
        sys.path.insert(0, SCORER_DIR)
    from checks.command_checks import COMMAND_CHECKS, REQUIREMENT_TABLE
    from checks.unit_scripts import REQUIRED_SYMBOLS, SCRIPTS
    from scorer import FILE_CHECKS
    return COMMAND_CHECKS, REQUIREMENT_TABLE, SCRIPTS, FILE_CHECKS, REQUIRED_SYMBOLS


def checks_requiring(module):
    """按依赖登记取回需要某个模块的单元检查编号。"""
    *_, required_symbols = load_checks()
    return sorted(check_id for check_id, symbols in required_symbols.items()
                  if module in symbols)


# 只用票价计算模块的单元检查，它们不需要数据加载与寻路。
FARE_ONLY_CHECKS = ("unit_2_2", "unit_6_1", "unit_6_2")

def test_requirement_table_matches_the_scorer():
    command_checks, requirement_table, scripts, file_checks, required_symbols = load_checks()
    with open(os.path.join(CHECKS_PARENT, "materials", "requirement-table.json"),
              encoding="utf-8") as handle:
        published = json.load(handle)

    implemented = set(scripts) | set(command_checks) | set(file_checks)
    assert published["check_count"] == len(implemented)

    counts = {"unit": len(scripts), "command": len(command_checks),
              "file_comparison": len(file_checks)}
    assert published["check_types"] == counts
    # 每一条单元检查都登记了依赖，登记没有多出已经不存在的检查
    assert sorted(required_symbols) == sorted(scripts)

    listed = {}
    for requirement in published["requirements"]:
        for check_id in requirement["checks"]:
            assert check_id not in listed, "check %s is listed twice" % check_id
            listed[check_id] = requirement["id"]

    # 评分器实际运行的每一条检查都在公开条目表中，公开条目表里的每一条检查都存在
    assert sorted(listed) == sorted(implemented)

    # 两处条目表给同一条检查分配的条目必须相同
    for check_id, name in listed.items():
        value = requirement_table[check_id]
        names = value if isinstance(value, list) else [value]
        assert names == [name], check_id

def test_text_export_separator_matches_the_interface_agreement():
    """导出的文本版面与约定写明的版面必须使用同一个分隔符。

    被测方按约定实现，评分时与基准文件逐字符比对，所以约定里写的分隔符
    与基准文件用的分隔符必须是同一个字符。
    """
    agreement_path = os.path.join(CHECKS_PARENT, "materials", "interface-agreement.md")
    with open(agreement_path, encoding="utf-8") as handle:
        agreement = handle.read()
    layout = agreement.split("```")[1]
    separator = layout[layout.index("<station>") + len("<station>"):].strip().split()[0]

    with open(os.path.join(FIXTURES, "path_fengtai_xidan.txt"), encoding="utf-8") as handle:
        fixture = handle.read()
    assert (" %s " % separator) in fixture, separator

    # 交给被测方的起点目录里的约定与公开材料里的约定是同一份
    with open(os.path.join(CHECKS_PARENT, "materials", "start", "files",
                           "interface_agreement.md"), encoding="utf-8") as handle:
        assert handle.read() == agreement

def test_reference_scores_full_marks(tmp_path):
    delivery = make_delivery(str(tmp_path))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert result["completion"] == 1.0
    assert result["correctness"] == 1.0
    assert result["not_done"] == []
    assert result["wrong"] == []
    assert len(result["checks"]) == 24


def test_empty_delivery_scores_zero(tmp_path):
    delivery = make_delivery(str(tmp_path), copy_reference=False)
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert result["completion"] == 0.0
    assert result["correctness"] == 0.0
    assert result["not_done_count"] == 24
    assert result["wrong"] == []
    for check in result["checks"]:
        assert check["status"] == "not_done"


def test_wrong_fare_is_classified_as_wrong(tmp_path):
    delivery = make_delivery(str(tmp_path))
    fare_path = os.path.join(delivery, "src", "fare_calculator.py")
    with open(fare_path, encoding="utf-8") as handle:
        source = handle.read()
    source = source.replace("if distance < 6000:", "if distance < 6001:")
    with open(fare_path, "w", encoding="utf-8") as handle:
        handle.write(source)

    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert "unit_6_1" in result["wrong"]
    assert "unit_6_1" not in result["not_done"]
    # the other fare checks are unaffected by the boundary change
    assert "unit_2_2" not in result["wrong"]
    assert "unit_6_2" not in result["wrong"]
    # correctness counts passes among attempted checks only
    assert result["not_done"] == []
    assert result["correctness"] == pytest.approx(23 / 24)
    assert result["completion"] < 1.0
    assert result["completion"] > 0.9


def test_line_preference_is_required_for_its_requirement(tmp_path):
    delivery = make_delivery(str(tmp_path))
    # 去掉参考实现里应用偏好线路的那一步：参考实现会在指定偏好线路时改走那条线路，
    # 这一份构建完全不理会这个设置。
    pathfinding_path = os.path.join(delivery, "src", "pathfinding.py")
    with open(pathfinding_path, encoding="utf-8") as handle:
        source = handle.read()
    preference_rule = ("                if self._line_preferred(edge.line):\n"
                       "                    key = (key[0] - 1, key[1])\n")
    assert preference_rule in source, "参考实现已不再按偏好线路改分，这条构建方式需要同步修改"
    with open(pathfinding_path, "w", encoding="utf-8") as handle:
        handle.write(source.replace(preference_rule, ""))

    result = run_scorer(delivery, str(tmp_path / "result.json"))
    by_id = {check["id"]: check for check in result["checks"]}
    assert by_id["unit_2_5"]["status"] == "wrong"
    # 这条检查所属的需求条目得分为 0
    assert result["requirements"]["R3"]["score"] == 0.0
    assert result["completion"] < 1.0
    # 其余寻路检查照常通过，因此只有 R3 受影响
    assert by_id["unit_2_3"]["status"] == "pass"
    assert by_id["unit_9_1"]["status"] == "pass"

def test_missing_data_loader_is_not_done_for_its_checks(tmp_path):
    delivery = make_delivery(str(tmp_path))
    os.remove(os.path.join(delivery, "src", "data_loader.py"))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    by_id = {check["id"]: check for check in result["checks"]}
    # 单元检查在探测阶段读取交付的数据加载结果，缺模块时这些检查全部记为「没有做」
    for check_id in checks_requiring("data_loader"):
        assert by_id[check_id]["status"] == "not_done", check_id
    # 只用票价计算模块的检查不需要数据加载，照常通过
    for check_id in FARE_ONLY_CHECKS:
        assert by_id[check_id]["status"] == "pass", check_id
    assert result["not_done"] == checks_requiring("data_loader")


def test_missing_pathfinding_is_not_done_for_its_checks(tmp_path):
    delivery = make_delivery(str(tmp_path))
    os.remove(os.path.join(delivery, "src", "pathfinding.py"))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    by_id = {check["id"]: check for check in result["checks"]}
    # 需要寻路模块的单元检查全部记为「没有做」
    for check_id in checks_requiring("pathfinding"):
        assert by_id[check_id]["status"] == "not_done", check_id
    # 票价检查不需要它，照常通过
    for check_id in FARE_ONLY_CHECKS:
        assert by_id[check_id]["status"] == "pass", check_id

def test_missing_cli_is_not_done(tmp_path):
    delivery = make_delivery(str(tmp_path))
    os.remove(os.path.join(delivery, "src", "cli.py"))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    command_checks = [check for check in result["checks"] if check["id"].startswith("cmd_")]
    assert command_checks
    for check in command_checks:
        assert check["status"] == "not_done"
    file_checks = [check for check in result["checks"] if check["id"].startswith("file_")]
    for check in file_checks:
        assert check["status"] == "not_done"
    # the unit checks do not need the entry point and still pass
    assert result["completion"] > 0.0


def test_reference_keeps_the_station_names_of_the_material(tmp_path):
    """独立的那条检查：交付照材料里的站名与线名原样使用时通过。"""
    delivery = make_delivery(str(tmp_path))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    fidelity = result["data_fidelity"]
    assert fidelity["id"] == "data_1_1"
    assert fidelity["status"] == "pass"
    # 这条检查单独报告：24 条检查与两个指标不因它改变
    assert len(result["checks"]) == 24
    assert result["completion"] == 1.0
    assert result["correctness"] == 1.0


def test_translated_station_names_are_found_by_the_fidelity_check(tmp_path):
    """站名换成另一种写法时，这条检查直接发现，不靠查询结果间接暴露（工单 #1369）。"""
    delivery = make_delivery(str(tmp_path))
    data_path = os.path.join(delivery, "src", "subway_data.json")
    with open(data_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["stations"] = [{"name": "苹果园", "lines": ["1号线"]}]
    with open(data_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)

    result = run_scorer(delivery, str(tmp_path / "result.json"))
    fidelity = result["data_fidelity"]
    assert fidelity["status"] == "wrong"
    assert "苹果园" in fidelity["detail"]
    assert "1号线" in fidelity["detail"]


def test_missing_data_file_is_not_done_for_the_fidelity_check(tmp_path):
    delivery = make_delivery(str(tmp_path))
    os.remove(os.path.join(delivery, "src", "subway_data.json"))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert result["data_fidelity"]["status"] == "not_done"
