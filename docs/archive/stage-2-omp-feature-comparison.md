# Stage 2 OMP 功能对比（2.4.1–2.4.4）

日期：2026-09-15  
性质：计划 2.4 的对比与优先级，**不改 harness 代码**。  
Stage 2 口径：日常可用的三部门 Harness；P0 只问「缺了是否挡住三部门日常使用」，不以 OMP 功能全集为完成标准。

## 底本

| 来源 | 路径 / SHA | 用途 |
| --- | --- | --- |
| Yudao 工作树 | `C:/project/yudao`，`harness_1` HEAD `bf3bd4114dd64c23dca893f29025c9e058a2dcc7`（`bf3bd41`） | 现状以当前 `harness/` 源码为准 |
| OMP 只读仓库 | `C:/project/codes/oh-my-pi` HEAD `fdfeef1f78ba75cd2c0a3b555be1d6043af4de57`（`fdfeef1f78`） | 核对工具名与包边界；**不复制 OMP 代码** |
| `D:/codes/oh-my-pi` | 本机不存在 | 计划 2.4.1 写的路径；改用上面的 C: 仓库 |
| Stage 2 系统审查 | `docs/research/omp-stage2-system-review.md`（OMP 固定 `e3106be68f778635da3a17106835ce2e0e6992af`，Yudao 当时 `fced43e`） | 采纳/不采用原则 |
| S4-A 采用映射 | `docs/s4a-omp-adoption-evidence-2026-09-08.md`（OMP `e3106be`，被测 `cdcdce5`） | 已采用机制 vs 归档不采用 |
| Stage 3 差距表 | `docs/stage-3/omp-capability-gap.md`（OMP 同 `fdfeef1f78`，Yudao 当时 `735e120`） | 避免把 3.x 项标成 Stage 2 P0 |
| 实施计划 2.4 | `docs/stage-2-implementation-plan.md` §2.4 | 任务范围与 2.4.3 假说 |
| 基线定义 | `docs/stage-2-harness-baseline.md` | 「日常可用」完成标准 |
| Web 原型账 | `docs/web-prototype-implementation-plan.md` | Context/Trace 主线已有，剩余属 2.3 |

OMP 工具名以 `packages/coding-agent/src/tools/builtin-names.ts`（`fdfeef1f78`）为准。Yudao 界面与运行以 `harness/web/server.py`、`harness/web/static/app.js`、`harness/runtime.py`、`harness/tools.py`、`harness/observability.py`、`harness/compaction.py`、`harness/provider_catalog.py` 为准。

## 优先级定义

| 级 | 含义 |
| --- | --- |
| **P0** | 缺了就挡住三部门日常使用（建事项、跑循环、取消、看失败、压缩、提交/质检） |
| **P1** | 明显提升日常体验或 Stage 2 完成标准要求，但现有路径已能工作 |
| **P2** | 锦上添花；规模/体验优化 |
| **P3** | Yudao 架构拒绝，或已由 S4-A / Stage 3 明确不采用、不搬 |

Stage 3 项（MCP、第二协议、`--resume`/`--continue`、技能发现、区间编辑、受控 shell、`grep`/`glob`）**一律不是 Stage 2 P0**。

---

## 2.4.3 假说核对（先于标 P0）

计划举例「任务搜索、SSE、错误文案、查询性能」是假说。对照当前 Yudao：

| 假说 | 实际 | 结论 |
| --- | --- | --- |
| 任务搜索/筛选缺失 | 侧栏 `filteredProjects()` 按项目名/`project_id` 过滤（`app.js`）；观测页 `department`/`status`/`q`/`work_item` 过滤，后端 `ObservabilityQuery.list_model_attempts`；事项看板按部门列。缺的是跨项目事项全文检索，不是「不能找任务」 | **不是 P0**。事项标题搜索属 P2 |
| 实时日志流（SSE）缺失 | `GET /api/projects/{id}/stream` 与 `GET /api/runs/{id}/stream` 为 `text/event-stream`；`Last-Event-ID` 游标、keepalive；前端 `EventSource` + 5s 轮询兜底（`app.js` `openStream`） | **不是 P0**。客户端未把 `Last-Event-ID` 写回重连属 P2 |
| 错误提示不可用 | `ProviderError.reason/retryable/diagnostics`（脱敏后进事件）；HTTP 带 `reason`（`busy`/`run_terminal`/`provider_unavailable`/`cancelled_input_not_saved`）；UI `dw-action-error`、对话框 `role=alert`、`execution_error`、观测失败态与事件摘要 | **不是 P0**。观测详情头未突出 `diagnostics` 分类属 P1 展示 |
| 查询速度挡住使用 | `events(run_id, seq)`、`project_events(project_id, seq)` 有索引；列表默认 `limit=50`、cursor 分页；用量按完整筛选集汇总、不按当前页截断 | **不是 P0**。项目级 attempts 先在内存合并再分页，事项很多时属 P2 |

以上四项 **不进入 Stage 2 P0 实现清单**。

---

## 对比总表

状态：`have` = 日常路径已有等价；`partial` = 内核或查询有、界面/完整度不够；`missing` = 无等价。优先级按上表。

### 1. 任务管理

| OMP 能力 | OMP 锚点 | Yudao 现状 | 状态 | 优先级 |
| --- | --- | --- | --- | --- |
| 创建会话/任务 | TUI / `prompt` RPC | `POST /api/projects`、`POST .../work-items` → `LoopSystem.create_run` | have | — |
| 取消 | RPC `abort`、`runSignal` | `POST /api/runs/{id}/cancel` → `orchestrator.cancel`；适配器 `abort` | have | — |
| 历史列表 | 会话文件 / resume 选择器 | 项目列表、事项看板/流转、`GET /api/runs` | have | — |
| 项目内搜索 | TUI 会话/文件搜索 | 项目名搜索 + 观测 `q`；无事项全文索引 | partial | P2 |
| 追加用户原文 | steering / 新 prompt | `POST .../inputs`；产品必须收进有效 PRD | have | — |
| 部门定向指导 | 无对等合同；OMP 是会话 steering | `POST .../departments/{d}/guidance` | have | — |
| 同时多活动 run | 多 session / `task` 子 Agent | 进程内一活动 run（`BusyError` 409） | have（有意收窄） | P3 |
| `--resume` / `--continue` | `main.ts`、`session-paths.ts` | `replay` 只重放投影；进程死后须新执行 | missing | P3（Stage 3.1，非 Stage 2 P0） |

### 2. 模型配置

| OMP 能力 | OMP 锚点 | Yudao 现状 | 状态 | 优先级 |
| --- | --- | --- | --- | --- |
| Provider+模型+窗口目录 | `catalog` `Model` | `ProviderCatalog` JSON：providers/models/bindings | have | — |
| 角色/部门绑定 | `model-roles`（smol/slow/…） | 三部门冻结绑定；创建事项时 snapshot | have | — |
| 宿主凭据 | env / auth storage | `credential_ref` → 环境变量；密钥不进文件/事件 | have | — |
| 配置界面 | TUI 模型切换 | 后端目录 + `/api/health` 只读绑定；**无** `/api/providers` CRUD。原型在 `docs/prototypes/provider-config/`（2.2） | missing（UI） | P1（2.2，非 2.4 新开） |
| 连接测试 | 登录/刷新 | 计划 2.2 `POST /api/providers/{id}/test`；现网未实现 | missing | P1（2.2） |
| 缺绑定拒绝创建 | 认证回退到父模型（不采用） | `start_work_item` 查 `provider_status`；缺绑定/凭据/容量 → 503 | have | — |
| 第二协议 | 14 种 `KnownApi` | 仅 `responses` + 测试 `fake` | missing | P3（Stage 3.3） |
| 思考等级/推理预算 | `ThinkingLevel` / `Effort` | 无绑定级思考字段；思考 token 计入 `max_output_tokens` | missing | P3（Stage 3.3；不作 Stage 2 P0） |
| 会话内换模型 | `set_model` | run 创建冻结；事项级换模 = 新 run | have（拒绝热换） | P3 |

### 3. 上下文与压缩

| OMP 能力 | OMP 锚点 | Yudao 现状 | 状态 | 优先级 |
| --- | --- | --- | --- | --- |
| 自动压缩 | `shouldCompact` | `plan_compaction`：输入将吃进输出预留则摘要 | have | — |
| 切点不切断工具回合 | `findCutPoint` 排除 `toolResult` | `compaction.py` 无未完成 tool 边界则不切 | have | — |
| 失败摘要不进历史 | 远端回退另说 | `finish_compaction` 失败不进有效历史 | have | — |
| 按真实窗口规划 | OMP 未知窗口可 fallback 200k | D18：未知 `context_window` 拒绝，不借用 | have | — |
| Context 只读查询 | Stats 详情不完整 | 部门检查区 Context 快照 + parts；`observability.department` / attempt `context` | have | — |
| 摘要来源展开 / 精确跳转 | 会话条目链 | 来源列表 + digest；跳到对应 attempt。原型 W3 部分 OPEN（超长 Raw 滚动等） | partial | P1（2.3） |
| 远端压缩 / Snapcompact | `compaction-methods.ts` | 固定部门冻结模型 | missing | P3 |

### 4. 工具执行

| OMP 能力 | OMP 锚点（`builtin-names.ts`） | Yudao 现状 | 状态 | 优先级 |
| --- | --- | --- | --- | --- |
| 整文件读/写 | `read` / `write` | `read_file` / `write_file`（工程写） | have | — |
| 列目录 | `read` 对目录；无独立 `ls` | `list_files` 前缀列举 | have | — |
| 删除/移动 | 无独立 builtin | `delete_file` / `move_file` + 计划范围 | have | — |
| 检查/证据 | bash 通用执行 | `run_check` / `collect_evidence`（预绑定 argv，副本 cwd） | have | — |
| 部门提交合同 | 无 | `submit_*`（PRD/计划/交付/质检/协作） | have | — |
| Git 版本 | 经 `bash` | 非模型工具：`GitVersionStore` 绑正式事件；查询可展开 | have | — |
| 区间 `edit` / `grep` / `glob` | `edit` `grep` `glob` | 无 | missing | P3（Stage 3.2） |
| 通用 `bash` | `bash` | 无任意 shell | missing | P3（Stage 3.2） |
| MCP | `mcp__*` | 无 | missing | P3（Stage 3.2） |
| 并行工具批次 / IRC `hub` | `task` `hub` | 工具串行；无 hub | missing | P3 |
| computer-use / `xd://` | `computer` | 无 | missing | P3 |

三部门日常闭环不依赖 grep/bash/MCP：工程改工作区文件 + 预绑定检查 + 质检放行已经闭合。

### 5. 观测（请求 / 用量 / Context / Trace）

| OMP 能力 | OMP 锚点 | Yudao 现状 | 状态 | 优先级 |
| --- | --- | --- | --- | --- |
| 逻辑调用 + 物理尝试身份 | Stats 数字 row id（不采用） | `logical_call_id` / `attempt_id`；requested vs actual | have | — |
| 失败可见、部分流不进历史 | run-collector 缺 usage 填 0（不采用） | `MODEL_ATTEMPT_FAILED`；部分流工件；`reported=False` 不填零 | have | — |
| 查询不推进 | Stats 读 SQLite | 观测 API 只读；`POST .../replay` 不跑模型 | have | — |
| 请求列表筛选/分页 | Stats recent | 部门/状态/`q`/事项 + cursor；默认 50 | have | — |
| 用量分组与覆盖率 | 独立 Stats 库 | `model-usage`：部门/Provider/模型；覆盖率可见 | have | — |
| Trace 时间线 / 重试关系 | OTEL spans（不采用） | 详情 siblings 按 attempt 排序；lifecycle 事件；非 OTEL | have | — |
| Context ↔ 请求互跳 | getRequestDetails TODO | Context「查看模型请求」；详情返回部门 | have | — |
| 导出 | JSONL / stats | `GET /api/runs/{id}/export` | have | — |
| 失败分类展示 | TUI 错误条 | 事件 `reason`/`retryable`/`diagnostics` 在原文里；列表主要是状态色 | partial | P1（展示，2.3） |

### 6. 界面体验

| OMP 能力 | OMP 锚点 | Yudao 现状 | 状态 | 优先级 |
| --- | --- | --- | --- | --- |
| 主界面 | TUI | Web 工作台（总览 / 三部门 / 观测） | have（产品选择不同） | P3（不搬 TUI） |
| 实时更新 | TUI 差分渲染 | SSE + 5s 刷新 | have | — |
| 响应式 | 终端宽 | CSS：1440 三栏、窄屏堆叠、390 单列、16px 输入防 iOS 缩放 | have | — |
| 错误反馈 | TUI 提示 | 操作错误条、对话框 alert、空态「重新读取」 | have | — |
| 草稿隔离 | 会话本地 | 任务/部门草稿；刷新保路由 | have | — |
| Provider 配置页 | 模型选择器 | 只读检查区快照；可写配置页属 2.2 | missing | P1（2.2） |

---

## P0 清单（Stage 2 内由 2.4 补齐）

**空。**

没有一项 OMP 能力同时满足：Yudao 缺失 **且** 挡住三部门日常使用 **且** 不属于 2.1/2.2/2.3 已排工作 **且** 不属于 Stage 3。

2.4.3 举例（搜索、SSE、错误文案、查询性能）已在现码中具备日常路径，见上文核对。真实验收与 TLS 稳定性是 **2.1**，不是功能缺口。Provider 表单是 **2.2**。Context/Trace 收口是 **2.3**。

「P0 缺失全部补齐」在本审查下成立为：**无额外 P0 要实现。**

---

## P1 计划（2.4.4）

| 项 | 现状 | 是否纳入 Stage 2 | 归属 | 说明 |
| --- | --- | --- | --- | --- |
| Provider 增删改查 + 三部门绑定 + 连接测试 | 目录内核有，Web CRUD 无 | **是** | **2.2** | Stage 2.6「配置可通过界面完成」。原型已在 `docs/prototypes/provider-config/`。2.4 不另开实现 |
| Context 来源展开 / 压缩覆盖 / 精确 attempt | 检查区 + observability 主线有；原型 W3 部分 OPEN | **是** | **2.3** | 失败可追溯的完成标准走 2.3，不在 2.4 重做查询 |
| Trace：重试链、失败分类、部分输出 | 详情 siblings + 事件原文有；头栏分类偏弱 | **是** | **2.3** | 把已有 `reason`/`diagnostics` 露到详情头即可，无需新事实源 |
| 请求列表筛选/分页/用量同口径 | 后端已同 FilterSpec | **是（收口）** | **2.3.4** | 主线已有；联调属 W7/2.6 |
| 桌面 1440 + 手机 390 | 已有响应式 CSS | **是（验收）** | **2.3 / 2.6** | 不是缺能力 |
| 观测失败原因更可读 | 数据有、展示弱 | 可随 2.3；不单独立项 | 2.3 | P1 展示，非新模块 |
| Prompt 减少无效往返 | 三部门 Prompt 已冻结版本 | **是** | **2.5** | 不是 OMP 功能对齐 |

**推迟（P1 能力但不是 Stage 2 基线）：** 无必须进 Stage 2 的 2.4 新功能。思考等级、第二协议、resume、技能、MCP、grep/edit/bash 全部 **Stage 3+**，本表标 P3 以免被当成 Stage 2 P1 施工。

粗估（仅 2.4 自身）：审查与优先级 **已完成**；2.4 不再排实现日。2.2/2.3/2.5 仍按其计划天数。

---

## P2（后续可做，不挡 Stage 2）

- 事项标题/正文搜索（侧栏目前只搜项目名）。
- SSE 重连携带 `Last-Event-ID`（现有 EventSource + 轮询已够用）。
- 项目级 attempts 改为存储层过滤，避免事项极多时内存合并。
- 观测详情默认展开失败 `diagnostics`（若 2.3 未做）。

---

## P3（架构拒绝，不对齐）

与 S4-A「未采用」及 Stage 3 差距表第 13 节一致：

- OAuth 运行时、模型自动发现、认证政策引擎  
- 适配器内部重试、key 轮换、strict-tools / reasoning fallback、`previous_response_id`（D17：`max_retries=0`，内核有界尝试）  
- 远端压缩回退、Snapcompact、分支摘要、append-only KV 作第二事实源  
- 独立 Stats 库、OTEL 作为领域事实、数字 row id  
- 并行工具批次原样、steering 硬中断、IRC/`hub`  
- computer-use、`xd://`、宽松参数校验、yolo 默认放开  
- 未知窗口套默认 200k（D18 必须显式容量）  
- 主界面改成 OMP TUI（Yudao 主界面是 Web）

---

## 明确排除的 Stage 3 项（禁止标 Stage 2 P0）

| 项 | Stage 3 包 | 本表 |
| --- | --- | --- |
| MCP 客户端 | 3.2 | P3 |
| 第二协议适配器 | 3.3 | P3 |
| `--resume` / 中断后续行 | 3.1 | P3 |
| 技能 `SKILL.md` / 斜杠 | 3.5 | P3 |
| `edit` / `grep` / `glob` / 受控 shell | 3.2 | P3 |
| 思考等级 | 3.3 | P3 |
| 扩展 hook / 自定义工具 | 3.7 | P3 |

---

## 与「核心功能不弱于 OMP」的读法

OMP 核心是单 Agent 编码循环（TUI + 大工具面 + 会话文件）。Yudao Stage 2 核心是 **三部门合同循环 + Web 工作台 + 尝试级观测**。弱于 OMP 的是编码工具面和会话恢复，那是 Stage 3；日常三部门路径（建事项、冻结 Provider、压缩、工具准入、取消、Context/Trace 查询、SSE）在当前 HEAD 上 **已有等价或主线**。剩下挡住「日常好用」的是 2.1 真实验收、2.2 配置界面、2.3 原型收口，不是 2.4 再搬一套 OMP 运行时。
