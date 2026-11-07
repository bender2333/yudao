"""内核的代码质量检查（docs/design/kernel-quality-gate.md「接口」「接入：按模块，两个开关」「改到的语句与函数」「复杂度检查」「变异检查」「存活的出口与理由登记」「全量模式与「立住」」「评价材料」）。

用法（在仓库根运行）：

    uv run python -m tools.kernel_checks check                 # 当前提交相对 origin/main 的合并基点
    uv run python -m tools.kernel_checks check --base <引用>   # 换一个合并基点所取的引用
    uv run python -m tools.kernel_checks check --report <文件> # 把 JSON 报告写到这个文件，目录不存在就建
    uv run python -m tools.kernel_checks check --ignore-switches  # 忽略复杂度开关，检查全部内核模块的复杂度
    uv run python -m tools.kernel_checks check --module <路径> --mutation-mode full  # 对任意内核模块跑全量

检查四样东西：相对合并基点的改动（按语法树找内容有变的语句与改到的函数）、改到的函数用 radon
量的圈复杂度（超过 10 不通过）、清单里变异开关已打开且改到的模块的变异（在没有变异的副本里跑
内核测试取覆盖与耗时，用 poodle 生成变异、筛掉没改到的语句与只给人看的文字，两层判定，
存活先查理由登记），以及理由登记的格式（harness/tests/kernel/mutation_reasons.json）。
只看内核清单（harness/definitions/kernel-manifest.json）里开关已打开的内核模块；
--ignore-switches 时对全部内核模块检查复杂度，--module 只检查指定的模块（复杂度与变异都检查）。
给人看的文字写到标准输出（按 UTF-8），一份 JSON 报告按 --report 写盘。退出码：0 通过，
1 不通过，2 工具自己出错；工具出错不算通过。

这个包的测试在 tools/kernel_checks/tests/，用 `uv run python -m pytest tools/kernel_checks/tests` 运行。
工具不导入 harness/ 里的代码，只读文件、起进程：被评价的代码不能影响评价它的工具。
"""
