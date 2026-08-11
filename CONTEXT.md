# Dynamic Harness

Dynamic Harness 是本分支用于讨论长期运行、分层学习与渐进自我改进的领域语言。它描述目标系统，不把当前三部门实验实现视为最终结构。

## Language

**Dynamic Harness**:
在外部治理约束下，能够版本化调整控制参数、知识、Skill 与执行拓扑，同时持续扩展可学习 Artifact 前沿，并通过并行验证和回滚保持连续运行的复合系统。
_Avoid_: 大 Agent Loop、自修改 Agent

**Harness Node**:
可递归组合的执行单元，对外只暴露目标、状态、预算、结果和证据契约；内部可以是确定性流程、单 Agent、多个角色或另一个 Harness。
_Avoid_: Department、Subagent（泛指时）

**Constitution**:
定义系统目标、授权、安全限制、证据要求与可接受变更范围的治理约束；它不由受其约束的同一自适应回路自动改写。
_Avoid_: Surprise Objective、System Prompt

**Evaluation Authority**:
独立于候选变更生成者，对结果和变更候选产出权威评价记录的角色或机制。
_Avoid_: Self-evaluation、Critic Agent

**Artifact**:
运行环或发展环产生的、可观察、可版本化且带生成谱系的产物，例如任务、环境、Schema、Skill、工具、拓扑或外部作品。
_Avoid_: Output（未带身份和谱系时）、File

**Developmental Observer**:
按冻结协议学习 Artifact 前缀并评价后续 Artifact 的观察者；其版本、训练历史和可见信息共同定义观察视角。
_Avoid_: Judge、Generator、固定基础模型

**Novelty**:
相对指定 Developmental Observer，未来持续存在比当前目标更难预测的 Artifact；它不是单次 Surprise，也不表示数值或复杂度无界。
_Avoid_: Unfamiliarity、绝对新颖性

**Learnability**:
对同一未来 Artifact，Observer 获得更多历史后能够降低预测损失的序列性质。
_Avoid_: Memorization、一次训练分数提升

**Open-Endedness Profile**:
某个 Artifact 序列相对于指定 Developmental Observer、预测损失和有限时域的新颖性、可学习性、学习进展与不确定性记录。
_Avoid_: Creativity Score、绝对新颖性

**Frontier Experiment**:
在隔离发展环中探索新 Artifact 作用域、生成规则或环境的有界实验，其结果只能作为 Change Candidate 的证据。
_Avoid_: Production Run、自动晋升

**Prediction Commitment**:
在行动或变更发生前固化的、带作用域和成功契约的预期，用于和后续证据形成可审计比较。
_Avoid_: Retrospective Expectation、Confidence Statement

**Surprise Profile**:
预测承诺与观测证据之间差异的结构化描述，分别保留误差维度、幅度、精度、影响、范围与持续性。
_Avoid_: Surprise Score、单一惊讶值

**Precision**:
某个误差信号值得信任的程度，而不是误差大小或业务严重性。
_Avoid_: Severity、Confidence（未说明对象时）

**Episode**:
一次具体经历的事实记录，包含预测、行动、观测、证据和残差，不声称已经找到可泛化原因。
_Avoid_: Lesson、Rule

**Lesson Card**:
从一个或多个 Episode 提出的可证伪经验假设，带证据、作用域、反例和生命周期；被记录不等于成为有效策略。
_Avoid_: Fact、Policy

**Schema**:
经过跨情境证据支持的预测结构，用来说明某类条件下应期待什么结果，但本身不一定包含执行步骤。
_Avoid_: Prompt Template、单次 Lesson

**Skill**:
带适用条件、结果契约、内部策略、终止条件、证据谱系和失败回退路径的可执行抽象。
_Avoid_: Prompt、不可展开的黑盒能力

**Fold**:
把经过验证的 Harness 子图封装成 Skill，使调用者无需持续承担其内部复杂度，同时保留原子图和证据谱系作为回退。
_Avoid_: Delete、Summarize

**Unfold**:
在适用条件不明或预测残差超过门槛时，恢复 Skill 的内部 Harness 子图以重新观察、诊断和修订。
_Avoid_: Retry、Explain

**Change Candidate**:
尚未取得活动权的控制参数、Lesson、Schema、Skill、拓扑或模型适配器版本，只能在隔离、影子或灰度环境中接受评价。
_Avoid_: Improvement、Active Update

**Execution Grant**:
由可信授权和版本解析生成的不可变执行许可，绑定确切拓扑哈希、作用域、模式、预算、有效期及可选流量分片；Harness Runtime 只执行 Grant，不接受调用者点名拓扑。
_Avoid_: TopologyRef、配置参数

**Active Topology**:
某一作用域当前获授权接收真实任务的 Harness Node 图版本；同一作用域必须能解析到唯一活动版本。
_Avoid_: Latest Version、Current Code

**Organizational Closure**:
系统逐步替换内部材料时仍必须保持的治理关系集合，包括宪法主权、独立评价、证据连续性、权限隔离和回滚可达性。
_Avoid_: Static Architecture、Identity by Implementation
