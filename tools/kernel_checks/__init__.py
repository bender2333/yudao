"""内核的代码质量检查（docs/design/kernel-quality-gate.md「接口」「方案」4.1 至 4.3、4.8）。

用法（在仓库根运行）：

    uv run python -m tools.kernel_checks check                 # 当前提交相对 origin/main 的合并基点
    uv run python -m tools.kernel_checks check --base <引用>   # 换一个合并基点所取的引用
    uv run python -m tools.kernel_checks check --report <文件> # 把 JSON 报告写到这个文件，目录不存在就建
    uv run python -m tools.kernel_checks check --ignore-switches  # 忽略清单里的开关，检查全部内核模块

检查三样东西：相对合并基点的改动（按语法树找内容有变的语句与改到的函数）、改到的函数用 radon
量的圈复杂度（超过 10 不通过）、理由登记的格式（harness/tests/kernel/mutation_reasons.json）。
只看内核清单（harness/definitions/kernel-manifest.json）里复杂度开关已打开的内核模块；
--ignore-switches 时对全部内核模块检查。给人看的文字写到标准输出（按 UTF-8），一份 JSON 报告
按 --report 写盘。退出码：0 通过，1 不通过，2 工具自己出错；工具出错不算通过。

这个包的测试在 tools/kernel_checks/tests/，用 `uv run python -m pytest tools/kernel_checks/tests` 运行。
工具不导入 harness/ 里的代码，只读文件、起进程：被评价的代码不能影响评价它的工具。
"""
