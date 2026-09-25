# 设计文档索引

本目录保存模块设计、架构图与设计说明。计划与工单引用这里的文档；设计变化时直接修改对应文件，并在 `docs/CHANGELOG.md` 记录。需求原文见 [requirements](../requirements/README.md)，难以撤销的决定见 [adr](../adr/)。

- [系统架构原理：控制核心与可替换的材料](architecture-core-and-materials.md)
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
  - 内容：语义单元与关系、材料投影、语义整理、语义视图、查回、数据流核对，与压缩及跨事项的关系，含模块关系图。
  - 状态：2026-09-24 设计草案，未实施；路线位置为 Stage 4（部门内协作、上下文与界面）。语义系统作为单独的项讨论，检索方式为 TODO，第 11 节的规则待用户确认。用户补充的第二项职责（整理知识图谱与语义工程，供演化使用）尚未写入草案，见 D25。
  - 需求：[D25](../requirements/semantic-system.md)。调研：[语义系统与部门内多角色](../research/semantic-system-and-department-roles.md)。
- [部门内多角色](department-roles.md)
  - 内容：部门经理、固定角色清单、角色任务、部门账本、并行与执行槽位、角色模型设置，含模块关系图与角色任务状态图。
  - 状态：2026-09-24 设计草案，第 15 节的规则待用户确认，未实施；路线位置为 Stage 4（部门内协作、上下文与界面）。
  - 需求：[D26](../requirements/department-roles.md)。前置设计：语义系统、模型管理。
- [恢复契约与故障矩阵](recovery-contract-and-fault-matrix.md)
  - 内容：3.1 单机可靠恢复的恢复契约、故障矩阵与产品边界。
  - 状态：2026-09-19 设计合同，未实现；对应工单 #16、#17、#18。
  - 计划：[Stage 3 计划](../stage-3-plan.md) 3.1。
