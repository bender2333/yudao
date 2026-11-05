# 等待主机工作的上限按层取值：取本层给每条用例上限的一半，并严格小于本层上限
# （docs/design/test-pyramid.md 「单项时间上限」）。两个数各在一处集中定义：等待的上限在
# harness/tests/wait_limits.py（按层的表，比例写成除法），层上限在根 conftest.py 的 TIMEOUTS。
# 这里逐层核对，失败时写明是哪一层。

import pytest

from conftest import INTEGRATION, MODULE, TIMEOUTS
from harness.tests.wait_limits import (
    MODULE_WAIT_FOR_HOST_WORK_SEC,
    WAIT_FOR_HOST_WORK_BY_LAYER,
    WAIT_FOR_HOST_WORK_SEC,
)

# 会等待主机工作的层，以及各层在用的名字：模块层的四个文件用模块层的上限，
# 集成层二十几个文件与两个辅助文件用集成层的上限（取值不变）。
WAIT_LIMITS_BY_LAYER = {
    MODULE: ("模块层", MODULE_WAIT_FOR_HOST_WORK_SEC),
    INTEGRATION: ("集成层", WAIT_FOR_HOST_WORK_SEC),
}


@pytest.mark.parametrize("layer", list(WAIT_LIMITS_BY_LAYER))
def test_wait_limit_is_half_of_the_layer_case_timeout(layer):
    name, wait_limit = WAIT_LIMITS_BY_LAYER[layer]
    layer_timeout = TIMEOUTS[layer]
    assert wait_limit == WAIT_FOR_HOST_WORK_BY_LAYER[layer], (
        f"{name}在用的等待上限 {wait_limit} 秒与按层的表里的 "
        f"{WAIT_FOR_HOST_WORK_BY_LAYER[layer]} 秒不一致")
    assert wait_limit == layer_timeout / 2, (
        f"{name}等待主机工作的上限 {wait_limit} 秒不等于本层给每条用例的 "
        f"{layer_timeout} 秒上限的一半")
    assert wait_limit < layer_timeout, (
        f"{name}等待主机工作的上限 {wait_limit} 秒不小于本层给每条用例的 "
        f"{layer_timeout} 秒上限")
