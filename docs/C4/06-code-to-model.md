# 代码怎样反映到上层模型

## 抽象的依据

| 代码证据 | 提升到哪个层次 | 判断依据 |
| --- | --- | --- |
| 用户目标、可接受的交付与外部依赖 | C1 软件系统 | 谁负责提供能力，谁处在系统之外 |
| `__main__`、`api.server`、页面构建与数据目录 | C2 容器 | 运行环境、启动生命周期和存储职责 |
| `LoopSystem` 的依赖组装、Protocol、公开入口 | C3 组件 | 一组内聚职责对外提供什么接口，谁依赖它 |
| 实现接口的类型与关键函数 | C4 代码 | 哪段调用和数据关系保证上层承诺 |
| 一条真实调用路径、事件和回执 | 动态视图 | 结构中的元素怎样合作，哪些判断发生在提交之前 |
| 导入检查、契约检查与验收用例 | 关系证据 | 哪些边界有自动约束，哪些结论仍需运行验证 |

模型中的组件可以跨越多个文件，一个文件也可以为多个职责提供实现。例如 `orchestrator.py` 既包含运行编排，也提供安全节点和提案提交入口。`B3` 描述编排职责，`B7` 描述裁决职责，`B8` 描述提交职责；模型中的边界需要结合调用方向和内核清单解释。

部门的身份、工具许可和关注的成果由 `organization.json`、`roles.json`、`tools.json` 等定义提供。部门会话是运行实例；多个会话复用同一组驱动与契约。C1 的人员角色、C2 的运行单元、C3 的实现组件分别具有自己的判据，不能仅凭名称相似互相替代。

## 从代码到总图的对应

| 总图位置 | 当前实现元素 | 可定位的代码证据 | 自动检查入口 |
| --- | --- | --- | --- |
| 第一节：部门围绕事实协作 | `B3/B4/B8/B9` | `runtime.LoopSystem`、`watched_outputs.WatchedOutputs`、`organization.json` | `test_orchestrator.py`、`test_watched_relations.py` |
| 第二节：可信内核、契约、应用 | `B7/B8/B9/B12` 与三个契约 | `kernel-manifest.json`、`routing_contract.py`、`assembly_contract.py`、`execution_contract.py` | `kernel/test_manifest.py`、`test_contract_modules.py`、`test_layers.py` |
| 第三节：工作轮转 | `B3/B4/B6` | `Orchestrator.run_until_stop`、`StepDriver`、询问分支入口 | `test_concurrent_departments.py`、`test_routing_ask.py` |
| 第四节：写入口与裁决 | `B7/B8/B9` | `tool_permission`、`commit_decision`、`WritePath.transact`、`EventStore.commit` | `kernel/test_single_write_path.py`、`kernel/test_tool_needs_permission.py` |
| 第四节：路由、装配、执行 | `B4/B5/B6` | 三个契约及 `LoopSystem` 的构造注入 | `test_slot_contracts.py`、`test_second_slot_implementations.py`、`test_second_routing.py` |
| 第四节：模型与动作 | `B11/B10` | `ProviderFacade`、`LocalEnvironment`、`actions.py` | `test_providers_module.py`、`test_actions_contract.py` |
| 第四节：投影与接口 | `B13/B1/B2/F1` | `projection.py`、`project_projection.py`、`app/event_stream.py`、`contract/view-sync.ts` | `test_saved_projections.py`、`test_openapi_snapshot.py`、`test_event_stream.py` |
| 第四节：画面 | `F3/F4` | `translate/`、`pixel/contract.ts`、`pixel/world/` | 客户端单元与逐场景回放；范围见 `client/package.json` |
| 第四节：定义 | `B12` | `definitions.__init__` 与定义 JSON | `test_frozen_definitions.py`、`kernel/test_manifest.py` |
| 第五节：自举与验收 | 运行模型之外的工程约束 | 内核清单、`evals/`、`scripts/release.py`、CI | 按验收证据规则选择当前版本的实际运行记录 |
| 第六节：拆开部署 | 当前 C2 + 部署图 | `api/server.py`、`environment.LocalEnvironment`、`mcp_client.py` | 当前实现仅证明已经存在的调用路径；未来远程拓扑需要新增实现证据 |

此表记录设计概念的实现位置。列出的测试是后续验证入口，本次文档工作没有运行产品测试，也不把测试文件存在解释为对应保证已经验收通过。

## 一次模型更新的操作

1. 固定代码提交并记录工作区状态。比较旧 `source_commit` 与新提交的差异，找到受影响的 `evidence.path`。
2. 沿元素的父级向上查找：符号移动更新定位；职责变化更新 C3；运行环境或存储生命周期变化更新 C2；系统责任与外部协作变化更新 C1。
3. 检查关系的证据。构造注入说明连接方式；方法调用说明运行协作；导入只说明静态依赖。每条架构关系同时写明方向、数据和调用方式。
4. 检查总图对应的保证。实现遗漏、合同冲突或未规定的边界按仓库规则登记到 `docs/architecture-issues.md`，由相应角色处理。
5. 修改 `model.json` 中的元素、关系和代码证据，并重新投影 C1–C3 图。元素只是搬迁时保留 ID；拆分或合并时明确替换关系。
6. 核对父子归属、关系端点、路径、符号和源码摘要；渲染图检查层次与标签。行为变化另外运行相关测试，把测试结果绑定到实现提交。

例如修改模型协议适配器的函数，通常影响 `B11` 的代码证据；新增协议仍在同一个接入组件内。若将执行环境迁到单独服务，除了 `B10` 的实现变化，还需要新的 C2 运行单元、传输关系和部署位置，并核对总图动作合同的超时、取消和结果未知语义。扩大到 C1 的条件是系统责任或外部协作发生变化。

## 覆盖与证据的限度

当前 C3 将项目、建档、决定、材料、参数与回写归入应用和项目服务，将统计、运行视图与项目视图归入查询投影组件；这两组还包含可以继续展开的子职责。模型覆盖产品的主要运行边界，`model.json` 的路径集合记录本次选取的证据，未声称所有代码文件均已归类。

静态检查可以发现符号消失、文件变化和模型引用不成立。是否保持状态主权、是否能够恢复、质检是否独立等行为，需要契约用例、事件重放与真实验收共同证明。后续审阅时分别给出“结构证据成立”和“行为验收通过”的结论。
