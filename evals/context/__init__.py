# 上下文装配的离线回放工具（#912）。
#
# 只读事件库与工件库，不导入 harness，不调用模型：同一条命令在别人的数据目录上
# 重跑出同样的表（`python -m evals.context measure --db <events.sqlite>`）。
# 本包是设计说明 docs/design/context-assembly.md 的测量与证明工具，不是内核的一部分。
