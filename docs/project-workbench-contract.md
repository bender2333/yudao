# B0 合同一页：项目、事项与部门 Prompt 项目配置

日期：2026-09-09。依据：[第二阶段重新排布](stage-2-replan-2026-09-09.md) 第 2–3 节的决定 D-A～D-J、[第三版原型](prototypes/2026-09-09/README.md)、[部门 Prompt 配置约定](prototypes/2026-09-09/department-prompt-configuration.md)、[原生项目演化设计](research/native-project-evolution-design.md) §3/§5/§6/§7。

用户已确认（2026-09-09）：轨道 A 与 B 并行；旧 `.yudao/*` 运行数据随新作用域直接弃用，不迁移、不加读入口；D-H 首批无活跃事项时的部门输入只"作为新事项开始 / 记录原文"，不做模型对话；实施交给子代理。

本页是实现前的合同：每个字段写明来源事件，每条命令写明写哪条流。实现不得增加本页没有的隐式行为；发现本页缺漏，先改本页再写代码。

## 1. 分层与责任

| 层 | 模块 | 责任 | 不做 |
| --- | --- | --- | --- |
| 运行内核（现有） | `orchestrator.py`、`context.py`、`validation.py`、`workspace.py`… | 一次 run 的部门交接、停止、合同、QA、封存、run 内 Git、重试。新增：接受归属参数并写入 `RUN_CREATED`；接受初始工作树并在建工作区前落盘；接受项目上下文材料并作为钉住材料装配 | 不知道"项目当前成果"、不做采纳、不读项目流 |
| 项目层（新增） | `harness/projects.py`（一个模块：服务 + 投影） | 项目登记、事项创建（含建其主 run）、采纳结算、继承恢复、部门 Prompt 项目配置、项目材料记录、项目读模型 | 不生成运行事实、不改 run 流、不调用模型 |
| 查询与 API | `web/server.py`、`observability.py`、`views.py` | `/api/projects…` 路由：命令转交项目层，只读查询拼装 | 不写事件 |
| 工作台 | `web/static/` | 第三版外壳 | 见 B3 |

项目层只通过 `Orchestrator.create_run(...)` 与内核交互，且只在事项创建时。项目层读 run 投影（`project_run`）和 run 工件（`ArtifactStore.get_for_run`），不读 run 内部状态锁。

## 2. 身份

| 对象 | 标识 | 生成 |
| --- | --- | --- |
| 项目 | `proj_<16hex>` | `new_id("proj")`，登记时生成 |
| 事项 | `wi_<16hex>` | `new_id("wi")`，创建时生成 |
| 采纳记录 | `adopt_<16hex>` | `new_id("adopt")`，结算时生成 |
| run | `run_<16hex>` | 内核现有；事项创建时由项目层预生成并传入 `create_run(run_id=...)` |

项目身份只来自 `project_registered` 事件。目录名、最新 DONE 的 run、聊天会话都不是项目身份。

## 3. 项目流：`project_events` 表

新增 SQLite 表，与 `events` 表同库、同连接、同 WAL：

```
project_events(event_id TEXT PK, project_id TEXT, seq INTEGER, type TEXT,
               payload_json TEXT, created_at TEXT, UNIQUE(project_id, seq))
```

`EventStore` 新增 `append_project(project_id, type, payload) -> ProjectEvent`、`list_project_events(project_id, after_seq=0)`、`list_project_ids()`（按最近写入排序）、`get_project_event(event_id)`。`seq` 按项目递增，与 run 流的 `seq` 无关。不给 `events` 表加列，不让项目事件进入 `events` 表、`iter_all()` 或 `project_run`。

事件类型（常量放在 `harness/projects.py` 的 `ProjectEventType`）：

| 类型 | 写入者（命令） | payload 字段 |
| --- | --- | --- |
| `project_registered` | 登记项目 | `name`、`goal`（原文）、`goal_ref`（工件，`text/markdown`，按 `project_id` 作用域存放）、`source: "idea"` |
| `project_renamed` | 重命名 | `name` |
| `project_pinned` | 置顶/取消 | `pinned: bool` |
| `project_archived` | 归档 | — |
| `project_restored` | 恢复 | — |
| `work_item_created` | 创建事项 | `work_item_id`、`title`、`text`（用户变更原文，即 run 的 task）、`run_id`、`baseline`（见 §7；无则 `null`）、`project_context_ref`、`prompt_config_versions: {department: int}`、`max_cycles`、`context_window` |
| `work_item_start_failed` | 创建事项时 `create_run` 抛错 | `work_item_id`、`run_id`、`error` |
| `deliverable_adopted` | 结算 | `adoption_id`、`work_item_id`、`run_id`、`delivery_event_id`、`qa_event_id`、`tree_ref`、`code_tree_digest`、`summary`、`files`、`check_names`、`known_risks`、`previous_adoption_id` |
| `adoption_held` | 结算 | `work_item_id`、`run_id`、`delivery_event_id`、`code_tree_digest`、`reason: "baseline_changed"`、`expected_adoption_id`、`current_adoption_id` |
| `department_prompt_configured` | 保存部门 Prompt 配置 | `department`、`version`、`text`、`prompt_ref`、`base_version` |
| `material_recorded` | 记录原文（D-H） | `material_id`、`text`、`material_ref`、`department`（来自哪个部门输入框，可 `null`） |

工件作用域：项目层的工件（goal、Prompt 配置、材料）用 `ArtifactStore.put(project_id, kind, ...)`，作用域键就是 `project_id`；`ArtifactStore` 现有校验只要求单一路径分量，`proj_…` 直接可用，不另建一套存储。事项的项目上下文材料是 run 工件（§5），因为它属于那一次 run 的模型输入。

## 4. run 归属：`RUN_CREATED` 与 `RunProjection`

`Orchestrator.create_run` 新增仅关键字参数（都可为 `None`；内核层 bare run 仍允许，供内核测试与 smoke 使用；产品入口只经项目层创建）：

| 参数 | 写入 `RUN_CREATED.payload` | `RunProjection` 字段 |
| --- | --- | --- |
| `project_id: str | None` | `project_id` | `project_id: str | None` |
| `work_item_id: str | None` | `work_item_id` | `work_item_id: str | None` |
| `baseline: dict | None` | `baseline` = `{adoption_id, source_run_id, delivery_event_id, tree_ref, code_tree_digest}` | `baseline: dict | None` |
| `initial_tree: CapturedTree | None` | 不写树本身；`workspace_digest` = 落盘后 `capture_public_tree(workspace).digest`（无树时为空目录 digest） | `workspace_digest: str` |
| `project_context: str | None` | `project_context_ref`（工件，`text/markdown`，run 作用域） | `project_context_ref: dict | None` |
| `department_prompts: dict[str, str] | None` | 替代 `DEFAULT_PROMPTS` 作为 run 初始 Prompt 文本（`InteractionWriter.initial` 接受该参数）；另写 `prompt_config_versions: {department: int}` | `prompt_config_versions: dict[str, int]` |

规则：

- `project_id`/`work_item_id`/`baseline`/`project_context`/`department_prompts` 要么全给（项目层调用），要么全不给（bare run）；混给抛 `ValueError`。
- `initial_tree` 给出时，内核在 `Workspace(...)` 之前调用 `materialize_tree(tree, workspace_root / run_id)`；目标目录已存在则抛错，不覆盖。`materialize_tree` 已自带落盘后核验。
- `baseline.code_tree_digest` 必须等于 `initial_tree.digest`，否则 `ValueError`（项目层传错不能静默）。
- POST `/api/runs` 在 B3 外壳切换时删除（B1 期间保留，避免旧外壳在 B1 与 B3 之间不可用；规则 3）。`GET /api/runs`、`/api/runs/{run_id}/…` 保留为 run 级只读查询与 run 级命令（inputs / prompts / guidance / cancel），供部门页与观测使用。

## 5. 项目上下文材料（钉住部件 `project`）

项目层在创建事项时生成一段确定性 Markdown（同输入同字节），存为 run 工件 `project_context_ref`，内核在 `ContextAssembler.assemble` 的钉住部件中、`current_work` 之后插入 `ContextPart("project", <content_hash 前 12 位>, text)`。所有部门、所有请求都带；压缩请求的钉住材料同样包含它（它属于 pinned_input）。

内容（顺序固定，无则写"无"）：

```
项目：<name>
长期目标：<goal 原文>
当前采用成果：<无（这是项目的第一个事项）| 来自事项「<title>」（run <run_id>，采纳 <adoption_id>）：<summary>；文件：<files>；检查：<check_names>；已知风险：<known_risks>。本 run 工作区已从该成果的完整封存恢复，digest <code_tree_digest>。>
已采纳事项：<按采纳顺序 1..n："<title>" — <summary>> | 无
本事项：<title>
```

不放历史对话、失败尝试、过时计划（2.E §6）。`smoke.py` 的输入审计把 `project` 部件视为合法钉住材料。

## 6. 项目投影 `ProjectProjection`（从 `project_events` 重建，再读所属 run 投影派生）

| 字段 | 来源 |
| --- | --- |
| `project_id`、`name`、`goal`、`goal_ref`、`created_at` | `project_registered`；`name` 被 `project_renamed` 覆盖 |
| `pinned`、`archived` | `project_pinned` / `project_archived` / `project_restored` 最后一条 |
| `work_items: list[WorkItem]` | 每条 `work_item_created` 一项；字段见 §7 |
| `current_adoption: Adoption | None` | 最后一条 `deliverable_adopted` |
| `adoptions: list[Adoption]` | 全部 `deliverable_adopted`，按 seq |
| `held: list[HeldCandidate]` | 全部 `adoption_held` |
| `prompt_configs: {department: PromptConfig}` | 每部门最后一条 `department_prompt_configured`；无则 `version=0, text=DEFAULT_PROMPTS[department], source="default"` |
| `prompt_config_history: list[PromptConfig]` | 全部 `department_prompt_configured` |
| `materials: list[Material]` | 全部 `material_recorded` |
| `updated_at`、`last_seq` | 最后一条项目事件 |

派生（不存事件，读所属 run 的 `project_run`）：

| 字段 | 派生规则 |
| --- | --- |
| `WorkItem.status` | `not_started`：run 无事件；`in_progress`：run 非终态；`adopted`：有该 run 的 `deliverable_adopted`；`held`：有 `adoption_held`；`released_unsettled`：run DONE 且两者都无（结算未跑）；`stopped`：run PAUSED/FAILED |
| `WorkItem.department` | run 阶段：PRODUCT_SPEC/REWORK_PRODUCT→product；ENGINEERING/REWORK_ENGINEERING→engineering；DELIVERY/QUALITY→quality；终态→`null` |
| `WorkItem.phase`、`stop_reason`、`human_action`、`cycle_count` | run 投影同名字段 |
| `WorkItem.last_handoff` | run 最后一条 `transition` 事件：`{from, to, seq, at}` |
| `WorkItem.rework` | run 全部 `qa_submitted` 中 verdict 为 rework_* 的记录：`{verdict, seq, at, summary}` 列表 |
| `WorkItem.pending_question` | run `pending_request`（专家请求）或 `waiting_reason` 摘要，供概览"待决" |
| `active_work_item_id` | `status == in_progress` 的事项（单工作进程下最多一个） |
| `overview.recent` | 项目事件与所属 run 的 `transition`/`run_done`/`run_failed`/`run_paused` 合并按时间倒序取 20 条 |

投影必须能在删除任何派生缓存后仅由两张表重建；`replay` CLI 对项目给出同样保证。

## 7. 事项创建、基线与继承

`ProjectService.start_work_item(project_id, text, *, title=None, max_cycles=8, context_window=32_000) -> (work_item_id, run_id)`：

1. 项目必须存在且未归档。`settle_pending(project_id)`（§8）先跑一遍，保证基线是最新的。
2. `title` 缺省取 `text` 首行截断 40 字。
3. `baseline`：`current_adoption` 为空 → `null`，工作区为空目录；否则 `{adoption_id, source_run_id, delivery_event_id, tree_ref, code_tree_digest}`，并 `load_tree(artifacts, source_run_id, tree_ref)` 得到 `initial_tree`，核对 `digest == code_tree_digest`。
4. `department_prompts` 取 `prompt_configs[dept].text`；`prompt_config_versions` 取其 `version`。
5. 生成 `project_context`（§5）。
6. 先写 `work_item_created`（含预生成 `run_id`），再 `orchestrator.create_run(text, run_id=..., project_id=..., work_item_id=..., baseline=..., initial_tree=..., project_context=..., department_prompts=..., max_cycles=..., context_window=...)`。`create_run` 抛错则写 `work_item_start_failed` 并重新抛出；该事项状态为 `not_started`，可再次创建新事项。
7. 返回后由调用方（Web 工作进程）执行 `run_until_stop`。首批仍是每进程一个活动 run（`LoopConsoleServer` 现有 BusyError 语义），活动 run 未停前创建事项返回 409 busy。

不做：同一事项追加第二个 run；项目级 Git；部门在无 run 下对话。

## 8. 采纳结算 `settle(run_id)`

幂等；由 Web 工作进程在 `run_until_stop` 返回后调用，也在 `start_work_item` 与 `GET /api/projects/{id}` 读取时通过 `settle_pending(project_id)` 补跑（覆盖进程中断在 RUN_DONE 与结算之间的情形）。

| 条件 | 结果 |
| --- | --- |
| run 非 DONE，或 run 不属于任何事项 | 无事件 |
| 该 run 已有 `deliverable_adopted` 或 `adoption_held` | 无事件 |
| run DONE 且 `work_item.baseline.adoption_id`（`null` 视为"无基线"）== `current_adoption.adoption_id`（无则 `null`） | 写 `deliverable_adopted`：取 run 最后一条 `delivery_accepted` 的 `tree_ref`/`code_tree_digest` 与 `DeliverySpec` 的 `summary`/`files`/`check_names`/`known_risks`，`qa_event_id` 为放行的 `qa_submitted` |
| run DONE 且基线不等 | 写 `adoption_held`，项目 `current_adoption` 不变 |

取消/失败/暂停的 run 不结算，事项显示原停止原因。采纳不等于部署，不修改任何外部目录。

## 9. 部门 Prompt 项目配置

- 版本空间：`config_version`（项目，`department_prompt_configured.version`，从 1 起；未配置为 0 表示默认）与 run 内 `prompt_version`（现有）分开命名，界面不混用。
- 保存：`configure_prompt(project_id, department, text, base_version)`：`text` 去空白为空 → `ValueError`（400）；`base_version != current.version` → `PromptConfigConflict`（409，响应带当前配置）；`text == current.text` → 不写事件，返回当前（200，`unchanged: true`）；否则 `version = current.version + 1`，工件 `save_department_prompt(artifacts, project_id, department, text)`，写事件。
- 读取：返回 `{department, text, default_text: DEFAULT_PROMPTS[department], version, updated_at, source: "default" | "configured"}`。
- 固化：`start_work_item` 把当时 `text` 传入 `create_run(department_prompts=...)`，run 内初始 `prompt_version = 1`、文本等于配置文本，`RUN_CREATED.payload.prompt_config_versions[dept]` 记来源版本。之后修改项目配置不影响该 run；run 内 `update_prompt` 只改本 run。
- 检查区数据：部门页 Prompt 页签同时拿 `GET /api/projects/{id}/prompts/{dept}`（项目当前配置）与所选请求的 `model_input`/`department_activated.prompt_version + prompt_hash`（实际采用，现有观测数据），不从当前配置回填。

## 10. D-H：无活跃事项时的部门输入

部门页输入框在项目没有 `in_progress` 事项时提供两项：`作为新事项开始`（= §7）与 `记录原文`（= `POST /api/projects/{id}/materials`，写 `material_recorded`，`department` 记来源部门）。不调用模型，不生成部门回应。有活跃事项时输入框走现有 run 级 `inputs`/`guidance`。

## 11. API 清单

所有错误体沿用 `{"error", "reason"?}`；`project not found` 404；归档项目上的写命令 409 `reason: "project_archived"`。

| 方法 路径 | 请求体 | 成功响应 | 写入 |
| --- | --- | --- | --- |
| `GET /api/projects` | — | `{projects: [{project_id, name, pinned, archived, created_at, updated_at, work_item_count, active_work_item_id, current_adoption: {adoption_id, summary, adopted_at} | null}]}`；置顶优先、再按 `updated_at` 倒序；`?archived=1` 含归档 | — |
| `POST /api/projects` | `{name, goal}` 均非空 | 201 `{project_id}` | `project_registered` |
| `GET /api/projects/{id}` | — | `ProjectProjection.to_dict()` + `overview: {goal, current_adoption, pending: [...], recent: [...]}`；读取前跑 `settle_pending` | 可能补写结算事件 |
| `POST /api/projects/{id}/rename` | `{name}` | 200 | `project_renamed` |
| `POST /api/projects/{id}/pin` | `{pinned: bool}` | 200 | `project_pinned` |
| `POST /api/projects/{id}/archive` / `restore` | — | 200 | `project_archived` / `project_restored` |
| `POST /api/projects/{id}/work-items` | `{text, title?, max_cycles?, context_window?}` | 201 `{work_item_id, run_id, phase}`；409 busy；503 provider 不可用（沿用现有） | `work_item_created`（+ 内核 `RUN_CREATED`） |
| `GET /api/projects/{id}/work-items/{wid}` | — | `WorkItem.to_dict()` + `handoffs: [所有 transition]` + `rework` + `adoption | held` + `run: {run_id, phase, outcome, stop_reason}` | — |
| `GET /api/projects/{id}/board` | — | `{work_items: [WorkItem 摘要]}`，流程图与看板同一份 | — |
| `GET /api/projects/{id}/departments/{dept}` | `?work_item=` 可选 | 无参数：`{department, project_id, prompt_config: {version, source}, items: [{work_item_id, title, status, view: observability.department(run_id, dept)}]}` 按事项倒序；有参数：只含该事项 | — |
| `GET /api/projects/{id}/prompts/{dept}` | — | §9 读取体 | — |
| `PUT /api/projects/{id}/prompts/{dept}` | `{text, base_version}` | 200 `{...读取体, unchanged: bool}`；400 空白；409 `{error, reason: "prompt_config_conflict", current: 读取体}` | `department_prompt_configured` |
| `POST /api/projects/{id}/materials` | `{text, department?}` | 201 `{material_id}` | `material_recorded` |
| `GET /api/projects/{id}/model-attempts` | 现有 `department/status/q/cursor/limit` + `work_item` | `{items: [...现有摘要 + run_id + work_item_id + title], next_cursor}`；跨该项目所有 run 合并、按时间倒序；`cursor` 不透明 | — |
| `GET /api/projects/{id}/model-usage` | 同上 | 现有用量体 + `by_work_item`；未上报用量保持未知 | — |
| `GET /api/projects/{id}/stream` | `after_seq` / `Last-Event-ID` | SSE：`event: project`（项目事件卡）与 `event: loop`（所属 run 的事件卡，data 含 `run_id`、`work_item_id`）；`id` 用 `"<project_seq>:<run_id>:<run_seq>"` 形式的游标或等价不透明串 | — |
| `POST /api/runs` | 保留至 B3 外壳切换时删除 | — | 内核 `RUN_CREATED`（bare run） |

现有 `GET /api/runs/{run_id}/...`、`POST /api/runs/{run_id}/{inputs,prompts,guidance,cancel}` 不变。`GET /api/health` 增加 `active_project_id`、`active_work_item_id`。

CLI（只读）：`python -m harness project list`、`python -m harness project show <project_id>`（打印投影 JSON）；`replay` 支持 `--project <project_id>`。

## 12. 隔离与不变量

1. 任何项目查询只读 `project_events WHERE project_id = ?` 与 `work_items[].run_id` 指向的 run；不用全表扫描猜归属。
2. 两个项目的事项、采纳、Prompt 配置、材料互不可见；同名项目允许（身份是 id）。
3. run 工件跨项目读取只发生在 `start_work_item` 读源 run 的封存树（项目层行为，且源 run 必须属于同一项目）。
4. 项目事件不改写 run 事件；结算只追加。
5. 重放：`ProjectProjection` 由 `project_events` + `project_run(run_id)` 完全重建，与在线状态 `canonical_state()` 一致。
6. 归档项目只读：写命令 409；仍可查询与恢复。
7. 删除派生缓存（若实现引入任何缓存）不改变任何查询结果。

## 13. 反例清单（B1 实现必须全部成为正式测试）

- 同一项目两事项：事项 2 的 run 工作区 `capture_public_tree` 与事项 1 采纳树逐字节一致；事项 2 交付后 `current_adoption` 指向新版本，`adoptions[0]` 仍可 `load_tree` 取回。
- 事项 B 在 A 采纳前创建（`baseline = null`），A 采纳后 B 放行 → B `adoption_held`，`current_adoption` 仍是 A，`held[0].reason == "baseline_changed"`。
- 取消 / max_cycles 暂停 / provider 失败的 run：事项 `status == stopped`，`stop_reason` 与 run 一致，无采纳事件。
- 两个项目各一事项：`GET /api/projects/{a}` 不含 `b` 的任何 id；`model-attempts` 按项目过滤。
- 事件重放：对任一项目 `ProjectProjection` 从两表重建结果 `canonical_state()` 与在线一致。
- `create_run` 混给归属参数 → `ValueError`；`baseline.code_tree_digest` 与 `initial_tree.digest` 不等 → `ValueError`；工作区目录已存在 → 抛错不覆盖。
- 项目上下文部件：每个部门首次请求的 `input_items` 中 `[project]` 出现在 `[current_work]` 之后、`[department_rules]` 之前；压缩请求的 pinned_input 含它；smoke 审计对含 `project` 部件的 run 为 verified。
- Prompt 配置：保存 v1 → 同文本再保存不加版本 → 空白 400 → `base_version` 过期 409 且响应含当前配置 → 保存 v2 后新事项 run 的 `department_prompts[dept].text == v2 文本`、`prompt_config_versions[dept] == 2`，而 v1 期间创建的 run 请求正文不变。
- 归档项目：`work-items`、`prompts` PUT、`materials` 均 409；`restore` 后恢复可写。
- D-H：无活跃事项时 `materials` 写入 `material_recorded`，不产生任何 run 事件。
- `GET /api/runs` 仍列出 run（含项目 run 与 bare run）；`POST /api/runs` 的删除与其反例放到 B3。

## 14. 首批不做

项目级 Git 与分支；同一事项多 run；拖拽改看板状态；无 run 的部门模型对话；接入已有项目建档（B5）；Provider 配置 UI；跨项目复用成果；多进程并发 run。

## 15. 实施切分（对排布文档的修正）

- **B1（后端一次交付）**：`event_store.py` 项目表；`harness/projects.py`（`ProjectEventType`、`ProjectService`、`ProjectProjection`、`project_projection(store, artifacts, project_id)`）；`create_run` 归属参数与 `initial_tree`/`project_context`/`department_prompts`；`context.py` 的 `project` 部件；`models.py`/`projection.py` 的 run 归属字段；`smoke.py` 审计接受 `project` 部件；`web/server.py` 全部 `/api/projects…` 路由（`POST /api/runs` 保留到 B3）；`__main__.py` 只读 CLI；§13 全部反例。原排布中的 B2 后端并入 B1（同一模块、同一批事件），B2 不再单列。
- **B3（前端）**：第三版外壳，消费 §11 接口；Prompt 检查区按 §9 分开展示；D-H 两项入口。
- **B4（联调与真实验收）**：不变。
