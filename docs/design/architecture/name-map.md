# 总图的词与代码名的对照

状态：子架构师维护的对照表，按 main 2026-10-25（`a8a2182c`）清点；只写文档，不改代码。总图位置：第四节「要守的缝」的十三道缝，以及第一节的方框、第三节内环六步与外环九个状态。由[总体架构](overall-architecture.md)第 1.3 节链接。

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
| 一份事实 | 第一节「一份事实」；第四节写入口的一侧 | `event_store.py` 的 `EventStore`；流 `run_stream`、`project_stream`、`catalog_stream`；`models.py` 的 `Event`、`ProjectEvent`、`CatalogEvent` | 写入口 | 一致（方框的技术名词是事件日志） |
| 写入口 | 第四节写入口 | `write_path.py` 的 `WritePath`、`Transaction`、`NewEvent`、`NewProjectEvent`、`NewCatalogEvent` | 写入口 | 一致 |
| 期望版本 | 第四节写入口「交换」 | `WritePath.transact`、`append` 的参数 `expected_version`；`StreamVersionConflict`；`Event.stream_version` | 写入口 | 一致 |
| 事项的执行权编号 | 第四节写入口「交换」 | `WritePath.claim_execution_right`、`StaleExecutionRight`；编号本身叫 `epoch`（`Event.epoch`、`event_store.py` 的表列） | 写入口 | 不一致：方法与异常叫执行权，编号字段叫 `epoch` |
| 派发编号 | 第四节写入口「交换」；第三节「重派与迟到的结果」 | 无。一轮工作只有身份 `activation_id`（`new_id("act")`，记在事件内容、`ContextManifest` 与 `CheckReceipt` 里），不递增，写入口不核对 | 写入口 | 代码里还没有 |
| 消息身份、按消息身份去重 | 第四节写入口 | `event_store.py` 的 `Command`、`CommandRecord`、`DuplicateCommand`、`CommandIdReused`；`Event.command_id` | 写入口 | 不一致：叫命令身份，只覆盖经接口发来的命令 |
| 来源（部门、角色、工作单元） | 第四节写入口「交换」 | `Event.department`、`Event.role`、`Event.actor`、`Event.session_id`；工作单元没有字段 | 写入口 | 不一致：分在四个字段里，没有「来源」这一组；工作单元代码里还没有 |
| 证据引用 | 第四节写入口「交换」 | `Event.artifact_hashes`、`models.py` 的 `ArtifactRef`、`artifacts.py` | 写入口 | 一致（方框的技术名词是工件） |
| 提案、完成提案 | 第一节方程「U ≠ f」；第四节执行「出」 | `proposals.py`、`submissions.py`；事件 `proposal_submitted`、`proposal_rejected`；定义 `proposal_contracts.json` | 写入口、执行 | 一致 |
| 裁决（U） | 第一节「裁决与边界」；方程里的 U | `adjudication.py`（`tool_permission`、`ToolPermission`、`proposal_decision`、`commit_decision`、`WorkBasis`）、`validation.py`（`evaluate_proposal`、`ProposalDecision`） | 写入口内侧（内核，不是缝） | 一致 |
| 边界 | 第一节「裁决与边界」；第三节「每一步先问边界」 | `bounds.py`（`activation_bound`、`time_used_up`、`time_left_sec`）；询问深度在 `adjudication.ask_chain_max_depth`，轮次的计数在 `orchestrator.py` | 写入口内侧（内核，不是缝） | 一致 |
| 最小投影 | 第四节投影「内核的最小投影」 | 无。裁决现在读 `models.py` 的 `RunProjection`（`projection.py` 折叠，应用的读取也用它） | 投影（内核内部，不在缝里） | 代码里还没有 |

### 路由

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 薄驱动 | 第一节「薄驱动」；第四节路由与执行的一侧 | `orchestrator.py` 的 `Orchestrator`（流程编排：调度、激活的准备与收尾、安全节点的实现都在里面），由 `runtime.py` 的 `LoopSystem` 构造 | 路由、执行 | 不一致：叫流程编排（`Orchestrator`），薄驱动与路由实现还在一个类里 |
| 插件加载 | 第二节「只由你批准」 | 无。`LoopSystem` 直接构造各实现，组织定义里没有 `routing` 字段 | 路由、装配、执行 | 代码里还没有 |
| 路由契约 | 第四节路由 | 无 | 路由 | 代码里还没有 |
| 槽位：路由、路由实现 | 第一节「槽位：路由」 | `collaboration.py`（`ready_departments`、`next_department`、`allowed_proposal_kinds`、`guidance_*`）与 `Orchestrator` 的调度部分 | 路由；道 03 | 不一致：叫 collaboration，名字看不出是一种路由实现，一部分还在 `Orchestrator` 里 |
| 按成果（关注的成果） | 第一节「轮转方式」 | `definitions/__init__.py` 的 `Definitions.watched_outputs`；`collaboration.py` 的 `watched_new_work`、`has_new_work` | 路由；道 03 | 一致 |
| 任务池、工作单元、认领 | 第一节「轮转方式」；第三节外环「待认领」 | 无（`claim_execution_right` 的 claim 是领取事项的执行权，不是认领工作单元） | 路由；道 03 | 代码里还没有 |
| 事项 | 第一、三节 | 项目流里叫 work_item（`work_item_created`、命令 `work_item.create`、`work_item.cancel`、`work_item.append_input`，查询 `work_item.*`）；事项的一次执行叫 run（`run_stream`、`run_created` 至 `run_continued`、`RunProjection`，查询 `run.*`） | 路由、接口 | 不一致：总图只有事项，代码与接口资源名里 `work_item` 与 `run` 两个名字并存 |
| 质检放行，事项完成 | 第三节外环 | 质检结论 `models.py` 的 `QAReview`（`verdict` 字段）、事件 `qa_submitted`；事项结束 `run_done` | 路由 | 不一致：放行没有自己的名字，是质检结论的一个取值 |

### 装配

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 槽位：装配、装配实现 | 第一节「槽位：装配」；第四节装配 | `assembly.py` 的 `ContextAssembly`（`department_history`、`pin`、`request`、`finish_compaction`）；`context.py` 的 `ContextAssembler`、`AssembledContext` | 装配；道 04 | 一致 |
| 装配契约 | 第四节装配 | 接口就是 `ContextAssembly` 的四个方法，没有版本号 | 装配 | 代码里还没有（契约与版本） |
| 交给模型的那份 | 第四节装配「出」 | `assembly.py` 的 `StepRequest`；事件 `model_request_serialized` | 装配 | 一致 |
| 上下文清单 | 第四节装配「出」 | `models.py` 的 `ContextManifest`、`ContextSource`、`ContextExclusion`；事件 `context_assembled` | 装配 | 一致 |
| 压缩 | 第三节「上下文逼近上限 → 压缩」 | `compaction.py`（`plan_compaction`、`finish_compaction`、`CompactionCheckpoint`）；事件 `compaction_recorded` | 装配；道 04 | 一致 |
| 待并入的指导 | 第四节装配「入」；第三节两环的关系 | `assembly.pending_guidance`、`models.py` 的 `DepartmentGuidance`；事件 `department_guidance_received`、`_applied`、`_responded`；命令 `guidance.send` | 装配 | 一致 |
| 判定点 | 第三节「判定点」；第四节装配「判定点的选择先写事件」 | 无 | 装配、定义；道 06 | 代码里还没有 |

### 执行

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 槽位：执行、执行实现 | 第一节「槽位：执行」；第四节执行 | `engine.py` 的 `StepDriver`（`start`、`cancel`）、`StepLimits`；`recording.py` 的 `StepRecorder`、`ActivationScope` | 执行 | 一致（方框的技术名词是步骤驱动） |
| 执行契约、每一步先问边界 | 第四节执行 | `StepDriver.start`、`cancel` 与 `engine.py` 的 `SafeNode` 协议（`proceed`、`settle`、`end`、`department_selection`、`department_prompt`）；`orchestrator.py` 的 `_SafeNode`；没有版本号 | 执行 | 不一致：协议里带着 `department_selection`、`department_prompt` 两个按部门的方法，路由的问题混在执行契约里 |
| 一轮工作 | 第三节外环「一轮工作中」；第一节方程 | 叫 activation：`orchestrator.py` 的 `_Activation`、事件 `department_activated`、`activation_finished`、`bounds.activation_bound`、身份 `activation_id` | 执行、路由 | 不一致：叫激活，术语表把「激活」列为避免的说法 |
| 部门成员（一个会话） | 第六节「可以多份」 | `sessions.py` 的 `DepartmentSession`、`SessionFactory`；`models.py` 的 `SessionRecord` | 执行 | 一致 |
| 询问 | 第三节外环「询问中」；第四节执行「出」 | 事件 `ask_started`、`ask_answered`；`adjudication.ask_chain_decision`；`collaboration.pending_ask_department`；查询 `run.asks` | 执行、路由 | 一致 |
| 外包角色 | 第一节「工程」；第四节执行 | 无 | 执行；道 02 | 代码里还没有 |

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
| 回执 | 第一节「独立的证据」；第四节动作「回执」 | `actions.py` 的 `ActionReceipt`（`status`、`output`、`error`）；检查回执 `models.py` 的 `CheckReceipt` | 动作 | 一致 |
| 工具请求 | 第四节执行「出」 | `tools.py`；事件 `tool_call_required`、`tool_called`、`tool_started`、`tool_skipped` | 动作、执行 | 一致 |
| 起点快照、封存快照 | 第一节「一份事实」；第四节动作「请求」 | 封存：`snapshot.py`（`ingest_snapshot`、`restore_snapshot`）、`workspace.py` 的 `WorkspaceSnapshot`、`LocalEnvironment.snapshot()`；动作请求里的起点叫 `Preconditions.tree_digest`（公开树摘要） | 动作 | 不一致：动作请求里的起点叫树摘要，不叫快照 |
| 终点快照、前后差异 | 第四节动作「回执」 | 无。`ActionReceipt` 不带终点与差异 | 动作 | 代码里还没有 |
| 核实方法、能否取消 | 第四节动作「请求」 | 动作请求里没有这两项；核实只有事件 `action_verified` 与 `environment.py` 的树核对，取消只表现为回执的 `cancelled` | 动作 | 代码里还没有（作为动作合同的字段） |
| 工作区 | 第三节「从快照建工作区」；第六节 | `workspace.py` 的 `Workspace`；检查工作区 `environment.inspection_root`（目录 `inspections`） | 动作 | 一致 |
| 远程执行 | 第一节「模型与工具」；第六节 | 无 | 动作；道 05、10 | 代码里还没有 |

### 投影

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 应用的投影 | 第四节投影 | `projection.py`（`project_run`、`replay_run`、`RunHandler`）、`project_projection.py`、`app/read_models.py` 的 `ReadModels`、`views.py`、`overview.py` | 投影 | 一致 |
| 折叠函数、从头重算 | 第四节投影「交换」 | `projection.py` 的 `apply_event`、`replay_events`；`replay_check.py`；查询 `replay.check` | 投影 | 一致 |
| 骨架事件、应用事件 | 第二节「只能向后兼容」；第四节投影 | 两类没有分开：`models.py` 的 `EventType`、`ProjectEventType`、`CatalogEventType` 按流分，不按骨架与应用分 | 投影、写入口 | 代码里还没有（两类的划分） |

### 接口

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 应用层 | 第一节「界面」悬停；第四节接口的内侧 | `app/application.py` 的 `Application`、`ReadOnlyCore`；`app/registry.py` 的 `Registry` | 接口 | 一致 |
| 命令（带身份） | 第四节接口 | `app/registry.py` 的 `CommandDefinition`、`app/contracts.py` 的 `CommandRequest`、`Accepted`、`Rejected`；路径 `/api/commands/<名字>` | 接口 | 一致 |
| 查询（只读快照） | 第四节接口 | `app/registry.py` 的 `QueryDefinition`、`app/contracts.py` 的 `Snapshot`；路径 `/api/queries/<名字>` | 接口 | 一致 |
| 事件流（从某个位置起） | 第四节接口 | `app/event_stream.py` 的 `EventStream`、`StreamCheckpoint`、`StreamResync`、`StreamDelta`；路径 `/api/events` | 接口 | 一致 |
| 带版本号 | 第四节接口 | `api/app.py` 的 `contract_digest`；接口快照 `harness/tests/openapi/openapi.json`；客户端 `api/interface-version.ts` 的 `CLIENT_API_VERSION`；能力清单 `/api/capabilities`（`Capabilities`） | 接口 | 一致 |
| 接口层 | 第一节「界面」悬停 | `api/`（`app.py` 的 `create_app`、`server.py`、`access.py`、`pages.py`） | 接口 | 一致 |
| 等用户、决定请求 | 第三节外环「等用户」 | `decisions.py`（`DecisionKind`、`blocks_run`）、`models.py` 的 `DecisionRequest`；事件 `decision_requested`、`decision_answered`、`decision_withdrawn`；命令 `decision.answer`，查询 `decisions.list` | 接口、写入口 | 一致 |

### 画面

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 界面 | 第一节「界面」 | `client/`；壳 `shell/`、页面 `views/` | 画面、接口；道 09 | 一致 |
| 同步层 | 第一节「界面」悬停 | `contract/view-sync.ts` 的 `ViewSync`、`contract/event-stream.ts`、`contract/stream-state.ts`（目录叫 contract） | 接口（读者一侧） | 一致 |
| 翻译层 | 第四节画面 | 无。房间、楼层、首页的画面直接读查询结果与事件（`pixel/room/driver.ts`、`pixel/world/`、`pixel/building/`） | 画面 | 代码里还没有 |
| 画面层 | 第四节画面 | `pixel/`（`view.ts`、`view-state.ts`、`view-types.ts`、`world/`、`room/`、`floor/`、`building/`）；页面里的挂载 `views/pixel/PixelCanvas.tsx` | 画面；道 09 | 不一致：叫 pixel，输入类型叫 `PixelEvent`、`PixelModel`，术语表把「像素事件」列为避免的说法 |
| 元件断言、回链 | 第四节画面「交换」 | 无 | 画面 | 代码里还没有 |
| 播放参数 | 第四节画面「交换」 | 无播放时间线；只有动画时钟 `pixel/clock.ts` 与 `pixel/anims.ts` 的 `reducedMotion` | 画面 | 代码里还没有 |
| 页面 | 第一节「界面」悬停 | `views/`（`home/`、`project/`、`decisions/`、`models/`、`system/`、`timeline/`）、`shell/` | 画面（页面一侧）、接口 | 一致 |

### 定义

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 定义、加载与校验 | 第二节「定义」；第四节定义 | `definitions/__init__.py` 的 `Definitions`、`load_definitions`、`DefinitionError`；文件 `organization.json`、`roles.json`、`tools.json`、`proposal_contracts.json`、`rules.json`、`stop_reasons.json`、`work_items.json`、`service_presets.json`、`model_capabilities.json` | 定义；道 10 | 一致 |
| 版本 | 第四节定义「交换」 | `Definitions` 的版本取全部文件的内容摘要 | 定义 | 一致 |
| 部门与角色 | 第一节「下一个部门」；第四节定义「交换」 | `Organization`、`Department`、`Role`；`organization.json` 的 `product`、`engineering`、`quality` | 定义；道 01、02 | 一致 |
| 上限 | 第四节定义「交换」 | `rules.json` 与 `Rule`；`parameters.py`（`check_bounds`、`ParameterChange`、`fold_parameters`）；命令 `parameter.set`、事件 `parameter_set`、`project_parameter_set` | 定义 | 一致（方框的技术名词是上限与规则、参数） |
| 停止原因清单 | 第三节外环「停止」；第四节定义「交换」 | `stop_reasons.json`、`StopReason`、`UnknownStopReason`、`models.stop_reason_name`、`Event.stop_reason` | 定义 | 一致 |
| 谁能拒绝谁 | 第四节定义「交换」 | 无单独的声明；关系写在 `proposal_contracts.json` 与 `collaboration.py` 里 | 定义 | 代码里还没有 |
| 路由实现与它的定义、工作单元的大小 | 第四节定义「交换」 | 无（`organization.json` 没有 `routing`） | 定义、路由；道 03 | 代码里还没有 |
| 登记的机器 | 第四节定义「交换」；第六节 | 无 | 定义；道 10 | 代码里还没有 |
| 限定采用的范围 | 第四节定义「交换」；第五节第二层 | 无 | 定义 | 代码里还没有 |

## 2. 系统之外的三道缝

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 评价 | 第一节「评价」；第四节评价 | `evals/`（`scenarios/*/checks`、`scorer/`、`runner/`、`baseline/`）；发布检查 `harness/release_check.py`、`scripts/release.py`；内核清单 `harness/definitions/kernel-manifest.json` | 评价；道 08 | 一致（方框的技术名词是评测场景与隐藏检查、评分器、发布检查） |
| 观察者 | 第一节「观察者」；第四节观察者 | 离线的叫 analysis：`harness/analysis/`（`review.py`、`trajectory.py`、`batch.py`）；教训候选由 `Orchestrator._record_lesson_candidate` 在控制核心里写，事件 `lesson_candidate_recorded`，不经观察者缝 | 观察者；道 07 | 不一致：离线的叫 analysis；教训候选由流程编排在内部写，没有观察者这个模块 |
| 读取范围、振荡信号 | 第四节观察者「交换」 | 无 | 观察者；道 07 | 代码里还没有 |
| 看门狗（健康探针、切换命令、排空命令） | 第一节「看门狗」；第四节看门狗 | 看门狗与健康探针、切换命令都没有；排空已有：`streams.py` 的 `DrainState`、命令 `runtime.start_drain`、`runtime.force_upgrade`，事件 `runtime_drain_started`、`runtime_drain_finished` | 看门狗；道 10 | 代码里还没有（排空命令一项一致） |

## 3. 外环的九个状态

外环的状态对一个部门成立；代码里 run 自己的状态只有 `models.py` 的 `RUN_STATUSES`（`running`、`done`、`paused`、`failed`），部门的状态由 `collaboration.py` 从事件推出来，没有一个列出九个状态的类型。

| 总图的词 | 总图位置 | 代码里现在的名字 | 归哪道缝或哪条道 | 状态 |
| --- | --- | --- | --- | --- |
| 等待工作 | 第三节外环 | `collaboration.is_waiting` | 路由 | 一致 |
| 一轮工作中 | 第三节外环 | `collaboration.is_working`；run 状态 `running` | 路由、执行 | 一致 |
| 询问中 | 第三节外环 | `collaboration.pending_ask_department`；事件 `ask_started` | 路由、执行 | 一致 |
| 等用户 | 第三节外环 | `decisions.blocks_run`、`DecisionRequest`（见接口一节） | 接口 | 一致 |
| 核验中 | 第三节外环 | 检查工作区 `environment.inspection_root`；没有表示「核验中」的状态值 | 路由、动作 | 代码里还没有（作为状态） |
| 接纳 | 第三节外环 | 事件 `spec_accepted`、`contract_accepted`、`delivery_accepted`、`structure_accepted`、`baseline_review_accepted`、`product_decision_accepted` | 写入口、路由 | 一致 |
| 返工 | 第三节外环 | 取值 `rework`（`views/timeline/logic.ts`）、`rework_engineering`（`views/project/materials.tsx`）；缺陷在 `QAReview.defects`，页面显示「缺陷记录」 | 路由 | 一致 |
| 排空中 | 第三节外环 | `streams.py` 的 `DrainState`（见看门狗一行） | 看门狗 | 一致 |
| 停止 | 第三节外环 | run 的终态 `paused`、`failed` 加 `stop_reason`；`done` 是放行以后的完成 | 路由、定义 | 不一致：代码按暂停、失败分两种终态，总图只有停止，原因来自封闭清单 |
