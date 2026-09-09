# 恢复契约与故障矩阵

日期：2026-09-09。状态：3.0 准备包，未实施。

上位依据：

- [组织与持续运行研究](../research/organization-runtime-evolution.md) 第 6 节（四种能力、最小持久事实、外部动作契约、中断后续行）、第 10.1 节（故障矩阵十二项）、第 11 节（准备包）
- [第三阶段计划](../stage-3-plan.md) 第 5 节 3.0 / 3.1
- [总体路线图](../program-roadmap.md) 第 4 节（异步与恢复：重放状态、恢复订阅和恢复执行分别验收）
- [项目工作台合同](../project-workbench-contract.md)（B0：项目/事项/采纳结算的事件与幂等，是恢复的雏形）

本文对照 **harness_1 分支当前代码** 写现状，对照研究稿写 3.1 目标。不写实现代码，不设计 DSL。不确定处标「待核对」。

---

## 1. 四种恢复能力：现状与目标

研究 §6.1 把「读回同一段消息」排除在第三阶段恢复验收之外。Yudao 现有的 `replay` 与 SSE 重连分别对应前两种能力；控制恢复与动作恢复尚未作为独立入口存在。

### 1.1 事实重建

| 项 | 内容 |
| --- | --- |
| 做什么 | 读取事件和工件，重建当时与当前的领域状态 |
| 绝不隐含 | 不调用模型或外部工具，不恢复执行权限 |

**现状**

- 唯一事实源：`harness/event_store.py::EventStore` 的 `events` 表，`UNIQUE(run_id, seq)`，连接上 `PRAGMA journal_mode=WAL`。
- 工件：`harness/artifacts.py::ArtifactStore.put` / `get_for_run`，按内容哈希落盘。
- 公开树封存：`harness/tree_archive.py::store_tree` / `load_tree`；工作区快照：`harness/public_tree.py::capture_public_tree`。
- 重建入口：`harness/projection.py::project_run` → `project_events` → `apply_event`。`harness/runtime.py::LoopSystem.replay` 就是再调一次 `project_run`。
- Web 对照：`harness/web/server.py::LoopConsoleHandler._replay_run` 对同一 `run_id` 投影两次，比较 `RunProjection.canonical_state()`。
- 项目流：`SCHEMA` 已有 `project_events` 表与 `EventStore.append_project`；`RUN_CREATED` 已带 `project_id` / `work_item_id` / `baseline` 等字段（`harness/orchestrator.py::create_run`、`harness/projection.py::apply_event` 的 `RUN_CREATED` 分支）。`harness/projects.py` 尚不存在，B0 的 `ProjectProjection` / `settle` 未实现。

**目标（3.1）**

- 进程重启后，仅凭 `events` + 工件 + 工作区磁盘状态，得到与崩溃前最后一条已提交事件一致的 `RunProjection`。
- 新增的执行所有权、代次、未完成动作、等待项，同样只从事件重建，不读进程内 `_active` / `_snapshots`。

**绝不隐含**

- 投影一致不等于可以继续调用模型。
- `canonical_state()` 一致不等于外部子进程或工作区文件与事件对齐（见 §4 工具中断）。

### 1.2 观察恢复

| 项 | 内容 |
| --- | --- |
| 做什么 | 重连界面或通知订阅，补齐缺失变化 |
| 绝不隐含 | 不触发任务继续，不重复原消息的业务副作用 |

**现状**

- Run 级 SSE：`harness/web/server.py::LoopConsoleHandler._stream`，事件卡 `id` 为 `event.seq`；`_resume_seq` 优先读请求头 `Last-Event-ID`，否则读查询参数 `after_seq`。
- 只读：`store.list_events(run_id, after_seq=last)`，不调用 `run_until_stop`、不写事件。
- 测试名参考：`harness/tests/test_web.py::test_sse_resumes_from_after_seq_and_last_event_id`。
- B0 §11 规定项目流 SSE 的 `id` 为 `"<project_seq>:<run_id>:<run_seq>"`。当前 `_stream` 只服务 `/api/runs/{id}/stream`，项目流未实现。

**目标（3.1 / 观测扩展）**

- 观察重连只补事件；恢复命令是另一条写路径。
- 项目流游标与 run 流 `seq` 分开，重连不把失联当成执行失败（研究 10.1 第 9 项）。

**绝不隐含**

- 客户端收到 `keepalive` 或补齐历史，不等于 Worker 仍在跑。`LoopConsoleHandler._get_run` 用 `worker_active`（`active_run_id() == run_id`）表示本进程线程是否活着，与投影 `phase` 独立。

### 1.3 控制恢复

| 项 | 内容 |
| --- | --- |
| 做什么 | 加载合法版本、未完成工作、等待条件与资源账，决定下一项可做工作 |
| 绝不隐含 | 不意味着每个外部动作都可以重试 |

**现状**

- 进程内互斥：`Orchestrator._state_lock`（`RLock`）、`_active: dict[run_id, _Activation]`、`_abort: dict[run_id, threading.Event]`。`_activate_once` 若 `run_id in self._active` 则抛 `RuntimeError("run already has an active department invocation")`。
- Web 进程互斥：`LoopConsoleServer.start_run` 在 `_worker_lock` 下检查 `_worker.is_alive()`，活着则 `BusyError`。`_run_worker` 只调 `run_until_stop`，结束后不写项目结算。
- 取消：`Orchestrator.cancel` 置 `_abort`、对当前 activation 调 `adapter.abort`、写 `run_failed`（`stop_reason=cancelled`）。迟到提案：`_apply_proposal` 在锁内核对 phase / `input_version` / 合同哈希 / 计划哈希 / `request_id` / `request_basis`，不一致则 `PROPOSAL_REJECTED`（`execution_basis`）。
- 工具准入同样核对这些版本：`_begin_tool`、`_prepare_step`。
- **没有**跨进程执行代次、lease、或 `resume` 命令。进程退出后 `_active`、`_abort`、`_snapshots`、`SessionFactory._sessions` 全部消失。
- 冻结 Provider 快照只在进程内存：`create_run` 把 `ProviderCatalogSnapshot` 放入 `self._snapshots[run_id]`。重启后 `_prepare_activation` 若投影里有 `provider_snapshot.snapshot_id` 但 `_snapshots.get(run_id)` 为空，写 `run_failed` / `provider_credentials_lost`，文案是「create a new run」，不是续行。
- Stage 3 计划第 2 节对这一现状的表述：控制恢复缺失，进程中断只能「以明确关联的新执行继续」。

**目标（3.1）**

- 取得当前执行所有权后再决定下一步（研究 §6.4 步骤 1）。
- 从最后一致边界续行，而不是默认新建 run。
- 旧执行者的推进决定被拒；分派入口核对代次（研究 §6.4 末段：拒收结果还不够，还要挡住旧 Worker 再发外部动作）。
- 迟到的 `tool_called` / 提案 / 模型回执没有推进权，用量仍可入账（路线图第 4 节；研究 OR-08）。

**绝不隐含**

- 本进程 `_active` 为空不等于全局无执行者。
- `BusyError` 不等于跨进程所有权。
- 续行不等于重放 `department_activated` 之后未完成的模型调用。

### 1.4 动作恢复

| 项 | 内容 |
| --- | --- |
| 做什么 | 查询已发出动作的真实状态，复用确认结果、受控重试或补偿 |
| 绝不隐含 | 不把工具超时等同于未执行，也不声称通用 exactly-once |

**现状**

- 工具入口：`Orchestrator._begin_tool` → 写 `tool_started` → `harness/engine.py::run_department` 调 `ToolRuntime.execute` → `_record_observation` 写 `tool_called` 或 `tool_skipped`。
- `harness/tools.py::TOOL_DEFS` 现有工具：只读 `read_file` / `list_files`；工作区写 `write_file` / `delete_file` / `move_file`；主机检查 `run_check` / `collect_evidence`（`subprocess.run`，`CHECK_TIMEOUT_SEC=30`）；提交类 `submit_*`（无外部副作用，产出提案 payload）。
- 没有 shell、网络取回、MCP、发布。
- `run_check` / `collect_evidence` 在工作区副本上执行（`Workspace.check_copy`），回执追加写入工作区收据文件（`Workspace.record_check`），再随 `tool_called` 进入事件。没有按动作身份查询「子进程是否仍在、是否已退出」的接口。
- D17 重试只覆盖模型适配器失败：`run_department` 中 `MAX_PROVIDER_ATTEMPTS = 3`，事件 `model_attempt_failed` / `model_retry_scheduled`。SDK 侧 `ResponsesAdapter` 的客户端 `max_retries=0`。这不是外部动作核实。

**目标（3.1 对已有副作用；3.2 对新增工具）**

- 3.1：对「已 `tool_started`、无匹配 `tool_called`」的写文件与主机检查，规定查询/复用/重试/转人工的出口（见 §4、§6）。
- 3.2：无契约的副作用工具不得进入持久执行（Stage 3 计划 3.2）。

**绝不隐含**

- 工作区现在的文件内容，不能单独证明「这次 `write_file` 已成功提交」或「这次检查未发出」。
- `subprocess.TimeoutExpired`（exit 124）只说明宿主等够了 30 秒，不证明子进程从未产生副作用。当前检查在副本上跑，源工作区被改的条件是 `tree_changed` 为真；副本侧的部分写入在进程被杀时可能既无收据也无 `tool_called`。

---

## 2. 最小持久事实清单（研究 6.2）

研究要求持久保存：当前责任、有效任务与要求版本、已采用组织及技能版本、已完成成果、未完成动作、依赖、等待条件、取消请求、可继续权限、已消耗与预留资源、外部结果核实事项。

下表「已有」指 `apply_event` 能重建、或事件 payload 中已有的字段。「缺失」是 3.1 草案，只写事件名与字段，不写代码。

| 研究项 | 现状 | 3.1 需新增（草案） |
| --- | --- | --- |
| 当前责任 | 派生：`RunProjection.phase`、`active_department`、`pending_request`（`collaboration_requested` 把 `active_department` 设为 `recipient`）。没有独立的「责任人 / 责任代次」事件。 | 事件 `execution_lease_acquired`：`run_id`、`owner_id`、`generation`、`acquired_at`、`expires_at?`。事件 `execution_lease_released`：`generation`、`reason`。投影字段 `execution_owner`、`execution_generation`。 |
| 有效任务与要求版本 | 已有：`task`、`intend_ref`、`input_version`、`product_work_input_version`、`processed_input_version`；`product_spec.content_hash` / `input_version`；`effective_contract.content_hash` / `revision` / `product_spec_hash` / `decision_hashes`；`engineering_plan.content_hash`。 | 续行时把「本代次绑定的要求哈希」写入 `execution_lease_acquired.requirement_digest`（合同哈希 + 输入版本 + `request_id`），避免旧代次用新要求推进。 |
| 已采用组织及技能版本 | 组织固定为三部门单循环，无组织版本字段。技能无。 | 3.1 可先写死 `organization_version: "triad-v1"` 到 `run_created` 或 lease。技能等到 3.5。 |
| 已完成成果 | 已有：`product_specs[]`、`effective_contracts[]`、`engineering_plans[]`、`delivery_specs[]`（含 `code_tree_digest`、`tree_ref`）、`reviews[]`、`request_results[]`。 | 续行核验：对 `delivery_spec.status==active` 再跑 `load_tree` 与工作区 `capture_public_tree` 对比。不通过则不得当作可复用成果（研究 §6.4 步骤 3）。可用只读查询，不必新事件；若核验失败则写 `delivery_integrity_failed`（`delivery_event_id`、`expected_digest`、`observed_digest`）。 |
| 未完成动作 | `tool_started` 已写入事件（`_begin_tool`），**投影不消费该类型**（`apply_event` 无 `TOOL_STARTED` 分支，只更新 `last_seq`）。`tool_called` / `tool_skipped` 有。无「动作业务身份」与「尝试身份」分离（研究 §6.3）。 | 投影增加 `inflight_actions[]`：由未配对的 `tool_started` 生成。事件草案 `action_verified`：`action_id`、`attempt_id`、`tool_started_event_id`、`external_state`（`not_started` / `completed` / `unknown` / `failed_partial`）、`disposition`（`reuse` / `retry` / `compensate` / `manual`）。`tool_started.payload` 增补 `action_id`（稳定）、`attempt_id`（已有模型侧 `attempt_id`，工具侧待加）。 |
| 依赖 | 协作 `CollaborationRequest.basis`（intend / 合同 / 计划 / 交付 / phase）；交付绑定合同与计划哈希。无通用依赖图。 | 3.1 不引入通用依赖 DSL。续行只认：phase、`pending_request`、未核验动作。并行依赖等到 3.4。 |
| 等待条件 | 派生：`waiting_reason_for(phase, stop_reason)`；有 `pending_request` 时改写为「recipient is handling…」。无「等待外部条件」对象，无期限。 | 事件 `wait_opened` / `wait_satisfied` / `wait_expired`：`wait_id`、`kind`（`collaboration` / `user_input` / `external`）、`until`、`wake_token`。3.1 至少覆盖协作未响应与用户输入未分配；外部等待随 3.2。 |
| 取消请求 | `cancel` 与用户 `/stop`/`/cancel` 直接写终态 `run_failed`（`cancelled`）。取消请求与「已停止执行」未分开。迟到结果靠激活仍持有的 `_abort` 与版本核对，进程死后无效。 | 事件 `cancel_requested`：`run_id`、`generation`、`source`。已有终态仍写 `run_failed`/`run_paused`，但必须能在「已请求、Worker 已死、外部未知」时停留非终态或停留在 `cancelling`。待决：3.1 是否引入 `CANCELLING` phase。 |
| 可继续权限 | 隐式：非 `TERMINAL_PHASES` 且 `_abort` 未置位。重启后 `_abort` 不在，投影若非终态则 `run_until_stop` **会试图再激活**，但 Provider 快照常已丢失。 | `execution_lease_acquired` 含 `may_dispatch: bool`。撤销/取消后 `may_dispatch=false`。旧 `generation` 的 `_begin_tool` / `_prepare_step` / `_apply_proposal` 拒绝。 |
| 已消耗与预留资源 | 已有消耗：`token_used`、`cost`、`latency_ms`、`tool_count`、`cycle_count` / `max_cycles`（`model_requested.max_attempts`、`MODEL_ATTEMPT_*` 的 `usage`）。无预留、无未结算项。 | 3.1 最小：`budget_reservation` / `budget_settled` 先只覆盖模型尝试（`attempt_id`、`reserved_output_tokens`、`actual_usage`）。完整预算账是 3.4。 |
| 外部结果核实事项 | 无。检查收据在工作区文件，不在事件投影里（交付/质检把当次收据编进 accepted payload 的 `checks`）。 | 见上 `action_verified`。核实本身占用的等待与预算可见（研究 §6.4 步骤 4）。 |
| 模型上下文摘要 | 已有 `compaction_recorded`、`compactions[]`。研究明确：摘要不能代替上表事实。 | 续行仍按当前职责从事实重装（现有 `ContextAssembler.assemble`），不把恢复当成交出全部私有对话的理由。 |

B0 已规定、代码尚未落地的项目层事实（控制恢复雏形）：

| B0 项 | 合同位置 | 与恢复的关系 |
| --- | --- | --- |
| `deliverable_adopted` / `adoption_held` | B0 §8 `settle`：按 `run_id` 幂等；`run_until_stop` 返回后调用，也在 `start_work_item` 与 `GET /api/projects/{id}` 时 `settle_pending` 补跑 | 覆盖「`run_done` 与结算之间进程中断」：读取时补跑，不靠内存 |
| `work_item_created` 先于 `create_run` | B0 §7 步骤 6 | 「事项已接收、run 未创建」可重建；`create_run` 抛错写 `work_item_start_failed` |
| 结算与 run 流分表 | B0 §3 `project_events` | 项目决定不改写 run 事件 |

---

## 3. 执行所有权与代次契约草案

### 3.1 谁持有 run 的执行权

| 层 | 今天实际持有什么 | 3.1 应持有什么 |
| --- | --- | --- |
| Web 工作进程 | `LoopConsoleServer._active_run_id` + 一条 daemon 线程。同进程第二项 `start_run` → `BusyError`。 | 调度器槽位（3.4）。3.1 仍可每进程一 run，但所有权记录必须在 SQLite，不在线程对象。 |
| 编排器 | `_active[run_id]` 表示「当前部门激活未结束」。 | 同一 `generation` 下最多一个激活；激活结束必须落到 `activation_finished`（现有 `finally` 已写该事件）。 |
| 事件库 | 任何能打开同一 `events.sqlite` 的进程都能 `append`。无代次列。 | `append` / `begin_tool` 携带 `generation`；不匹配则拒绝写入推进类事件（工具开始、提案接纳、transition）。观察类事件是否允许迟到入账：待决。 |

「执行者」建议身份：`owner_id = "{process_start_id}:{thread_name}"` 或主机名+pid。不把模型 session_id 当执行权。

### 3.2 代次如何递增

草案：

1. `run_created` 时 `generation = 1`，尚无 lease（或创建者立即 `execution_lease_acquired` generation=1）。
2. 合法 `resume` / 抢占：读当前 `execution_generation`，写入 `generation+1` 的 `execution_lease_acquired`，并写 `execution_lease_released`（旧代次，`reason=superseded`）。同一 SQLite 事务。
3. 取消：先 `cancel_requested`（仍属当前代次），再在收尾完成后释放 lease。
4. 终态（`run_done` / `run_failed` / `run_paused`）后不得再 `acquired`。

今天没有等价物。`SessionFactory` 的 `activation_id`（`new_id("act")`）是部门激活身份，不是执行代次；重启后 `create_run_sessions` 用投影里的 `session_id` 重建会话对象，再发全新 `activation_id`。

### 3.3 旧执行者的提交如何被拒

今天（同进程、激活仍活着）已有的拒收点：

| 入口 | 函数 | 条件 |
| --- | --- | --- |
| 下一步模型请求 | `_prepare_step` | 终态、`abort_flag`、合同/计划/`request_id`/`input_version`/指导版本变化 → 返回 `None` |
| 发出模型 HTTP 前 | `_begin_request` | 同上 → `False`，且不写 `model_requested` |
| 开始工具 | `_begin_tool` | 同上 → `ToolAdmission(stopped=True)` |
| 提案提交 | `_apply_proposal` | 终态、abort、phase/输入/指导/合同/计划/`request_id`/`request_basis` 变化 → 拒绝 |
| 取消后的适配器 | `cancel` → `adapter.abort` | 流式请求可停；已返回的 `complete` 仍可能走到 `_apply_proposal`，由上面核对挡住推进 |

进程死后这些内存开关不存在。两个进程打开同一库时，双方都可以 `_prepare_activation` 并写第二条 `department_activated`。

3.1 拒收规则：

- 推进类写入必须带 `generation`，等于投影中的当前代次。
- 旧代次的 `tool_started`、`proposal_submitted`、`transition` 拒绝。
- 旧代次的 `model_attempt_finished` / 用量：允许只追加事实、禁止触发 `_commit_accepted`（OR-08）。
- 旧代次若在拒收前已调用 `ToolRuntime.execute`：转入动作核实，不能只凭拒收宣称外部无变化（研究 OR-15、10.1 第 5 项）。

### 3.4 `activation_finished` 与下一次 `department_activated` 之间的一致边界

时间线（`run_until_stop`）：

1. `_prepare_activation` 写 `department_activated`，把 activation 放入 `_active`。
2. `_invoke_activation`：装配、模型、工具、可选 `_apply_proposal`（接纳 + 可能多条 `transition` + 可能 `run_done`）。
3. `finally`：无论成败写 `activation_finished`（payload：`activation_id`、versions、`latency_ms`、`stop_reason`），`sessions.idle()`，`_active.pop`。
4. 循环：若非终态，再次 `_activate_once`。

**一致边界（草案）**：最后一条**已提交**的领域推进事件之后、下一条 `department_activated` 之前。具体包括：

- 本激活未提交提案：最后领域事件是 `proposal_rejected` 或仅观测事件 + `activation_finished`。phase 未变。续行：同一 phase 再激活（受 `max_cycles` 约束）。
- 本激活已接纳且 `transition` 已提交：phase 已是接收方阶段。`activation_finished` 的 `state_before`/`state_after` 都是**当时投影的 phase**（即过渡之后）。续行：按新 phase 选部门。
- 本激活写了接纳事件、**尚未**写 `transition`：见 §7 待决与下文不一致。此时投影可能已有 `product_spec` / `delivery_spec`，但 `phase` 仍是发送方。这不是一致边界，恢复不得猜测「本该 transition」。

`activation_finished` 本身不改变 `phase`（`apply_event` 只加 latency、把 session 标 idle/closed）。它标记「本激活的内存所有者已放弃 `_active`」，适合作为**控制边界**，不适合单独作为**领域边界**。领域边界仍是 `append_batch` 提交成功的那组事件。

---

## 4. 中断位置清单

约定：杀进程发生在「该行事件已成功 `commit` 之后、下一行事件尚未写入之前」，或标为「无事件的内存/外部窗口」。恢复后的允许项以 3.1 目标为准；现状栏说明今天实际会怎样。

贯穿任务领域与交接样例相同：文本逐行处理 CLI（先 echo，再文件输入，再去重只保留首次出现）。此处只列控制与动作边界。

| # | 中断位置 | 已持久的事实 | 恢复后允许 | 禁止推断 | 验收观察 |
| --- | --- | --- | --- | --- | --- |
| I0 | `run_created` 后、首次 `department_activated` 前 | `create_run` 写 `run_created`（`state_before=CREATED`，`state_after=PRODUCT_SPEC`），再单独 `append` 一条 `transition` `CREATED->PRODUCT_SPEC`。若死在两条之间：投影 phase 已是 `PRODUCT_SPEC`（来自 `run_created`），`transitions[]` 可能尚无该路由 | 取得 lease 后激活产品；不补写猜测的 transition 以外的领域事件 | 工作区空等于未创建 run | 有 `run_created`；无 `model_requested` |
| I1 | `department_activated` 后、`context_assembled` 前 | `activation_id`、`cycle`、合同/计划哈希、`input_version`、`prompt_version`；`cycle_count` 已 +1 | 本激活视为未开始模型工作；可写 `activation_finished`（若缺失）后按同一 phase 再激活或记失败激活 | 已激活等于已向模型付费 | 无 `model_requested`；`cycle_count` 不因恢复再 +1 除非新的 `department_activated` |
| I2 | `context_assembled` 后、`model_requested` 前 | 上下文工件 `request_ref` / `parts_ref`、`admitted` | 丢弃未发出的请求，按事实重装；溢出时现状会 `_fail(context_overflow)` | 已有装配等于请求已达提供方 | 无 `attempted: true` 的 `model_requested` |
| I3 | `model_requested` 后、流式首包前 | `attempt_id`、`logical_call_id`、`max_attempts` | 查询提供方（若协议允许）或记 `unknown`；D17 重试前提：`attempt < 3` 且非停机 | 无响应等于未计费、未生成 | `model_attempt_failed` 或 `action_verified`；不得无事件地再发同一 `attempt_id` |
| I4 | 流式进行中（`model_stream_progress` / 内存 `_AttemptCapture`） | 可能已有 progress 事件；完整 `sdk_stream_events` 工件要等 `_finalize_capture` | 同 I3；未 finalize 的 spool 文件丢失 | 本地没有 stream 文件等于提供方未输出 | 恢复后不得把半截 stream 当 `model_attempt_finished` |
| I5 | `model_attempt_finished` 后、第一件工具 `tool_started` 前 | 响应工件、usage；工具尚未准入 | 按响应里的 `function_call` 顺序执行；若激活已过期则 `tool_skipped` | 有工具列表等于已执行写文件 | 无 `tool_started`；工作区 digest 与激活前一致 |
| I6 | `tool_started` 后、`tool_called` 前（写文件） | `tool_started.payload` 含 `name`/`args`/`activation_id` | 查工作区文件是否已是目标内容；是则补 `tool_called`（reuse），否则按契约重试或人工 | 有 `tool_started` 等于已写入；无 `tool_called` 等于未写入 | 至多一次领域可见的成功写；`delivery` 不得在未核对 digest 时沿用 |
| I7 | 同上，工具为 `run_check` / `collect_evidence` | `tool_started`；可能已有收据文件行（`record_check` 在 `execute` 返回前） | 查收据文件与副本目录/进程；窗口内 unknown 则等待或人工；不得直接再跑同一检查并当作两次独立证据，除非契约允许 | 超时或杀进程等于检查未跑；exit 124 等于外部环境未变 | `action_verified`；交付接纳仍要求当次 activation 绑定的收据（`validation.py::_accept_delivery`） |
| I8 | `tool_called`（submit_*）后、`proposal_submitted` 前 | 工具输出已作为 function_call_output；提案尚未 `_apply_proposal` | 可从工具输出重建提案再走宿主校验；若激活过期则拒绝 | 提交类工具成功等于部门责任已转移 | 无 `spec_accepted` / `plan_accepted` 等 |
| I9 | `proposal_submitted` 后、接纳或拒绝前 | 提案种类与 `input_version` | 重新 `evaluate_proposal`；过期则拒绝 | 已提交等于已采纳 | 下一条必须是 `proposal_rejected` 或接纳事件 |
| I10 | `SubmissionWriter.commit` 的 `append_batch` 中途 | 整批回滚（`test_event_store_batch.py`：后条失败不消耗 seq） | 视为未接纳 | 磁盘上出现过临时材料文件等于事件已提交（`commit` 在 append 失败时回滚 PRD/PLAN 材料） | 无接纳事件；材料文件与旧版一致 |
| I11 | `append_batch` 已提交接纳、**尚未** `transition` | 例如已有 `spec_accepted`+`contract_accepted`，`phase` 仍为 `PRODUCT_SPEC` | **禁止**自动补 `transition`。待决：视为发送方仍负责，或写明确的 `handoff_pending` | 「有合同就是工程的责任」 | 见交接样例文档；本表验收：恢复后 `active_department` 仍为产品，直到一条显式接收/transition |
| I12 | `transition` 已提交、`activation_finished` 前 | 新 phase；`_active` 可能仍占用 | 补 `activation_finished` 或在续行时发现无 `_active` 直接按新 phase 激活 | 没有 `activation_finished` 等于过渡无效 | `phase` 与最后 `transition.state_after` 一致 |
| I13 | `activation_finished` 后、下一次 `department_activated` 前 | 控制边界：无内存激活 | 取得 lease 后按 phase 激活下一部门 | 空闲等于 run 结束 | `sessions[].status` 投影为 idle；`outcome` 仍 running |
| I14 | `run_done` 后、项目 `settle` 前 | run 终态 `DONE`；无 `deliverable_adopted` | 按 B0 §8 幂等补 `settle`（读取路径 `settle_pending`） | DONE 等于项目已采用该树 | 补跑后仅一条 `deliverable_adopted` 或一条 `adoption_held`；基线变化走 held |
| I15 | `collaboration_requested` 后、对方 `collaboration_responded` 前 | `pending_request`；`active_department=recipient` | 恢复订阅/激活接收方；重复请求拒绝（已有「finish the pending request」） | 请求事件存在等于接收方已答应承担责任——接收方尚未 `responded`，责任仍是「接收方必须回答」，发送方跟进超时（研究 5.1） | 无第二条 open request；`request_id` 稳定 |
| I16 | `user_input_received` 后、`product_input_assigned` 前 | `input_version` 已增；phase 未改 | `_assign_new_inputs` 可在下次 `_prepare_activation` / `_activation_stopped` 补写 assigned | 新输入已进事件等于产品已开始改需求 | `product_work_input_version < input_version` 直到 assigned |
| I17 | `cancel` 已写 `run_failed`、旧 Worker 仍在 `adapter.complete` | 终态 cancelled | 用量可追加；提案必须拒 | 终态等于外部检查未发生 | 无新的 `transition`；可能有迟到 `tool_started` 需核实 |

`create_run`（`harness/orchestrator.py::create_run`）已核对：`run_created.state_after` 为 `PRODUCT_SPEC`，随后另写 `transition`。

---

## 5. 故障矩阵（研究 10.1 → Yudao）

「当前适用」：用现有工具/交接就能注入。「等 3.2」：需要 shell / 网络 / MCP / 发布类外部动作才有真实对象。

| # | 研究故障点 | Yudao 映射 | 适用时机 | 预期测试名草案 |
| --- | --- | --- | --- | --- |
| 1 | 工作已持久接收但还未发送 | 事项：`work_item_created` 后 `create_run` 前（B0 §7）；run：`transition` 到工程后进程死在 I13；协作：`collaboration_requested` 已提交、接收方激活未发出 | 当前：I13、I15。事项路径等 `projects.py` 落地后同测 | `test_resume_after_transition_before_next_activation_does_not_duplicate_domain_progress` |
| 2 | 已发送，尚无 Worker 接收回执 | `model_requested` 后无 `model_attempt_*`（I3）；`tool_started` 后无 `tool_called`（I6/I7） | 当前即适用（模型 HTTP、写文件、主机检查） | `test_inflight_tool_started_without_tool_called_uses_stable_action_id` |
| 3 | 外部完成，本地尚未保存 | 写文件已改磁盘、无 `tool_called`；`run_check` 子进程已退出、收据或事件未写；模型已计费、无 `model_attempt_finished` | 写文件与检查：当前。发布/扣费：3.2 | `test_workspace_write_completed_before_tool_called_is_reused_not_replayed` |
| 4 | 两个 Worker 同时认为拥有任务 | 两个进程打开同一 `events.sqlite` 并 `run_until_stop`；或 3.1 后旧 generation 与新 generation 并发 | 当前：库文件无 lease，缺陷可测。3.1 后应失败在第二者 `acquired` | `test_second_worker_cannot_append_transition_with_stale_generation` |
| 5 | 旧 Worker 失权后继续调用外部工具 | 新 lease 已建立，旧进程仍走 `ToolRuntime.execute` | 当前：无 generation，只能在同进程 abort 窗口测。3.1 必须覆盖跨进程 | `test_stale_generation_begin_tool_is_rejected_and_unknown_side_effect_is_recorded` |
| 6 | 并行节点之一失败 | 无并行调度（每进程一 run、一事一 run） | 等 3.4 | `test_parallel_readonly_failure_does_not_rerun_successful_sibling` |
| 7 | 模型输出无法解析 | `_validate_response` / 未声明工具 / 无效 JSON 参数；D17 有界重试；用量经 `record_attempt_failed` | 当前即适用 | `test_unparseable_model_output_retries_at_most_three_attempts_and_keeps_usage` |
| 8 | 事件库或工件写入失败 | `host_commit_error`；`append_batch` 整批回滚；`ArtifactStore.put_stream` 失败删临时文件 | 当前即适用 | `test_event_append_failure_does_not_confirm_accepted_spec_in_projection_or_ui` |
| 9 | 观察订阅断开 | SSE 杀客户端；`Last-Event-ID` 重连 | 当前即适用 | `test_sse_reconnect_with_last_event_id_replays_gap_without_starting_worker` |
| 10 | 版本更新遇到等待任务 | 代码部署时 run 停在 I13 或 I15；普通更新应对旧 run 保持旧语义 | 3.1 起要有「恢复使用的代码版本」记录；完整撤销是研究 §8 / 第四阶段 | `test_resume_does_not_reinterpret_old_run_events_with_new_transition_rules` |
| 11 | 监测无数据或全是错误样本 | `Usage.reported=False`；观测导出缺价格 | 当前可测未知用量；采用流程暂停属第二/四阶段 | `test_missing_provider_usage_is_unknown_not_zero_cost` |
| 12 | 父任务停止而子任务失联 | 无子任务。近义：`cancel` 后主机检查子进程仍在；或 3.4 父事项取消 | 检查子进程：当前弱适用。父子：3.4 | `test_cancel_records_unknown_host_check_until_verified` |
| 附 | 恢复命令与撤销命令并发（矩阵第 12 行原文） | 3.1 的 `resume` 与 `cancel` / 未来撤销同时到达 | 3.1 | `test_resume_and_cancel_are_ordered_by_generation_cancel_wins_if_first` |

研究 10.1 表共十二行；上表第 12 项对应「父任务停止而子任务失联」，「恢复与撤销并发」单列以免与父取消混淆。

与研究 OR 编号的对应（§9.2）：OR-05≈#1 交接；OR-06≈等待+重复唤醒；OR-07≈#3；OR-08≈#4+#5 的迟到成功；OR-13/14≈#10；OR-15≈#5。

---

## 6. 外部动作契约模板（研究 6.3）

### 6.1 字段表

| 字段 | 要回答的问题 |
| --- | --- |
| 动作身份 `action_id` | 同一业务动作在重试之间如何保持稳定？与每次 `attempt_id` 如何分开？ |
| 目标环境 | 改的是哪棵工作区、哪台主机、哪个副本目录？ |
| 请求内容 | argv / 路径 / 正文的哪些字节进入身份哈希？ |
| 幂等键 | 外部是否接受同一键只生效一次？仅本地去重是否不够？ |
| 查询外部状态 | 崩溃后问谁？问不到时处于哪段一致性窗口？ |
| 结果一致性窗口 | 「查不到」在多少时间内不得当成未生效？ |
| 重试前提 | 授权、预算、代次、树 digest 仍成立才重试？ |
| 取消能力 | 能否通知外部停止？停止回执是否等于已停？ |
| 补偿条件 | 部分成功时预定义的反向动作是什么？没有则转人工 |
| 处置责任 | 谁跟进 unknown？超时后是否仍由原部门负责？ |

研究给出的可证明状态 → 允许操作，见研究稿 §6.3 表，此处不重复；Yudao 实现时按该表勾选，不另造状态机名词。

### 6.2 填好的例子：主机检查 `run_check`

对应代码：`harness/tools.py::ToolRuntime._run_check` → `_execute_check`；准入 `Orchestrator._begin_tool`；绑定 `Workspace.bind_check`；收据 `Workspace.record_check`。

| 字段 | 当前事实 | 3.1 契约填法 |
| --- | --- | --- |
| `action_id` | 无。`tool_started` 有工具 `id`（模型 `call_id`）和 `activation_id` | `action_id = hash(run_id, activation_id, logical_call_id 或 call_id, name, canonical(argv))`；重试共用 `action_id`，新 `attempt_id` |
| 目标环境 | `check_copy` 得到的临时目录；`cwd=copy_root`；`sanitized_env()` + `PYTHONDONTWRITEBYTECODE=1` | 查询对象：该副本路径是否仍在、进程是否仍持有该 cwd。源工作区默认不应被检查改写 |
| 请求内容 | `name` + 解析后的 argv；显示用 `_display_argv` | 身份包含解析后 argv，避免相对路径歧义 |
| 幂等键 | 无。每次 `execute` 都 `subprocess.run` | 子进程不提供幂等。恢复不得「再跑一遍当查询」 |
| 查询外部状态 | 无进程句柄持久化。收据文件是本地追加写 | 3.1：若无收据且无进程，状态=`unknown`（一致性窗口内）或 `not_started`（能证明副本从未创建）。不能把杀进程当成 `not_started` |
| 一致性窗口 | `CHECK_TIMEOUT_SEC=30` 是执行超时，不是查询窗口 | 建议窗口 ≥ 30s + 宿主杀进程宽限；窗口内禁止认定未生效 |
| 重试前提 | 无恢复重试。质检明确「prior receipts are not reused」（`_accept_review`） | 仅当核实为 `not_started` 或 `confirmed_not_applied`，且代次/合同/计划/snapshot 仍匹配，才允许再执行。收据已存在则 reuse |
| 取消 | `TimeoutExpired` → exit 124；进程被杀时无取消 API | 取消 run 时把 in-flight 检查标 unknown，不标已取消 |
| 补偿 | 副本可丢弃；若 `tree_changed` 则源树也可能变 | `tree_changed=true` 的未知结果转人工，不自动 `restore` 工作区 |
| 处置责任 | 当前激活的部门；超时后激活可能被 abort | 原部门仍负责跟进，直到 `action_verified`；与 phase 转移独立 |

`collect_evidence` 同一套 `_execute_check`，部门仅 quality，绑定还要求 `delivery_spec_hash`。契约拷贝上表，身份多一项交付哈希。

### 6.3 3.2 将新增的三类：契约必须先回答的问题

| 工具类 | 契约要回答的问题（每类一行，实施前填完） |
| --- | --- |
| 受控 shell | 工作区外进程、网络、环境变量是否可能被碰到？超时后如何查询该 pid 的真实退出与文件系统变化？命令原文与规范化 argv 哪一个进入 `action_id`？stdout 截断是否仍算完成？ |
| 网络取回 | 对端是否支持幂等或 `ETag`？本地无文件是否可能对端已生成资源？重试会不会造成双份副作用（订阅、计费）？授权范围如何进入查询凭证且不写入事件明文？ |
| MCP 工具 | 远端工具自己的幂等与查询 API 是什么？MCP 会话断开后如何用同一 `action_id` 问结果？宿主代次如何传给远端（传不了时 unknown 的责任在谁）？ |

写文件三类（`write_file` / `delete_file` / `move_file`）不是 3.2 新工具，但 3.1 就要有契约：查询手段是工作区字节与 `tool_started.args` 比对；无 POSIX 事务，unknown 时不得对同一路径做相反操作冒充补偿。

---

## 7. 待决

需要用户或主代理拍板后，3.1 才能把「禁止猜测」写成测试：

1. **I11（接纳已提交、transition 未写）**：视为发送方仍拥有责任（推荐，符合研究 5.1），还是恢复时由宿主补写 transition（把提出当接收）？
2. **是否引入 `CANCELLING` / `handoff_pending` phase**，还是只用新事件、phase 枚举不变？
3. **`resume` 与 `provider_credentials_lost`**：3.1 是否把冻结凭据持久化到仅宿主可读的机密存储，从而允许同绑定续行？还是维持「丢凭据必须新 run」，控制恢复只覆盖凭据仍在的进程崩溃？
4. **观察类迟到事件**：旧代次的 `model_attempt_finished` 用量是否允许写入？若允许，用什么事件类型以免误推进？
5. **lease 存放**：与 `events` 同库同事务（推荐，沿用现有 SQLite），还是 3.1 比较完 Temporal 再决定？Stage 3 计划写明现有 SQLite 内核为首选。
6. **B0 `settle` 与 3.1 的关系**：项目层未落地前，3.1 故障注入是否只覆盖 run 流（I0–I13、I15–I17），I14 等 B1 实现后补测？
7. **两个 OS 进程抢同一 `events.sqlite` 是否纳入 3.1 必测**？不纳入则所有权只证明「同进程代次」，与研究 10.1 第 4 项不完全同构。
8. **`tool_started` 是否纳入投影**为 `inflight_actions`，还是恢复引擎直接扫事件？
