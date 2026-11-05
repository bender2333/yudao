# CI 的分层摘要与用例变化（scripts/ci_layers.py，测试分层设计说明第 4.3、4.4 节）：只调用函数，
# 输入写在用例里，不读临时文件，不启动子进程
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_layers.py"


def _load():
    # dataclass 按模块名在 sys.modules 中查找模块，执行脚本之前先登记
    spec = importlib.util.spec_from_file_location("yudao_ci_layers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ci = _load()

LAYERS = {"test_a.py": "unit", "kernel/test_b.py": "module", "test_c.py": "integration"}


def test_each_test_belongs_to_the_layer_of_its_file():
    assert ci.layer_of("harness/tests/test_a.py::test_x", LAYERS) == "unit"
    assert ci.layer_of("harness\\tests\\kernel\\test_b.py::test_y[1]", LAYERS) == "module"
    assert ci.layer_of("evals/tests/test_runner.py::test_z", LAYERS) == "evals"
    assert ci.layer_of("harness/tests/test_new.py::test_w", LAYERS) == ci.UNREGISTERED


def test_collected_ids_skip_the_count_and_warning_lines():
    text = "\n".join([
        "harness/tests/test_a.py::test_x",
        "harness/tests/test_c.py::test_param[two words]",
        "",
        "  harness/tests/test_a.py:12: DeprecationWarning: old",
        "2 tests collected in 1.20s",
    ])
    assert ci.parse_nodeids(text) == {"harness/tests/test_a.py::test_x",
                                      "harness/tests/test_c.py::test_param[two words]"}


def test_junit_counts_and_files_fold_test_classes_into_their_module():
    text = """<testsuites><testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1" time="65.4">
      <testcase classname="harness.tests.test_a" name="test_x" time="1"/>
      <testcase classname="harness.tests.test_a.TestGroup" name="test_y" time="1"/>
      <testcase classname="evals.tests.test_runner" name="test_z" time="1"/>
      <testcase classname="evals.tests.test_runner" name="test_w" time="1"/>
    </testsuite></testsuites>"""
    result = ci.parse_junit(text)
    assert (result.tests, result.failures, result.errors, result.skipped, result.files) == (4, 1, 1, 1, 2)
    assert round(result.seconds, 1) == 65.4


def test_summary_lists_each_layer_from_the_bottom_with_pending_and_missing_rows():
    unit = ci.LayerResult(tests=10, failures=1, errors=0, skipped=2, seconds=75, files=99)
    text = ci.summary_markdown({"unit": unit, "module": None}, LAYERS, ["integration"])
    rows = [line for line in text.splitlines() if line.startswith("| ①") or line.startswith("| ②")
            or line.startswith("| ③")]
    # 文件数取登记表，不取 junit；通过 = 用例 - 失败 - 跳过
    assert rows[0] == "| ① 单元层 | 1 | 10 | 7 | 1 | 2 | 1:15 |"
    assert "没有结果" in rows[1]
    assert rows[2].startswith("| ③ 集成层 | 1 |") and "合并到 main 以后运行" in rows[2]
    assert "评测工具" not in text


def test_inventory_counts_added_removed_and_moved_tests_per_layer():
    base_layers = {"test_a.py": "unit", "test_c.py": "integration"}
    head_layers = {"test_a.py": "module", "test_c.py": "integration"}
    base = {"harness/tests/test_a.py::test_x", "harness/tests/test_c.py::test_old",
            "harness/tests/test_c.py::test_kept"}
    head = {"harness/tests/test_a.py::test_x", "harness/tests/test_c.py::test_new",
            "harness/tests/test_c.py::test_kept", "evals/tests/test_runner.py::test_z"}
    text = ci.inventory_markdown(base, head, base_layers, head_layers)
    lines = text.splitlines()
    # 层 | 合并前 | 合并后 | 新增 | 删除 | 移入 | 移出
    assert "| ① 单元层 | 1 | 0 | 0 | 0 | 0 | 1 |" in lines
    assert "| ② 模块层 | 0 | 1 | 0 | 0 | 1 | 0 |" in lines
    assert "| ③ 集成层 | 2 | 2 | 1 | 1 | 0 | 0 |" in lines
    assert "| 评测工具 | 0 | 1 | 1 | 0 | 0 | 0 |" in lines
    # 改名显示为一删一增；删除与换层逐条列出
    assert "- ③ 集成层：`harness/tests/test_c.py::test_old`" in lines
    assert "- ① 单元层 → ② 模块层：`harness/tests/test_a.py::test_x`" in lines
    assert "- ③ 集成层：`harness/tests/test_c.py::test_new`" in lines


def test_a_failed_collection_is_reported_instead_of_no_change():
    head = "harness/tests/test_a.py::test_x\n1 test collected in 0.10s\n"
    failed = "ERROR harness/tests/test_a.py - ImportError: boom\n1 error in 0.20s\n"
    text = ci.inventory_from_outputs(failed, head, LAYERS, LAYERS)
    assert "没有收集到合并前的用例" in text and "ImportError: boom" in text
    assert "用例没有变化" not in text
    assert "没有收集到合并后的用例" in ci.inventory_from_outputs(head, None, LAYERS, LAYERS)


def test_inventory_says_so_when_nothing_changed():
    ids = {"harness/tests/test_a.py::test_x"}
    text = ci.inventory_markdown(ids, ids, LAYERS, LAYERS)
    assert "用例没有变化。" in text
    assert "**删除的用例" not in text
