# Yudao Loop System

面向自治系统研发者的三部门循环运行时。产品、工程、质检使用隔离会话，只通过结构化 spec 交接。模型自然语言不能结束任务；只有绑定当前 ProductSpec 和代码快照的 QA release 才能进入 `DONE`。

当前已有真实 provider 的直达与 Ask → React 成功样例。运行时独立审查仍在返修，完整验收状态见 [MVP 验收记录](docs/mvp-acceptance.md)。

## 分层

```text
可视化层  本地 Web 控制台 / REST / SSE（查询只读；创建与取消走控制层）
控制层    Orchestrator、状态机、校验、预算与停止判定
状态层    SQLite Event Store、文件 Artifact Store、投影与 replay
会话层    ContextAssembler、部门 Session、Fake / OMP adapter
执行层    工具白名单与工作区
```

Event Store 是唯一事实来源。Adapter 只能提交结构化提案；状态迁移函数内不调用 LLM。

## 启动

```bash
pip install pytest
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

通过环境变量注入，不要把凭据写进仓库：

```bash
set YUDAO_OMP_ENABLED=1
set YUDAO_OMP_COMMAND=<bun-or-omp>
set YUDAO_OMP_ARGS=<cli.js --mode rpc --no-extensions --no-skills --no-rules --no-session>
set YUDAO_OMP_PROVIDER=blackrouter
set YUDAO_OMP_MODEL=gpt-5.6-terra
```

Adapter 会禁用 OMP 内建工具、LSP 和持久会话，改用 Yudao host tools（`read_file` / `write_file` / `run_check` / `collect_evidence` / `submit_*`）。检查由主机执行并写入 `.checks` 回执；模型自报 `exit_code` 不是证据。Product/Quality 没有写工具。确定性端到端请使用 fake：

```bash
python -m harness demo --serve
```
