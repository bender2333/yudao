# Yudao Loop System

面向自治系统研发者的三部门原生循环运行时。产品、工程、质检共同构成 Yudao 的 Agent loop：内核逐步装配上下文、调用模型、执行工具并决定部门交接。模型自然语言不能结束任务；只有绑定当前有效合同、计划、交付和完整代码树的 QA release 才能进入 `DONE`。

## 当前状态

- **Stage 1（可信交付）**: ✅ 已完成。三部门循环、压缩、Git 版本、重试、完整封存已验收通过。
- **Stage 2（三部门 Harness 基线）**: 2.1–2.6 按 2026-09-15 合同关闭；**2.7 统一 Provider 层、无配置启动与 OpenCode Go 接入**已实现并通过本地回归，真实 Go 覆盖 Responses 与 Chat Completions 两个协议并各自完成三部门任务（Anthropic Messages 对当前两个模型受区域与端点限制）。历史十场为 9 次完成、1 次计划取消，不外推复杂任务成功率。
- **Stage 3（通用工具、可靠恢复与并行）**: 设计中。当前版本基线 → 本地通用工具 → 单机恢复 → 恢复验收通过后隔离并行。
- **持续改进工作线 / Stage 7 系统演化**: 后续。已有离线分析与经验候选，尚无经验验证、采用、失效的完整学习闭环。

当前入口：[总体路线图](docs/program-roadmap.md)、[Stage 2.7 计划](docs/archive/stage-2-provider-plan.md)、[Provider 设计说明与交互图](docs/design/provider-layer.md)。后续见 [当前验收基线](docs/current-baseline.md) 与 [Stage 3 计划](docs/stage-3-plan.md)。历史证据见 [验收记录](docs/archive/mvp-acceptance.md) 与 [Stage 2 进度](docs/archive/stage-2-progress.md)。

## 分层

```text
任务与观察层  本地 Web 控制台 / REST / SSE
三部门循环核  Orchestrator、逐步上下文装配、合同校验、循环次数与停止判定
基础能力层    单次 Responses 模型请求、宿主工具、工作区、事件、工件与 Git 版本存储
```

Event Store 是唯一事实来源。Provider adapter 只做一次模型请求并返回输出，不执行工具、不管理部门历史、不决定循环。内核消费模型输出，调用工具或校验提交，再装配下一步输入。每一步的部门指令、当前合同、本部门历史与工具 schema 都保存为可核对摘要的工件。

## 快速开始

### 前置要求

- Python 3.11 或更新版本
- uv（建立与使用项目环境）
- Git CLI（可从 `PATH` 调用）
- 模型 API 密钥（如 OpenAI、Anthropic 或兼容服务）

### 安装

按锁文件 `uv.lock` 在仓库内建立项目环境（`.venv`，包含测试依赖）：

```bash
uv sync --frozen
```

之后的命令用 `uv run` 在项目环境中运行，例如 `uv run python -m harness`。

### 配置 Provider

无配置也能启动控制台：`python -m harness` 直接使用默认路径，配置缺失时进入空态，可以在页面里逐项完成接入。非敏感配置写在 `.yudao/providers.json`；凭据默认只在进程内存中有效，需要跨重启时写入 `.yudao/.env`。

```json
{
  "providers": [
    {
      "id": "opencode-go",
      "name": "OpenCode Go",
      "base_url": "https://opencode.ai/zen/go/v1",
      "credential_ref": "YUDAO_OPENCODE_GO_KEY",
      "timeout_sec": 600,
      "preset_id": "opencode-go",
      "models_url": "https://opencode.ai/zen/go/v1/models"
    }
  ],
  "models": [
    {
      "id": "go-glm-chat",
      "provider_id": "opencode-go",
      "model": "glm-5.1",
      "protocol": "chat_completions",
      "context_window": 128000,
      "max_output_tokens": 8192,
      "capability_source": "预置提示：官方端点示例"
    }
  ],
  "bindings": {
    "product": { "provider_id": "opencode-go", "model_id": "go-glm-chat" },
    "engineering": { "provider_id": "opencode-go", "model_id": "go-glm-chat" },
    "quality": { "provider_id": "opencode-go", "model_id": "go-glm-chat" }
  }
}
```

协议在模型访问定义上声明，一条定义只走一条协议（`responses` / `chat_completions` / `messages`），需要多协议时在同一模型上建多条定义。`preset_id` 与 `models_url` 可省略，省略时使用服务方案默认值。参考 [Provider 配置示例](docs/examples/providers.json)。

凭据来源优先级为进程内存覆盖 > 进程环境变量 > `.yudao/.env`。页面填写 Key 默认只对本进程有效，勾选持久化才写入 `.env`；已保存的 Key 不回填，也不进入日志、事件与导出。

服务方案（OpenCode Go 是第一个预置方案）自带端点、认证方式与模型列表地址；模型列表只产生候选，候选要建立访问定义并执行一次模型测试通过（准入）后才能绑定到部门。

### 启动服务

```bash
# 等价于 python -m harness serve，默认 data-dir .yudao/native-loop、provider-config .yudao/providers.json、端口 8765
python -m harness
```

访问 [http://localhost:8765](http://localhost:8765) 打开 Web 控制台。

界面保存、磁盘修改（约 1 秒轮询，按内容哈希核对）与手动重载都对新建事项生效；已创建事项继续使用创建时冻结的模型、协议与凭据。

桌面客户端使用的应用接口（命令、查询、能力清单与 OpenAPI，见[应用层与接口层设计说明](docs/design/app-and-interface.md)）单独启动，参数与 `serve` 相同：

```bash
python -m harness api --data-dir .yudao/native-loop --port 8765
```

同一个数据目录只允许一个服务进程：`api` 与 `serve`（含 `demo --serve`）启动时取得数据目录的进程锁，另一个服务进程正在使用这个数据目录时以非零状态退出。

### 运行演示（无需 API 密钥）

```bash
python -m harness demo --serve --port 8765
```

### 重放历史任务

```bash
python -m harness replay <run_id>
```

默认数据目录是 `.yudao/native-loop`。

## 测试

Python 测试在项目环境中运行：

```bash
uv run python -m pytest harness/tests -q
node --test harness/tests/test_web_ui.js
```

应用接口的 OpenAPI 快照（`harness/tests/openapi/openapi.json`）由 `test_openapi_snapshot.py` 与运行中的服务比较；由快照生成 TypeScript 接口类型并编译：

```bash
cd harness/tests/openapi && npm ci && npm run check
```

按目录绑定执行三部门真实 smoke（凭据引用从环境解析，应用不读取 `provider.md`）：

```bash
python -m harness smoke --provider-config .yudao/providers.json --data-dir .yudao/native-validation
python -m harness smoke --provider-config .yudao/providers.json --scenario happy
python -m harness smoke --provider-config .yudao/providers.json --scenario collaboration
```

报告写在 `.yudao/native-validation/smoke-report.md`，包含 run id、路由、provider/model、宿主检查回执、结束原因、replay 一致性、Git 版本及逐步模型输入审计。Git 审计缺失或未通过时不能返回验收成功。每次只记录本次选择的场景，不继承上次报告中的验收结果。

## 如何使用

### 1. 创建项目与任务

通过 Web 界面：
1. 访问控制台首页
2. 点击"新建项目"，输入项目名称
3. 在项目中点击"作为新事项开始"
4. 输入需求描述，例如："创建一个 Python 脚本，从 CSV 读取数据并输出统计信息"

通过 API：

```bash
# 创建项目
curl -X POST http://localhost:8765/api/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "我的项目"}'

# 创建任务
curl -X POST http://localhost:8765/api/projects/{project_id}/work-items \
  -H "Content-Type: application/json" \
  -d '{"intent": "创建一个 hello world 脚本"}'
```

### 2. 观察三部门协作

任务会经过三个部门：

- **产品部 (Product)**: 理解需求，形成有效 PRD
- **工程部 (Engineering)**: 制定计划，实现代码
- **质检部 (Quality)**: 独立验证，放行交付

在 Web 界面可以：
- **总览页**: 查看部门流转和交接状态
- **部门页**: 查看各部门的工作消息和历史
- **观测页**: 查看模型请求、用量统计、Context/Trace

### 3. 追加需求与调整方向

任务运行中可以追加输入：

```bash
# 全局输入（交给产品处理）
curl -X POST http://localhost:8765/api/runs/{run_id}/inputs \
  -H "Content-Type: application/json" \
  -d '{"text": "需要支持 UTF-8 编码"}'

# 部门定向指导（直接给工程/质检）
curl -X POST http://localhost:8765/api/runs/{run_id}/departments/engineering/guidance \
  -H "Content-Type: application/json" \
  -d '{"text": "使用 pandas 库处理 CSV"}'
```

Web 界面：
- 总览页底部输入框：全局追加
- 部门页指导区：定向指导

### 4. 查看失败原因

如果任务失败或暂停：
1. 进入**观测页** → **请求列表**
2. 筛选失败状态
3. 点击失败请求查看详情：
   - **Context**: 查看失败时的上下文快照
   - **Trace**: 查看错误分类和重试历史
   - **Response**: 查看部分输出（如有）

### 5. 取消任务

```bash
curl -X POST http://localhost:8765/api/runs/{run_id}/cancel
```

或在 Web 界面点击"取消"按钮。

### 6. 下载交付物

任务完成后：

```bash
# 导出事件与投影
curl http://localhost:8765/api/runs/{run_id}/export > run.json

# 下载交付文件
curl "http://localhost:8765/api/runs/{run_id}/events/{event_id}/files?path=output.csv" > output.csv
```

Web 界面可在事项详情页查看完整交付清单和 Git 差异。

### 7. 编辑部门 Prompt

```bash
curl -X POST http://localhost:8765/api/runs/{run_id}/prompts/engineering \
  -H "Content-Type: application/json" \
  -d '{"text": "你是资深 Python 工程师，优先使用标准库..."}'
```

Prompt 在下次该部门激活时生效，当前激活不受影响。

## HTTP 接口

`python -m harness api` 提供的应用接口：`POST /api/commands/{名称}`（命令带 `command_id`，接受返回位置，拒绝返回 409 与原因）、`GET /api/queries/{名称}`（快照与位置）、`GET /api/capabilities`（能力清单）、`GET /openapi.json`；已登记的命令与查询以能力清单为准。

下表是旧 Web 控制台（`python -m harness serve`）的接口，冻结，桌面客户端完成以后删除。查询接口只读。创建 run 和取消走控制层，界面不能直接改 spec、投影或完成状态。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 控制台：项目列表、看板、部门视图、观测 |
| GET | `/api/health` | 健康检查与 Provider 可用性 |
| GET | `/api/projects` | 项目列表 |
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects/{id}` | 项目详情 |
| POST | `/api/projects/{id}/work-items` | 创建任务 |
| GET | `/api/projects/{id}/stream` | 项目级 SSE |
| GET | `/api/runs/{id}` | 任务详情 |
| GET | `/api/runs/{id}/events` | 事件列表 |
| GET | `/api/runs/{id}/events/{event_id}` | 事件详情（含 Git diff） |
| GET | `/api/runs/{id}/events/{event_id}/files?path=...` | 下载交付文件 |
| GET | `/api/runs/{id}/stream` | 任务级 SSE |
| GET | `/api/runs/{id}/export` | 导出事件与投影 |
| POST | `/api/runs/{id}/replay` | 校验可重放性 |
| POST | `/api/runs/{id}/cancel` | 取消任务 |
| POST | `/api/runs/{id}/inputs` | 追加全局输入 |
| POST | `/api/runs/{id}/departments/{dept}/guidance` | 部门定向指导 |
| POST | `/api/runs/{id}/prompts/{department}` | 修改部门 prompt |
| GET | `/api/runs/{id}/departments/{dept}` | 部门视图 |
| GET | `/api/runs/{id}/model-attempts` | 模型请求列表 |
| GET | `/api/runs/{id}/model-attempts/{id}` | 请求详情（Context/Trace） |

## 任务内 Git 版本

原文、需求/spec 与 PRD、计划与 PLAN、交付代码和公开验收记录在正式接纳时形成 Git 提交。新需求引起的 spec 变化可以在 Web 对应事件详情中查看提交、父提交及真实 diff。查询核验当前和父版本与正式材料一致，缺失或篡改会明确报错。

每个任务的仓库保存在 `<data-dir>/git/<run_id>.git`，由主机调用 Git CLI 管理。事件决定哪些版本已经接纳；`refs/snapshots/` 仅保留不可变对象。新输入或需求提交保留上次正式交付代码，工作目录中的修改到交付接纳时才进入代码版本。部门私有历史与 Git 元数据不进入公开交付或跨部门上下文。

Git 与完整交付封存使用同一次采集的文件字节，空目录和独立恢复继续由封存保证。第一阶段提供任务内版本与差异，不提供任意 Git 命令、历史 reset、跨任务合并、项目导入或远程推送配置；详见单独记录的 [D16](docs/requirements/git-change-management.md)。

## 模型配置

模型接入由独立的 Provider 模块承担（`harness/providers/`），三部门循环、Web、CLI 与 smoke 都经同一接口调用，不各自直连 SDK。Provider 配置、模型访问定义与部门绑定统一管理，产品、工程、质检分别绑定，允许共享或使用不同服务。创建任务前验证三部门绑定、凭据与模型准入；缺失配置明确拒绝创建。原生内核对连接中断、超时、限流和临时服务错误进行有界重试，不切换 Provider，详见 [D17](docs/requirements/provider-retries.md)、[D18](docs/requirements/department-providers.md)、[D23](docs/requirements/provider-layer.md)。

需要 Python 3.11 或更新版本，`uv sync --frozen` 按锁文件安装 SDK：OpenAI SDK 经 HTTPX 连接，Anthropic SDK 经 HTTPX2 连接。运行不需要 OMP、Bun、Node 或 OMP profile；Node 仅用于前端自动化测试。

目录格式见 [Provider 与三部门绑定示例](docs/examples/providers.json)。示例的服务地址、模型名称和容量均为占位示意，使用前按所选服务的实际能力填写。`context_window` 与 `max_output_tokens` 必须明确；协议在模型访问定义上声明，`responses`、`chat_completions`、`messages` 三条已接入，一条定义只走一条协议。有效窗口取任务限制与模型窗口较小值，工作与压缩输出均受该模型限制。

凭据只经内存、进程环境或 `.yudao/.env` 解析，Key 不回填、不进入日志、事件、Git 与导出：

```powershell
$env:YUDAO_OPENCODE_GO_KEY = '<your-api-key>'
python -m harness
```

`credential_ref` 对应环境变量名称；应用不读取 `provider.md`。旧的 `YUDAO_MODEL_*` 单配置入口与 Provider 级 `protocol` 字段已移除，旧的目录文件按新结构明确报错，不做迁移。任务创建时冻结三部门的目标与认证句柄，凭据只保存在进程内存中；宿主更换默认目录或凭据来源只影响新任务。Provider 模块在后台轮询本地配置与 `.env`（约 1 秒，按内容核对），界面保存与手动重载也经同一接口发布；文件损坏时保留上一有效版本并持续显示重载错误。进程重启后无法继续使用已丢失原凭据的旧任务，但仍可查看和重放其历史。

默认单次等待 600 秒，由目录中 Provider 的 `timeout_sec` 设置。每个逻辑请求最多尝试 3 次，通常间隔 1 秒、2 秒；有效 Retry-After 最多等 60 秒，超过时明确停止而不提前重发。各实际尝试计入每次部门激活的 32 次模型调用上限，压缩调用同样适用，不另设累计耗时预算。等待可被取消或新增输入打断，每次实际尝试重新装配上下文并准入。失败部分输出可回查，但不执行其工具、不进入有效部门历史。SDK 不另开隐藏重试。

工具由 Yudao 内核执行（读取、写入、删除、移动、检查和结构化提交）。Product/Quality 没有写工具，工程修改受有效合同及事前计划范围约束。检查在可丢弃的完整公开树副本执行，由主机签发绑定当前合同、计划、交付和激活的回执；模型自报 `exit_code` 不是证据。交付保存完整文件字节、二进制与空目录，原工作区不可用后仍可独立恢复。该副本机制不提供操作系统沙箱。

三个部门均可通过 `submit_request` 咨询或请求职责内动作，经 `submit_response` 回应。一次只有一个未结请求，保留原工作，使用同一个部门循环。普通意见不改变需求，正式产品决定单独接纳；动作回复引用真实结果，最后仍须独立 QA。

部门指令作为显式 developer 输入发送；原始任务逐字保留，本部门完整历史跨激活延续，部门交接时重新装配当前合同，不携带其它部门的私有历史。接近窗口上限时自动压缩部门历史视图，保留摘要来源、原始事件与近期完整工具回合；摘要调用同样可取消并计入模型步数。上下文视图可按步骤打开实际输入、摘要及原始来源。调用尝试事件表示内核已开始调用 provider，不承诺网络请求已经送达。SDK 返回的用量仅作只读记录，不估算、不用于暂停任务；未上报用量或费用显示为“未上报”。

## 停止与后续范围

只有独立质检 release 才能进入 `DONE`。运行时间达到 `run_time_limit_sec` 上限进入 `FAILED`（停止原因为 `time_limit`）；取消、不可重试的 provider 错误、重试耗尽或上下文溢出同样进入 `FAILED`。部门激活次数上限（`max_cycles`）和单次激活模型步数上限仍保留，但默认值已大幅放宽（均为 999999），在实际运行中不再成为有效约束。调用方仍可显式配置较小值以恢复旧行为，达到上限时进入 `PAUSED`。压缩返回空摘要或超限时不终止任务，部门继续工作，后续激活重试压缩。当前以运行时间（`run_time_limit_sec`，默认 7200 秒）作为主要收敛保证，辅以循环次数、模型步数、有界重试和单次请求超时限制执行，不设置 token 预算。固定原文与当前工作无法容纳时明确停止，不静默截断或无限压缩。停止后仍可查看、导出和重放事件，迟到结果不能继续提交。

当前不提供暂停任务的继续执行，也不自动复用经验、修改规则或模型。知识图谱、长期记忆、异步恢复及新增部门属于后续阶段，见 [总体路线图](docs/program-roadmap.md)。

经验候选仅来自已接受的质检返工或非取消失败，可在证据视图查看来源、导出和重放。候选保持待验证，不自动注入部门上下文。
