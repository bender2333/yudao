# Yudao Loop System

面向自治系统研发者的三部门原生循环运行时。产品、工程、质检共同构成 Yudao 的 Agent loop：内核逐步装配上下文、调用模型、执行工具并决定部门交接。模型自然语言不能结束任务；只有绑定当前有效合同、计划、交付和完整代码树的 QA release 才能进入 `DONE`。

OMP 仅作为底层实现的代码参考，不是运行依赖。旧 OMP 架构的运行证据与本次原生循环的验证分开记录，见 [MVP 验收记录](docs/mvp-acceptance.md)。

第一阶段正在按 [A-H 工作包](docs/stage-1-alignment.md) 验收。原生循环、部门完整历史与自动压缩、同源 PRD、事前计划、完整交付封存、受控删除移动、通用专家协作、持续输入及 prompt 编辑均已实现。任务内 Git 版本和差异已实现并通过确定性验收。H 模型有界重试已实现，慢响应、取消、追加输入和桌面手机已验证；真实完整方向调整和压缩后最终放行仍有连续连接失败导致的缺口，结果见 [验收记录](docs/mvp-acceptance.md)。

第二阶段首批已接入统一 Provider/模型目录和三部门独立绑定，覆盖任务冻结、请求路由、模型容量及只读观察，见 [D18](docs/requirements/department-providers.md)。本地多连接与完整回归已通过；真实跨 Provider 最终 QA 仍待验收，Provider 配置界面等待原型。

第一阶段此前保留的真实控制台地址为 [http://127.0.0.1:8774](http://127.0.0.1:8774)，数据目录为 `.yudao/stage1-retry-final-20260906`，对应当时的单 Provider 基线及 600 秒默认等待。该历史基线取得了 `gpt-5.6-luna` 的真实响应和重试恢复证据，但未完成最终 QA；不能将这个旧进程视为当前部门绑定实现。运行基线与历史服务记录见 [验收记录](docs/mvp-acceptance.md)。

## 分层

```text
任务与观察层  本地 Web 控制台 / REST / SSE
三部门循环核  Orchestrator、逐步上下文装配、合同校验、循环次数与停止判定
基础能力层    单次 Responses 模型请求、宿主工具、工作区、事件、工件与 Git 版本存储
```

Event Store 是唯一事实来源。Provider adapter 只做一次模型请求并返回输出，不执行工具、不管理部门历史、不决定循环。内核消费模型输出，调用工具或校验提交，再装配下一步输入。每一步的部门指令、当前合同、本部门历史与工具 schema 都保存为可核对摘要的工件。

## 启动

需要 Python 3.11 或更新版本，以及可从 `PATH` 调用的 Git CLI。Git 用于每个任务的本地版本存储，无需配置远程仓库。

```bash
python -m pip install -e ".[dev]"
python -m harness demo --serve --port 8765
```

只跑样例：

```bash
python -m harness demo
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

按目录绑定执行三部门真实 smoke（凭据引用从环境解析，应用不读取 `provider.md`）：

```bash
python -m harness smoke --provider-config .yudao/providers.json --data-dir .yudao/native-validation
python -m harness smoke --provider-config .yudao/providers.json --scenario happy
python -m harness smoke --provider-config .yudao/providers.json --scenario collaboration
```

报告写在 `.yudao/native-validation/smoke-report.md`，包含 run id、路由、provider/model、宿主检查回执、结束原因、replay 一致性、Git 版本及逐步模型输入审计。Git 审计缺失或未通过时不能返回验收成功。每次只记录本次选择的场景，不继承上次报告中的验收结果。

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
| GET | `/api/runs/{id}/events/{event_id}` | 完整事件；附实际模型输入或正式材料及经前后版本核验的 Git diff |
| GET | `/api/runs/{id}/events/{event_id}/files?path=...` | 从已接纳交付封存下载文件原字节 |
| GET | `/api/runs/{id}/stream` | SSE |
| GET | `/api/runs/{id}/export` | 导出事件与投影 |
| POST | `/api/runs/{id}/replay` | 校验投影可重放，不写状态 |
| POST | `/api/runs/{id}/cancel` | 取消当前 run |
| POST | `/api/runs/{id}/inputs` | 按原文补充当前任务，正文 `{ "text": "..." }` |
| POST | `/api/runs/{id}/prompts/{department}` | 修改当前任务的部门 prompt，正文 `{ "text": "..." }` |

活动任务中可持续提交原文；当前已开始工具结束后回产品维护需求，尚未开始的工具跳过。输入接收、交给产品与有效需求处理分别展示。`/stop`、`/cancel` 立即发出停止信号并保存原文；Git 或材料保存失败也会停止，界面保留草稿并说明保存失败，不生成虚假的输入版本。按钮取消不生成文本。终态任务不恢复，新的工作明确创建新任务。prompt 可折叠和编辑，一次激活固定版本，下一次目标部门激活采用更新，实际输入与采用历史可查。

## 任务内 Git 版本

原文、需求/spec 与 PRD、计划与 PLAN、交付代码和公开验收记录在正式接纳时形成 Git 提交。新需求引起的 spec 变化可以在 Web 对应事件详情中查看提交、父提交及真实 diff。查询核验当前和父版本与正式材料一致，缺失或篡改会明确报错。

每个任务的仓库保存在 `<data-dir>/git/<run_id>.git`，由主机调用 Git CLI 管理。事件决定哪些版本已经接纳；`refs/snapshots/` 仅保留不可变对象。新输入或需求提交保留上次正式交付代码，工作目录中的修改到交付接纳时才进入代码版本。部门私有历史与 Git 元数据不进入公开交付或跨部门上下文。

Git 与完整交付封存使用同一次采集的文件字节，空目录和独立恢复继续由封存保证。第一阶段提供任务内版本与差异，不提供任意 Git 命令、历史 reset、跨任务合并、项目导入或远程推送配置；详见单独记录的 [D16](docs/requirements/git-change-management.md)。

## 模型配置

真实模型通过官方 OpenAI Python SDK 发送单次、无服务端会话续接的 Responses 请求。Provider 和模型由统一目录管理，产品、工程、质检分别绑定，允许共享或使用不同服务。创建任务前验证三部门绑定和凭据；缺失配置明确拒绝创建。原生内核对连接中断、超时、限流和临时服务错误进行有界重试，不切换 Provider，详见 [D17](docs/requirements/provider-retries.md) 和 [D18](docs/requirements/department-providers.md)。

需要 Python 3.11 或更新版本，`pip install -e ".[dev]"` 会安装 SDK。运行不需要 OMP、Bun、Node 或 OMP profile；Node 仅用于前端自动化测试。

目录格式见 [两套 Provider、三部门绑定示例](docs/examples/providers.json)。示例的服务地址、模型名称和容量均为占位示意，使用前按所选服务的实际能力填写。`context_window` 和 `max_output_tokens` 必须明确；当前真实协议仅支持 `responses`。有效窗口取任务限制与模型窗口较小值，工作与压缩输出均受该模型限制。

PowerShell 启动示例，目录放在 `.yudao/providers.json`。`credential_ref` 对应环境变量名称，密钥只通过当前终端环境注入，应用不读取 `provider.md`：

```powershell
$env:YUDAO_PROVIDER_A_KEY = '<provider-a-key>'
$env:YUDAO_PROVIDER_B_KEY = '<provider-b-key>'
python -m harness serve --provider-config .yudao/providers.json --data-dir .yudao/native-loop --port 8766
```

旧的 `YUDAO_MODEL_*` 单配置入口已移除。任务创建时冻结三部门配置，凭据只保存在进程内存中；宿主更换默认目录或凭据来源只影响新任务。CLI 在服务启动时读取 JSON 文件，不自动重载文件变更。进程重启后无法继续使用已丢失原凭据的旧任务，但仍可查看和重放其历史。Provider 配置及绑定选择界面等待对应原型。

默认单次等待 600 秒，由目录中 Provider 的 `timeout_sec` 设置。每个逻辑请求最多尝试 3 次，通常间隔 1 秒、2 秒；有效 Retry-After 最多等 60 秒，超过时明确停止而不提前重发。各实际尝试计入每次部门激活的 32 次模型调用上限，压缩调用同样适用，不另设累计耗时预算。等待可被取消或新增输入打断，每次实际尝试重新装配上下文并准入。失败部分输出可回查，但不执行其工具、不进入有效部门历史。SDK 不另开隐藏重试。

工具由 Yudao 内核执行（读取、写入、删除、移动、检查和结构化提交）。Product/Quality 没有写工具，工程修改受有效合同及事前计划范围约束。检查在可丢弃的完整公开树副本执行，由主机签发绑定当前合同、计划、交付和激活的回执；模型自报 `exit_code` 不是证据。交付保存完整文件字节、二进制与空目录，原工作区不可用后仍可独立恢复。该副本机制不提供操作系统沙箱。

三个部门均可通过 `submit_request` 咨询或请求职责内动作，经 `submit_response` 回应。一次只有一个未结请求，保留原工作，使用同一个部门循环。普通意见不改变需求，正式产品决定单独接纳；动作回复引用真实结果，最后仍须独立 QA。

部门指令作为显式 developer 输入发送；原始任务逐字保留，本部门完整历史跨激活延续，部门交接时重新装配当前合同，不携带其它部门的私有历史。接近窗口上限时自动压缩部门历史视图，保留摘要来源、原始事件与近期完整工具回合；摘要调用同样可取消并计入模型步数。上下文视图可按步骤打开实际输入、摘要及原始来源。调用尝试事件表示内核已开始调用 provider，不承诺网络请求已经送达。SDK 返回的用量仅作只读记录，不估算、不用于暂停任务；未上报用量或费用显示为“未上报”。

## 停止与后续范围

只有独立质检 release 才能进入 `DONE`。达到部门激活次数或单次激活模型步数上限进入 `PAUSED`；取消、不可重试的 provider 错误、重试耗尽、上下文溢出或压缩失败进入 `FAILED`。当前使用循环次数、模型步数、有界重试和单次请求超时限制执行，不设置 token 预算。固定原文与当前工作无法容纳时明确停止，不静默截断或无限压缩。停止后仍可查看、导出和重放事件，迟到结果不能继续提交。

当前不提供暂停任务的继续执行，也不自动复用经验、修改规则或模型。知识图谱、长期记忆、异步恢复及新增部门属于后续阶段，见 [总体路线图](docs/program-roadmap.md)。

经验候选仅来自已接受的质检返工或非取消失败，可在证据视图查看来源、导出和重放。候选保持待验证，不自动注入部门上下文。
