# Yudao Loop System

[![CI](https://github.com/bender2333/yudao/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/bender2333/yudao/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)

徽章显示 main 上最近一次合并以后的 CI 结果。测试分三层，按时机运行（[测试分层](docs/design/test-pyramid.md)第 4 节）：

| 时机 | CI 作业 | 挡什么 |
| --- | --- | --- |
| 每次推送到 PR | ① 单元层、② 模块层、评测工具、客户端（并行），`check` 汇总 | 挡合并 |
| 每次合并到 main 以后 | ③ 集成层 | 不挡；失败交回引入它的工单 |
| 里程碑发布之前 | 不在 CI：真实模型冒烟、客户端端到端、桌面测试 | 挡发布 |

每次运行的摘要页列出各层的文件数、用例数与结果；PR 上的「用例变化」列出合并前后各层用例的增减。只改 `docs/` 与日记的提交不运行 CI，徽章保持上一次的结果。

面向自治系统研发者的三部门原生循环运行时。产品、工程、质检共同构成 Yudao 的 Agent loop：内核逐步装配上下文、调用模型、执行工具并决定部门交接。模型自然语言不能结束任务；只有绑定当前有效合同、交付和完整代码树的 QA release 才能进入 `DONE`。

## 当前状态

- **Stage 1（可信交付）**: ✅ 已完成。三部门循环、压缩、Git 版本、重试、完整封存已验收通过。
- **Stage 2（三部门 Harness 基线）**: 2.1–2.6 按 2026-09-15 合同关闭；**2.7 统一 Provider 层、无配置启动与 OpenCode Go 接入**已实现并通过本地回归，真实 Go 覆盖 Responses 与 Chat Completions 两个协议并各自完成三部门任务（Anthropic Messages 对当前两个模型受区域与端点限制）。历史十场为 9 次完成、1 次计划取消，不外推复杂任务成功率。
- **Stage 3（通用工具、可靠恢复与执行环境）**: 进行中，按 GitHub 里程碑推进（2026-10-19）：
  - M0 三部门的循环结构与命令执行：进行中，36 张工单关闭、26 张打开。命令执行一线（bash、检查、质检的测试材料、结果未知的动作交还会话）已合并，还剩 bash 后台命令（#549、#550）与两张修正（#616、#617）；循环结构一线（询问、部门同时运行、PRD 新版本的通知）从 #551 开始依次进行。
  - M1 网页界面与模型管理：代码已完成，没有单独发布，与 M0 一起发布。
  - M2 至 M5 排在 M0 之后。
- **持续改进工作线 / Stage 7 系统演化**: 后续。已有离线分析与经验候选，尚无经验验证、采用、失效的完整学习闭环。

### 现在能试什么

- 最新的发布是 [v0.1.1](https://github.com/bender2333/yudao/releases/tag/v0.1.1)（2026-10-06），早于网页界面。
- 下一个发布是 M0 与 M1 一起的 0.1.2，附试用指南。发布之前要完成 M0 剩下的工单，并修好发布构建测试的崩溃（#614）。
- 想先看 main 上的网页界面：在与 origin/main 一致、没有未提交改动的检出上运行 `uv run python scripts/release.py`（需要 Node 22.12 以上；只构建 wheel，不发布），再按下面「安装与启动」安装它输出的 wheel。直接从源码运行服务时没有页面文件，页面只返回「没有页面文件」。

当前入口：[总体路线图](docs/program-roadmap.md)、[Stage 3 计划](docs/stage-3-plan.md)、[当前验收基线](docs/current-baseline.md)；进度看 GitHub 的里程碑。历史证据见 [验收记录](docs/archive/mvp-acceptance.md) 与 [Stage 2 进度](docs/archive/stage-2-progress.md)。

## 分层

```text
任务与观察层  网页界面 / 应用接口 / REST / 事件流（SSE）
三部门循环核  Orchestrator、逐步上下文装配、合同校验、循环次数与停止判定
基础能力层    单次 Responses 模型请求、宿主工具、工作区、事件、工件与 Git 版本存储
```

Event Store 是唯一事实来源。Provider adapter 只做一次模型请求并返回输出，不执行工具、不管理部门历史、不决定循环。内核消费模型输出，调用工具或校验提交，再装配下一步输入。每一步的部门指令、当前合同、本部门历史与工具 schema 都保存为可核对摘要的工件。界面由服务提供的网页（client/ 构建的页面文件）提供，停止服务就是结束这个进程（Ctrl+C）。

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

之后的命令都用 `uv run` 在项目环境中运行。

### 配置 Provider

无配置也能启动服务：`yudao api`（从源码运行时为 `uv run python -m harness api`）直接使用默认路径，配置缺失时进入空态，可以在页面里逐项完成接入。非敏感配置写在数据目录内的 `providers.json`；凭据默认只在进程内存中有效，需要跨重启时写入数据目录内的 `.env`。

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

调用协议（`responses` / `chat_completions` / `messages`）在每个模型访问定义上声明，一份 Provider 配置（连接）只有一个服务方案下的地址与凭据引用，不声明协议（[ADR-0033](docs/adr/0033-protocol-belongs-to-model-access.md)）；在连接上声明协议会在读取目录时报错并指出字段位置。请求时基址取所属连接的地址，请求路径由协议适配器拼接（Responses 与 Chat Completions 在基址后拼接 `/responses`、`/chat/completions`，Anthropic Messages 去掉基址末尾的 `/v1` 后拼接 `/v1/messages`）。`preset_id` 与 `models_url` 可省略，省略时使用服务方案默认值。参考 [Provider 配置示例](docs/examples/providers.json)。

Provider 连接只信任操作系统的证书库：私有 CA 与企业代理的证书装在系统证书库中即可；`SSL_CERT_FILE`、`SSL_CERT_DIR` 这两个环境变量对 Provider 连接不起作用。

凭据来源优先级为进程内存覆盖 > 进程环境变量 > 数据目录内的 `.env`。页面填写 Key 默认只对本进程有效，勾选持久化才写入 `.env`；已保存的 Key 不回填，也不进入日志、事件与导出。

服务方案（OpenCode Go 是第一个预置方案）自带端点、认证方式与模型列表地址；模型列表只产生候选，候选要建立访问定义并执行一次模型测试通过（准入）后才能绑定到部门。

### 启动服务

Yudao 服务用 `yudao` 命令启动（安装发布 wheel 以后；从源码运行时用 `uv run python -m harness`）：

```bash
yudao api
```

`yudao api` 的参数与 `python -m harness api` 相同：`--data-dir`、`--host`、`--port`、`--access`、`--provider-config`。`yudao --version` 输出发布版本号。停止服务就是结束这个进程（Ctrl+C）。

默认数据目录是用户数据目录：Windows 为 `%LOCALAPPDATA%\Yudao`，Linux 为 `~/.local/share/yudao`（遵守 `XDG_DATA_HOME`）。事件日志、工件、进程锁 `service.lock`、`providers.json`、`.env` 与日志目录 `logs/` 都在其中；日志按大小轮换。开发、评测与走查用 `--data-dir` 指向其他目录。`--provider-config` 没有给出时目录文件为 `<--data-dir>/providers.json`，准入记录 `admissions.json` 与它同目录；明确给出时以该路径为准。

不写子命令时启动的就是应用接口（与 `api` 子命令相同），同时提供网页界面；用浏览器打开服务地址即可，`--access lan` 时局域网内的另一台电脑也能打开。

服务提供网页界面与应用接口（命令、查询、能力清单与 OpenAPI，见[应用层与接口层设计说明](docs/design/app-and-interface.md)）：

- `POST /api/commands/{名称}`（命令带 `command_id`，接受返回位置，拒绝返回 409 与原因）
- `GET /api/queries/{名称}`（快照与位置）
- `GET /api/capabilities`、`GET /openapi.json`

同一个数据目录只允许一个服务进程：启动时取得数据目录的进程锁，另一个服务进程正在使用这个数据目录时以非零状态退出并写明占用的数据目录。

### 运行演示（无需 API 密钥）

```bash
uv run python -m harness demo
```

演示经应用层的命令新建项目与事项，运行结束后打印 run id、阶段、流转与计数。

### 重放历史任务

```bash
yudao replay <run_id>
```

只读的子命令（`replay`、`project`）默认使用上面说的用户数据目录，用 `--data-dir` 指向其他目录。

## 安装与启动

上面「快速开始」是从源码运行的开发方式。按发布版本安装时，一次发布只含一个 wheel `yudao_harness-<版本>-py3-none-any.whl`：Yudao 服务的代码、页面文件与执行代理的 wheel。

一次发布是一个 wheel `yudao_harness-<版本>-py3-none-any.whl`，其中包含 Yudao 服务的代码、页面文件与执行代理的 wheel。停止服务就是结束这个进程（Ctrl+C）。

### 控制主机上的 Yudao 服务

前提：控制主机上有 [uv](https://docs.astral.sh/uv/)。安装 uv：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

uv 的可执行文件目录（Windows 为 `%USERPROFILE%\.local\bin`）要加入 `PATH`，重新打开终端以后生效。

安装 Yudao 服务：

```bash
uv tool install --python 3.12 <wheel 的路径>
```

`yudao` 命令安装到 uv 的可执行文件目录（Windows 为 `%USERPROFILE%\.local\bin`）；该目录不在 `PATH` 中时，按 uv 的提示运行 `uv tool update-shell`。

安装以后启动：

```bash
yudao api
```

`yudao api` 的参数与 `python -m harness api` 相同：`--data-dir`、`--host`、`--port`、`--access`、`--provider-config`。

控制主机换到另一台机器时，从私有仓库的 Release 取得 wheel：

```bash
gh release download v<版本> --pattern 'yudao_harness-*.whl'
```

### 网页界面

启动服务以后，用浏览器打开服务地址即可使用（默认 `http://127.0.0.1:8765`）。`--access lan` 时局域网内的另一台电脑也能打开同一地址。页面文件由服务随 wheel 一起提供，不需要单独安装客户端。

### 升级

Yudao 服务按 [ADR-0019](docs/adr/0019-project-stream-across-versions.md) 先排空，停止服务，再安装新的 wheel，然后重新启动。排空是命令 `runtime.start_drain`，停止开始新事项并等待进行中的 run 结束：

```bash
curl -X POST http://127.0.0.1:8765/api/commands/runtime.start_drain \
  -H "Content-Type: application/json" \
  -d '{"command_id": "<客户端生成的 UUID>"}'
# 等待进行中的 run 结束，停止 Yudao 服务
uv tool install --reinstall --python 3.12 <新的 wheel 的路径>
yudao api
```

同一个地址上的文件被替换以后，没有 `--reinstall` 的再次安装按「已经安装」结束，所以升级要带 `--reinstall`。页面文件随 wheel 一起提供，每次部署都是同一版本。

## 测试

Python 测试按三层分批运行（分层见 `docs/design/test-pyramid.md`）：单元层与模块层一起跑，
集成层只跑本次改动或新增的文件，全量集成层由架构师按批运行。

```bash
uv run python -m pytest -m "unit or module"
uv run python -m pytest harness/tests/<本次改动或新增的集成层文件>
```

客户端的检查在 `client/` 中运行：单元用 `cd client && npm test`，端到端用 `cd client && npm run test:e2e`。

应用接口的 OpenAPI 快照（`harness/tests/openapi/openapi.json`）由 `test_openapi_snapshot.py` 与运行中的服务比较；由快照生成 TypeScript 接口类型并编译：

```bash
cd harness/tests/openapi && npm ci && npm run check
```

按目录绑定执行三部门真实 smoke（凭据引用从环境解析，应用不读取 `provider.md`）：

```bash
uv run python -m harness smoke --provider-config .yudao/providers.json --data-dir .yudao/native-validation
uv run python -m harness smoke --provider-config .yudao/providers.json --scenario happy
uv run python -m harness smoke --provider-config .yudao/providers.json --scenario collaboration
```

报告写在 `.yudao/native-validation/smoke-report.md`，包含 run id、路由、provider/model、宿主检查回执、结束原因、replay 一致性、Git 版本及逐步模型输入审计。Git 审计缺失或未通过时不能返回验收成功。每次只记录本次选择的场景，不继承上次报告中的验收结果。

## 如何使用

界面由服务提供的网页提供，命令与查询经应用接口提交与读取。下面的例子用 `curl` 直接调用接口；每条命令都带客户端生成的 `command_id`（重试使用同一个值）。

### 1. 创建项目与任务

```bash
# 创建项目
curl -X POST http://localhost:8765/api/commands/project.create \
  -H "Content-Type: application/json" \
  -d '{"command_id": "c1", "name": "我的项目", "goal": "创建一个 Python 脚本，从 CSV 读取数据并输出统计信息"}'

# 创建任务（被接受以后由流程编排开始执行）
curl -X POST http://localhost:8765/api/commands/work_item.create \
  -H "Content-Type: application/json" \
  -d '{"command_id": "c2", "project_id": "{project_id}", "text": "创建一个 hello world 脚本"}'
```

### 2. 观察三部门协作

任务会经过三个部门：

- **产品部 (Product)**: 理解需求，形成有效 PRD
- **工程部 (Engineering)**: 制定计划，实现代码
- **质检部 (Quality)**: 独立验证，放行交付

读取状态用查询（快照带全局位置；事件流从该位置补齐）：

```bash
# 项目概览与流转
curl "http://localhost:8765/api/queries/project.overview?project_id={project_id}"
curl "http://localhost:8765/api/queries/project.flow?project_id={project_id}&work_item={work_item_id}"

# 部门工作间：部门消息、指导记录、Context 快照与部门 Prompt
curl "http://localhost:8765/api/queries/department.workspace?project_id={project_id}&department=product&work_item={work_item_id}"
```

### 3. 追加需求与调整方向

任务运行中可以追加输入与部门定向指导：

```bash
# 追加输入（交给产品处理）
curl -X POST http://localhost:8765/api/commands/work_item.append_input \
  -H "Content-Type: application/json" \
  -d '{"command_id": "c3", "work_item_id": "{work_item_id}", "text": "需要支持 UTF-8 编码"}'

# 部门定向指导（直接给工程/质检）
curl -X POST http://localhost:8765/api/commands/guidance.send \
  -H "Content-Type: application/json" \
  -d '{"command_id": "c4", "work_item_id": "{work_item_id}", "department": "engineering", "text": "使用 pandas 库处理 CSV"}'
```

### 4. 查看失败原因

如果任务失败或暂停，读取调用尝试（可按部门、状态、Provider 与模型筛选）：

```bash
curl "http://localhost:8765/api/queries/project.attempts?project_id={project_id}&work_item={work_item_id}&status=failed"
```

按某个调用尝试的标识读取详情（输入、输出、SDK 流事件、用量与错误）：

```bash
curl "http://localhost:8765/api/queries/run.attempt?run_id={run_id}&attempt_id={attempt_id}"
```

### 5. 取消任务

```bash
curl -X POST http://localhost:8765/api/commands/work_item.cancel \
  -H "Content-Type: application/json" \
  -d '{"command_id": "c5", "work_item_id": "{work_item_id}"}'
```

### 6. 下载交付物

任务完成后：

```bash
# 导出事件、投影、调用尝试与用量
curl "http://localhost:8765/api/queries/run.export?run_id={run_id}" > run.json

# 下载交付文件（按交付事件与路径）
curl "http://localhost:8765/api/queries/delivery.file?event_id={event_id}&path=output.csv" > output.csv
```

### 7. 编辑部门 Prompt

```bash
curl -X POST http://localhost:8765/api/commands/department_settings.save \
  -H "Content-Type: application/json" \
  -d '{"command_id": "c6", "project_id": "{project_id}", "department": "engineering", "base_version": 0, "text": "你是资深 Python 工程师，优先使用标准库..."}'
```

Prompt 在下次该部门激活时生效，当前激活不受影响。

## HTTP 接口

`python -m harness api`（无参启动相同）提供的应用接口：`POST /api/commands/{名称}`（命令带 `command_id`，接受返回位置，拒绝返回 409 与原因）、`GET /api/queries/{名称}`（快照与位置）、`GET /api/events`（按范围筛选、从位置补齐的事件流）、`GET /api/capabilities`（能力清单）、`GET /openapi.json`；已登记的命令与查询以能力清单为准。查询只读，创建事项与取消走命令，界面不能直接改 spec、投影或完成状态。旧 Web 控制台与它的一批旧路由已经删除（[应用层与接口层设计说明](docs/design/app-and-interface.md)第 7.1、7.3 节）。

## 任务内 Git 版本

原文、需求/spec 与 PRD、计划与 PLAN、交付代码和公开验收记录在正式接纳时形成 Git 提交。新需求引起的 spec 变化可以在对应事件详情（`event.detail`）中查看提交、父提交及真实 diff。查询核验当前和父版本与正式材料一致，缺失或篡改会明确报错。

每个任务的仓库保存在 `<data-dir>/git/<run_id>.git`，由主机调用 Git CLI 管理。事件决定哪些版本已经接纳；`refs/snapshots/` 仅保留不可变对象。新输入或需求提交保留上次正式交付代码，工作目录中的修改到交付接纳时才进入代码版本。部门私有历史与 Git 元数据不进入公开交付或跨部门上下文。

Git 与完整交付封存使用同一次采集的文件字节，空目录和独立恢复继续由封存保证。第一阶段提供任务内版本与差异，不提供任意 Git 命令、历史 reset、跨任务合并、项目导入或远程推送配置；详见单独记录的 [D16](docs/requirements/git-change-management.md)。

## 模型配置

模型接入由独立的 Provider 模块承担（`harness/providers/`），三部门循环、界面、CLI 与 smoke 都经同一接口调用，不各自直连 SDK。Provider 配置、模型访问定义与部门绑定统一管理，产品、工程、质检分别绑定，允许共享或使用不同服务。创建任务前验证三部门绑定、凭据与模型准入；缺失配置明确拒绝创建。原生内核对连接中断、超时、限流和临时服务错误进行有界重试，不切换 Provider，详见 [D17](docs/requirements/provider-retries.md)、[D18](docs/requirements/department-providers.md)、[D23](docs/requirements/provider-layer.md)。

需要 Python 3.11 或更新版本，`uv sync --frozen` 按锁文件安装 SDK：OpenAI SDK 经 HTTPX 连接，Anthropic SDK 经 HTTPX2 连接。运行不需要 OMP、Bun、Node 或 OMP profile；Node 仅用于前端自动化测试。

目录格式见 [Provider 与三部门绑定示例](docs/examples/providers.json)。示例的服务地址、模型名称和容量均为占位示意，使用前按所选服务的实际能力填写。`context_window` 与 `max_output_tokens` 必须明确；协议在模型访问定义上声明，`responses`、`chat_completions`、`messages` 三条已接入，一条定义只走一条协议。有效窗口取任务限制与模型窗口较小值，工作与压缩输出均受该模型限制。

凭据只经内存、进程环境或数据目录内的 `.env` 解析，Key 不回填、不进入日志、事件、Git 与导出：

```powershell
$env:YUDAO_OPENCODE_GO_KEY = '<your-api-key>'
yudao api
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
