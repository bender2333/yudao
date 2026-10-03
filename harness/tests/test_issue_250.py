import ctypes
import os

import pytest

from harness.actions import FactsQuery
from harness.adapters.fake import FakeAdapter
from harness.environment import LocalEnvironment
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem

# 数据目录以 Windows 的 8.3 短路径给出时（用户名超过 8 个字符的机器上 TEMP 的默认值就是这种形式），
# 工作区与材料目录的路径判断必须与解析后的根一致（工单 #250）。

def _short_path(path):
    # 用 Win32 的 GetShortPathName 取得 8.3 短路径形式；路径本身很短时返回值与原路径相同
    buffer = ctypes.create_unicode_buffer(1024)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    assert length, f"GetShortPathName failed for {path!r}"
    return buffer.value

def _delivery_script():
    # 一轮完整的三部门：产品规格、工程计划、交付提案与质检放行
    return [product_spec(), plan_turn(), delivery_turn(), review_turn("release", "Checks passed")]

@pytest.mark.skipif(os.name != "nt", reason="8.3 short paths are Windows-specific")
def test_delivery_accepts_a_short_data_directory(tmp_path):
    short = _short_path(tmp_path)
    system = LoopSystem.for_testing(short, FakeAdapter(_delivery_script()))
    run_id = system.create_run("Build echo")
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    assert result.delivery_spec.files == ["src/echo.py"]
    # 材料目录的读写：接纳写入的意图与 PRD 材料落在解析后的材料根下，可以按同一份根读回
    materials = system.orchestrator.materials_root
    assert materials == system.data_dir / "materials"
    assert (materials / run_id / "intend.md").is_file()
    assert (materials / run_id / "PRD.md").read_bytes() == system.artifacts.get_for_run(
        run_id, result.effective_contract.prd_ref)

@pytest.mark.skipif(os.name != "nt", reason="8.3 short paths are Windows-specific")
def test_workspace_write_and_facts_use_the_same_resolved_root(tmp_path):
    short = _short_path(tmp_path)
    environment = LocalEnvironment.establish(f"{short}\\workspaces\\run1", None)
    assert environment.workspace.write_file("src/echo.py", "print(1)\n") == "src/echo.py"
    path_facts = environment.query(FactsQuery(paths=["src/echo.py"])).paths["src/echo.py"]
    assert path_facts.error is None, path_facts.error
    assert path_facts.canonical == "src/echo.py"
    assert path_facts.kind == "file"
