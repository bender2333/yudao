# 设计文档索引

本目录保存模块设计、架构图与设计说明。计划与工单引用这里的文档；设计变化时直接修改对应文件，并在 `docs/CHANGELOG.md` 记录。需求原文见 [requirements](../requirements/README.md)，难以撤销的决定见 [adr](../adr/)。

- 总体架构设计（`architecture/`）
  - [总体架构：职责分层](architecture/overall-architecture.md)
    - 内容：分层图（客户端、接口层、应用层、控制核心、知识层、观察层、执行层）、各层职责与边界、按依赖顺序待讨论的六项事项、控制核心与执行者合同中需要先确定的问题。
    - 状态：2026-09-26 草案；用户认可分层图与职责分层表，讨论顺序与第 4 节的建议待确认。
  - [系统架构原理：控制核心与可替换的材料](architecture/core-and-materials.md)
    - 内容：出发点、核心公式与部门的身份、三个控制层次、确定性流程能消除什么、循环系统（Ralph 与 GPT-6 Astra）与控制的位置、与 2026 年 loop 工程、graph 工程、AI-native SDLC 的对照、原生核心与材料、分布式部署、外包角色、界面与后端的技术方向、项目的意义，含两张架构图。
    - 状态：2026-09-26 架构讨论记录；用户陈述与确认单独标注，第 11 节的事项待用户确认。
  - 依据：[Loop System 原理](../archive/native-harness/loop-system-principles.md)、[ADR-0007](../adr/0007-boundaries-for-distributed-deployment.md)。需求：[D29](../requirements/distributed-deployment.md)、[D31](../requirements/outsourced-agent-roles.md)。
- [模型管理](model-management.md)
  - 内容：模型目录、部门默认与项目部门设置、调用目标按每次请求解析、推理档位、压缩参数。
  - 状态：2026-09-24 设计已确认，未实施。
  - 需求：[D24](../requirements/model-management.md)。ADR：0002 至 0006。
- [Provider 层](provider-layer.md)
  - 内容：独立 Provider 模块的统一调用、服务方案、候选与准入、配置生效，含模块关系图。
  - 状态：Stage 2.7 已实现。「冻结目标」「协议归于模型访问定义」等部分由模型管理设计取代，模块边界、统一调用、取消与观测部分继续有效。
  - 需求：[D22](../requirements/startup-provider-reload.md)、[D23](../requirements/provider-layer.md)。ADR：0001 至 0004。
- [部门定向指导](department-guidance.md)
  - 内容：部门指导的处理时机、原文范围与放行关系。
  - 状态：2026-09-06 设计；指导接口已在 `harness/web/server.py` 实现。
  - 需求：[D20](../requirements/department-guidance.md)。
- [语义系统](semantic-system.md)
  - 内容：整理（轨迹、七类图谱内容与抽象层、写入与证据核对）与上下文组装（栏目、目录、接触时附加、通知、查询、各角色的上下文、长度控制、提示缓存）。
  - 状态：2026-09-26 设计说明，规则已由用户确认，未实施；路线位置为 Stage 4（部门内协作、上下文与界面）。惊讶机制放到后面，设计中保留扩展点。
  - 需求：[D25](../requirements/semantic-system.md)。ADR：0008、0009。调研：[语义系统与部门内多角色](../research/semantic-system-and-department-roles.md)、[Semantica 参照调研](../research/semantica-reference.md)、[上下文组装：参照调研](../research/context-assembly-reference.md)、[JEV 决策模型](../research/jev-decision-model.md)。
- [部门内多角色](department-roles.md)
  - 内容：中心型协作（中心角色、经理、探索者、主程、审查者）、角色清单、内部循环、角色任务、预测性探索与执行槽位、部门账本与交出检查、角色模型设置，含概念图、模块关系图、内部循环图与角色任务状态图。
  - 状态：2026-09-25 设计草案，规则已由用户确认，未实施；路线位置为 Stage 4（部门内协作、上下文与界面）。
  - 需求：[D26](../requirements/department-roles.md)。前置设计：语义系统、模型管理。
- [恢复契约与故障矩阵](recovery-contract-and-fault-matrix.md)
  - 内容：3.1 单机可靠恢复的恢复契约、故障矩阵与产品边界。
  - 状态：2026-09-19 设计合同，未实现；对应工单 #16、#17、#18。
  - 计划：[Stage 3 计划](../stage-3-plan.md) 3.1。
