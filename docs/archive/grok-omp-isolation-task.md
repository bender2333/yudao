# Grok 小步返修：OMP 上下文隔离

只完成本批后返回，由 Codex 验收、commit 和 push。不要操作暂存区或开始下一批。

## 范围

落实 `docs/grok-runtime-review-task.md` 第 4 项。该文档已给出发布版 OMP 18.1.11 的本地请求捕获结果、有效 overlay、明确 system prompt 组合与复现方式。不要重复研究已被否定的单独 `--no-rules` 或 `--system-prompt` 方案。

- Yudao 提供不可被交付文件覆盖的 OMP 启动配置和 system 提示；模型 provider 配置仍使用用户选择，不自动 fallback。
- 系统提示来源与装配清单可审计。明确 OMP 自身的环境/footer，不宣称只有 manifest 的字节。
- 将已有本地 canary 实验收敛为可重复的接入验证，并注册实际 Yudao host tools，证明过滤自动上下文后工具仍可用。使用本地 stub 和虚构凭据，不使用真实 provider。
- smoke 报告分别表达 manifest 边界和实际 OMP 策略验证依据，缺少验证时不得称隔离通过。

不修改检查副本/回执合同、有效 Ask/React 内容、usage 汇总、取消串行化或 lesson 候选。其他 Grok 可能正在处理这些模块。

## 交付

报告改动、相关测试与 canary 捕获证据。默认只修改 OMP adapter、其配置资源、`test_omp.py`、smoke 报告及对应测试/文档；需要跨出范围时先向 Codex说明依赖，不自行覆盖并行模块。不修改 OMP 源码，不修改 Web 文件。不输出凭据。
