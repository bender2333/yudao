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

已归档的调研见 `docs/archive/research/`，索引是 [README-2026-09-06.md](../archive/research/README-2026-09-06.md)。
