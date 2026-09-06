# Yudao Loop System

面向自治系统研发者的三部门循环运行时。产品、工程、质检使用隔离会话，只通过结构化 spec 交接。模型自然语言不能结束任务；只有绑定当前 ProductSpec 和代码快照的 QA release 才能进入 `DONE`。

三部门循环 MVP 已通过真实 provider 的直达、Ask → React 及浏览器取消验收。完整 Python 测试 135 项、前端测试 23 项通过，证据与边界见 [MVP 验收记录](docs/mvp-acceptance.md)。

## 分层

```text
可视化层  本地 Web 控制台 / REST / SSE（查询只读；创建与取消走控制层）
控制层    Orchestrator、状态机、校验、预算与停止判定
状态层    SQLite Event Store、文件 Artifact Store、投影与 replay
会话层    ContextAssembler、部门 Session、Fake / OMP adapter
执行层    工具白名单与工作区
```

Event Store 是唯一事实来源。Adapter 上报结构化提案与执行观察，由控制层校验并记录；状态迁移函数内不调用 LLM。

## 启动

```bash
python -m pip install -e ".[dev]"
python -m harness demo --serve --port 8765
```

只跑样例：

```bash
python -m harness demo
python -m harness serve --adapter fake --data-dir .yudao/loop
```

重放：

```bash
python -m harness replay <run_id>
```

默认数据目录是 `.yudao/loop`。

## 测试

```bash
python -m pytest harness/tests -q
node --test harness/tests/test_web_ui.js
```

真实主 provider 三部门 smoke（读取环境变量，不读取 `provider.md`，失败时不会改用 fake）：

```bash
python -m harness smoke --data-dir .yudao/provider-validation
python -m harness smoke --scenario happy
python -m harness smoke --scenario ask
```

报告写在 `.yudao/provider-validation/smoke-report.md`，包含 run id、路由、provider/model、主机检查回执、结束原因、replay 一致性和上下文隔离。

## HTTP 接口

查询接口只读。创建 run 和取消走控制层，界面不能直接改 spec、投影或完成状态。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 控制台：运行看板、规格时间线、证据、上下文/追踪 |
| GET | `/api/health` | 健康检查与 adapter 可用性 |
| GET | `/api/runs` | run 列表 |
| POST | `/api/runs` | 创建任务并由控制层执行 |
| GET | `/api/runs/{id}` | 四个视图的聚合 |
| GET | `/api/runs/{id}/events` | 事件卡片 |
| GET | `/api/runs/{id}/events/{event_id}` | 完整事件 |
| GET | `/api/runs/{id}/stream` | SSE |
| GET | `/api/runs/{id}/export` | 导出事件与投影 |
| POST | `/api/runs/{id}/replay` | 校验投影可重放，不写状态 |
| POST | `/api/runs/{id}/cancel` | 取消当前 run |

## OMP 配置前提

真实 LLM 走 `oh-my-pi` RPC/NDJSON。**未配置时不会改用 fake**。Web 返回配置错误并拒绝创建任务；直接调用运行内核时，run 进入 `FAILED / provider_unavailable`。

需要 Python 3.11 或更新版本，以及可运行的 OMP。当前接入已用 Bun 和发布版 OMP 18.1.11 验证；源码目录缺少 native addon 时不能直接代替发布包。

PowerShell 配置示例，路径指向本机安装位置。`PI_CODING_AGENT_DIR` 使用已有模型与认证配置的 profile：

```powershell
$env:PI_CODING_AGENT_DIR = 'C:/path/to/omp-profile/agent'
$env:YUDAO_OMP_ENABLED = '1'
$env:YUDAO_OMP_COMMAND = 'C:/path/to/bun.exe'
$env:YUDAO_OMP_ARGS = 'C:/path/to/pi-coding-agent/dist/cli.js --mode rpc'
$env:YUDAO_OMP_PROVIDER = 'blackrouter'
$env:YUDAO_OMP_MODEL = 'gpt-5.6-terra'
$env:YUDAO_OMP_TIMEOUT = '600'
python -m harness serve --adapter omp --data-dir .yudao/loop --port 8765
```

该 profile 的 `models.yml` 可以使用环境变量名引用密钥，实际值通过环境注入，不进入仓库：

```yaml
providers:
  blackrouter:
    baseUrl: https://blackrouter.top/v1
    api: openai-responses
    apiKey: BLACKROUTER_API_KEY
    models:
      - id: gpt-5.6-terra
        name: Blackrouter Terra
        contextWindow: 200000
        maxTokens: 4096
```

启动前确保同一终端中的 `BLACKROUTER_API_KEY` 已设置。应用不会读取 `provider.md`，不会自动切换备用 provider。

Adapter 会禁用 OMP 内建工具、LSP 和持久会话，改用 Yudao host tools（`read_file` / `write_file` / `run_check` / `collect_evidence` / `submit_*`）。Product/Quality 没有写工具。检查在可丢弃的普通文件副本执行，由主机签发绑定当前合同、交付和激活的回执；模型自报 `exit_code` 不是证据。该副本机制不提供操作系统沙箱。

上下文隔离的来源与验收方式见 [OMP 上下文隔离](docs/omp-context-isolation.md)。完整模型消息、工具输出与上报用量会在激活期间持久化；用量统计覆盖可观测主对话，缺少上报时明确使用估算。

## 停止与后续范围

只有独立质检 release 才能进入 `DONE`。达到循环或 token 上限进入 `PAUSED`；取消、provider 错误或上下文溢出进入 `FAILED`。停止后仍可查看、导出和重放事件，迟到结果不能继续提交。

首版不提供暂停任务的继续执行，也不自动复用经验、修改规则或模型。知识图谱、长期记忆、异步恢复、部门内部循环及运维部门属于后续阶段，见 [总体路线图](docs/program-roadmap.md)。

经验候选仅来自已接受的质检返工或非取消失败，可在证据视图查看来源、导出和重放。候选保持待验证，不自动注入部门上下文。
