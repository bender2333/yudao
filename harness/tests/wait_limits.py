# 等待主机工作完成的墙钟时限集中在这里定义。按 #107 的裁定（架构师 2026-09-27 16:55，
# docs/archive/architecture-issues-2026-09-10.md），这些时限只用来防止测试一直等待，设为远大于负载下正常用时的值；
# 被等待的工作是完整三部门循环或一次事项结算，正常用时数秒，并发负载下更慢。
# 这些时限不判定被测行为：被等待的事情是否按预期发生，由等待之后的断言核对。
# 证明某件事「立即」发生的界限属于业务断言，各测试文件自行定义。
#
# 上限取集成层给每条用例的上限的一半（docs/design/test-pyramid.md 第 2.2 节）：卡住时用例自己以一条失败
# 结束，不等 pytest-timeout 结束 worker。两个数各在一处集中定义：层上限在根 conftest.py 的 TIMEOUTS，
# 这里的比例写成除法，单元层用例核对它们的大小关系（harness/tests/test_wait_limits.py）。
from conftest import INTEGRATION, TIMEOUTS

WAIT_FOR_HOST_WORK_SEC = TIMEOUTS[INTEGRATION] / 2
