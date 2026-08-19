# 三部门工单系统架构设计 v2

> 状态：**REVISED / 待评审（评审基线变化见 §13）**
> 日期：2026-08-06
> 本届骨架定位：本文档实现的正是 Obsidian《Harness 调研-8月》中"LLM Kernel / Agent Runtime / Domain Control Plane"三层业界共识——Orchestrator+EventBus+StateStore 属 Agent Runtime，Council+工单验收属 Domain Control Plane，Session+Distiller+ProbeTool 属 LLM Kernel。见 §13.0。
> 取代对象：`exp/native-harness` 分支现有 harness 实现的全部内部结构（`work_order_loop.py` / `role_session.py` / `agent_loop.py` 的会话模型）。旧实现保留至 v2 落地后整体删除，不做兼容层。
> 设计依据：三波演化研究（`docs/native-harness/2026-08-06-research-findings.md`，标注 [R1]/[R2]/[R3]）+ 第二波委派调研（`jour.md` 2026-08-06 第四波条目，标注 [R4]）。
> 与业界的对应关系：本文的 Orchestrator/Checkpoint/EventBus/StateStore 四层，是业界"LLM Kernel（建议做什么）/ Agent Runtime（是否允许、是否真发生、是否成功）/ Domain Control Plane（业务验收与最终责任）"三层结构在本项目的实例化，见 §13.0。

---

## 1. 设计不变量（来自调研的证据链，任何模块不得违反）

1. **I-1 唯一活态**：任何 LLM 会话的上下文里，同一事实只有一个当前版本。旧版本全文永远不进上下文 [R2]。
2. **I-2 状态外置**：一切超过单次调用窗口的状态，落为显式工件（artifact），不进对话历史。LLM 永远无状态 [R3]。
3. **I-3 检查点事件驱动**：会话的生死、记忆的写入与注入，由编排层根据领域事件确定性触发，不由 agent 自决 [R1][R3]。
4. **I-4 因果链薄注入**：演化因果以 ≤10 行更替链形式注入上下文；完整历史外置可检索，检索结果必须带显式失效注记 [R2]。
5. **I-5 蒸馏者隔离**：经验蒸馏由 fresh context 子 agent 完成，禁止当事部门自评 [R1]。
6. **I-6 记忆可失效**：所有经验性记录带生命周期状态，append-only 被禁止 [R1][R2]。
7. **I-7 确定性归代码**：路由、版本、哈希、计数、停止原因、触发判定全部由普通代码执行，模型只产出内容与工单 [原有不变量，保留]。
8. **I-8 不知情权威**：质检的上下文实现级隔离于开发推理过程；循环外判分不接 agent 自述 [原有，保留]。
9. **I-9 叠加式探测**：探测工具（§10.2）是对部门自有上下文的**补充**，永不成为替代。触发以下任一条即退化为替代式中继，本设计禁止之 [R4]：
    - a) 部门 Session 自身上下文被压缩/截断，probe 结论成为该问题唯一信息源；
    - b) 取消 Snapshot 引用通道（`full_log_ref` → 全文），封存变成"永久不可达"；
    - c) probe 结论被当作检查点判据的唯一输入。
10. **I-10 探测不可信**：probe 读的代码/日志/网页属不可信外部内容，其返回值经"数据区"隔离注入，文字不得改变系统权限或系统指令；probe 的派生集合留痕，重放时不重新派生（§6.1）[R4]。

---

## 2. 概念模型（名词表，全设计统一用词）

| 名词 | 定义 |
|---|---|
| **Run** | 一次完整任务执行，从原始任务进入到 DONE/STOPPED |
| **Department** | 需求 / 工程 / 质检三个角色之一；接口上是一个可递归的容器（见 §10 分形） |
| **Session** | 一次 LLM 会话实例。**消耗品**：由 SessionFactory 在检查点派生，产出终止工单后死亡 |
| **WorkOrder** | 部门间交接的唯一合法载体，带 schema 校验、父哈希、内容哈希 |
| **StateArtifact** | 部门级状态表示层：唯一活态 + 因果链 + 缺陷 + 经验，见 §5.2 |
| **Event** | 编排总线上的不可变事实记录，append-only |
| **Checkpoint** | 触发会话派生 / 蒸馏 / 注入的领域事件，见 §8 触发规则表 |
| **LessonCard** | 蒸馏后的经验规则，带 scope 与生命周期状态 |
| **CausalLink** | 演化更替链的一环："v→v+1 因 X"，由代码从工单事件生成 |
| **Snapshot** | 已死亡的 Session 的封存件（输入装配 + 终止工单 + 停止原因） |
| **Council** | 产品理事会：低频元角色，审查因果链本身，不处理日常工单 |

---

## 3. 分层结构

```text
┌─────────────────────────────────────────────────┐
│ L4 元层    Council（低频，审视因果链/元工单）      │   ⇠ Domain Control Plane
├─────────────────────────────────────────────────┤
│ L3 编排面  Orchestrator · EventBus · Checkpoint    │   ⇠ Agent Runtime（业界共识层）
│            ProbeManager（配额/缓存/谱系）          │
├─────────────────────────────────────────────────┤
│ L2 表示面  StateStore（StateArtifact / Ledger）   │
├─────────────────────────────────────────────────┤
│ L1 计算面  SessionFactory · ContextAssembler      │   ⇠ LLM Kernel（建议层）
│            Session(消耗品) · Distiller           │
│            ProbeTool（Session 手里的工具）         │
├─────────────────────────────────────────────────┤
│ L0 执行面  ToolRuntime（受限文件工具/检查）         │   ⇠ ACI / 沙箱执行层
└─────────────────────────────────────────────────┘
           外部：Scorer（循环外判分，实验模式）
```

**依赖方向只允许向下**：L4 不依赖 L2 内部格式，只读 StateArtifact 的 causal_chain 视图；L1 不知道状态机长什么样，Session 只认识装配好的 messages 和工具。

---

## 4. 模块详设

### 4.1 Orchestrator（编排器，L3）

**职责**：状态机位移、检查点判定、会话派生调度、预算与停止裁决。不含任何 LLM 调用。

**接口**：

```python
class Orchestrator:
    def start(self, run_id: str, task: str, budget: Budget) -> RunHandle
    def step(self) -> Event          # 推进一个检查点周期，返回本轮事件
    def state(self) -> RunState      # 当前状态机位置（只读视图）
    def stop_reason(self) -> str | None
```

**内部状态机**（§7.1 详述）：`REQUIREMENTS ⇄ ENGINEERING → QUALITY → DONE | rework → 回退`。

**硬约束**：
- Orchestrator 永远不知道 prompt 内容的语义，只读工单 schema 字段与系统计数；
- 每个 step 结束必须落 Event；Event 写失败 = run 立即 fail-closed；
- 任何 LLM 相关的"要不要继续"判断都被禁止出现在这里。

### 4.2 EventBus（事件总线，L3）

**职责**：append-only 的不可变事件流，是整个 run 的唯一事实来源。StateArtifact 是事件流的物化视图，可由此重建。

**事件类型**（完整表见 §8，这里给骨架）：

```
run_started / role_activated / session_spawned / session_stopped
work_order_issued / work_order_rejected
checkpoint/distill_started / checkpoint/distill_completed
checkpoint/context_assembled (含注入的 lesson ids 与 causal chain 长度)
transition / run_stopped
```

**接口**：

```python
class EventBus:
    def emit(self, event: Event) -> None        # 写失败抛异常（fail-closed）
    def replay(self, run_id: str) -> Iterator[Event]
```

### 4.3 SessionFactory（会话工厂，L1）

**职责**：在检查点派生全新 Session。Session 从派生起就是消耗品——无跨检查点记忆，产出终止工单即死亡并封存为 Snapshot。

**接口**：

```python
class SessionFactory:
    def spawn(self,
              role: Role,
              context: AssembledContext,   # 来自 ContextAssembler
              tools: list[ToolDef],
              budget: Budget) -> SessionHandle

class SessionHandle:
    def run(self, max_steps: int) -> SessionOutcome
    # SessionOutcome = TerminalWorkOrder | Stop(reason)
```

**派生规则**（I-3）：只允许在 §8 触发点 spawn；运行中的 Session 若被外部原因中止（预算/监督），其事件保留、Snapshot 标记 `aborted`，不进入任何后续注入。

### 4.4 ContextAssembler（上下文装配器，L1）

**职责**：把"当前唯一活态"装配成新 Session 的初始 messages。**这是 I-1/I-4 的执行点。**

**输入**：部门、当前工单、StateStore。
**输出**：固定结构的 messages：

```
[0] system: 角色规约（固定，不含任何历史）
[1] user: 装配包 =
    ├─ current_spec        # 唯一活态（唯一！）
    ├─ causal_chain        # ≤10 行更替链，超长出略号+检索提示
    ├─ lessons             # top-k active（k≤5，总≤1.5k token），置顶在该块最前
    ├─ current_work_order  # 本检查点要处理的工单
    └─ workspace_view      # 文件清单 + 树哈希（不含毕业版本全文）
```

**规则**：
- 装配是确定性代码，无 LLM 参与；
- 装配事件（注入了哪些 lesson id、chain 截断与否）落 EventBus，可审计；
- 任何"旧版本全文"字段在 schema 层就不存在——不是过滤，是 structurally impossible。

### 4.5 Distiller（蒸馏器，L1）

**职责**：检查点处把失败轨迹蒸馏为 LessonCard / 更新 CausalLink。Fresh context，与当事部门零共享。

**接口**：

```python
class Distiller:
    def distill_defect(self,
                       defect: WorkOrder,          # QA 拒单
                       scratchpad_ref: str)         # 当事 Session 的封存 Snapshot 引用
              -> list[LessonCard]                  # 1–3 张
```

**契约**：
- 输入只有 defect 工单 + scratchpad 引用（可经工具读取），无部门历史；
- 输出强 schema（§5.2 LessonCard），编排层校验后写入 StateStore；
- 回主流程的只有 ≤200 token 确认 + 卡片 id，全文永不进任何 Session 上下文 [R4]；
- 蒸馏本身的调用也落 Event（可计量其成本）。

### 4.6 StateStore（状态工件库，L2）

**职责**：StateArtifact 的存储、版本化、失效语义、检索。**这是系统的"纸带"。**

**接口**：

```python
class StateStore:
    def current(self, dept: Department) -> StateArtifact      # 活态视图
    def record(self, event: Event) -> None                    # 物化更新（由 EventBus 驱动）
    def retrieve_lessons(self, dept: Department, scope: str,
                         k: int, token_budget: int) -> list[LessonCard]
    def retrieve_history(self, ref: HistoryRef) -> HistoricalView
    # retrieve_history 的返回强制携带失效注记（"已被 v_k 取代于 date，原因 Y"）
    def supersede(self, snapshot_id: str) -> None
    def invalidate(self, lesson_id: str, reason: str, by: str) -> None
```

**实现约束**：
- 底层是 append-only 事件文件 + 物化 JSON 视图，可整体重建，不允许手工编辑物化视图；
- 检索无向量库依赖：第一版只做 scope 精确匹配 + 新鲜度排序（调研结论：精确匹配优先于向量相似度）；
- 所有写入带哈希链，防篡改可与旧 TicketLedger 思路合并。

### 4.7 ToolRuntime（受限工具运行时，L0）

沿用现有结论：restricted file tools + 命名检查 + workspace 边界 + 进程树监督。**不属于本次重新设计的变动范围**，接口保持不变。

### 4.8 Council（产品理事会，L4）

**职责**：低频审查 causal_chain 整体，提元工单（meta），质疑三部门的共同假设。不参与日常工单流。

**接口**：

```python
class Council:
    def review(self, chain_view: CausalChainView,
               stats: RunStats) -> list[MetaWorkOrder]
```

**激活规则**（默认，可调）：每 N 次 acceptance 修订（默认 N=3）触发一次；或 run 结束时总结性触发一次。Council 的会话同样由 SessionFactory 派生、同样是消耗品，输入只有 causal_chain 视图 + 统计，不含任何部门私有材料。

### 4.9 Scorer（循环外判分，外部）

实验模式下独立存在，与本架构的唯一接口是读取冻结的 workspace 快照与 StateArtifact 终态。agent 侧无感知。

### 4.10 ProbeManager（探测管理器，L3）

**职责**：探测调用的配额裁决、内容寻址缓存、谱系记录、注入边界守护。**不含任何 LLM 调用。**

**接口**：

```python
class ProbeManager:
    def dispatch(self, question: str, scope: ProbeScope,
                 parent_role: Role, budget: Budget) -> ProbeResult
    # ProbeResult = Answer(text, artifact_refs) | NoAnswer(reason)
```

**内置规则**：
- 深度恒等于 1（子 agent 工具表内**不存在** `delegate_probe`，见 §6.1）；
- 预算从父子共享池扣减，失败返回 `NoAnswer` **不阻塞**任何工单；
- `question + workspace 树哈希` 作缓存键，命中直接返回；
- 探测返回以**数据形式**写入 Session 的工具结果（隔离区），标记为外部信息（I-10）；影响了工单决策的 probe 记录在 EventBus 与工单引用里（§5.1）。

---

## 5. 核心工件 Schema

### 5.1 WorkOrder（工单）

```json
{
  "order_id": "wo-20260806-007",
  "kind": "acceptance | clarification | delivery | defect | release | meta",
  "issuer": "requirements | engineering | quality | council",
  "parent_hash": "sha256:...",
  "content_hash": "sha256:...",
  "payload": { "按 kind 分 schema，编排层校验" },
  "status": "active | superseded | invalidated",
  "created_at": "..."
}
```

特别地，`acceptance` 修订版 payload **强制携带**：

```json
"revision_of": "wo-...", 
"reason": "为什么变",
"trigger": "defect | user_feedback | tech_constraint | council",
"rejected_alternatives": ["..."]
```

——这是因果链的原材料，由代码从工单直接生成 CausalLink，LLM 不自由书写演化史。

### 5.2 StateArtifact（部门状态工件）

```json
{
  "department": "engineering",
  "current_spec": { "版本化活态，唯一可注入" },
  "causal_chain": [ {"from": "v1", "to": "v2", "reason": "...", "evidence": "wo-..."} ],
  "defects": [ {"id": "...", "detail": "...", "valid_at": "...", "invalid_at": null} ],
  "lessons": [
    {
      "id": "eng-0142", "type": "avoid | require",
      "scope": "work_order_type:api_change",
      "rule": "一句话规则",
      "evidence": "wo-..., qa_reject#2, snap://...",
      "status": "active | superseded | invalidated",
      "created_at": "...", "last_confirmed_at": "..."
    }
  ],
  "snapshots": [ {"session_id": "...", "status": "sealed | superseded | aborted"} ]
}
```

### 5.3 LessonCard：字段如 §5.2 内嵌，独立可检索。

### 5.4 Snapshot（会话封存件）

```json
{
  "session_id": "req-20260806-01",
  "assembled_context_digest": "sha256:...",   // 装配内容的哈希，不是全文
  "terminal_order": "wo-...",
  "stop_reason": "terminal | max_steps | budget_exhausted | ...",
  "status": "sealed | superseded | aborted",
  "full_log_ref": "runs/.../sessions/xxx.jsonl"    // 外置全文，默认不回注；Distinct tool 可经引用取回（I-9 的护栏）
}
```

封存 ≠ 永久不可达：Distiller / 授权探测 / Council 可拿着 `full_log_ref` 读取全文，但**主流程自动注入永远不发生**。

### 5.5 MetaWorkOrder（理事会元工单）

`kind=meta`，payload：`{target_chain_links: [...], challenge: "...", required_response: "revise | justify"}`。进入正常工单流，由需求部受理。

### 5.6 ProbeCall（探测调用留痕）

```json
{
  "probe_id": "pb-20260806-003",
  "parent_session": "eng-20260806-02",
  "question": "...",
  "scope": {"allowed_paths": ["..."], "read_only": true},
  "cache_key": "sha256:question+tree_hash",
  "cache_hit": false,
  "result_ref": "runs/.../probes/pb-003.md",   // 结构化结论 + 强制 artifact_refs
  "budget_consumed": {"calls": 1, "tokens": 1240},
  "decision_impact": "wo-20260806-007"          // 若影响了某工单，记录其 id（否则 null）
}
```

记录进 EventBus 的目的是让 supervisor 的权威结果可重放：同一 run 内 probe 的**问题与结论**都被固定，重放时不重新派生 [R4]。

---

## 6. 接口协议（跨模块调用规约）

| 调用 | 方向 | 触发者 | 返回 |
|---|---|---|---|
| Orchestrator → SessionFactory.spawn | L3→L1 | §8 检查点 | SessionHandle |
| Orchestrator → ContextAssembler.build | L3→L1 | spawn 前置 | AssembledContext |
| Session → ToolRuntime.dispatch | L1→L0 | agent step | tool result |
| Session → ProbeManager.dispatch | L1→L3 | agent 调用 `delegate_probe` | ProbeResult |
| Session → Orchestrator(终止工单) | L1→L3 | terminal tool call | Accepted / Rejected（校验失败原因） |
| Orchestrator → Distiller.distill_defect | L3→L1 | qa_defect 检查点 | LessonCard[] |
| Orchestrator → StateStore.* | L3→L2 | 全程 | 视图/确认 |
| Council → Orchestrator(meta) | L4→L3 | council_review 检查点 | MetaWorkOrder |
| 任何模块 → EventBus.emit | →L3 | 任何事实 | void / fail-closed |

**禁止的调用**（架构级红线）：
- Session → StateStore（会话不许自己查历史，只能经 ContextAssembler 注入）；
- Distiller → 部门 Session 上下文（蒸馏产物只进 StateStore）；
- Session → Session（任何会话间直连）;
- Orchestrator → LLM（编排层零模型调用）。
- ProbeManager → 主流程检查点判据（probe 结论不作唯一判据，见 I-9.c）。

---

## 7. 状态与时序

### 7.1 主状态机

```
            ┌──────────── clarification ──────────┐
            ▼                                     │
   REQUIREMENTS ──acceptance──▶ ENGINEERING ──delivery──▶ QUALITY
            ▲                       ▲                  │
            │                       │                  │
            └──── defect(route=requirements)           │
                                    └──── defect(route=engineering)
                                                          │
                                            release ──────┴──▶ DONE

   任何状态 + budget/stall/system → STOPPED(reason)
   每 N 次 acceptance 修订 → COUNCIL_REVIEW → 回到原状态（可带 meta 工单）
```

停止原因全集（封闭枚举）：`done / max_reworks / stalled / no_change_stall / budget_exhausted / provider_blocked / role_incomplete / system_error / aborted`。新增停止原因必须改这张表，不许自由字符串。

### 7.2 时序 A：Happy Path（无返工）

```
t0  Orchestrator.start
      └ emit(run_started)
t1  Checkpoint[run_start]
      ├ ContextAssembler.build(requirements)   ← 活态=原始任务，chain=空，lessons=空
      ├ SessionFactory.spawn(requirements)
      └ Session 产出 acceptance 工单 → 校验通过 → Ledger 入链
        emit(work_order_issued); transition(ENGINEERING)
t2  Checkpoint[ticket_handoff]
      ├ ContextAssembler.build(engineering)    ← 注入当前 acceptance + top-k lessons
      ├ SessionFactory.spawn(engineering)
      └ Session 产出 delivery（changed_files 与 workspace diff 校验）
        transition(QUALITY)
t3  Checkpoint[ticket_handoff]
      ├ SessionFactory.spawn(quality)          ← 注意：不注入 engineering 的任何过程材料
      └ Session 产出 release（verified_requirements 全覆盖校验）
        emit(run_stopped, reason=done)
t4  StateStore 物化终态；Scorer 在循环外取快照判分
```

### 7.3 时序 B：一次返工（核心时序，全设计的心脏）

```
t0  quality Session 产出 defect（evidence_check 校验通过）
t1  Checkpoint[qa_defect]  ←★ 三件事在此发生，全部由编排层完成：
   a) StateStore.record(defect) → 生成 CausalLink 追加进工程链
   b) Distiller.distill_defect(defect, snapshot_ref)
        └ fresh context 子 agent，输出 1–3 张 LessonCard
        └ 编排层校验 schema → StateStore 写入（去重合并）
   c) 当事 engineering Session 的 Snapshot 标记 superseded
      （它死了。它的自言自语、试错、自我辩护全部随它封存，不外流）
t2  emit(checkpoint/distill_completed, lesson_ids=[...])
t3  transition(ENGINEERING)（按 defect.route 决定回工程还是回需求）
t4  Checkpoint[ticket_handoff]
      ├ ContextAssembler.build(engineering)
      │    注入：current_spec(活态) + causal_chain(含本次新链环) + top-k lessons(含新卡)
      │    —— 注意：新工程 Session 看到的是"规则"，不是"上次我怎么说错的"
      ├ SessionFactory.spawn(engineering)   ← 全新会话，零历史
      └ 继续后续流程
```

### 7.4 时序 C：QA 翻案（release 推翻先前 defect）

```
t0  engineering 提交 clarification 质疑 defect → 回 quality
t1  quality Session 复检后改判 release
t2  Checkpoint[qa_reverse]
      ├ StateStore.invalidate(lesson_id, reason, by=release工单id)   ← I-6 的关键半环
      └ 对应 defect 的 CausalLink 标记 retracted（不删，链路完整可审计）
```

### 7.5 时序 D：Council 审查

```
t0  acceptance 修订计数器达到 N（默认 3）
t1  Checkpoint[council_review]
      ├ ContextAssembler 装配 chain 视图（只给链 + 统计，不给部门私有材料）
      ├ SessionFactory.spawn(council)
      └ Council 产出 0..n 张 meta 工单 → 入工单流 → 需求部优先受理
t2  回到中断前的状态继续
```

---

## 8. 检查点触发规则表（I-3 的唯一事实来源）

| 触发事件 | 编排层动作 |
|---|---|
| run_start | spawn(requirements)；lessons 按任务 scope 预注入 |
| ticket_handoff（每次状态转移） | 旧 session 封存(sealed)；装配 + spawn 新 session |
| qa_defect | 蒸馏 + 新卡入库 + 旧 session superseded + 按 route 定向转移 |
| qa_reverse | 相关 lesson invalidation + chain 标记 retracted |
| acceptance.revision_count % N == 0 | council_review |
| 预算/步数/失速 | run_stopped（对应 reason），不改写任何工件状态 |
| distill/history 检索 | 返回强制带失效注记 |

---

## 9. 容量与预算契约（数字钉死，可调参数集中在 Budget）

> 原则：所有数值都是**位置合理的初值**，全部集中在单一 `Budget`/`Limits` 对象里——抄机制，不抄数值 [R4]。

| 参数 | 初值 | 说明 |
|---|---|---|
| lessons 注入 | k≤5，总 ≤1.5k token，置顶 | [R1] |
| causal_chain 注入 | ≤10 行，超长截断+检索提示 | [R2] |
| 蒸馏器返回主流 | ≤200 token + 卡片 id | [R4 类比] |
| `delegate_probe` 单会话上限 | 3 次 / 并发 1 | 初值，须以 P3 日志校准 [R4] |
| `delegate_probe` 返回 | schema 化断言+refs，长度不设硬指标 | 上限以 token 计量，软阀值可操作化 |
| max_reworks | 8 | 沿用现有结论，P3 校准后复核 |
| MAX activations | 与预算同阶（待定，见开放问题 §12.1） | 上一轮 review 已标记 |
| council 频率 | 每 3 次 acceptance 修订 | 可调 |

---

## 10. 第二层与扩展点

### 10.1 部门内分形（远景愿景，形状未定）

用户认可"未来部门内部再分角色、再循环"的方向。但 [R4] 的对抗性审查已否决了"递归复用同一个 Orchestrator"的同构方案：

第一层对抗过早停止，机制是权威隔离，靠**契约**收敛，多轮是特性；第二层对抗单会话上下文爆炸，机制是计算隔离，靠**丢弃**收敛，多轮是故障。递归会把"探索轨迹"升格为工单，正是要防的爆炸。

因此：本终版**不预留**已知的同构形状。长期分形待真实需求出现时单独立题，方向上只有一条约束保留——子层内部同样是"检查点 + 唯一活态 + 外置历史"，但收敛机制偏丢弃而非契约。Council 升级、OS 级隔离两个旧扩展点不变。

### 10.2 `delegate_probe`：部门手里的探测工具（第一版实现）

第二层循环的落地形态：**工具形态归模型，配额与语义归代码** [R4]。

```python
class ProbeTool:  # 与 Session 同层，L1
    name = "delegate_probe"
    def call(self, question: str, scope: ProbeScope) -> ProbeResult
        # 内部转发给 ProbeManager.dispatch
```

- **谁派**：部门 Session 自主（它是唯一知道"要问什么"的地方）；编排层只在 §8 触发点**开启**窗口，不强制派 [R4]。
- **能派多少**：会话级次数/并发上限 + 深度=1（工具表内没有 `delegate_probe`）+ 共享池扣减，全部是代码硬约束。
- **失败怎么办**：统一降级为 `NoAnswer`，不阻塞工单，不重试语义错误。
- **数据形态**：返回≠自由叙事——**结构化断言 + 强制 artifact_refs**（指向它读过的文件行号/日志偏移）；父 Session 可沿 refs 自己核对，probe 永不做唯一信息源（I-9）。
- **注入边界**：probe 返回走数据区隔离（I-10）；有工单决策影响的 probe 在工单 payload 中留引用。

### 10.3 扩展点（接口为之预留，第一版不实现）

1. **Council 触发升级**：从"每 N 次修订"换为方差/情绪等元指标——激活规则集中在 §8，改规则不改引擎。
2. **OS 级隔离**：ToolRuntime 与 Session 边界已按"可被容器替换"的形状设计。
3. **跨 run lessons 继承**：实验模式每 run 独立；平台模式开放（见 §12.4）。

---

## 11. 与旧实现的关系（删除清单原则）

- `role_session.py` 的单调累加消息模型：**整体作废**，被 SessionFactory + ContextAssembler 替代。
- `work_order_loop.py` 的状态机与账本：状态迁移部分重写为 Orchestrator + EventBus + StateStore 三层；工单 schema 校验与哈希链逻辑可移植。
- `agent_loop.py` 的 content_filter/budget/stop 处理：**保留**，挪入 Session 内部（它是"单会话内的正确行为"，与长程记忆问题无关）。
- `local_tools.py` / `workspace.py` / `supervisor.py` / `artifacts.py`：**保留**（L0 层不在本次重设计范围）。
- `contracts.py` 工单校验：**保留并扩展**（新增 acceptance 修订四字段、meta 工单）。

---

## 12. 开放问题（评审时必须回答）

1. **MAX activations 与 budget 的同阶问题**（上次 review 遗留，现在必须定）。
2. **Lesson 去重合并的具体规则**：scope 相同 + rule 语义近似的判定，代码做到什么程度（只比较 scope？加 rule 关键词重叠？）。
3. **Council 的终裁权边界**：meta 工单若与需求部判断冲突，谁有终裁权？（默认：Council 无强制权，只强制"必须回应"。）
4. **StateArtifact 的 run 间存续**：lessons 是否跨 run 继承？（实验模式应为"每 run 独立"；平台模式待定。）
5. **Probe 预算在三部门间的分配机理**：文献空白 [R4]——公共池 + 先到先得足以起步？还是质检需要保底？须以 P3 日志实测。
6. **十年尺度问题**（调研遗留）：什么样的状态转移表示能在十年尺度持续服务一个部门而不腐化因果链——目前无人有答案。本设计把 causal_chain 的可审计性放在第一位作为对冲。

---

## 13. 评审基线变化（相对初稿）

### 13.0 为什么这套四层不是自研

业界共识（见 Obsidian《Harness 调研-8月》）已经把下一代 harness 收敛成三层：**LLM Kernel（建议做什么）/ Agent Runtime（是否允许、是否真发生、是否成功）/ Domain Control Plane（业务验收与最终责任）**。

本设计的对应关系：

| 业界分层 | 本设计 | 说明 |
|---|---|---|
| Domain Control Plane | Council + 三部门工单验收 | 业务规则、验收标准、最终责任 |
| Agent Runtime | Orchestrator · EventBus · Checkpoint · StateStore · ProbeManager | 状态主权、上下文编译、检查点、配额与谱系 |
| LLM Kernel | Session · Distiller · ProbeTool | 语义理解、局部决策、工具选择 |

对应不是修辞——它把"确定性归代码 / LLM 只产出内容与工单"这条老原则，落实到了业界认可的分层职责上，也让未来的扩展（如 MCP 对接、容器隔离）有标准位置可放。

本节约略记录本次 REVISED 与初稿的差异，详情以 diff 为准：

- **§0/§13.0（新增）**：明确四层是"Agent Runtime"业界通用骨架在三部门场景的具现，消除"自研一套"的印象。
- **§1 不变量增至 10 条**：新增 I-9（叠加式探测）与 I-10（探测不可信 + 重放规则）。[R4]
- **§3 层次图**：新增 ProbeManager（L3）与 ProbeTool（L1）。
- **§4.10（新增）**：ProbeManager 模块。
- **§5.4 措辞修正**：从"full_log_ref 永不自动注入"改为"默认不回注，Distinct 工具可经 ref 取回"，保留引用通道。
- **§5.6（新增）**：ProbeCall 留痕 Schema，让 authoritative supervisor 结果可重放。
- **§6 接口协议表**：新增 Session→ProbeManager 调用、ProbeManager→主流程判据的禁用红线。
- **§9 预算契约**：数值从"默认值"改为"初值"，新增 `delegate_probe` 配额条目，强调集中可调、抄机制不抄数值。
- **§10 重写拆为三小节**：分形从"递归 Orchestrator"降级为形状未定的远景愿景；新增 10.2 `delegate_probe`；保留 10.3 三个扩展点。
- **§12 开放问题**：新增第 5 条（探测预算分配机理），并修正编号。
