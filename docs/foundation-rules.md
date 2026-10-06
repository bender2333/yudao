# 基础规则

更新：2026-10-07。本文件属于[可信内核](design/trusted-kernel.md)，列在内核清单里，只由用户修改。

六条基础规则是整个系统最底层的规则，高于任何具体设计，不随演化改变，不进入规则登记。原文见 [D38 系统意图与基础规则](requirements/system-intent.md)「三、基础规则」。下表列出六条规则，以及系统中已有的、属于基础规则的具体规则；B1 建立内核清单时，为每条具体规则补上对应的测试名称。

| 基础规则 | 系统中的具体规则 | 出处 |
| --- | --- | --- |
| 1. 现实的证据高于模型的意见 | 检查结果只认主机执行的回执 | `harness/definitions/roles.json`、`work_items.json` |
| | 放行必须绑定当前有效的合同、计划、交付与代码快照 | `work_items.json` 的质检说明 |
| | 准入记录只由真实的最小推理请求写入，目录的编辑、导入与导出都不含准入记录 | [ADR-0002](adr/0002-candidates-need-test-to-admit.md) |
| 2. 没有传感器的地方明说是开环 | 没有可执行检验的验收条件标为开环，写进放行记录与离开期间的报告 | [验证的独立性设计说明](design/independent-verification.md) |
| 3. 生成者不裁决自己，被评价者改不了评价标准 | 模型只能提议；写入只经过写入口；控制核心的决定只依据已记录的事实与事先规定的去向 | [ADR-0013](adr/0013-event-log-and-single-write-path.md)、[ADR-0028](adr/0028-three-means-of-adjudication.md) |
| | 目标、约束、验收标准只由用户修改 | [ADR-0020](adr/0020-block-only-when-no-downstream-check.md) |
| | 权威关系只随定义的版本改变；运行中 agent 与观察者不能修改定义 | [ADR-0014](adr/0014-versioned-definitions.md) |
| | 达到上限记为失败或暂停，恢复不重新计数，参数修改不让它继续 | [ADR-0030](adr/0030-rules-are-provisional-defaults.md)、[ADR-0031](adr/0031-declared-loop-layers-and-sub-loops.md) |
| | 质检放行与产品取舍不外包，也不交给判定点 | [系统架构原理](design/architecture/core-and-materials.md)第 8 节、ADR-0028 |
| | 角色只提交记录与尝试，主机按本体校验后写成事件；重放不调用模型 | [ADR-0008](adr/0008-trajectory-and-graph-as-event-projections.md) |
| | 评测的隐藏材料对被测方不可见；隐藏检查、条目表与参考解法在运行结束以后才进入评分目录 | [评测场景设计说明](design/evaluation-scenarios.md)第 3 节、[ADR-0022](adr/0022-run-directly-without-containers.md) |
| | 项目流只增加字段、事件种类或取值，已有字段的含义不变，删除或改变类型时测试失败 | [ADR-0019](adr/0019-project-stream-across-versions.md) |
| | 准入钩子只能收紧，不能放开内置规则；新的检查不修改控制核心 | [阶段需求概览](requirements/stage-requirements-overview.md) |
| 4. 可信内核在自我修改之外，并且小到用户本人能看懂 | 内核清单只由用户修改，行数上限只降不升；修改内核路径的交付不自动采纳 | [ADR-0027](adr/0027-trusted-kernel-outside-self-modification.md) |
| 5. 每条规则和结构都要付租金 | 新增结构写明它拦截哪一类现有结构拦截不到的错误；新增的部门、角色、观察者、循环层写明它内聚的目标函数、证据来源与工作过程 | [ADR-0029](adr/0029-departments-form-by-information-cohesion.md)、ADR-0030 |
| 6. 一定会停；改进只有超过噪声才算数 | 停止原因是一份封闭清单 | `harness/definitions/stop_reasons.json` |
| | 取消沿调用链立即生效；超时与取消结束整个进程树 | [ADR-0011](adr/0011-async-control-core.md) |
| | 版本比较的差值超出噪声范围才算改进或退化 | [规则登记与参数设计说明](design/rules-and-parameters.md) |
