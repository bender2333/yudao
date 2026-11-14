---
name: yudao-ops
description: 协助用户配置、巡检与维护运行中的 Yudao（枢道）服务：经通用命令行执行能力发现、单项合同自省、先读取基准版本后提交幂等命令、有界事件流等待，并遵守凭据隔离规程、用户决定确认规程与三条改动通道分流规程。
---

# Yudao 进程外运维规程

本技能面向运行在 Yudao 服务进程之外的通用智能体，用于经 `yudao` 通用命令行操作运行中的 Yudao 实例，无需打开浏览器或手动拼接底层 HTTP 与 SSE 请求。

## 一、先读取后修改与基准版本规程

### 1. 连接与认证设置

- 默认连接本机回环地址 `http://127.0.0.1:8765`。目标地址可通过 `--url <地址>` 或环境变量 `YUDAO_URL` 指定，命令行参数优先于环境变量。
- 目标实例采用局域网访问方式（`access="lan"`）时，必须提供访问令牌：优先通过环境变量 `YUDAO_TOKEN` 或单行标准输入 `--token-stdin` 传入（命令提示注意：`--token-stdin` 与 `command --stdin` 共用标准输入时不可同时开启，需要同时传入令牌与标准输入载荷时使用环境变量 `YUDAO_TOKEN`）。

### 2. 标准六步操作闭环

每次配置或状态变更都遵循以下顺序：

1. **读取能力清单（`capabilities`）**：执行 `yudao capabilities`，确认服务进程可达、记录部署身份 `deployment.log_id`、访问方式 `deployment.access`，并查看当前实例已登记的全部查询 `queries`、命令 `commands`、决定种类 `decisions` 与事件种类 `events`。
2. **自省单项合同（`describe`）**：调用任何未核对过参数的命令或查询前，先执行 `yudao describe <名称>`，读取该项的输入字段名称、类型、必填约束、默认值、允许枚举、返回结构，以及命令的拒绝原因列表 `rejections` 或查询的刷新事件列表 `refresh_on` 与按位置回放标记 `replayable`。
3. **读取当前快照与基准版本（`query`）**：执行 `yudao query <查询名> [--param key=value ...]`，获取带全局位置 `position` 的只读快照。对要求并发控制的命令（例如模型目录修订号 `revision`、项目组织版本号 `version`、部门设置版本号 `version`），必须从刚读取的查询结果中提取对应的当前版本号作为 `base_version`，禁止猜测或硬编码版本号。
4. **提交幂等命令（`command`）**：执行 `yudao command <命令名> [--command-id <UUID>] [--param key=value | --string-param key=value | --json <JSON> | --stdin]`。命令被接受时标准输出返回含 `position` 与 `refs` 的 JSON，退出码为 `0`。遇到网络超时或连接中断需要重试同一意图时，传入上一次使用的 `--command-id`，由服务端命令去重保证只生效一次。
5. **有界等待后台事件（`events`）**：一步连接模型服务、选用模型、连接测试、模型测试、工具服务器探测、事项运行与排空等待等异步进展，统一从前一步返回的 `position` 起执行有界订阅：`yudao events --after <位置> [范围筛选] [停止条件]`。禁止编写无界循环轮询脚本。
6. **复核最终快照（`query`）**：有界事件流命中目标事件退出后，再次执行对应的 `yudao query` 读取最新快照，向用户汇报核实后的状态。

### 3. 退出码处置规则

- **退出码 `0`**：查询成功、命令被接受，或 `yudao events` 满足 `--limit`、`--until-position`、`--until-type` 停止条件正常结束。
- **退出码 `1`（业务拒绝）**：服务端返回 HTTP `409`，标准输出打印完整拒绝 JSON（含 `reason` 与 `message`）。遇到 `version_conflict` 等基准版本冲突时，重新执行 `yudao query` 获取最新状态与新 `base_version`，核对无误后再提交；遇到前置条件未满足时向用户如实说明原因。
- **退出码 `2`（参数或合同错误）**：未知名称、缺少必填字段、类型不符，或命令行参数超出允许范围（单次请求 `--timeout` 允许 `5`–`600` 秒，`events` 的 `--limit` 允许 `1`–`1000` 条、`--timeout` 允许 `1`–`3600` 秒）。立即执行 `yudao describe <名称>` 核对合同后修正参数。
- **退出码 `3`（连接或认证错误）**：目标服务未启动、网络不可达、本机模式拒绝非回环主机头（HTTP `403`）、局域网模式缺少有效令牌（HTTP `401`）或服务端 `5xx` 异常。检查服务进程状态、地址与令牌配置。
- **退出码 `4`（有界事件流等待超时）**：`yudao events` 到达 `--timeout` 仍未命中停止条件，标准错误会给出最新扫描到的全局位置 `position`（含检查点推进的位置）。可从该最新位置继续执行下一次有界 `yudao events --after <最新位置>`，或直接执行 `yudao query` 检查当前投影状态。
- **退出码 `5`（事件流重新同步）**：收到服务端 `resync` 帧（原因包括起始位置超出当前日志末尾 `position_unknown` 或订阅队列溢出 `queue_overflow`），标准错误输出原因与当前日志末尾位置 `end_position`。必须先重新执行 `yudao capabilities` 与对应的 `yudao query` 读取最新快照及 `position`，再从新位置续订。

---

## 二、凭据安全与隔离规程

1. **禁止明文索取与回显**：绝不在对话消息中要求用户直接粘贴 API Key 或访问令牌原文，也绝不在终端标准输出、错误说明或总结回复中回显任何密钥原文。
2. **禁止明文留痕**：绝不将明文密钥写入命令行参数（如 `--param api_key=...`）、Shell 历史记录、项目工作区源码与配置文件、事项输入文本（`work_item.create` / `material.record`）或任何 Git 提交记录。
3. **合规凭据配置途径**：
   - 优先引导用户在 Yudao 服务所在控制主机的数据目录 `.env` 文件中写入键值（键名须由字母、数字与下划线组成且不以数字开头，如 `YUDAO_OPENCODE_GO_KEY`），或在启动服务的用户环境变量中设置，目录配置只填写凭据引用名 `credential_ref`。
   - 确需通过命令行向运行中服务提交凭据（如 `catalog.connect`、`credential.set`）时，统一由本机安全凭据源经标准输入管道传入 `yudao command <命令名> --stdin`；传入局域网访问令牌时使用环境变量 `YUDAO_TOKEN` 或 `--token-stdin`。
   - 需要清理内存临时凭据或已持久化凭据时，分别调用 `credential.clear_override` 或 `credential.remove_persisted`。

---

## 三、三条改动通道分流规程

收到用户的配置、扩展或改造需求时，必须先识别改动所属的层次，严格走对应的唯一通道，禁止跨通道绕行：

### 第一条通道：数据定义与参数命令

- **适用范围**：连接模型服务与拉取候选、建立模型访问定义与准入测试、配置职能或角色默认模型、切换项目组织形态与角色合成、在规则允许区间内修改运行参数、配置项目源码目录与外部 MCP 工具服务器登记。
- **进入方式与守卫**：一律通过 `yudao query` 读取当前状态与基准版本后，使用 `yudao command` 调用接口层已登记命令。所有修改均经过定义加载结构校验、规则界限核对、基准版本核对与控制核心唯一写入口，严禁绕过服务直接编辑运行中数据目录下的数据库或内部状态文件。
- **失败与回退方式**：参数超界或基准版本冲突时命令直接返回退出码 `1`，不产生脏事件；改动生效后如需恢复，运行参数通过 `yudao command parameter.withdraw` 按修改记录身份撤回，项目组织通过 `yudao command organization.adopt` 重新采用上一形态或调整合成项恢复，全部变更与撤回均留有完整事件记录。

### 第二条通道：隔离动作与外部工具

- **适用范围**：为具体项目编写定制辅助脚本、自动化检查脚本，或接入外部数据源与第三方服务工具。
- **进入方式与守卫**：项目专用的辅助脚本与检查脚本放入目标项目的工作区目录，由角色在执行环境中按工具许可调用并随交付快照封存；跨项目或独立驻留的外部工具封装为独立的 MCP 服务器子进程，先调用 `tool_server.probe` 探测并在 `yudao events` 中等待探测结果，验证通过后再调用 `mcp_servers.save` 登记到项目。控制核心进程不加载任何此类外部脚本或插件代码。
- **失败与回退方式**：脚本报错或独立 MCP 子进程异常仅体现为单次工具回执失败或探测失败，不影响 Yudao 控制核心进程稳定；删除工作区脚本或通过 `mcp_servers.save` 移除对应服务器条目即可立即停用。

### 第三条通道：修改 Yudao 自身代码

- **适用范围**：新增路由或装配实现、扩展接口合同、调整应用层服务逻辑，或修改可信内核模块。
- **进入方式与守卫**：严禁向运行中的 Yudao 服务进程热加载代码或动态替换内存对象。所有对 Yudao 自身代码的修改必须在 Yudao 代码仓库的独立工作区中作为正式开发事项推进，完成自动化测试与独立核验；当改动触及可信内核清单路径时，系统发出 `kernel_modification`（「内核修改」）决定请求，必须等待用户明确批准。
- **升级与回退方式**：测试或独立核验未通过的改动不予采纳。对运行中的 Yudao 实例执行版本升级前，必须先调用 `yudao command runtime.start_drain` 进入排空状态，等待进行中的全部运行自然结束（经 `yudao query system.status` 或 `yudao events` 核实），并在控制主机执行离线发布检查 `yudao release-check <待发布仓库路径>` 生成 `instance_upgrade`（「实例升级」）决定请求；经用户确认后停止服务进程、使用 `uv tool install --reinstall` 安装新版本 wheel 并重启。升级后若发现异常，排空并重装上一发布版本 wheel 恢复。

---

## 四、用户决定请求拍板规程与常见运维操作序列

### 1. 决定请求用户拍板确认规程

- 用户对系统的待回答决定请求拥有最终裁决权，特别是 `kernel_modification`（「内核修改」）、`instance_upgrade`（「实例升级」）、`initial_prd`（「确认初始 PRD」）、`qa_cannot_verify`、`definitions_changed`、`model_unavailable` 等影响范围与边界的决定。
- 运维代理执行 `yudao query decisions.list` 发现待处理决定请求时，职责是读取决定的背景说明、关联证据与可选方案并完整呈现给用户，解释各选项的后果。
- **只有在用户明确给出具体选择之后**，运维代理才可调用 `yudao command decision.answer` 代为提交回答；绝不允许猜测用户偏好或自行替用户拍板。

### 2. 常见运维操作序列

执行下列任一序列前，如对具体字段名称或枚举值不确定，先运行 `yudao describe <名称>` 核对当前实例合同。

#### （1）一步连接模型服务、选用模型并完成准入

```bash
# 1. 读取当前模型目录快照与 revision
yudao query catalog

# 2. 从标准输入传入包含 base_version、base_url（及可选 api_key）的 JSON，不把密钥放进命令行参数
yudao command catalog.connect --stdin

# 3. 从命令返回的 position 起有界等待候选模型收集完成事件
yudao events --after <position> --until-type catalog_candidates_collected --timeout 60

# 4. 读取更新后的目录快照与新 revision，选用目标模型（自动触发准入测试与默认绑定）
yudao query catalog
yudao command catalog.model.select --param base_version=<revision> --string-param provider_id=<provider_id> --string-param model=<model_name> --string-param protocol=chat_completions --param context_window=128000 --param max_output_tokens=8192

# 5. 等待模型准入测试事件并核实目录就绪状态
yudao events --after <position> --type catalog_model_tested --limit 1 --timeout 120
yudao query catalog
```

#### （2）新建或接入已有项目并切换组织形态

```bash
# 查看可用组织形态目录（如 product_engineering_quality、product_engineering、single_role_direct）
yudao query forms.list

# 新建项目（接入已有源码目录可改用 project.onboard，先用 describe project.onboard 查看字段）
yudao command project.create --string-param name="示例项目" --string-param goal="构建命令行统计工具"

# 读取项目当前组织定义与版本号 version，切换组织形态
yudao query project.organization --param project_id=<project_id>
yudao command organization.adopt --string-param project_id=<project_id> --param base_version=<version> --string-param form=single_role_direct --string-param reason="单角色直做验证"
yudao query project.organization --param project_id=<project_id>
```

#### （3）在规则界限内调整运行参数与按记录撤回

```bash
# 1. 查询规则与参数注册表，读取 parameters_version 以及目标参数的允许范围与当前有效值
yudao query rules.registry

# 2. 先用 describe parameter.set 核对请求字段，提交界限内的参数调整
yudao describe parameter.set
yudao command parameter.set --param name=run_time_limit_sec --param value=3600 --string-param reason="按运维巡检调优" --param base_version=<parameters_version>

# 3. 需要恢复原值时，读取最新 parameters_version 与该条修改记录的 event_id，撤回该次修改
yudao describe parameter.withdraw
yudao command parameter.withdraw --string-param name=run_time_limit_sec --string-param expected_change_id=<event_id> --string-param reason="撤回：按运维巡检调优" --param base_version=<parameters_version>
yudao query rules.registry
```

#### （4）探测并登记独立外部 MCP 工具服务器（第二条通道）

```bash
# 1. 查看工具注册表与探测命令合同
yudao query tools.registry
yudao describe tool_server.probe

# 2. 发起独立 MCP 子进程探测并有界等待结果事件
yudao command tool_server.probe --json '<探测配置 JSON>'
yudao events --after <position> --timeout 60 --limit 5

# 3. 探测通过后读取项目设置基准版本，调用 mcp_servers.save 登记到目标项目
yudao query project.settings --param project_id=<project_id>
yudao describe mcp_servers.save
yudao command mcp_servers.save --json '<包含 project_id、base_version 与 servers 的 JSON>'
```

#### （5）发起事项、有界跟踪进展与故障排查

```bash
# 1. 创建事项并记录返回的全局位置 position 与 work_item_id
yudao command work_item.create --string-param project_id=<project_id> --string-param text="实现 CSV 行数统计脚本"

# 2. 有界订阅该事项事件流，遇到运行结束或产生待回答决定请求时立即停止
yudao events --after <position> --work-item <work_item_id> --until-type run_done --until-type decision_requested --timeout 300

# 3. 核实项目概览、流转与失败调用尝试详情，必要时导出运行记录（导出不含明文密钥）
yudao query project.overview --param project_id=<project_id>
yudao query project.flow --param project_id=<project_id> --param work_item=<work_item_id>
yudao query project.attempts --param project_id=<project_id> --param work_item=<work_item_id> --param status=failed
yudao query run.export --param run_id=<run_id>
```

#### （6）巡检待回答决定请求并在取得用户确认后提交回答

```bash
# 1. 列出当前未决的决定请求，向用户完整展示题目、背景证据与可选项
yudao query decisions.list
yudao describe decision.answer

# 2. 取得用户明确拍板指令后，提交对应选项回答
yudao command decision.answer --string-param decision_id=<decision_id> --string-param option_id=<用户选定的选项>
```

#### （7）实例升级前排空与发布检查（第三条通道）

```bash
# 1. 启动排空，停止接纳新运行并等待在途运行自然结束
yudao command runtime.start_drain
yudao query system.status

# 2. 在控制主机对通过测试的待发布仓库执行发布检查，生成「实例升级」决定请求供用户确认
yudao release-check <待发布仓库路径>
```
