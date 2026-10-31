# 基础规则

六条基础规则是整个系统最底层的规则，高于任何具体设计，不随演化改变，不进入规则登记。原文见 [D38 系统意图与基础规则](requirements/system-intent.md)「基础规则」。下表列出六条规则，以及系统中属于它们的具体规则；由内核测试守着的具体规则，测试登记在内核清单（`harness/definitions/kernel-manifest.json`）的 rules 一节。本文件属于[可信内核](design/trusted-kernel.md)，列在内核清单里，只由用户修改。

| 基础规则 | 系统中的具体规则 | 出处 |
| --- | --- | --- |
| 1. 现实的证据高于模型的意见 | 检查结果只认主机执行的回执 | `harness/definitions/roles.json`、`work_items.json` |
| | 放行必须绑定当前有效的合同、计划、交付与代码快照 | `work_items.json` 的质检说明 |
| | 准入记录只由真实的最小推理请求写入，目录的编辑、导入与导出都不含准入记录 | [模型管理设计说明](design/model-management.md)第 4.3 节 |
| 2. 没有传感器的地方明说是开环 | 没有可执行检验的验收条件标为开环，写进放行记录与离开期间的报告 | [验证的独立性设计说明](design/independent-verification.md) |
| | 没有核验角色的事项以开环完成结束；记录、页面与报告上写开环完成，不写成放行 | [总图](architecture.html)第三节「开环完成」、[形态与核验角色设计说明](design/forms-and-verifier-role.md) |
| 3. 生成者不裁决自己，被评价者改不了评价标准 | 模型只能提议；写入只经过写入口；控制核心的决定只依据已记录的事实与事先规定的去向 | [总图](architecture.html)第四节「写入口」的缝、[总体架构](design/architecture/overall-architecture.md)第 7.5 节 |
| | 目标、约束、验收标准只由用户修改 | [D38](requirements/system-intent.md)「基础规则」第 3 条、[总图](architecture.html)第四节「定义」的缝 |
| | 权威关系只随定义的版本改变；运行中 agent 与观察者不能修改定义 | [总图](architecture.html)第四节「定义」的缝 |
| | 达到上限记为失败或暂停，恢复不重新计数，参数修改不让它继续 | [规则登记与参数设计说明](design/rules-and-parameters.md)第 3 节、[循环与收敛设计说明](design/loops-and-convergence.md)第 3 节 |
| | 核验角色的结论不外包；放行、要求里的取舍与规则修改不交给判定点 | [总图](architecture.html)第一节「质检」与第四节「执行」的缝、[形态与核验角色设计说明](design/forms-and-verifier-role.md)「核验角色」、[总体架构](design/architecture/overall-architecture.md)第 7.5 节 |
| | 角色只提交记录与尝试，主机按本体校验后写成事件；重放不调用模型 | [语义系统设计说明](design/semantic-system.md)第 7 节 |
| | 隐藏材料不进入运行目录，隐藏检查、条目表与参考解法在运行结束以后才进入评分目录；评分之前核对材料的摘要，不同则这次运行无效 | [评测场景设计说明](design/evaluation-scenarios.md)第 3 节、[ADR-0038](adr/0038-function-first-commands-without-registration.md) |
| | 项目流只增加字段、事件种类或取值，已有字段的含义不变，删除或改变类型时测试失败 | [ADR-0019](adr/0019-project-stream-across-versions.md) |
| | 新的检查不修改控制核心 | [总图](architecture.html)第二节「什么能动」 |
| 4. 可信内核在自我修改之外，并且小到用户本人能看懂 | 运行中的实例改内核由用户经决定请求批准；开发仓库里改内核清单与内核路径不事前批准，经 CI 里的内核测试与测试覆盖核对；行数上限只降不升；修改内核路径的交付不自动采纳 | [可信内核设计说明](design/trusted-kernel.md) |
| | 改内核路径要保持这部分的测试覆盖：内核模块合计的行覆盖率不低于动手前，改动的行有测试执行到；内核测试和其他测试一样可以删，删了覆盖率照样不降 | [AGENTS.md](../AGENTS.md) 共同要求「内核路径的测试覆盖」 |
| 5. 每条规则和结构都要付租金 | 新增结构写明它拦截哪一类现有结构拦截不到的错误；新增的部门、角色、观察者、循环层写明它内聚的目标函数、证据来源与工作过程 | [验证的独立性设计说明](design/independent-verification.md)、[规则登记与参数设计说明](design/rules-and-parameters.md) |
| 6. 一定会停；改进只有超过噪声才算数 | 停止原因是一份封闭清单 | `harness/definitions/stop_reasons.json` |
| | 取消沿调用链立即生效；超时与取消结束整个进程树 | [总体架构](design/architecture/overall-architecture.md)第 3 节 |
| | 版本比较的差值超出噪声范围才算改进或退化 | [规则登记与参数设计说明](design/rules-and-parameters.md) |
