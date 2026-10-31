# 等待主机工作的上限与集成层给每条用例的上限的大小关系（docs/design/test-pyramid.md 第 2.2 节）。
# 两个数各在一处集中定义：等待的上限在 harness/tests/wait_limits.py（取层上限的一半），
# 层上限在根 conftest.py 的 TIMEOUTS。这里核对它们的关系：等待的上限比层上限短，卡住时用例自己
# 以一条失败结束，不等 pytest-timeout 结束 worker。

from conftest import INTEGRATION, TIMEOUTS
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC


def test_wait_limit_is_half_of_the_integration_case_timeout():
    assert WAIT_FOR_HOST_WORK_SEC * 2 <= TIMEOUTS[INTEGRATION], (
        f"等待主机工作的上限 {WAIT_FOR_HOST_WORK_SEC} 秒的两倍不小于集成层给每条用例的 "
        f"{TIMEOUTS[INTEGRATION]} 秒上限")
    assert WAIT_FOR_HOST_WORK_SEC == TIMEOUTS[INTEGRATION] / 2, (
        f"等待主机工作的上限 {WAIT_FOR_HOST_WORK_SEC} 秒不等于集成层给每条用例的 "
        f"{TIMEOUTS[INTEGRATION]} 秒上限的一半")
