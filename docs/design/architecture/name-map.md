# 总图的词与代码名的对照

总图位置：第四节「要守的缝」的十三道缝，以及第一节的方框、第三节内环六步与外环九个状态。

子架构师维护的对照表：总图的词、代码里现在的名字、归哪道缝。立缝时把那一行改成「一致」。按 main 2026-10-29（`c5308acf`）清点。

## 用法

1. 代码名随立缝工单改成总图的词，旧名留别名一版。
2. 没立的缝不改名；不为对上这张表单独开改名工单。
3. 立缝工单关闭时，子架构师在这里把该行的状态改为「一致」，代码名一栏写新名字。

判断口径：**一致**：代码名是总图这个词的直译，或是总图第一节方框悬停里给出的技术名词、术语表（`CONTEXT.md`）里的词；**不一致**：代码里有对应的东西，但叫的是旧说法、术语表列为「避免」的说法，或者一个名字盖住了总图分开的两样东西，这一栏写明现在叫什么，不写改法；**代码里还没有**：没有对应的模块、类型、字段或标识符。「归哪道缝或哪条道」一栏，缝用总图第四节的名字，道用[路线图](../../program-roadmap.md)第 3 节的编号。

内环六步各对应一道缝，不另列行：1 路由与边界 → 路由、写入口内侧（边界）；2 装配 → 装配；3 模型 / 外包 → 模型、执行（外包角色）；4 工具与环境 → 动作；5 裁决与写入口 → 写入口；6 投影 → 投影。

路径省略的前缀：Python 在 `harness/` 下，TypeScript 在 `client/src/renderer/src/` 下。

## 1. 系统里的十道缝

### 写入口

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 一份事实 | 第一节「一份事实」；第四节写入口的一侧 | `event_store.py` 的 `EventStore`；流 `run_stream`、`project_stream`、`catalog_stream`；`kernel_events.py` 的 `Event`、`ProjectEvent`、`CatalogEvent`（`models.py` 转出） | 写入口 | 一致（方框的技术名词是事件日志） |
| 写入口 | 第四节写入口 | `write_path.py` 的 `WritePath`、`Transaction`、`NewEvent`、`NewProjectEvent`、`NewCatalogEvent` | 写入口 | 一致 |
| 期望版本 | 第四节写入口「交换」 | `WritePath.transact`、`append` 的参数 `expected_version`；`StreamVersionConflict`；`Event.stream_version` | 写入口 | 一致 |
| 事项的执行权编号 | 第四节写入口「交换」 | `WritePath.claim_execution_right`、`StaleExecutionRight`；编号本身叫 `epoch`（`Event.epoch`、`event_store.py` 的表列） | 写入口 | 不一致：方法与异常叫执行权，编号字段叫 `epoch` |
| 派发编号 | 第四节写入口「交换」；第三节「重派与迟到的结果」 | 无。一轮工作只有身份 `activation_id`（`new_id("act")`，记在事件内容、`ContextManifest` 与 `CheckReceipt` 里），不递增，写入口不核对 | 写入口 | 代码里还没有 |
| 消息身份、按消息身份去重 | 第四节写入口 | `event_store.py` 的 `Command`、`CommandRecord`、`DuplicateCommand`、`CommandIdReused`；`Event.command_id` | 写入口 | 不一致：叫命令身份，只覆盖经接口发来的命令 |
| 来源（部门、角色、工作单元） | 第四节写入口「交换」 | `Event.department`、`Event.role`、`Event.actor`、`Event.session_id`；工作单元没有字段 | 写入口 | 不一致：分在四个字段里，没有「来源」这一组；工作单元代码里还没有 |
| 证据引用 | 第四节写入口「交换」 | `Event.artifact_hashes`、`models.py` 的 `ArtifactRef`、`artifacts.py` | 写入口 | 一致（方框的技术名词是工件） |
| 提案、完成提案 | 第一节方程「U ≠ f」；第四节执行「出」 | `proposals.py`、`submissions.py`；事件 `proposal_submitted`、`proposal_rejected`；定义 `proposal_contracts.json` | 写入口、执行 | 一致 |
| 裁决（U） | 第一节「裁决与边界」；方程里的 U | `adjudication.py`（`tool_permission`、`ToolPermission`、`proposal_decision`、`commit_decision`、`WorkBasis`）、`validation.py`（`evaluate_proposal`、`ProposalDecision`）；路由的收紧检查（总图没有这个词）：接口 `tightening_contract.py`，实现 `tightening.py` 的 `WatchedOutputsTightening` | 写入口内侧（内核，不是缝） | 一致 |
| 边界 | 第一节「裁决与边界」；第三节「每一步先问边界」 | `bounds.py`（`activation_bound`、`time_used_up`、`time_left_sec`），读 `minimal_projection.py` 里的已用量（`UsedAmount`）；询问深度在 `adjudication.ask_chain_max_depth`；时钟的起点与事件写入在 `orchestrator.py` | 写入口内侧（内核，不是缝） | 一致 |
| 最小投影 | 第四节投影「内核的最小投影」 | `minimal_projection.py` 的 `MinimalProjection`（`fold_events`、`fold_more`、`UsedAmount`、`AcceptedArtifact`）；`write_path.py` 的 `Snapshot.minimal`、`Transaction.minimal`、`WritePath.minimal` 交给裁决（`adjudication.py`、`validation.py`）与边界（`bounds.py`）读。`RunProjection` 是应用的投影，不是这一行 | 投影（内核内部，不在缝里） | 一致 |

### 路由

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 薄驱动 | 第一节「薄驱动」；第四节路由与执行的一侧 | `orchestrator.py` 的 `Orchestrator`（流程编排：调度、激活的准备与收尾、新输入的分派、安全节点的实现；路由经 `routing_contract.py` 的 `Routing` 问，装配与执行经各自的契约调用），由 `runtime.py` 的 `LoopSystem` 构造 | 路由、执行 | 不一致：叫流程编排（`Orchestrator`），没有叫薄驱动的类或模块；路由实现已分到 `watched_outputs.py`，调度、激活的准备与收尾仍在这个类里 |
| 插件加载 | 第二节「只由你批准」 | `routing_contract.py` 的 `register`、`select`：路由实现登记名称，启动时按组织定义的 `routing` 接上（`routings.json` 登记可用的名称）；装配与执行没有按名字加载，由 `LoopSystem` 的构造参数 `assembly`、`execution` 交给 `Orchestrator`（默认 `ContextAssembly`、`StepDriver`），构造时核对四份契约的版本 | 路由、装配、执行 | 不一致：只有路由按定义里的名字接上（`register`、`select`），装配与执行经构造参数接上，没有叫插件加载的模块 |
| 路由契约 | 第四节路由 | `routing_contract.py`（`CURRENT_VERSION`、`PREVIOUS_VERSION`、`accept`、`Routing` 协议）；实现 `watched_outputs.py` 的 `WatchedOutputs` 声明 `CONTRACT_VERSION` | 路由 | 一致 |
| 槽位：路由、路由实现 | 第一节「槽位：路由」 | `watched_outputs.py` 的 `WatchedOutputs`（成果驱动，登记名称 `watched_outputs`；`ready_departments`、`next_department`、`round_end`、`item_end`）；`tightening.py` 的 `WatchedOutputsTightening`（含 `allowed_proposal_kinds`）；`routings.json` | 路由；道 03 | 一致 |
| 按成果（关注的成果） | 第一节「轮转方式」 | `definitions/__init__.py` 的 `Definitions.watched_outputs`、组织定义里部门的 `watched`；`watched_outputs.py` 的 `watched_new_work`、`has_new_work` | 路由；道 03 | 一致 |
| 任务池、工作单元、认领 | 第一节「轮转方式」；第三节外环「待认领」 | 无（`claim_execution_right` 的 claim 是领取事项的执行权，不是认领工作单元） | 路由；道 03 | 代码里还没有 |
| 事项 | 第一、三节 | 项目流里叫 work_item（`work_item_created`、命令 `work_item.create`、`work_item.cancel`、`work_item.append_input`，查询 `work_item.*`）；事项的一次执行叫 run（`run_stream`、`run_created` 至 `run_continued`、`RunProjection`，查询 `run.*`） | 路由、接口 | 不一致：总图只有事项，代码与接口资源名里 `work_item` 与 `run` 两个名字并存 |
| 放行或开环完成，事项完成 | 第三节外环 | 放行：质检结论 `models.py` 的 `QAReview`（`verdict` 字段）、事件 `qa_submitted`；事项结束 `run_done`；开环完成：无 | 路由 | 不一致：放行没有自己的名字，是质检结论的一个取值；开环完成代码里还没有 |
| 直做 | 第一节「轮转方式」 | 无 | 路由；道 03 | 代码里还没有 |
| 交完成（直做） | 第一节「轮转方式」；第三节外环「开环时交完成」 | 无；成果驱动下结束事项的是质检结论 `submit_review` 的 `verdict: release` | 路由；道 03 | 代码里还没有 |
| 子事项、子组织 | 第一节「工程」；第三节「子组织」 | 无 | 路由、执行；道 02 | 代码里还没有 |

### 装配

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 槽位：装配、装配实现 | 第一节「槽位：装配」；第四节装配 | `assembly.py` 的 `ContextAssembly`（`department_history`、`pin`、`request`、`finish_compaction`）；`context.py` 的 `ContextAssembler`、`AssembledContext` | 装配；道 04 | 一致 |
| 装配契约 | 第四节装配 | `assembly_contract.py`（`CURRENT_VERSION`、`PREVIOUS_VERSION`、`accept`、`ContextAssembly` 协议的四个方法）；实现 `assembly.py` 的 `ContextAssembly` 声明 `CONTRACT_VERSION` | 装配 | 一致 |
| 交给模型的那份 | 第四节装配「出」 | `assembly.py` 的 `StepRequest`；事件 `model_request_serialized` | 装配 | 一致 |
| 上下文清单 | 第四节装配「出」 | `models.py` 的 `ContextManifest`、`ContextSource`、`ContextExclusion`；事件 `context_assembled` | 装配 | 一致 |
| 压缩 | 第三节「上下文逼近上限 → 压缩」 | `compaction.py`（`plan_compaction`、`finish_compaction`、`CompactionCheckpoint`）；事件 `compaction_recorded` | 装配；道 04 | 一致 |
| 待并入的指导 | 第四节装配「入」；第三节两环的关系 | `assembly.pending_guidance`、`models.py` 的 `DepartmentGuidance`；事件 `department_guidance_received`、`_applied`、`_responded`；命令 `guidance.send` | 装配 | 一致 |
| 判定点 | 第三节「判定点」；第四节装配「判定点的选择先写事件」 | 无 | 装配、定义；道 06 | 代码里还没有 |

### 执行

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 槽位：执行、执行实现 | 第一节「槽位：执行」；第四节执行 | `engine.py` 的 `StepDriver`（`start`、`cancel`）；`execution_contract.py` 的 `StepLimits`、`ActivationScope`；`recording.py` 的 `StepRecorder` | 执行 | 一致（方框的技术名词是步骤驱动） |
| 执行契约、每一步先问边界 | 第四节执行 | `execution_contract.py`（`CURRENT_VERSION`、`PREVIOUS_VERSION`、`accept`；`StepDriver` 协议的 `start`、`cancel`、`result`；`SafeNode` 协议的 `proceed`、`settle`、`wait`、`end`、`department_selection`、`department_prompt`、`ask`）；`orchestrator.py` 的 `_SafeNode` 实现安全节点；实现 `engine.py` 的 `StepDriver` 声明 `CONTRACT_VERSION` | 执行 | 不一致：协议里带着 `department_selection`、`department_prompt` 两个按部门的方法，路由的问题混在执行契约里 |
| 一轮工作 | 第三节外环「一轮工作中」；第一节方程 | 叫 activation：`orchestrator.py` 的 `_Activation`、事件 `department_activated`、`activation_finished`、`bounds.activation_bound`、身份 `activation_id` | 执行、路由 | 不一致：叫激活，术语表把「激活」列为避免的说法 |
| 部门成员（一个会话） | 第六节「可以多份」 | `sessions.py` 的 `DepartmentSession`、`SessionFactory`；`models.py` 的 `SessionRecord` | 执行 | 一致 |
| 询问 | 第三节外环「询问中」；第四节执行「出」 | 事件 `ask_started`、`ask_answered`；`adjudication.ask_chain_decision`；`watched_outputs.py` 的 `pending_ask_department`、`ask_branch`、`ask_outcome`；`SafeNode.ask`；查询 `run.asks` | 执行、路由 | 一致 |
| 外包角色 | 第一节「工程」；第四节执行 | 无 | 执行；道 02 | 代码里还没有 |
| 开子事项的请求 | 第四节执行「出」；第三节「子组织」 | 无（执行契约的结果只有这一轮写下的事件范围、停止原因与三样观察） | 执行；道 02 | 代码里还没有 |

### 模型

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 模型服务 | 第一节「模型与工具」；第四节模型 | `providers/`（`call.py` 的 `ModelCall`、`ModelResponse`、`ModelStreamEvent`；`invoke.py` 的 `ProviderInput`、`InvokeResult`、`CancelRegistry`）；`adapters/base.py` 的 `ModelAdapter`，`adapters/fake.py` 的 `FakeAdapter` | 模型；道 06 | 一致（方框的技术名词是 Provider） |
| 调用目标 | 第四节模型「每次请求解析一次调用目标」 | `providers/resolve.py` 的 `resolve_call_target`、`CallTargetResolution`；解析结果的类型叫 `FrozenTarget` | 模型 | 不一致：结果类型叫 `FrozenTarget`，术语表把「冻结目标」列为避免的说法 |
| 尝试记录 | 第四节模型「出」 | 事件 `model_requested`、`model_attempt_finished`、`model_attempt_failed`、`model_retry_scheduled` | 模型 | 一致 |
| 模型输出事件 | 第四节模型「出」 | 事件 `model_message`、`model_reasoning`、`model_stream_progress` | 模型 | 一致 |
| 用量 | 第四节模型「出」 | `providers/call.py` 的 `CallUsage`、`models.py` 的 `Usage`；查询 `project.usage` | 模型 | 一致 |
| 凭据只在控制主机 | 第四节模型 | `providers/credentials.py`；命令 `credential.set`、`credential.clear_override`、`credential.remove_persisted`；事件 `credential_changed` | 模型 | 一致 |

### 动作

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 执行环境 | 第一节「模型与工具」；第四节动作 | `environment.py` 的 `LocalEnvironment`、`BackgroundJobTable` | 动作；道 05 | 一致 |
| 动作、动作身份 | 第四节动作「请求」 | `actions.py` 的 `Action`（`action_id`、`kind`、`tool`、`input`）、`Preconditions` | 动作 | 一致 |
| 回执 | 第一节「独立的证据」；第四节动作「回执」 | `actions.py` 的 `ActionReceipt`（`status`、`output`、`error`）；检查回执 `actions.py` 的 `CheckReceipt` | 动作 | 一致 |
| 工具请求 | 第四节执行「出」 | `tools.py`；事件 `tool_call_required`、`tool_called`、`tool_started`、`tool_skipped` | 动作、执行 | 一致 |
| 起点快照、封存快照 | 第一节「一份事实」；第四节动作「请求」 | 封存：`snapshot.py`（`ingest_snapshot`、`restore_snapshot`）、`workspace.py` 的 `WorkspaceSnapshot`、`LocalEnvironment.snapshot()`；动作请求里的起点叫 `Preconditions.tree_digest`（公开树摘要）；动作前的公开树快照记在事件 `tool_started` 的 `before_snapshot_ref` | 动作 | 不一致：动作请求里的起点叫树摘要，不叫快照；快照在事件载荷里，不在请求里 |
| 终点快照、前后差异 | 第四节动作「回执」 | 回执 `ActionReceipt` 不带终点与差异；动作后的公开树快照记在事件 `tool_called` 的 `after_snapshot_ref`；前后差异只在恢复核实时比较（`app/payloads.py` 的 `FileActionComparison`） | 动作 | 不一致：终点快照在事件载荷里，不在回执里；前后差异代码里还没有字段 |
| 核实方法、能否取消 | 第四节动作「请求」 | `actions.py` 的 `Action.verification`（`Verification`）、`Action.cancellable`，缺少时按类别的既定值解释（`check_contract`）；核实的执行是事件 `action_verified` 与 `environment.py` 的 `LocalEnvironment.verify_tree`，取消是 `LocalEnvironment.cancel`、回执状态 `cancelled` | 动作 | 一致 |
| 工作区 | 第三节「从快照建工作区」；第六节 | `workspace.py` 的 `Workspace`；检查工作区 `environment.inspection_root`（目录 `inspections`） | 动作 | 一致 |
| 远程执行 | 第一节「模型与工具」；第六节 | 无 | 动作；道 05、10 | 代码里还没有 |

### 投影

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 应用的投影 | 第四节投影 | `projection.py`（`project_run`、`replay_run`、`RunHandler`）、`project_projection.py`、`app/read_models.py` 的 `ReadModels`、`views.py`、`overview.py` | 投影 | 一致 |
| 折叠函数、从头重算 | 第四节投影「交换」 | `projection.py` 的 `apply_event`、`replay_events`；`replay_check.py`；查询 `replay.check` | 投影 | 一致 |
| 骨架事件、应用事件 | 第二节「只能向后兼容」；第四节投影 | 骨架事件：`kernel_events.py` 的 `SkeletonEventType`（run 流）、`ProjectEventType`、`CatalogEventType`，登记表 `SKELETON_EVENTS`；应用事件：`models.py` 的 `EventType` 里接着声明的部分，由 `app/payloads.py` 经 `register_application_event_types` 登记 | 投影、写入口 | 一致 |

### 接口

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 应用层 | 第一节「界面」悬停；第四节接口的内侧 | `app/application.py` 的 `Application`、`ReadOnlyCore`；`app/registry.py` 的 `Registry` | 接口 | 一致 |
| 命令（带身份） | 第四节接口 | `app/registry.py` 的 `CommandDefinition`、`app/contracts.py` 的 `CommandRequest`、`Accepted`、`Rejected`；路径 `/api/commands/<名字>` | 接口 | 一致 |
| 查询（只读快照） | 第四节接口 | `app/registry.py` 的 `QueryDefinition`、`app/contracts.py` 的 `Snapshot`；路径 `/api/queries/<名字>` | 接口 | 一致 |
| 事件流（从某个位置起） | 第四节接口 | `app/event_stream.py` 的 `EventStream`、`StreamCheckpoint`、`StreamResync`、`StreamDelta`；路径 `/api/events` | 接口 | 一致 |
| 带版本号 | 第四节接口 | `api/app.py` 的 `contract_digest`；接口快照 `harness/tests/openapi/openapi.json`；客户端 `api/interface-version.ts` 的 `CLIENT_API_VERSION`；能力清单 `/api/capabilities`（`Capabilities`） | 接口 | 一致 |
| 接口层 | 第一节「界面」悬停 | `api/`（`app.py` 的 `create_app`、`server.py`、`access.py`、`pages.py`） | 接口 | 一致 |
| 等用户、决定请求 | 第三节外环「等用户」 | `decisions.py`（`DecisionKind`、`blocks_run`）、`kernel_events.py` 的 `DecisionRequest`；事件 `decision_requested`、`decision_answered`、`decision_withdrawn`；命令 `decision.answer`，查询 `decisions.list` | 接口、写入口 | 一致 |

### 画面

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 界面 | 第一节「界面」 | `client/`；壳 `shell/`、页面 `views/` | 画面、接口；道 09 | 一致 |
| 同步层 | 第一节「界面」悬停 | `contract/view-sync.ts` 的 `ViewSync`、`contract/event-stream.ts`、`contract/stream-state.ts`（目录叫 contract） | 接口（读者一侧） | 一致 |
| 翻译层 | 第四节画面 | `translate/`（`building.ts` 的 `buildingState`、`buildingActions`；`floor.ts` 的 `floorState`、`floorActions`、`floorCards`、`streamText`；`room.ts` 的 `state`、`actions`；`tables.ts` 的状态对应表；`say.ts`；`coverage.ts` 核对每种事件的归属） | 画面 | 一致 |
| 画面层 | 第四节画面 | `pixel/`（`building/view.ts`、`floor/view.ts`、`room/view.ts` 的 `createBuildingView`、`createFloorView`、`createRoomView`；`world/`、`room/`、`floor/`、`building/`）；页面里的挂载 `views/home/building-section.tsx`、`views/project/floor-screen.tsx`、`views/project/room-screen.tsx` | 画面；道 09 | 不一致：叫 pixel，不叫画面层；输入类型带 Pixel 前缀（`PixelState`、`PixelAction`，在 `pixel/contract.ts`） |
| 元件断言、回链 | 第四节画面「交换」 | 画面合同 `pixel/contract.ts`：状态 `PixelState` 与动作 `PixelAction` 都带 `position`（注释写作回链：来源的查询快照或事件的位置），事实元素带来源 `SourceRef`；没有元件断言这个单位，动作的种类取自场景的声明表（`floor-decl`、`room-decl`、`building-decl`） | 画面 | 不一致：回链叫 `position`；元件断言代码里还没有 |
| 播放参数 | 第四节画面「交换」 | `pixel/timeline.ts`（播放时间线）的 `settings`（`lagMs`、`minMs`、`speed`）与 `rate()`；动画时钟 `pixel/clock.ts`；`pixel/anims.ts` 的 `reducedMotion` | 画面 | 不一致：叫 `settings`，在时间线模块里，不经画面合同给出 |
| 页面 | 第一节「界面」悬停 | `views/`（`home/`、`project/`、`decisions/`、`models/`、`system/`、`timeline/`）、`shell/` | 画面（页面一侧）、接口 | 一致 |
| 七种元件的对照表 | 画面总图第四节「映射」 | `translate/coverage.ts`：事件在三个场景的归属 `COVERAGE`、覆盖层的中文名 `OVERLAY_LABELS`；概念到元件的行：无 | 画面；道 09 | 不一致：只有事件与覆盖层两份，没有概念到七种元件的表，事实元素与视觉通道没有核对 |
| 画面拓扑（屋、管道、盖章台从定义推出） | 画面总图第五节 | 写死在画面层：`pixel/world/floor-decl.ts` 的 `ROOMS`、`pixel/building/render.ts` 的 `ROOMS`、`pixel/room/layout.ts` 的 `ROOM_DEPTS`；合同里楼的亮灯 `lit` 是固定的四个部门字段（`pixel/contract.ts`）；楼层查询的 `departments` 按固定的 `DEPARTMENTS` 列出（`harness/app/project_queries.py`） | 画面、接口；道 09 | 不一致：拓扑不从事项冻结的定义来，画面层按部门名分支 |
| 盖章台、出口托盘 | 画面总图第五节 | 盖章台：`pixel/room/layout.ts` 按部门 `quality` 画「检验台」；出口托盘：无 | 画面 | 不一致：按部门名取，不按核验角色 |
| 章（放行、开环完成） | 画面总图第五节 | 合同 `pixel/contract.ts` 的 `Stamp`（楼层状态的 `stamp`）；动作 `stamp_release`、`stamp_defect`、`stamp_valid`（`translate/floor.ts`）；开环完成章：无 | 画面 | 不一致：开环完成章代码里还没有 |
| 点开回链 | 画面总图第一节「页面」、第四节「回调」 | 画布上的来源卡片 `pixel/floor/card.ts` 的 `createSourceCard`，卡片内容 `SourceCardFace`（`pixel/contract.ts`）画原始事件与差异 | 画面（页面一侧） | 不一致：细内容画在画布上，没有交给页面 |

### 定义

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 定义、加载与校验 | 第二节「定义」；第四节定义 | `definitions/__init__.py` 的 `Definitions`、`load_definitions`、`DefinitionError`；文件 `organization.json`、`roles.json`、`tools.json`、`proposal_contracts.json`、`rules.json`、`stop_reasons.json`、`work_items.json`、`service_presets.json`、`model_capabilities.json`、`routings.json` | 定义；道 10 | 一致 |
| 版本 | 第四节定义「交换」 | `Definitions` 的版本取全部文件的内容摘要 | 定义 | 一致 |
| 部门与角色 | 第一节「下一个部门」；第四节定义「交换」 | `Organization`、`Department`、`Role`；`organization.json` 的 `product`、`engineering`、`quality` | 定义；道 01、02 | 不一致：部门是固定取值，`models.py` 的 `DEPARTMENTS` 取自加载的定义并在 `app/payloads.py` 写成 `Literal[DEPARTMENTS]`，`providers/facade.py` 的 `REQUIRED_DEPARTMENTS` 写死三部门；总图要的是随事项冻结的定义给出 |
| 上限 | 第四节定义「交换」 | `rules.json` 与 `Rule`；`parameters.py`（`check_bounds`、`ParameterChange`、`fold_parameters`）；命令 `parameter.set`、事件 `parameter_set`、`project_parameter_set` | 定义 | 一致（方框的技术名词是上限与规则、参数） |
| 停止原因清单 | 第三节外环「停止」；第四节定义「交换」 | `stop_reasons.json`、`StopReason`、`UnknownStopReason`、`models.stop_reason_name`、`Event.stop_reason` | 定义 | 一致 |
| 谁能拒绝谁 | 第四节定义「交换」 | 无单独的声明；各部门能提交什么写在 `proposal_contracts.json` | 定义 | 代码里还没有 |
| 核验角色（是否核验角色及核验谁） | 第一节「质检」「独立的证据」；第四节定义「交换」 | 无声明；`app/project_queries.py` 的 `VERIFIER_OF`（`{"engineering": "quality"}`）写死，检查材料目录 `path_rules.py` 的 `QA_TESTS_DIR`，部门 id `quality` | 定义、路由；道 01 | 不一致：写死在部门名上 |
| 写入范围 | 第四节定义「交换」 | 无声明；最接近的是 `adjudication.py` 按部门名 `quality` 把写入限在 `QA_TESTS_DIR` 下 | 定义、写入口 | 不一致：按部门名写死，不是角色的通用权限 |
| 成果种类与提案合同 | 第四节定义「交换」 | `routings.json` 每种路由的 `outcome_kinds`；`proposal_contracts.json` | 定义；道 03 | 不一致：成果种类放在路由自己的定义里，总图是定义里单独的一项 |
| 路由实现与它的定义、工作单元的大小 | 第四节定义「交换」 | 路由实现与它的定义：组织定义的 `routing`、`routings.json`（每种路由一条）、`Definitions.routing_definition`；工作单元的大小：无 | 定义、路由；道 03 | 一致（路由实现与它的定义）；代码里还没有（工作单元的大小） |
| 登记的机器 | 第四节定义「交换」；第六节 | 无 | 定义；道 10 | 代码里还没有 |
| 限定采用的范围 | 第四节定义「交换」；第五节第二层 | 无 | 定义 | 代码里还没有 |

## 2. 系统之外的三道缝

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 评价 | 第一节「评价」；第四节评价 | `evals/`（`scenarios/*/checks`、`scorer/`、`runner/`、`baseline/`）；发布检查 `harness/release_check.py`、`scripts/release.py`；内核清单 `harness/definitions/kernel-manifest.json` | 评价；道 08 | 一致（方框的技术名词是评测场景与隐藏检查、评分器、发布检查） |
| 观察者 | 第一节「观察者」；第四节观察者 | 无；教训候选由 `submissions.py` 的 `SubmissionWriter.record_lesson_candidate` 在控制核心里写（`orchestrator.py` 调用），事件 `lesson_candidate_recorded`，不经观察者缝 | 观察者；道 07 | 代码里还没有 |
| 读取范围、振荡信号 | 第四节观察者「交换」 | 无（最接近的是事件流按范围筛选，`app/event_stream.py` 的 `EventScope`，范围由连接的参数给出，不在定义里声明） | 观察者；道 07 | 代码里还没有 |
| 看门狗（健康探针、切换命令、排空命令） | 第一节「看门狗」；第四节看门狗 | 看门狗与健康探针、切换命令都没有；排空已有：`streams.py` 的 `DrainState`、命令 `runtime.start_drain`、`runtime.force_upgrade`，事件 `runtime_drain_started`、`runtime_drain_finished` | 看门狗；道 10 | 代码里还没有（排空命令一项一致） |

## 3. 外环的九个状态

外环的状态对一个部门成立；代码里 run 自己的状态只有 `kernel_events.py` 的 `RUN_STATUSES`（`running`、`done`、`paused`、`failed`，`models.py` 转出）。部门的状态里五个由查询算出来：`app/project_queries.py` 的 `DEPARTMENT_STATES` 与 `DepartmentState`（`waiting_user`、`working`、`asking`、`verifying`、`waiting`），在 `project.loop`、`department.workspace` 等查询的结果里；其余四个（接纳、返工、排空中、停止）不在这个类型里，没有一个列出九个状态的类型。

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 等待工作 | 第三节外环 | `watched_outputs.is_waiting`；部门状态 `waiting`（`app/project_queries.py` 的 `DepartmentState`） | 路由 | 一致 |
| 一轮工作中 | 第三节外环 | `watched_outputs.is_working`；部门状态 `working`；run 状态 `running` | 路由、执行 | 一致 |
| 询问中 | 第三节外环 | `watched_outputs.pending_ask_department`；部门状态 `asking`；事件 `ask_started` | 路由、执行 | 一致 |
| 等用户 | 第三节外环 | `decisions.blocks_run`、`DecisionRequest`（见接口一节）；部门状态 `waiting_user` | 接口 | 一致 |
| 核验中 | 第三节外环 | 部门状态 `verifying`（`app/project_queries.py` 的 `DepartmentState`；`_awaiting_verification`：最新的交付还没有质检的缺陷记录或放行）；检查工作区 `environment.inspection_root` | 路由、动作 | 不一致：`_awaiting_verification` 按质检与交付写死，不按核验角色 |
| 接纳 | 第三节外环 | 通用接纳事件 `artifact_accepted`（`kernel_events.py`）；成果驱动的老事件 `spec_accepted`、`contract_accepted`、`delivery_accepted`、`structure_accepted`、`baseline_review_accepted`、`product_decision_accepted` | 写入口、路由 | 一致 |
| 返工 | 第三节外环 | 质检结论的取值 `rework_engineering`（`kernel_events.py` 的 `QA_VERDICTS`）；取值 `rework`（`views/timeline/logic.ts`）；缺陷在 `QAReview.defects`，页面显示「缺陷记录」 | 路由 | 一致 |
| 排空中 | 第三节外环 | `streams.py` 的 `DrainState`（见看门狗一行） | 看门狗 | 一致 |
| 停止 | 第三节外环 | run 的终态 `paused`、`failed` 加 `stop_reason`；`done` 是放行或开环完成以后的完成（开环完成代码里还没有；`coverage.py` 里的「开环」是检验覆盖的说法，不是这个词） | 路由、定义 | 不一致：代码按暂停、失败分两种终态，总图只有停止，原因来自封闭清单 |

## 4. 每道缝的守卫

守卫是 CI 或手动能跑的自动检查。这张表是长期记录，按缝的差异报告（`.claude/skills/seam-diff/SKILL.md`）每次从这里取守卫清单去跑；守卫加了、删了、改名了，在这里改。「守的规矩」只写守卫实际断言的那几条，总图这道缝的规矩里没写进这一栏的，就是没有守卫。测试文件省略前缀 `harness/tests/`，括号里是测试分层登记表（`harness/tests/layers.toml`）的层。

| 缝 | 两侧在代码里 | 守卫 | 守的规矩 |
| --- | --- | --- | --- |
| 写入口 | 写入方：`orchestrator.py`、`projects.py`、`app/` 的命令 ↔ `write_path.py`、`event_store.py` | `kernel/test_single_write_path.py`（单元）、`test_write_path.py`（模块）、`test_concurrent_commands.py`（集成）、`kernel/test_tool_needs_permission.py`（单元）、`kernel/test_tightening_only_rejects_or_waits.py`（模块） | 事实只经写入口写入；先过裁决；同一事务核对执行权编号与流版本；按命令身份去重；工具开始之前有许可记录 |
| 路由 | 薄驱动 `orchestrator.py` ↔ 契约 `routing_contract.py`，实现 `watched_outputs.py`、`tightening.py` | `test_routing_contract.py`（单元）、`test_second_routing.py`（模块）、`test_thin_driver_names.py`（单元）、`test_routing_definition.py`（模块）、`kernel/test_contract_surface.py`（单元） | 契约的公开名称与版本；第二种路由（测试里的任务池）接上同一副骨架跑完一个事项；薄驱动的源码里没有部门与成果的名字；每种路由带自己的定义与结束原因 |
| 装配 | 执行 `engine.py` ↔ 契约 `assembly_contract.py`，实现 `assembly.py`、`context.py`、`compaction.py` | `test_slot_contracts.py`（模块）、`test_contract_seams.py`（模块）、`test_second_slot_implementations.py`（模块）、`test_contract_modules.py`（单元） | 输入输出的形状；交给模型的那份与上下文清单记进事实；装配不写事实事件；第二种装配接上以后薄驱动不改 |
| 执行 | 薄驱动 `orchestrator.py`（安全节点 `_SafeNode`）↔ 契约 `execution_contract.py`，实现 `engine.py`、`recording.py` | `test_slot_contracts.py`（模块）、`test_second_slot_implementations.py`（模块）、`test_contract_seams.py`（模块）、`kernel/test_every_stop_has_reason.py`（单元）、`kernel/test_limits_survive_restart.py`（集成） | 每一步先问安全节点；取消与上限时停下，停止原因取自封闭清单；重启以后用量连续累计；第二种执行接上以后薄驱动不改 |
| 模型 | 执行 `engine.py` ↔ `providers/`、`adapters/` | `test_providers_module.py`（集成）、`test_call_target_per_request.py`（集成）、`test_resolve_call_target.py`（单元）、`test_redact.py`（模块）、`test_saved_projections.py`（集成） | 每次请求解析一次调用目标；凭据不进事实与导出；重放不调模型 |
| 动作 | 工具 `tools.py`、`engine.py` ↔ `environment.py`、`actions.py`、`workspace.py`、`snapshot.py` | `test_action_contract.py`（模块）、`test_tool_contracts.py`（单元）、`kernel/test_only_grows.py`（单元）、`test_workspace_boundary.py`（单元） | 两种环境（本机与测试里的第二种）接受同一份动作合同、给出同样的回执；动作类别与回执字段只增；控制核心不直接读写工作区 |
| 投影 | `event_store.py` → `projection.py`、`project_projection.py`、`app/read_models.py`；内核的 `minimal_projection.py` | `test_replay.py`（模块）、`test_saved_projections.py`（集成）、`kernel/test_minimal_projection.py`（模块）、`kernel/test_minimal_projection_baselines.py`（集成）、`kernel/test_skeleton_events.py`（单元）、`test_event_classification.py`（单元） | 从头重算得到同一状态；最小投影与应用投影逐项一致；骨架事件有登记表；每种事件声明所属的流 |
| 接口 | 页面 `client/`、命令行、`evals/` ↔ 应用层 `app/`，经接口层 `api/` | `test_layers.py`（单元，导入方向合同，定义在 `pyproject.toml` 的 `[tool.importlinter]`）、`test_openapi_snapshot.py`（模块）、`test_event_stream.py`（模块）、`test_capabilities.py`（模块） | 接口层只导入应用层、应用层只导入控制核心的公开接口；合同快照不偷偷改；事件流按位置续；能力清单列出改变每条查询的事件 |
| 画面 | 翻译层 `translate/` ↔ 画面层 `pixel/`，合同 `pixel/contract.ts` | 客户端 `client/tests/unit/pixel-imports.test.ts`、`pixel-contract.test.ts`、`translate-coverage.test.ts`；逐场景回放 `pixel-floor-replay.test.ts`、`pixel-room-replay.test.ts`、`pixel-building-replay.test.ts`（不在 CI 里，手动跑） | 画面层只导入画面合同与自己的声明表；合同取值逐项校验；每种事件在三个场景里都有归属；回放的每个检查点与原型逐像素相同 |
| 定义 | 文件 `harness/definitions/*.json` ↔ `definitions/__init__.py` | `test_definitions.py`（集成）、`test_definition_rules.py`（单元）、`test_routing_definition.py`（模块）、`kernel/test_definitions_decide.py`（单元）、`test_frozen_parameters.py`（集成） | 加载与校验；版本是内容摘要；裁决读事项所用的那份定义；参数建 run 时冻结 |
| 评价 | `evals/`、`release_check.py` → 系统（经接口） | `evals/tests/test_no_harness_import.py`、`evals/tests/test_no_harness_paths.py`；内核清单的 `material` 条目由 `path_guard.py` 在采纳前比较（`test_projects.py` 的内核守卫用例，集成）；`test_release_check.py`（模块） | 评测工具不导入 `harness`、不引用它的内部路径；改动评价材料的交付不自动采纳；发布检查的清单与检查取自运行中的实例，改待发布提交里的清单与检查不改变结果 |
| 观察者 | 无 | 无 | 无 |
| 看门狗 | 无；排空在 `streams.py` 的 `DrainState` | `test_runtime_drain.py`、`test_drain_upgrade.py`（集成，只守排空） | 排空期间新事项排队、在跑的照常结束 |
| 四层 | 上面两层（事实与裁决、循环）的文件：内核清单里 `kind` 为 `module` 的文件，五个契约模块，`orchestrator.py`、`runtime.py`、`engine.py`、`assembly.py`、`context.py` | `test_thin_driver_names.py`（单元，只查 `orchestrator.py`）；其余文件靠差异报告里的部门名检索 | 薄驱动不写部门与成果的名字 |
| 三环 | 第三环：内核清单 `harness/definitions/kernel-manifest.json`；第二环：五个契约模块、骨架事件、接口合同、定义格式；第一环：各道缝的实现 | 第三环 `kernel/test_manifest.py`（单元，导入方向与行数）、`path_guard.py`；第二环 `kernel/test_contract_surface.py`、`kernel/test_only_grows.py`、`test_contract_modules.py`、`test_openapi_snapshot.py`；第一环 `test_second_routing.py`、`test_second_slot_implementations.py`、`test_action_contract.py` 的第二种实现 | 内核只导入内核与标准库、行数有上限；契约名称与版本、骨架事件与停止原因只增；路由、装配、执行、执行环境能换第二种实现 |

## 变更记录

- 2026-10-29 / claude-sonnet-5-5 / 对着 main c5308acf 重核全表：改了 34 行（11 行把原来写「无」或「代码里还没有」的补上了代码里已有的名字，4 行补上漏记的名字，19 行订正名字或它所在的文件）；判断改为「一致」的 7 行、改为「不一致」的 4 行，「路由实现与它的定义、工作单元的大小」一行拆成两半分别判断；去掉旧提交号，其余行的名字核对无误；说明段里「一致的词不用记，立缝时逐行消」一句改为立缝时把那一行改成一致（表里仍有大量一致的行，原句与表相矛盾） / 原表按 2026-10-25 清点，整片过期（decision.md 2026-10-29）
- 2026-10-31 / claude-opus-5-5 / 加直做、子事项与子组织、核验角色、写入范围、成果种类与提案合同五行，「质检放行，事项完成」改为「放行或开环完成，事项完成」；「部门与角色」「核验中」改为不一致，`VERIFIER_OF` 从「谁能拒绝谁」移到核验角色一行；接纳补 `artifact_accepted`；`done` 一句补开环完成 / 按总图 ADR-0044 的改动核对
- 2026-10-31 / claude-opus-5-5（子架构师） / 「画面」一节加七种元件的对照表、画面拓扑、盖章台与出口托盘、章、点开回链五行，都是不一致 / 按画面总图与画面与播放设计说明第 10 至 13 节核对
- 2026-10-31 / claude-opus-5-5 / 加第 4 节「每道缝的守卫」：十三道缝与四层、三环各一行，写两侧在代码里、守卫文件与层、守卫实际断言的规矩；「核实方法、能否取消」一行改为一致（`Action.verification`、`Action.cancellable` 已在动作合同里） / 按缝的差异报告从这里取守卫清单；对着 main 5f5ff252 核对时发现该行过期
