# 复杂度检查（docs/design/kernel-quality-gate.md「复杂度检查」）：对改到的函数用 radon 量圈
# 复杂度，超过 10 就不通过，报告写出函数与数值。没有改到的函数不量；复杂度没有登记出口。
#
# 量一个函数时只把它自己的源码交给 radon：方法先取出再量，所以拿到的是这个函数自己的复杂度，
# 不受它在类里与嵌套函数的影响。radon 自己把嵌套函数挂在所属函数的 closures 里，不计入它的数值。

from __future__ import annotations

import ast
from dataclasses import dataclass

from radon.complexity import cc_visit
from radon.visitors import Function

# 基础规则四与总图第二节「只由你批准」的上限：改到的函数圈复杂度不超过 10（分支路径不多于十条）
LIMIT = 10


class ComplexityError(Exception):
    """radon 没有给出这个函数的复杂度。"""


@dataclass(frozen=True)
class Measurement:
    name: str
    value: int

    @property
    def over_limit(self) -> bool:
        return self.value > LIMIT


def measure(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Measurement:
    blocks = [block for block in cc_visit(ast.unparse(function)) if isinstance(block, Function)]
    if not blocks:
        raise ComplexityError(f"radon 没有给出函数 {function.name} 的圈复杂度")
    return Measurement(name=function.name, value=blocks[0].complexity)
