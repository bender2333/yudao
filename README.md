# Yudao Loop System

面向自治系统研发者的三部门原生循环运行时。产品、工程、质检共同构成 Yudao 的 Agent loop：内核逐步装配上下文、调用模型、执行工具并决定部门交接。模型自然语言不能结束任务；只有绑定当前 ProductSpec 和代码快照的 QA release 才能进入 `DONE`。

OMP 仅作为底层实现的代码参考，不是运行依赖。旧 OMP 架构的运行证据与本次原生循环的验证分开记录，见 [MVP 验收记录](docs/mvp-acceptance.md)。

第一阶段正在按 [A-F 工作包](docs/stage-1-alignment.md) 推进。A 已实现原生循环、同部门跨激活历史、自动压缩、逐步输入审计和 Web 观察，完整回归为 187 项 Python、26 项 JavaScript 通过；修复后的真实 Ask 已完成独立 QA。真实压缩后的完整交付仍待补验，近期重测因 provider 连接失败停止。持续输入、PRD/计划、通用专家协作、prompt 编辑及完整封存尚在后续工作包，不能据此称第一阶段整体完成。

本机当前原生控制台为 [http://127.0.0.1:8766](http://127.0.0.1:8766)，使用 `.yudao/native-final-validation`；8765 的旧 OMP 服务不代表本次实现。

## 分层

```text
任务与观察层  本地 Web 控制台 / REST / SSE
三部门循环核  Orchestrator、逐步上下文装配、合同校验、循环次数与停止判定
基础能力层    单次 Responses 模型请求、宿主工具、工作区、事件与工件存储
```

Event Store 是唯一事实来源。Provider adapter 只做一次模型请求并返回输出，不执行工具、不管理部门历史、不决定循环。内核消费模型输出，调用工具或校验提交，再装配下一步输入。每一步的部门指令、当前合同、本部门历史与工具 schema 都保存为可核对摘要的工件。

## 启动

```bash
python -m pip install -e ".[dev]"
python -m harness demo --serve --port 8765
```

只跑样例：

```bash
python -m harness demo
python -m harness serve --adapter fake --data-dir .yudao/native-loop
```

重放：

```bash
python -m harness replay <run_id>
```

默认数据目录是 `.yudao/native-loop`。旧 OMP 数据目录保留为历史证据，与原生事件格式不兼容，不能交给新服务混用；本次不提供迁移或兼容层。

## 测试

```bash
python -m pytest harness/tests -q
node --test harness/tests/test_web_ui.js
```

真实主 provider 三部门 smoke（读取环境变量，不读取 `provider.md`，失败时不会改用 fake）：

```bash
python -m harness smoke --data-dir .yudao/native-validation
python -m harness smoke --scenario happy
python -m harness smoke --scenario ask
```

报告写在 `.yudao/native-validation/smoke-report.md`，包含 run id、路由、provider/model、宿主检查回执、结束原因、replay 一致性和逐步模型输入审计。每次只记录本次选择的场景，不继承上次报告中的验收结果。

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
| GET | `/api/runs/{id}/events/{event_id}` | 完整事件；上下文事件附实际模型输入 |
| GET | `/api/runs/{id}/stream` | SSE |
| GET | `/api/runs/{id}/export` | 导出事件与投影 |
| POST | `/api/runs/{id}/replay` | 校验投影可重放，不写状态 |
| POST | `/api/runs/{id}/cancel` | 取消当前 run |

## 模型配置

真实模型通过官方 OpenAI Python SDK 发送单次、无服务端会话续接的 Responses 请求。未配置时 Web 返回配置错误并拒绝创建任务；直接调用运行内核时，run 进入 `FAILED / provider_unavailable`。不自动重试或切换 provider。

需要 Python 3.11 或更新版本，`pip install -e ".[dev]"` 会安装 SDK。运行不需要 OMP、Bun、Node 或 OMP profile；Node 仅用于前端自动化测试。

PowerShell 配置示例。密钥通过当前终端环境注入，应用不读取 `provider.md`：

```powershell
$env:YUDAO_MODEL_API_KEY = '<your-api-key>'
$env:YUDAO_MODEL_NAME = '<model-name>'
$env:YUDAO_MODEL_BASE_URL = 'https://api.openai.com/v1'
$env:YUDAO_MODEL_PROVIDER = 'openai'
$env:YUDAO_MODEL_TIMEOUT_SEC = '600'
python -m harness serve --adapter responses --data-dir .yudao/native-loop --port 8766
```

`YUDAO_MODEL_API_KEY` 与 `YUDAO_MODEL_NAME` 必填；其余配置的默认值与示例相同。兼容 Responses 协议的服务可以修改 `YUDAO_MODEL_BASE_URL` 和 provider 标识。

工具由 Yudao 内核执行（`read_file` / `write_file` / `run_check` / `collect_evidence` / `submit_*`）。Product/Quality 没有写工具。检查在可丢弃的普通文件副本执行，由主机签发绑定当前合同、交付和激活的回执；模型自报 `exit_code` 不是证据。该副本机制不提供操作系统沙箱。

部门指令作为显式 developer 输入发送；原始任务逐字保留，本部门完整历史跨激活延续，部门交接时重新装配当前合同，不携带其它部门的私有历史。接近窗口上限时自动压缩部门历史视图，保留摘要来源、原始事件与近期完整工具回合；摘要调用同样可取消并计入模型步数。上下文视图可按步骤打开实际输入、摘要及原始来源。调用尝试事件表示内核已开始调用 provider，不承诺网络请求已经送达。SDK 返回的用量仅作只读记录，不估算、不用于暂停任务；未上报用量或费用显示为“未上报”。

## 停止与后续范围

只有独立质检 release 才能进入 `DONE`。达到部门激活次数或单次激活模型步数上限进入 `PAUSED`；取消、provider 超时或错误、上下文溢出、压缩失败进入 `FAILED`。当前只使用循环次数、模型步数和单次请求超时限制执行，不设置 token 预算。固定原文与当前工作无法容纳时明确停止，不静默截断或无限压缩。停止后仍可查看、导出和重放事件，迟到结果不能继续提交。

当前不提供暂停任务的继续执行，也不自动复用经验、修改规则或模型。知识图谱、长期记忆、异步恢复及新增部门属于后续阶段，见 [总体路线图](docs/program-roadmap.md)。

经验候选仅来自已接受的质检返工或非取消失败，可在证据视图查看来源、导出和重放。候选保持待验证，不自动注入部门上下文。
