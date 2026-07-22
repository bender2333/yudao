# 三部门工单闭环与本机验证设计

> 状态：**APPROVED / 待实施**  
> 日期：2026-07-22  
> 分支：`exp/native-harness`  
> 取代对象：旧 `UNDERSTAND -> PLAN_EXECUTE -> VERIFY` 编排及其 cold/persistent 消融设计不再作为下一轮主方案；历史实现和数据只保留作追溯，不作为新协议兼容目标。

## 1. 目标

从零重做三部门工作方式，并验证下面这个单一问题：

> 面对自建的复杂软件任务，让需求、开发、质检三个部门通过正式工单闭环工作，是否比一个 Agent 独立做到完成更容易交付正确结果？

“做对”由循环外隐藏评分机械判定，不以 Agent 自述、公开测试或部门放行代替。

本轮允许两种结论之外的第三种结果：**证据不足**。三部门获胜不是项目完成条件。

## 2. 已确定的研究边界

### 2.1 本轮比较

只比较两种处理：

- **S — Solo**：一个长期会话自行调查、实现、自测并显式提交完成。
- **T — Team**：需求部、开发部、质检部三个长期私有会话，通过工单完成交接、返工和放行。

不保留 cold multi，不做部门消融，也不增加“solo + reviewer”。第一轮只判断完整工单闭环这一整套方案有没有质量信号。

### 2.2 公平条件

S/T 固定使用：

- 同一个 provider、模型和模型版本；
- 同一组可用模型参数；
- 同一段原始任务说明；
- 同一份初始代码与公开测试；
- 同一组文件工具和命名检查；
- 同样的安全上限；
- 同样看不到隐藏评分和参考修复。

两边**不要求消耗相同调用数、token 或墙钟**，均允许在安全上限内做到完成。因此本轮回答的是“各自跑到完成时谁更容易做对”，不能声称“同等推理预算下三部门更强”。成本只作副指标，不作为质量结论门槛。

### 2.3 本机软隔离限制

本轮暂不引入 Docker、Podman、WSL 或远程容器节点。采用受限工具和目录隔离降低意外泄露风险，但 Agent 生成的代码会以当前 Windows 用户权限运行，理论上仍可能读取宿主机可访问文件。

因此：

- 本轮结果只能称为“**本机软隔离、自建复杂任务下的工程证据**”；
- 不宣称 hidden oracle 具有 OS 级不可见性；
- 不把本轮结果外推为所有 Agent、模型或软件任务的普遍规律；
- 未来若要形成更强科学结论，必须另立采用一次性执行容器和独立判分容器的协议。

## 3. 核心架构

```text
控制进程
  ├─ 模型调用与计量
  ├─ 确定性状态机
  ├─ 工单校验、版本与哈希
  ├─ 三个私有会话（T）或一个私有会话（S）
  └─ 外层运行监督
          │
          ▼
本次运行工作区
  ├─ 原始任务
  ├─ 初始代码
  ├─ 公开测试
  └─ Agent 修改后的交付物
          │ 冻结代码快照
          ▼
循环外判分
  ├─ 隐藏测试
  ├─ 0–100 分评分
  └─ 致命错误门槛
```

模型不决定路由、版本、哈希、权限、停止原因、计数或最终分数。这些均由普通代码机械执行。

## 4. 三部门职责与可见边界

### 4.1 需求部（Requirements）

职责：把原始需求转化为可执行、可检查的验收合同。

可做：

- 读取原始任务、当前代码、公开文档和公开测试；
- 搜索和运行只读的公开检查；
- 提交或修订验收单；
- 回答开发部的澄清单；
- 处理质检部指向需求理解的返工单。

不可做：

- 修改代码；
- 替开发部选择具体实现；
- 查看开发部或质检部的私有会话；
- 直接放行任务。

### 4.2 开发部（Engineering）

职责：依据最新验收单完成实现并提交可核查证据。

可做：

- 读取原始任务、最新验收单、当前代码和指向开发的返工单；
- 修改和创建工作区文件；
- 运行预先登记的公开检查；
- 提交交付单；
- 在验收要求确实无法执行时提交澄清单。

不可做：

- 自行改写验收标准；
- 查看需求部或质检部的私有会话；
- 自己宣布外部评分通过；
- 直接放行任务。

### 4.3 质检部（Quality Assurance）

职责：独立复核真实代码和验收合同，亲自取得检查证据。

可做：

- 读取原始任务、最新验收单、当前代码和交付单；
- 搜索并运行预先登记的公开检查；
- 提交返工单，明确退回需求部或开发部；
- 所有公开验收满足后提交放行单。

不可做：

- 修改任何交付文件；
- 查看需求部或开发部的私有会话；
- 只依据交付单中的“测试通过”文字放行；
- 查看循环外隐藏评分。

## 5. 私有会话模型

T 的三个部门各拥有一个 run 级长期会话：

```text
RequirementsSession
EngineeringSession
QualitySession
```

规则：

1. 每个会话在 run 开始时创建，run 结束时销毁，不跨 run 延续。
2. 部门返工后重新激活时，继续自己的完整消息历史和工具回执。
3. 三个会话的 messages、推理、工具回执和私有元数据绝不互相注入。
4. 跨部门唯一通道是控制层校验过的正式工单。
5. 每次激活仍附上原始需求、最新有效工单和当前工作区摘要，避免只依赖记忆。
6. 原始需求是不可变 L0；最新验收单是当前执行合同。若二者疑似冲突，必须走澄清或需求返工，不能由开发部静默选择。
7. 最新有效工单覆盖私有会话中的旧判断；system prompt 明确写入这一优先级。
8. 完整私有 transcript 单独落盘，用于审计串线；不作为其他部门输入。
9. MVP 不做聊天压缩。若模型上下文溢出，run 以 `context_overflow` 失败并保留证据。

S 使用一个 run 级长期会话。它拥有与开发部相同的文件能力和公开检查，但没有部门工单、独立质检或返工路由。S 必须调用结构化 `submit_done` 才算自报完成；自然语言停下不算完成。

## 6. 工单协议

### 6.1 公共头部

所有工单包含：

```json
{
  "schema_version": 1,
  "ticket_id": "...",
  "task_id": "...",
  "issuer": "requirements|engineering|quality",
  "revision": 1,
  "parent_hash": null,
  "content_hash": "sha256:..."
}
```

控制层将除 `content_hash` 外的工单内容按 UTF-8、键排序、紧凑 JSON 规范化后计算 SHA-256。时间戳和本地文件路径属于事件元数据，不进入工单内容哈希。

校验规则：

- schema 不合法：留在当前部门并返回字段级错误；
- `task_id` 不符：拒绝；
- revision 不连续：拒绝；
- `parent_hash` 不是当前有效上游工单：拒绝；
- `content_hash` 不匹配：拒绝；
- 引用旧验收单或旧代码哈希：拒绝；
- 工单校验通过后才允许状态跳转。

### 6.2 验收单（AcceptanceSpec）

需求部提交：

```json
{
  "summary": "要解决的问题",
  "requirements": [
    {"id": "R-001", "behavior": "可观察行为", "evidence": "如何公开检查"}
  ],
  "edge_cases": [
    {"id": "E-001", "behavior": "边界行为", "evidence": "如何观察"}
  ],
  "regressions_to_avoid": [
    {"id": "G-001", "behavior": "不能破坏的旧行为"}
  ],
  "fatal_conditions": [
    {"id": "F-001", "behavior": "数据损坏、越权、假成功等"}
  ],
  "constraints": ["明确约束"],
  "non_goals": ["明确不做的内容"],
  "clarification_responses": []
}
```

每条要求必须可观察，禁止使用“合理处理”“做好错误处理”等无法机械核查的表达。需求部不得看到隐藏测试，验收单也不得猜测隐藏用例源码。

### 6.3 澄清单（ClarificationTicket）

开发部提交：

```json
{
  "blocked_requirement_ids": ["R-001"],
  "question": "缺少的决定",
  "interpretations": [
    {"choice": "A", "observable_result": "结果 A"},
    {"choice": "B", "observable_result": "结果 B"}
  ],
  "why_blocking": "不澄清会产生的合同差异"
}
```

澄清单进入需求部。需求部必须通过新 revision 的验收单回答，不能只返回散文消息。

### 6.4 交付单（DeliveryReport）

开发部提交：

```json
{
  "acceptance_hash": "sha256:...",
  "code_tree_hash": "sha256:...",
  "changed_files": ["relative/path.py"],
  "requirement_mapping": [
    {"requirement_id": "R-001", "files": ["relative/path.py"]}
  ],
  "checks": [
    {"name": "public_tests", "exit_code": 0, "result_digest": "sha256:..."}
  ],
  "known_risks": []
}
```

控制层验证文件确实存在、代码树哈希匹配、检查确实由本 run 的 `run_check` 产生。模型不能伪造退出码或检查摘要。

### 6.5 返工单（DefectTicket）

质检部提交：

```json
{
  "acceptance_hash": "sha256:...",
  "code_tree_hash": "sha256:...",
  "route": "requirements|engineering",
  "defects": [
    {
      "defect_id": "D-001",
      "requirement_ids": ["R-001"],
      "severity": "fatal|major|minor",
      "reproduction": ["机械复现步骤"],
      "expected": "期望结果",
      "actual": "实际结果",
      "evidence": [{"check": "public_tests", "result_digest": "sha256:..."}]
    }
  ]
}
```

`route=requirements` 表示验收合同错误、矛盾或缺失；`route=engineering` 表示合同足够清楚而实现不满足。返工单可包含多个缺陷，但整张单只允许一个 route，避免一次跳向两个状态。

### 6.6 放行单（ReleaseDecision）

质检部提交：

```json
{
  "acceptance_hash": "sha256:...",
  "code_tree_hash": "sha256:...",
  "verified_requirements": ["R-001", "E-001", "G-001", "F-001"],
  "checks": [
    {"name": "public_tests", "exit_code": 0, "result_digest": "sha256:..."}
  ],
  "closed_defects": ["D-001"],
  "decision": "release"
}
```

只有质检部可以提交，且必须覆盖验收单全部可验证项。控制层只把它解释为“Team 自报完成”；真正正确性仍由循环外隐藏评分决定。

## 7. 确定性状态机

```text
REQUIREMENTS
  └─ valid AcceptanceSpec ───────────────► ENGINEERING

ENGINEERING
  ├─ valid ClarificationTicket ──────────► REQUIREMENTS
  └─ valid DeliveryReport ───────────────► QUALITY

QUALITY
  ├─ DefectTicket(route=requirements) ───► REQUIREMENTS
  ├─ DefectTicket(route=engineering) ────► ENGINEERING
  └─ valid ReleaseDecision ──────────────► DONE
```

附加规则：

- 需求部因澄清或需求返工产生新验收单后，必须重新经过开发部和质检部。
- 自然语言结束、空回复、普通 assistant 文本均不触发状态跳转。
- 部门没有提交合法终端工单时，控制层在同一私有会话中提示一次格式错误并继续；连续两次仍无合法工单，run 以 `role_incomplete` 失败。
- 质检部没有隐式 PASS；只有合法放行单进入 DONE。
- Solo 没有隐式 PASS；只有合法 `submit_done` 进入 DONE。

## 8. 卡死与安全上限

S/T 使用相同的宽松保险丝：

- 最多 200 次成功模型调用；
- 最长 90 分钟真实进程墙钟；
- Team 最多 8 个质检返工循环；
- 相同验收单哈希、代码树哈希和缺陷内容哈希连续出现两次，记 `stalled`；
- 没有代码变化却连续两次提交交付单，记 `stalled`；
- 上下文溢出记 `context_overflow`；
- 达到任一上限均记失败，不能标为完成。

两边不要求实际消耗相同。调用数、token、墙钟和费用全部记录。

## 9. 工具设计

### 9.1 Agent 可用工具

移除任意 `bash`。只保留：

```text
read_file(path)
write_file(path, content)
edit_file(path, old, new)
list_files(path)
search_text(pattern, path)
run_check(name)
```

Team 权限：

| 工具 | 需求部 | 开发部 | 质检部 | Solo |
|---|---:|---:|---:|---:|
| read/list/search | 是 | 是 | 是 | 是 |
| write/edit | 否 | 是 | 否 | 是 |
| run_check | 是 | 是 | 是 | 是 |
| 提交验收单 | 是 | 否 | 否 | 否 |
| 提交澄清/交付单 | 否 | 是 | 否 | 否 |
| 提交返工/放行单 | 否 | 否 | 是 | 否 |
| submit_done | 否 | 否 | 否 | 是 |

### 9.2 命名检查

每题 manifest 预先声明检查：

```json
{
  "checks": {
    "public_tests": ["python", "-m", "pytest", "tests/public", "-q"],
    "build": ["python", "-m", "compileall", "src"]
  }
}
```

执行规则：

- Agent 只能传检查名，不能传命令或额外参数；
- 每次检查先计算当前代码树哈希，再把工作区复制到一次性检查镜像；
- 控制层在镜像中使用参数数组直接启动，不经过 shell；检查结束后删除镜像，任何角色的检查都不能改写真实工作区；
- 检查结果绑定调用前的代码树哈希，代码变化后旧证据自动失效；
- cwd 固定为一次性检查镜像；
- 环境变量使用最小允许列表，不继承 provider key；
- 每个检查有 manifest 固定超时；
- stdout/stderr 截断落盘并返回摘要；
- 退出码和结果摘要由控制层生成，模型不能覆盖；
- manifest、任务种子和检查配置在正式运行前冻结。

### 9.3 路径边界

所有文件工具：

- 只接受相对路径；
- `realpath` 后必须位于工作区；
- 不跟随逃出工作区的符号链接；
- 种子复制时拒绝符号链接和特殊文件；
- list/search 不遍历工作区外目录；
- provider 配置、judge 路径和仓库根路径不进入 prompt、事件或 summary。

这只能降低工具层泄露风险，不能消除 Agent 生成代码在公开检查运行时读取宿主机的理论能力。

## 10. 模型与基础设施故障

停止原因必须分类，不能把异常当自然完成：

| 类别 | 示例 | 处理 |
|---|---|---|
| 正常工单 | 合法 terminal ticket | 按状态机跳转 |
| 格式失败 | 空工单、缺字段、旧哈希 | 同会话返回一次校验错误；再次失败则 `role_incomplete` |
| 模型策略拒绝 | `finish_reason=content_filter` | 相同上下文重试一次；再次发生记 `provider_blocked`，该 run 失败 |
| 暂时 provider 故障 | 429、503、连接超时 | 固定退避最多三次；仍失败则整对 cell 标记 infrastructure-invalid |
| 预算/保险丝 | calls、墙钟、返工上限 | run 失败并保留全部产物 |
| 系统失败 | 缺 summary、状态损坏、快照失败 | run 失败；不能进入隐藏评分 PASS |
| 任务失败 | Agent 放行但隐藏评分不通过 | 正常有效样本，记录实际分数和 false-complete |

若某个 `(task, repetition)` 中任一臂因暂时 provider 故障被判 infrastructure-invalid，则 S/T 整对从全新工作区重跑一次，防止只重跑失败的一边。相同 block 再次出现基础设施故障时停止批次并调查，不选择性删除样本。

`content_filter` 在一次原样重试后仍失败，被视为该处理在当前 provider 下未能完成，不从结果中静默剔除。

## 11. 本机运行监督

每个 run 由独立子进程执行，外层 supervisor 负责：

1. 创建全新运行目录，已存在即失败；
2. 注入不含密钥的最小环境；
3. 启动 S 或 T；
4. 记录真实墙钟；
5. 90 分钟时终止整个 Windows 进程树；
6. 等待文件句柄关闭后检查 `summary.json`；
7. 冻结最终代码树和 SHA-256；
8. 结束 Agent 流程后再启动循环外评分。

`summary.json` 必须最后原子写入。缺 summary、半写 JSON 或代码哈希不一致均为系统失败。

## 12. 自建复杂任务集

### 12.1 规模与类型

正式题共 12 道，每类 3 道：

1. **跨文件根因故障**：表象在局部，根因位于共享代码，局部补丁会漏 sibling path。
2. **完整功能改动**：至少跨接口、业务逻辑、存储或调用端三层。
3. **失败恢复**：覆盖重试、幂等、部分成功、并发或中途失败后的状态正确性。
4. **安全与数据保护**：覆盖权限、输入边界、路径、敏感信息或防数据丢失。

每题要求：

- 10–40 个相关文件；
- 正确修复通常改 2–8 个文件；
- 专家参考修复约 40–200 LOC；
- 初始项目可启动，但目标行为确实失败；
- 有公开测试供 Agent 自查；
- 有独立隐藏评分；
- 无联网、人工交互和真实需求歧义；
- 不以文字游戏或冷知识制造难度。

### 12.2 目录约定

```text
experiments/work-order/
  development/
    <task-id>/
      task.md
      manifest.json
      visible/
      judge/
  formal/
    <task-id>/
      task.md
      manifest.json
      visible/
      judge/
```

`visible/` 是唯一可复制进 Agent 工作区的内容。`judge/` 包含隐藏测试、评分器、参考修复和不完整修复样本，不复制、不引用、不把路径写入任何 Agent 可见产物。

### 12.3 每题准入门槛

每题在冻结前必须证明：

1. 初始代码在隐藏评分中失败；
2. 专家参考修复得到 100 分且无致命错误；
3. 至少两种表面合理但不完整的修法被指定隐藏检查抓住；
4. 一个未参与出题的复核者仅凭 `task.md + visible/` 能完成参考级修复；
5. 初始代码、参考修复和两种不完整修复的公开检查与隐藏评分，各自连续运行三次且退出结果、分数和 fatal 分类完全一致；
6. manifest、任务、visible、judge 和评分权重均记录 SHA-256。

不满足任一项的题废弃，不进入正式题库。

## 13. 隐藏评分

### 13.1 分数

每题满分 100，权重冻结为：

- 50 分：核心功能；
- 25 分：错误和边界情况；
- 15 分：旧功能回归；
- 10 分：安全、数据完整性和错误报告。

每个隐藏检查在 manifest 中预先映射到唯一分类和固定分值。评分器只根据确定性进程退出、断言和产物计算，不调用 LLM。

### 13.2 致命错误

出现任一项，`fatal=true`，该 run 的 `effective_score=0`；原始 0–100 分仍保留：

- 数据损坏或静默丢失；
- 越权或泄露敏感信息；
- 实际失败却报告成功；
- 项目无法启动、构建或导入；
- 删除、篡改或绕过测试；
- 伪造控制层检查证据。

### 13.3 自报完成偏差

- `false_complete`：S 调用 `submit_done` 或 T 获得放行单，但隐藏评分不是 100 分或出现 fatal。
- `missed_win`：run 因非基础设施原因未自报完成，但隐藏评分为 100 且无 fatal。

无论 harness 自报什么，主质量只认循环外评分。

## 14. 校准与正式实验

### 14.1 校准题

先制作两道 development 题：

- 一道跨文件根因故障；
- 一道部分失败恢复功能题。

每题各跑一次 S 和 T，只验证：

- 工单闭环与私有会话；
- 返工路由；
- 命名检查；
- provider 异常分类；
- 外层超时；
- 循环外评分；
- 日志、代码哈希和成本记录。

校准题以及任何用于修改 prompt、工单或流程的题永不进入 formal。

### 14.2 冻结

校准通过后一次性冻结：

- provider、模型和可用模型参数；
- S/T system prompts；
- 五类工单 schema；
- 状态机和停止原因；
- 工具定义与每题命名检查；
- 12 道任务、公开材料、隐藏评分和参考修复；
- 运行顺序 seed；
- 安全上限；
- 第 15 节结论门槛。

冻结清单记录所有输入 SHA-256 和 git commit。正式运行开始后，修改任一冻结输入都使当前批次作废，必须使用新版本重跑全部样本。

### 14.3 运行规模

```text
12 tasks × 2 treatments × 3 repetitions = 72 runs
```

- 每个 `(task, repetition)` 是一个配对 block；
- block 内 S/T 顺序按冻结 seed 随机；
- 每次从全新 visible 副本开始；
- run 目录禁止复用；
- 失败、超时、卡死、拒绝输出和 false-complete 全部保留；
- 隐藏评分在 Agent 结束后独立执行。

## 15. 聚合与结论规则

### 15.1 统计单位

run 级记录全部 72 个样本。主比较以 task 为单位：

1. 每个 task/treatment 对三次 `effective_score` 取中位数；
2. T 中位数大于 S 记 T 赢一题；相等记平；小于记输；
3. 对 12 个 task-level 中位数计算平均差 `T - S`；
4. fatal 和 false-complete 以全部 run 数比较。

### 15.2 三种允许结论

**支持三部门更容易做对**，必须同时满足：

- T 至少赢 10/12 题；
- task-level 平均有效分提升至少 +5；
- T 的 fatal 次数不多于 S；
- T 的 false-complete 次数不多于 S。

10/12 胜题在无平局、双方等概率假设下的单侧精确 sign test 为：

```text
(C(12,10) + C(12,11) + C(12,12)) / 2^12
= 79 / 4096
≈ 0.0193
```

**不支持**，满足任一项：

- task-level 平均有效分差 `<= 0`；
- T 只赢 6/12 题或更少。

**证据不足**：其余所有情况，包括赢 7–9 题、平均提升在 0–5 之间，或质量门槛满足但 fatal/false-complete 门槛未满足。

成本不改变上述质量结论，但报告必须同时给出 calls、tokens、墙钟和费用倍数。若 T 质量达标但成本极高，结论写为“本机工程证据支持质量提升，但成本代价为 X”，不得省略代价。

## 16. 运行产物与可审计性

```text
runs/work-order/<batch-id>/
  batch_config.json
  frozen_inputs.json
  results.jsonl
  results.csv
  tasks/<task-id>/<treatment>_r<rep>/
    input.json
    events.jsonl
    tickets/
      acceptance-r*.json
      clarification-*.json
      delivery-*.json
      defect-*.json
      release.json
    sessions/
      requirements.jsonl
      engineering.jsonl
      quality.jsonl
      solo.jsonl
    workspace/
    final_tree.json
    summary.json
    score.json
    judge.log
```

规则：

- T 只写前三个 session 文件；S 只写 solo；
- events 不含 provider key、隐藏测试、judge 路径或完整敏感环境；
- `final_tree.json` 记录相对路径、大小和 SHA-256；
- `summary.json` 最后原子写入；
- `score.json` 由循环外评分器写入；
- `results.jsonl` 保留每个计划 run，不筛失败；
- `runs/`、原始 transcript 和 provider 配置不提交；研究报告只引用脱敏聚合。

每个 run 至少记录：

- task、treatment、repetition、顺序 seed；
- 模型标识和可获得的 provider fingerprint；
- outcome、stop_reason、状态跳转和返工数；
- calls、prompt/completion/reasoning tokens、真实墙钟和费用；
- 最终代码哈希；
- raw/effective score、fatal、false_complete、missed_win；
- 基础设施和 provider 故障分类。

## 17. 代码边界

重用现有、已经验证的底层 LLM client 与确定性计量；不重用旧 U/P/V 路由和 prompt。文件按以下职责切分：

| 文件 | 唯一职责 |
|---|---|
| `harness/contracts.py` | 工单 dataclass/schema、规范化、SHA-256 和字段校验 |
| `harness/role_session.py` | 单个长期私有会话及 transcript 落盘 |
| `harness/work_order_loop.py` | T 确定性状态机、路由、卡死检测和汇总 |
| `harness/local_tools.py` | 相对路径文件工具、权限过滤和命名检查 |
| `harness/run_team.py` | 单次 T CLI 装配，不包含批次逻辑 |
| `harness/run_solo.py` | S 单会话入口，改为同工具边界与显式 `submit_done` |
| `harness/supervisor.py` | 子进程、90 分钟硬超时、进程树终止和 summary 完整性 |
| `scripts/work_order_experiment.py` | 配对顺序、workspace 复制、循环外评分和批次汇总 |
| `harness/tests/test_contracts.py` | 工单、版本、哈希和 stale 引用 |
| `harness/tests/test_work_order_loop.py` | 全状态路径、返工、权限、私有记忆和卡死 |
| `harness/tests/test_local_tools.py` | 路径、符号链接、命名检查和环境清理 |
| `harness/tests/test_supervisor.py` | 超时强杀、缺 summary 和进程失败 |
| `harness/tests/test_experiment.py` | 配对、重跑规则、评分和结果完整性 |

干净切换后删除无调用方的旧 orchestrator/session/stage 工具和相应旧测试，不保留别名、双路由或兼容 shim。历史协议文档继续保留并标明已被本设计取代。

## 18. 分阶段验收

### P0 — 合同与状态机

交付：五类 schema、哈希、版本、路由和错误分类，全部使用假模型。

验收：

- 合法状态路径全覆盖；
- 缺字段、旧哈希、错 issuer、错 revision 均失败；
- 不从自然语言推断状态；
- 相同输入得到相同路由。

### P1 — 私有会话与权限

交付：三个 T 长期私有会话、一个 S 会话、工具权限和 transcript。

验收：

- 部门重入保留本部门完整历史；
- 三个部门 transcript 不串线；
- 最新工单覆盖旧记忆；
- 需求/质检不能写文件；
- 只有质检能放行；
- Solo 必须显式 `submit_done`。

### P2 — 本机工具边界与 supervisor

交付：移除任意 shell、命名检查、环境清理、run 子进程和进程树硬超时。

验收：

- 绝对路径、`..`、逃逸 symlink 和未登记检查均失败；
- provider key 不出现在工作区、事件和 child env；
- 卡住的模型或检查最终被 supervisor 收口；
- 缺 summary 大声失败。

### P3 — 两道 development 校准题

交付：两道题、S/T 各一次、循环外评分和完整产物。

验收：

- 4/4 计划 run 都有 summary 和 score；
- 至少人工触发一次返工路径；
- content_filter、暂时 provider 故障和超时通过可控 fixture 验证分类；
- 隐藏材料不在 Agent 工作区；
- development 题标记为永不进入 formal。

### P4 — 12 道 formal 题与冻结

交付：12 题、参考修复、不完整修复、评分、独立复核和冻结哈希。

验收：

- 每题满足第 12.3 节六项门槛；
- 所有评分连续运行三次一致；
- 题库、prompt、schema、模型参数、顺序和结论门槛完成冻结 commit。

### P5 — 72 次正式运行与报告

前置：`NEXT.md` 明确授权模型、72 次运行、费用上限和冻结 commit。

验收：

- 72 个计划 cell 全部存在，不筛失败；
- infrastructure-invalid 只按预注册的整对重跑规则处理；
- summary/events/score 计数一致；
- 报告同时给出质量、代价和过程指标；
- 结论严格落在“支持 / 不支持 / 证据不足”之一；
- 标题明确“本机软隔离、自建复杂任务下的工程证据”。

## 19. 非目标

本设计不做：

- OS 级安全沙箱；
- 三部门并行执行；
- 多模型分部门；
- 部门数量消融；
- 自动聊天压缩；
- 跨 run 长期记忆；
- 人工主观代码质量作为主分；
- 在看到正式结果后修改题目、评分或胜负门槛。

## 20. 关键风险

| 风险 | 处理 |
|---|---|
| 本机软隔离不能证明 oracle 不可见 | 限定结论，移除 shell，隐藏路径不注入，未来另立容器协议 |
| 三部门靠更多计算取胜 | 不作等预算声明，完整报告成本；后续若质量信号成立再做等预算实验 |
| 自建题偏向三部门 | 四类均衡、独立复核、不完整修复检查、校准题与正式题隔离 |
| 私有会话越来越长 | 8 次返工与 200 calls 保险丝；溢出明确失败，不静默截断 |
| 质检被开发交付单带偏 | 不共享开发聊天；质检必须亲自运行检查；隐藏评分仍在循环外 |
| provider 偶发故障污染比较 | 固定重试、故障分类、配对 block 整对重跑一次、再次失败停止批次 |
| 形式化工单变成文书负担 | 字段只保留路由、验收、证据和追责必需信息；不增加审批层级 |

## 21. 决策摘要

1. 旧 U/P/V 设计退出下一轮主方案；改为需求、开发、质检工单闭环。
2. 三部门各自保留完整 run 级私有会话；跨部门只传正式工单。
3. 最新有效工单高于私有旧记忆。
4. 质检部独立运行公开检查，且拥有唯一放行权；隐藏评分始终在循环外。
5. Solo 与 Team 各自在宽松相同保险丝内跑到完成，不做等预算质量声明。
6. 移除任意 shell，只允许相对路径文件工具和预登记 `run_check`。
7. 本机软隔离结果只作为工程证据，不冒充 OS 级隐藏 oracle 实验。
8. 12 道自建复杂题、每种处理 3 次，共 72 个正式 run。
9. 主结论门槛为赢至少 10/12 题、平均提升至少 5 分、fatal 和 false-complete 均不增加。
10. 先完成机械底座与两道 development 校准，再冻结正式输入并申请 live 额度。
