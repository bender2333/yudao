# 契约版本的共用部分：三道缝的契约各带一个版本号，实现声明它实现哪一版，薄驱动在一个发布里同时接受
# 当前版与上一版（骨架与应用设计说明第 3.2、5 节；总图第四节「执行」「装配」缝）。
# 契约圈的模块（本模块、execution_contract、assembly_contract）只导入内核与标准库，彼此之间可以互相导入；
# 除契约圈、内核与标准库以外不导入任何模块，由 tests/test_contract_modules.py 核对。

from __future__ import annotations

from typing import Any


class ContractVersionError(RuntimeError):
    # 薄驱动不接受实现声明的契约版本：这条缝接不起来时在开始一轮工作之前失败，不带着版本不合的实现在跑
    pass


def accepted_versions(current: int, previous: int | None = None) -> tuple[int, ...]:
    # 一个发布接受当前版；上一版存在时一并接受（第一版的上一版是空的）
    return (current,) if previous is None else (current, previous)


def require_version(
    implementation: Any,
    *,
    component: str,
    current: int,
    previous: int | None = None,
) -> int:
    # 薄驱动核对实现声明的契约版本。声明缺失、类型不对或不在接受的版本里都失败，说明里写明
    # 是哪一样的实现、它声明了哪一版、薄驱动接受哪几版
    allowed = accepted_versions(current, previous)
    declared = getattr(implementation, "CONTRACT_VERSION", None)
    if type(declared) is not int or declared not in allowed:
        raise ContractVersionError(
            f"{component} declares contract version {declared!r}; "
            f"the thin driver accepts {list(allowed)} (current {current}, previous {previous})"
        )
    return declared
