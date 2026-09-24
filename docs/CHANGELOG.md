# 文档变更记录 (Docs Changelog)

本文档记录 `docs/` 目录下全部文档的新增、修改、重构与归档记录。修改 `docs/` 下任意文档时必须在本文档追加记录。

## 记录格式规范
`模型 ID / 时间（到分钟） / 具体的改动 / 原因`

---

claude-opus-5-5 / 2026-09-24 16:52 / 新增 docs/model-management-design.md（模型管理设计说明）、docs/requirements/model-management.md（D24）、docs/adr/0005-resolve-call-target-per-request.md、docs/adr/0006-reasoning-levels-declared-per-model.md；改写 docs/adr/0002、0003、0004 / 用户要求编写模型管理配置的需求与设计说明，作为以后判断冲突的标准：部门默认加项目部门设置、按每次模型请求解析调用目标、推理档位由模型声明、压缩参照 OMP 与 opencode

claude-opus-5-5 / 2026-09-24 16:52 / 在 docs/requirements/README.md 登记 D24；在 department-providers.md、startup-provider-reload.md、provider-layer.md、context-compaction.md、department-prompts.md、docs/provider-layer-design.md 开头说明被 D24 取代的部分；docs/decision.md 新增 2026-09-24 条目；docs/stage-3/omp-capability-gap.md「会话内换模型」改为采用并更新合计 / 使旧文档与新设计说明保持一致，避免按已取代的「任务冻结」「仅新任务生效」实施
