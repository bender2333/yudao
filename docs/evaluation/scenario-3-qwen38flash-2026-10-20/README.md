# 场景 3 · qhub/Qwen3.8-Flash · 2026-10-20

架构与需求诊断（[docs/research/architecture-diagnosis-2026-10-19.md](../../research/architecture-diagnosis-2026-10-19.md)第 2 节）的评测结果。`yudao.*` 与 `opencode.*` 由运行器的报告函数写出，读之前先看下面四条运行条件：

- Yudao 一侧由补跑脚本运行：新建项目时经 `project.create` 的 `initial_directory` 带入题目的 `subway_data.json`，事项文字去掉了运行器原文里请工程自己写出数据文件的一段（`evals/runner/yudao.py:93-97`），即 #324 的写法；运行器代码没有改。报告第七节的「起点」说明写的就是这一点。
- Yudao 的 3 次分属两个提交：start-1 的服务用 `909deda6`，start-2、start-3 用 `ffb099c7`（运行中途共用的工作区被切换）。报告里的「Yudao 提交号 `2959f3fd`」是运行器在全部结束时读到的，只对后两次成立；`ffb099c7` 到 `2959f3fd` 之间只有日记。
- OpenCode 一侧的补跑在复制与评分时多忽略了被测模型留下的 `nul` 文件；第 1 次用保存的输出补完评分，耗时是约值。第 3 次是重跑的 `oc-q38f-3b`（原来的第 3 次被 Claude Code 的内存回收结束）。
- 「被测模型」一栏的 `auto` 是模型服务在准入时报告的服务模型名，请求的模型是 `qhub/Qwen3.8-Flash`。

原始证据（事件日志导出、交付副本、评分日志）不进 Git，在 `C:\project\yudao-evals\s3-qwen38flash-20261019\evidence\`。
