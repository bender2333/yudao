# 路由的收紧检查这份契约的圈（工单 #1095；骨架与应用设计说明第 3.2、5.5 节；总图第二节第二环「契约」）。
#
# 契约模块只导入内核、标准库与契约圈自己；实现（harness/tightening.py，应用层）声明它实现的版本，
# 薄的一侧在一个发布里接受当前版与上一版，版本不合格时在开始一轮工作之前失败并写明原因——
# 与执行、装配两份契约同一个做法（harness/execution_contract.py、harness/assembly_contract.py）。
# 接口与两条数据（TightenRequest、Tightened）住在内核的 harness/validation.py：内核只按形状调用，
# 内核文件不导入契约圈。这里不写事件、不读数据库。

from __future__ import annotations

from typing import Any

from . import contract_versions

# 收紧检查接口的版本（工单 #1095 第一次建立）：通过、拒绝、等待三种结果与请求的字段。
# 加字段只增；换掉字段的含义或删字段时把当前版降为上一版，薄的一侧同时接受两版。
CURRENT_VERSION = 1
PREVIOUS_VERSION: int | None = None


def accept(tightening: Any) -> int:
    # 组装时核对收紧检查的契约版本：不合格时在开始一轮工作之前失败并写明原因
    return contract_versions.require_version(
        tightening, component="the tightening check", current=CURRENT_VERSION,
        previous=PREVIOUS_VERSION)
