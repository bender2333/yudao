# 假模型的脚本检查（工单 #879）：一条按先后排队的列表脚本被工程与质检同时取用时，用例失败。
#
# 假模型只记下这件事（harness/adapters/fake.py 的 FakeAdapter），失败落在用例上：
# harness/tests/conftest.py 在每个用例结束时核对，记下的违反写进失败信息
# （写明是哪条脚本、被哪两个部门取用、应当按部门给出）。
# 只看工程与质检这一对：产品与另一个部门共用一条列表、始终先后进行的老用例不受影响。
#
# 这几项用例起独立的 pytest 会话（pytester），会话里用真实的夹具检查；
# 子进程里的违反写进子进程的输出（harness/tests/process_kill.py 读到以后让用例失败）。

import subprocess
import sys

import pytest

from harness.adapters.fake import SHARED_LIST_SCRIPT_PREFIX

pytest_plugins = ["pytester"]

# 独立会话用真实的夹具检查：仓库里的 harness/tests/conftest.py 作为插件加载
NESTED_CONFTEST = 'pytest_plugins = ["harness.tests.conftest"]\n'

# 子进程里的违反写进子进程的输出（工单 #879）
SUBPROCESS_SCRIPT = """
import asyncio

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.providers.call import ModelCall


def _call(department):
    return ModelCall(run_id="run", department=department, session_id="session", activation_id="activation",
                     step_id=1, logical_call_id="logical", attempt=1, attempt_id="activation:attempt-1",
                     purpose="work", input_items=[], tools=[])


adapter = FakeAdapter([FakeTurn(transcript="first"), FakeTurn(transcript="second")])
for department in ("engineering", "quality"):
    async def drain():
        async for _ in adapter.stream(_call(department)):
            pass
    asyncio.run(drain())
"""


def _case_body(departments: tuple[str, ...]) -> str:
    # 独立会话里的一项用例：一条列表脚本被给出的这些部门先后取用
    return f'''
import asyncio

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.providers.call import ModelCall

DEPARTMENTS = {departments!r}


def _call(department):
    return ModelCall(run_id="run", department=department, session_id="session", activation_id="activation",
                     step_id=1, logical_call_id="logical", attempt=1, attempt_id="activation:attempt-1",
                     purpose="work", input_items=[], tools=[])


def test_the_list_script_is_taken_by_several_departments():
    adapter = FakeAdapter([FakeTurn(transcript="first"), FakeTurn(transcript="second")])
    for department in DEPARTMENTS:
        async def drain():
            async for _ in adapter.stream(_call(department)):
                pass
        asyncio.run(drain())
'''


def _session(pytester: pytest.Pytester, departments: tuple[str, ...]) -> pytest.RunResult:
    pytester.makeconftest(NESTED_CONFTEST)
    pytester.makepyfile(test_nested=_case_body(departments))
    return pytester.runpytest_subprocess()


def test_a_list_script_taken_by_engineering_and_quality_fails_the_case(pytester: pytest.Pytester) -> None:
    # 一条列表脚本先后被工程与质检取用时，用例失败，信息写明脚本与两个部门
    result = _session(pytester, ("engineering", "quality"))
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert SHARED_LIST_SCRIPT_PREFIX in output
    assert "第 1 项由 engineering 取用" in output
    assert "第 2 项由 quality 取用" in output
    # 失败落在用例上：不是模型服务的错误，事项没有停在 provider_error
    assert "provider_error" not in output


def test_a_list_script_taken_by_one_department_passes(pytester: pytest.Pytester) -> None:
    # 只被一个部门取用的列表脚本照常工作
    _session(pytester, ("engineering",)).assert_outcomes(passed=1)


def test_a_list_script_taken_by_product_and_engineering_passes(pytester: pytest.Pytester) -> None:
    # 产品与工程先后取用的列表脚本照常工作（两个部门始终先后进行）
    _session(pytester, ("product", "engineering")).assert_outcomes(passed=1)


def test_the_violation_is_written_into_the_subprocess_output() -> None:
    # 子进程里的违反写进子进程的输出（工单 #879）：父进程读到以后让用例失败
    completed = subprocess.run([sys.executable, "-c", SUBPROCESS_SCRIPT],
                               capture_output=True, text=True, encoding="utf-8", check=False)
    assert SHARED_LIST_SCRIPT_PREFIX in completed.stderr
    assert "第 1 项由 engineering 取用" in completed.stderr
    assert "第 2 项由 quality 取用" in completed.stderr


def test_the_parent_fails_when_the_subprocess_reports_a_violation(tmp_path) -> None:
    # 父进程读到子进程输出里的违反以后让用例失败（harness/tests/process_kill.py）
    from harness.tests.process_kill import _assert_no_shared_list_script

    log = tmp_path / "run.log"
    log.write_text("run started\n" + SHARED_LIST_SCRIPT_PREFIX + "：第 1 项由 engineering 取用。\n",
                   encoding="utf-8")
    with pytest.raises(AssertionError, match="列表脚本"):
        _assert_no_shared_list_script(log)
