# Grok 隔离批验收返修

当前会话的实际隔离能力已独立通过，但审计与 provider 保留仍需修正。本批完成后返回，不提交、不碰暂存区。

## 独立验证已通过

`python .tmp/omp_isolation_acceptance_probe.py` 使用发布版 OMP 18.1.11、虚构密钥和本地 Responses stub，调用实际 Yudao adapter。

- 两次模型请求，真实 `read_file` 成功且结果进入第二次请求。
- workspace、profile、用户 Codex、用户 Claude、项目 `.omp/AGENTS.md` 的五类 canary 均未注入。
- workspace `.omp/config.yml` 尝试重开发现也未生效。
- 当前 test_omp/test_smoke 独立执行通过。

## 需要修复的具体问题

1. `smoke.isolation_fields` 仅凭当下 `describe_launch_policy()` 和全局捕获文件中的静态 `policy_id`，给任意有 manifest 的 run 标记 `context_isolated=True`。一个从未启动 OMP 的历史 run，只要后来有人跑一次 canary，也会突然被称已隔离。这不是该 run 的实际证据。
2. `IsolationFiles.prompt_sources` 虽生成，adapter 没有交给控制层持久化，清理临时目录后没有实际启动来源记录。必须让宿主产生的来源与策略记录绑定 run/session/activation/context digest，并在启动失败时仍保留已经发生的诊断。不能让模型或提案声称隔离通过。
3. 捕获文件只检查静态名称与 verified 字段，未绑定被测 OMP 可执行入口/版本或内容、overlay 内容与实际策略。改变实际 runtime 或 overlay 后旧证据不能继续标记验证通过；输入错误、旧格式、未知实际 launch、canary 阳性、缺 host tools 往返等均需 unverified。保持方案简单，不另造平台。若表达的是接入策略验证，明确写出该语义，不能冒充该生产请求正文已被捕获。
4. 当前独立 profile 只复制 models 配置，会丢失用户 profile 的正常认证（OMP 默认从 agent.db 解析认证）与显式 profile 选择。这是 provider 兼容性退化。已证实 `disabledProviders` + 宿主 system prompt 可以阻断原 profile 的 AGENTS 注入，因此采用保留用户明确选定原 profile 与认证的方案，以宿主 overlay 和隔离参数控制上下文发现。不要再写认证复制层、不要读出凭据，仍每次独立 OMP 进程和无 session。用本地 canary 再验证 profile AGENTS 未注入。对于会改变发现/提示来源的命令和环境参数，需要核对实际优先级或明确拒绝不可验证组合，不能悄悄接受后称已验证。
5. 把机器特定的 PUBLISHED_BUN/PUBLISHED_OMP 路径从生产模块移走。接入测试可通过显式环境变量指定实际可执行入口；缺少时清晰 skip，不绑定某个用户的 npm cache。删除不再需要的 profile 复制等死代码。
6. 接入测试的 host result 断言不能以最终 transcript 替代第二次请求中的真实工具返回。必须证明至少第二次请求带宿主结果，且所有已捕获请求均无 canary。

## 实现范围

主协调 Codex 已确认当前没有其他会话修改用量/取消批，允许极小改动 `harness/adapters/base.py` 和 `harness/orchestrator.py`，把宿主启动诊断持久化。这两处仅做这一连接，不展开 usage、取消、提案或循环状态逻辑。事件类型可用已有事件载荷承载独立诊断，不能伪装成模型工具调用，不必为了增加常量越界修改并行的 models.py。

其余范围保持本批文件：OMP adapter/isolation 资源，smoke、test_omp/test_smoke、隔离文档与必要打包资源。不修改 context.py/models.py/projection.py/validation.py/tools.py/workspace.py/Web/jour.md，不修改 OMP 源码，不读 provider.md，不操作 Git 暂存区。

## 验收

- 没有真实启动诊断的历史 run，即使有全局 probe 证据仍 unverified。
- 实际启动记录和 probe 的 runtime/overlay/策略不匹配时 unverified。
- 正确绑定的实际启动可审计；装配清单与接入捕获证明仍各自表达。
- 启动失败已产生的宿主诊断不丢失。
- profile 认证配置不被临时空 profile 替换；保留 profile 的真实本地 OMP + host-tools canary 通过。
- 缺失、无效、失败的证据均不造成 isolation true。
- 不增加永久请求正文或凭据存储，不输出真实凭据，不进行真实 provider 请求。
