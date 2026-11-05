# 调研资料

仍在使用的调研。每份调研支持一份需求记录或设计说明；设计写定以后，调研随设计索引归档到 `docs/archive/research/`，不在这里保留。

| 调研 | 支持的文档 | 用途 |
| --- | --- | --- |
| [游戏世界与代码世界的映射：可行性、图灵完备与路径](game-world-as-projection.md) | [D41 三个空间](../requirements/game-world-three-spaces.md)、[总体路线图](../program-roadmap.md)第 4 节 | 七种元件、三个空间与五层、投影的三条性质与三种检验、六步路径、可能错的七处 |
| [JEV 决策模型：能力边界与在 Yudao 中的用法](jev-decision-model.md) | [D28 元观察与规则检查部门](../requirements/meta-observer.md) | 元观察的设计还没有写，这份调研是能力边界的依据 |
| [圈复杂度与变异测试调研](complexity-and-mutation-testing.md) | [D35 自举](../requirements/self-hosting.md) | 阶段二结束之前手动进行的步骤与工具选择 |
| [组织、运行与演化研究](organization-runtime-evolution.md) | [恢复合同与故障矩阵](../design/recovery-contract-and-fault-matrix.md)、[D29 远程执行](../requirements/remote-execution.md) | 子循环、持久恢复与运维分工的依据 |
| [改善验证与选型实验规约](experiment-protocol.md) | [规则与参数](../design/rules-and-parameters.md) | 校准、选型、收益与采用的区分，正式实验之前读 |
| [内核读取运行状态投影的清点（2026-10-24）](kernel-projection-reads-2026-10-24.md) | [骨架与应用设计说明](../design/skeleton-and-application.md)第 5.5、12 节 | S1a 至 S1d、S2a 的范围；S1a 放出之前在当时的 main 上重做 |
| [DeepSeek Super-agent 与 Yudao 的异步框架](deepseek-superagent-async-framework.md) | [总体路线图](../program-roadmap.md)阶段二薄片 ⑤、阶段三、道 03 与道 10，[D06 运行中追加输入](../requirements/in-flight-input.md) | 不引入它的框架与代码的理由；外部入口、长命令转后台、并发槽留人槽、发件箱四个可借鉴的做法；外部入口是否算新方框交总架构师 |
| [文档一致性核对：概念模型与符号推理方案](doc-consistency-concept-model.md) | [决策记录](../decision.md)「文档一致性」四条 | 方向已定，索引与确定性规则已建在 `tools/doc-consistency/`，不开工单；只服务 Yudao 开发，分设计与脚手架两条线；文件图谱、关系与 hash 放在 `.doc-index/`，判断走样靠 clingo 规则；LLM 开放提取的试验没有通过（第 13 节），定向提取待验证 |
| [文档一致性：规则事实线方案](doc-consistency-rule-facts.md) | [决策记录](../decision.md)「文档一致性：规则事实单独成线」 | 给 LLM 读的规则文件单独成线，先做：规则类事实只在正本表格写一行，别处引用或用固定句式复述，clingo 比对，写文件时钩子提醒；工具没有改，第 1 至 4 步不改文档，用植入的矛盾验收 |
| [Uncle Bob 的 ub-mode 调研](uncle-bob-ub-mode.md) | [总体路线图](../program-roadmap.md)第 3 节「内核的代码质量门槛」、[可信内核设计说明](../design/trusted-kernel.md) | ub-mode 的做法与参数速查、它调用的 crapper、dryer、mutator 三个工具的阈值与用法、他本人关于不读代码的公开说法，以及与内核质量门槛的逐项对照（只写事实） |
| [Yudao 自身的本体建模：调研与方案](yudao-ontology.md) | [概念模型方案](doc-consistency-concept-model.md)、[规则事实线方案](doc-consistency-rule-facts.md)、[语义系统设计说明](../design/semantic-system.md)第 5 节 | 只在分支 `research/yudao-ontology` 上，不合进 main；本体内容的共用做法用户定了 C（重叠处与规则事实线同一份，按需长），第 10 节其余选择还没定。两个用途：按规格查架构到代码、测试的一致，给 agent 装上下文。MOF 式分层（写法、Yudao 本体、产品领域模型、事实），从意图、需求、总图到代码、测试、守卫的整条链放进同一份模型；clingo 闭世界检查本体自检、实例符合、分层、演化只增与链上的断点；同一份事实按关系给 agent 挑上下文，和记忆加 RAG 的对照，接语义系统第 10 节；和反射模型、代码事实库、可追踪模型等业界做法的对照；与规则事实线的三种共用做法及已定的 C 怎么接；分层规则的原型结果 |
| [Yudao 本体方案（第二版）：现在只建 Yudao 自己](yudao-ontology-v2.md) | [第一版](yudao-ontology.md)、[总图](../architecture.html)、[总图与代码的名字对照](../design/architecture/name-map.md)、[语义系统设计说明](../design/semantic-system.md)第 5 节 | 只在分支 `research/yudao-ontology` 上。分三样：Yudao 自己的本体（骨架、定义、裁决、路由、循环、组织、缝与环）现在建，挂在上面一层和脚手架接着；软件工程通用方法模板、流程里的领域建模一步现在不建，只写边界与以后怎么接。每个种类对到总图与代码，按三份发布形态编实例；第一步与成功标准对着 main 的 32753a3。取代第一版第 10.1、11 节 |

已归档的调研见 `docs/archive/research/`，索引是 [README-2026-09-06.md](../archive/research/README-2026-09-06.md)。
