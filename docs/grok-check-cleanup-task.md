# Grok 小步修复：检查副本异常清理

只修本批并运行相关测试后立即返回，由 Codex 独立验收及统一 commit/push。禁止操作暂存区，保留同工作区并行修改。

## 已复现问题

`ToolRuntime._execute_check` 先创建副本，再在 try/finally 外调用 `_resolve_argv`。命令不存在时解析抛错，副本不会清理。独立验收用 mock 让解析抛 FileNotFoundError，工具正确返回拒绝，但 `shutil.rmtree` 没有被调用。真实使用中每次误写检查命令都会留下整个副本。

## 本批要求

- 从副本创建、材料复制、命令解析到执行的任意失败路径，都可靠释放本次临时副本。
- 优先使用 Python 标准库的临时目录生命周期能力；不添加新的配置或运行时层。
- 保持现有回执绑定和原工作区不被检查后还原的行为。
- 用针对性的失败注入测试验证命令不存在、复制中失败、正常成功/检查失败之后均无临时目录残留；不写仅复刻内部调用顺序的测试。

只允许修改 `harness/tools.py`、`harness/workspace.py`、`harness/tests/test_tools.py`。另两个 Grok 正在处理 OMP adapter 与产品合同上下文，不修改他们的文件。只运行相关检查测试，不调用真实 provider。若遇并行测试短暂失败，报告事实，不覆盖其他模块。

## 首轮独立复核后的两项修正

首轮 15 项工具测试已通过，只完成下列两项后立即返回：

1. 项目要求 Python >= 3.11，无需 `_check_tempdir` 的 TypeError 兼容 fallback；删除多层 cleanup/rmtree 兜底，直接用标准 `TemporaryDirectory` 上下文管理生命周期。清理失败须明确可见，不能通过 `ignore_errors` 静默报告成功。用户明确禁止兼容层。
2. 三个清理测试目前扫描系统临时目录下全部 `yudao-check-*`，会与并行测试或真实运行相互干扰。每个测试将副本目录限定在自己的 `tmp_path` 中，验证实际残留行为。不要依赖整个系统临时目录在测试期间不变。
