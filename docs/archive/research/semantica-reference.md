# Semantica 参照调研

日期：2026-09-25。用途：为 [D25 语义系统](../requirements/semantic-system.md)整理部分（轨迹与图谱）提供参照。

来源：
- 上游仓库 `semantica-agi/semantica`（原 `Hawksight-AI/semantica`）提交 `2173308`（2026-09-25），与本机 `C:/project/codes/semantica` 相同；PyPI `semantica` 0.7.0（2026-09-22）。下文源码路径相对于仓库中的 `semantica/` 包目录，行号对应 `2173308`。
- 旧目录 `C:/project/yudao-refact` 的 `Docs/semantica-integration-research.md`、`Docs/semantica-integration-design.md`、`Docs/adr/0001-three-department-harness-semantica.md`（2026-09-01，基于 0.6.7）。
- 导入与行为测试在临时虚拟环境中进行，只安装核心依赖，没有修改仓库。

## 1. 项目身份与维护

| 项 | 事实 |
| --- | --- |
| 许可证 | MIT（`pyproject.toml:10`） |
| 版本 | 0.7.0，共 24 个发布，首个发布 2025-11-21；分类标记写 Production/Stable（`pyproject.toml:29`），0.7.0 仍有破坏性变更（`CHANGELOG.md:140-157`） |
| 活跃度（GitHub API，2026-09-25） | 星标 13,457；具名贡献者 110 个，一位维护者提交 2,045 次，占具名提交 68%；近 52 周 2,983 次提交；工单开放 57、关闭 440 |
| Python | 3.10 至 3.13（`pyproject.toml:26`） |
| 核心安装 | 47 个包、377 MB（scipy 87 MB、pyarrow 84 MB）；首次导入 ContextGraph 15 秒 |
| 测试 | 410 个测试文件，CI 只运行 `tests/reasoning/` 与少数文件（`.github/workflows/ci.yml:122-228`），没有覆盖率统计 |

## 2. 定位（官方原文）

- 仓库描述：「Graph-Native Infrastructure for Context and Accountable AI Systems」。
- README.md:69：「the semantic/context layer underneath your LLM, vector store, and agent framework: deterministic infrastructure (no LLM required for graph construction, reasoning, or provenance ...)」。
- README.md:253：「A Context Graph is the structured memory layer that traditional RAG is missing」。
- 主流程依次为 ingest、parse、normalize、split、semantic_extract、conflicts、deduplication、kg；上层模块为 ontology、reasoning、provenance、context（`ARCHITECTURE.md:11-67`）。

## 3. 模块与数据模型

### 3.1 本体（ontology）

- 本体是字典 `{uri, name, version, classes, properties, imports, metadata}`（`ontology/ontology_generator.py:497-509`）。类有名称、父类与说明；属性分对象属性与数据属性，带 domain 与 range；约束只有 cardinality、required、enum、pattern（`ontology_generator.py:1133-1155`）。
- 可以用 rdflib 输出 OWL（`owl_generator.py:241-322`），推导出 SHACL 形状（`ontology_generator.py:747-770`），用 pyshacl 校验 RDF 数据（`ontology_validator.py:148-273`，需要可选依赖）。
- 本体的三种来源：从数据归纳（类按实体类型出现的次数产生，结果标为草稿，需要人工确认，`bootstrap_schema.py:61-95`）；由大模型生成 JSON（`llm_generator.py:26-75`）；手写或导入。
- 校验的实际强度：GraphValidator 只在提供实体类型清单时对未知类型给出警告，不检查关系类型（`kg/graph_validator.py:188-198`）；推理机校验是占位实现，只检查两个键是否存在（`ontology_validator.py:340-369`）；约束检查固定返回通过（`ontology_validator.py:381-382`）。
- 版本放在内存字典中；可以比较两个版本并判定破坏性变更（`change_management/change_log.py:167-273`）。

### 3.2 抽取与实体身份

- 抽取方法有规则、正则、spaCy、HuggingFace、大模型等（`semantic_extract/methods.py:2868-2945`）；没有安装 spaCy 时改用正则（`ner_extractor.py:208-213`）。
- 实体合并默认关闭；开启后按名称或字符串相似度（阈值 0.7）合并，来源记入 `merged_from`（`kg/entity_resolver.py:51-53`、`entity_merger.py:475-505`）。

### 3.3 来源与证据（provenance）

- ProvenanceEntry 字段包括活动、执行者与角色、来源文档与原文摘录、置信度、派生来源、前一版本、有效起止、取代关系、作废信息与校验值（`provenance/schemas.py:80-165`）。
- 对应 W3C PROV-O：条目为 prov:Entity，活动为 prov:Activity，执行者为 prov:Agent，派生为 wasDerivedFrom，作废为 prov:Invalidation（`schemas.py:13-23`，导出在 `manager.py:1238-1400`）。
- 用 SQLite 保存；同一条目再次记录时，旧行改名保存，新行指向它，形成版本链（`manager.py:329-353`）；作废时追加新条目并记录时间、执行者与原因（`manager.py:1032-1104`）；每条记录串联 SHA-256，可以发现被删除的行。
- 有效起止与取代关系由调用者填写，系统不计算（`schemas.py:133-142`）。知识图谱的边另有有效起止、记录时间、被取代时间四个时间字段（`kg/temporal_model.py:28-66`）。

### 3.4 冲突与变更管理

- ConflictDetector 按实体比较同一属性的取值，冲突类型有取值、类型、关系、时间、逻辑五种，附来源与严重程度（`conflicts/conflict_detector.py:68-92`）。
- 解决策略有七种，其中两种人工审查策略只返回未解决标记，没有后续流程（`conflict_resolver.py:566-582`）；构图时调用的冲突解决只计数，注释写明是占位实现（`conflict_detector.py:1381-1389`）。
- 变更管理只做记录（快照、变更记录、版本标签），没有审批流程；全库没有事件重放，恢复依靠快照。

### 3.5 上下文、决定与因果（context）

- ContextGraph 是进程内的字典结构（`context/context_graph.py:612-633`），节点与边带有效期，可以查询某一时刻的有效状态（`:3747-3788`）；撤回节点时关闭有效期并保留历史（`:2699-2803`）；只能整份保存为 JSON 或 Markdown（`:1382-1443`）。
- 决定含类别、情景、理由、结果、置信度、作出者与有效期（`decision_models.py:87-102`），另有决策情境、带版本的政策、先例与审批链。
- 因果边只有 CAUSED、INFLUENCED、PRECEDENT_FOR 三种，两端都必须是决定（`context_graph.py:543-560`）。
- AgentContext 必须传入向量库（`agent_context.py:163-168`），检索为向量检索加图扩展（`:500-604`）。
- `tiers.py` 按佐证来源数与置信度把检索结果分为 gold、silver、bronze、quarantine 四级，只在检索时计算。
- 全库没有轨迹、尝试或工具调用的模型；最接近的是决定之间的因果边，以及 PROV 中串联活动的 wasInformedBy。

## 4. 与 Yudao 已确定内容的对照

| Yudao | Semantica |
| --- | --- |
| 证据（独立的一类内容） | 没有独立节点，来源是条目上的字段（`schemas.py:231-261`） |
| 事实（至少一条证据） | 关系字典加时间字段，或来源条目；不强制有证据 |
| 知识 | 没有对应类型 |
| 决定 | Decision；向来源记录写入决定的调用有缺陷（见第 5 节） |
| 要求、验收条件、约束 | Policy 带编号与版本，可以判定决定是否合规（`policy_engine.py:168-418`） |
| 实体 | 实体字典；节点类型是任意字符串 |
| 推测 | 没有对应类型 |
| 轨迹（尝试与因果） | 没有对应物 |

## 5. 与 Yudao 架构原则的冲突

- **事件溯源**：没有事件重放，恢复依靠快照；ContextGraph 只能整份保存。Yudao 的事件存储是唯一事实来源，状态可以完整重放。
- **状态主权**：#1639 原文「Semantica writes to the graph through several paths, and none of them asks permission first」；MCP 对外提供 add_entity、update_node、delete_node 等写入工具（README.md:1405-1423）。Yudao 中模型只提交提案，由主机校验后写入。
- **就地失败**：嵌入失败时静默改用随机向量（`vector_store.py:316-317`）；决定写入来源记录的调用缺少必填参数，还调用了不存在的方法，异常被捕获后只写日志（`decision_recorder.py:614-645`）；`ContextManagerWithProvenance(provenance=True)` 导入即报错（`context_provenance.py:30`）；实测撤回原因在保存再加载后丢失。
- **第二个事实来源**：provenance 模块自己用 SQLite 保存版本链，引入后会与事件存储并存。

## 6. 可以借用的做法

- 来源记录对应 W3C PROV-O：内容、活动、执行者，以及产生、使用、派生、归属、作废等关系。
- 四个时间字段：有效起止、记录时间、被取代时间。
- 决定带理由、结果与作出者，决定之间有因果与先例关系。
- 本体用类与属性定义，约束写成形状，主机据此校验数据。
- 冲突分类型记录，附来源与严重程度。
- 按佐证数量给内容分级（属于上下文组装专题）。

## 7. refact 的集成设计（2026-09-01）

- Semantica 位于事件之后：事件账本 → 语义投影 → Semantica；编排器是唯一的状态写入者，图谱是最终一致的读取模型，部门拿不到写入句柄（refact `Docs/harness-architecture-baseline.md:19,48-76,826`）。
- 只开放五个命名查询：trace_run、why_decision、evidence_for_criterion、supersession_chain、lesson_lineage（同文件 `:794-804`）。
- 推理或相似度得到的关系标为假设，不进入上下文（同文件 `:874`）。
- 2026-09-07 本仓库决定不引入 Semantica 依赖，只借用「图谱是下游读取模型、不拥有事实写入权」（`docs/archive/jour.md:547`）。

## 8. 同类项目

| 项目 | 事实 | 与 Semantica 的差别 |
| --- | --- | --- |
| Graphiti（Apache-2.0，v0.30.2） | 双时态；新事实让旧事实失效但保留历史；每个实体与关系可追溯到原始数据；需要 Neo4j、FalkorDB 或 Neptune，默认用 OpenAI 抽取与嵌入 | Graphiti 由大模型抽取并自动让旧事实失效；Semantica 由调用方显式撤回 |
| Cognee（Apache-2.0，v1.6.1） | 自称 Agent 记忆平台，接口为 remember 与 recall，支持自定义本体 | 重在记忆读写；Semantica 重在来源、推理与审计 |
| Microsoft GraphRAG（MIT，v3.2.0） | README 声明基本处于维护状态，不再接受新功能；批量建立索引，没有增量写入与时间维度 | Semantica 0.7.0 已加入同类的社区摘要与全局检索 |
