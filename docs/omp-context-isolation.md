# OMP 上下文隔离

Yudao 自己提供 OMP 启动 overlay 和 system prompt，不从交付目录读取这两个参数。模型 provider / model 仍用用户选择的值，不会因为隔离配置而改用别的 provider。

## 实际启动策略

已用发布版 OMP 18.1.11 和本地 Responses stub 验证的组合：

1. 宿主 `--config` overlay 禁用全部九个 context-files discovery provider，并关闭工作区树。
2. 宿主 `--system-prompt` 写入当前部门装配后的上下文。
3. 继续使用 `--no-tools --no-lsp --no-session --no-extensions --no-skills --no-rules --no-title`。
4. 每次激活启动独立进程并关闭 session 持久化；保留用户选定的 profile、模型配置和认证，由禁用发现源的 overlay 阻止 profile 上下文自动注入。

overlay 内容见 `harness/adapters/omp_isolation.yml`。单独 `--no-rules` 或单独 `--system-prompt` 不能阻止工作目录 / profile 的 `AGENTS.md` 注入，不要再使用那两条被否定的路径。

## 系统提示来源

实际发给模型的 system 提示不是部门 manifest 的字节拷贝。来源清单是：

- Yudao 宿主 system prompt：当前激活的装配上下文（部门规则、合同、绑定引用等）。
- 宿主 overlay：禁用自动上下文发现。
- OMP 自己追加的 environment / footer（`project-prompt` 中的 workstation 与 critical 段）。

因此不能宣称“只有 manifest 的字节”。装配清单仍记录 injected / excluded；那只是 Yudao 侧边界，不是 OMP 最终请求的证明。

adapter 产生宿主启动诊断，由控制层关联到 run、session、activation 和 context digest 后写入事件。诊断保留实际 runtime 文件指纹、启动参数指纹、overlay 指纹和系统提示来源清单；临时提示文件清理后仍可查询其摘要。进程启动后即使 ready、协议协商或工具注册失败，已产生的诊断仍持久化。这里不保存模型请求正文或认证内容。

## 接入验证

可重复验证是 `harness/tests/test_omp.py::test_omp_isolation_policy_registers_host_tools_and_filters_context`。

通过 `YUDAO_OMP_TEST_BUN` 与 `YUDAO_OMP_TEST_CLI` 显式指定要验收的 Bun 可执行文件和发布版 OMP `dist/cli.js`，然后运行上述 pytest 用例。缺少有效路径时明确跳过，不提供默认的机器专用路径。测试连接 `127.0.0.1` 随机端口 stub 和虚构密钥，不读 `provider.md`。验证内容：

- 工作区、用户目录、profile 中的 canary 字符串不出现在捕获请求里。
- 宿主 system prompt 在 system 中，OMP footer 也在。
- 通过 RPC `set_host_tools` 注册实际 Yudao host tools 后，`read_file` 仍可执行。
- 宿主读取结果确实进入第二次模型请求；两次请求均不包含 canary。
- 原 profile `.env` 中的虚构认证仍有效；交付目录和 `PI_CONFIG_FILES` 中尝试恢复自动发现的配置不能覆盖宿主 overlay。

通过后写入 `.tmp/omp_isolation_capture.json`，含验证布尔值、字节统计和 runtime、启动参数、overlay 指纹，不含请求正文或凭据。smoke 报告读取该文件作为本地接入策略验证依据，不表示某次生产请求正文已经被捕获。

## smoke 报告口径

报告分三项，不能互相推导：

| 字段 | 含义 |
| --- | --- |
| `manifest_boundary` | 装配事件是否排除跨部门 transcript 并注入合同 |
| `omp_launch_policy` | 实际使用的 overlay / flags / 宿主 system prompt 策略 |
| `omp_policy_capture` | 该策略是否已有本地请求捕获证据 |

`context_isolated` 要求装配边界成立，每次装配都有唯一且匹配的宿主启动诊断，且实际 runtime、启动参数和 overlay 与通过的本地捕获证据一致。历史任务缺诊断、未知 runtime、无效或过期格式的证据、canary 阳性、缺少工具往返，以及指纹不匹配，均保持 `unverified`。

这是已验收接入策略在本次任务中的应用记录，不是普遍的上下文安全保证。当前报告使用 `access_policy_verification` 标明这一语义。provider 的业务调用成功或失败仍由 `phase` / `stop_reason` 单独表达。
