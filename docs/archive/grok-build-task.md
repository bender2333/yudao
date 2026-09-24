# Grok Build 实施任务：Yudao Loop System MVP

你在 `D:\codes\yudao` 工作。请先完整阅读：

- `AGENTS.md`
- `docs/loop-system-mvp-design.md`
- `docs/grok-implementation-plan.md`
- 现有 `harness/` 代码与测试

目标是将当前确定性三部门样例替换为可运行、可观察、可测试的 Yudao Loop System MVP。它服务自治系统研发者，通过 `product -> engineering -> quality` 的隔离会话和结构化 spec 形成真实数据循环。不要为旧的 `requirements` 命名保留兼容层。

本次要落实 Phase 1、Phase 2 和 Phase 4，并提供 Phase 3 所需的可运行接口和明确的不可用状态；没有已经配置的 OMP RPC 服务时，不能伪造真实 LLM 成功。fake adapter 必须可以完整运行端到端场景。

## 必须交付

1. Python 控制层：
   - `ProductSpec`、`DeliverySpec`、`AskRequest`、`ProductReaction`、`QAReview`、`ArtifactRef`、`ContextManifest` 和 append-only Event；
   - SQLite Event Store、文件 artifact store、状态投影和 replay；
   - 闭合的 orchestrator 状态机，具有独立的 `product`、`engineering`、`quality`；
   - `ask -> react`：Engineering 提交 AskRequest，Product 对它 `accept/reply/reject` 或更新 ProductSpec，控制层验证后路由；
   - QA 能退回 Product 或 Engineering；只有绑定当前 ProductSpec 和代码快照的 QA release 才允许 DONE；
   - 循环/预算耗尽进入可观察的 `PAUSED` 终态，带明确停止原因和人工介入信息；provider 失败、取消、上下文超限等必须是显式终态事件；
   - 模型自然语言“完成”绝不能改变任务终态。

2. 会话和上下文边界：
   - 每个部门有独立 session；每次激活从投影重新装配，而非传递完整历史；
   - ContextManifest 记录注入/排除来源、token 估算、budget 和 digest；
   - Product 与 Quality 只能获得只读/检查工具，Engineering 才有写工具；
   - fake adapter 通过相同接口支持确定性测试；
   - 为 OMP RPC/NDJSON 实现实际 adapter 边界、错误映射和 abort；在 OMP 未配置时报告明晰的 provider-unavailable，不可静默降级到 fake。

3. 基础可视化：
   - 本地 Web 控制台作为 MVP 入口，提供 REST 查询、SSE 事件流和浏览器页面；
   - 页面须有 Run Board、Spec Timeline（包括 ask/react 与版本关系）、Evidence View、Context/Trace View；
   - UI 只读 Event Store/State Projection，不包含直接改写任务权威状态的路径；
   - 使用成熟且当前仓库可支撑的最简单方案。若没有前端构建系统，优先使用 Python 后端服务的静态 HTML/CSS/JavaScript，不引入没有必要的复杂框架。

4. 测试、演示与文档：
   - 全量替换旧 tests，覆盖：happy path、ask 的三种回答、QA 到 Product/Engineering 的返工、非法工件、提前停止文本、循环上限/预算耗尽、取消、provider error、replay 一致性、context 隔离；
   - 为 fake adapter 提供一个可运行的 Web 演示或样例 run，使页面四个视图都有数据；
   - 增加简明 README，写清启动、测试、可用 endpoint 和 OMP 配置前提；
   - 运行测试并修复失败；不得保留 TODO 或通过跳过测试掩盖问题。

## 架构约束

- Event Store 是唯一事实来源；投影可以从事件重放，Agent 不能直接写投影。
- LLM/adapter 只能提交结构化提案和证据；schema、权限、版本、前置条件和状态改变必须在普通控制代码中验证。
- 跨部门仅传正式 spec、artifact ref、证据和有限因果链；禁止默认注入其他部门的 transcript 或旧 spec 全文。
- 控制层不能在状态迁移函数内调用 LLM。
- 先做小而完整、能运行验证的版本，不实现知识图谱、长期记忆、运维部、动态角色、分布式调度、自动改写规则或模型。
- 尊重现有未提交的设计文档和 `jour.md`，不要删除或覆盖它们。

完成后，在最终回复中提供：修改文件、架构分层、执行的测试及结果、fake 样例事件摘要、OMP 未配置时的实际行为、任何明确的局限。不要只写计划，直接实现。
