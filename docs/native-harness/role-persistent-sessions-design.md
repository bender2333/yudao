# 设计方案：三角色常驻会话（彼此不共享上下文）

> 状态：**P0-P3 已实现**
> 日期：2026-07-10  
> 分支语境：`exp/native-harness`  
> 关联：默认实现为「三角色常驻线程」；保留 `cold` 作为同拓扑消融臂。

---

## 1. 背景与问题

### 1.1 当前实现（基线）

```
每次进入阶段 → 新建 messages = [system, user] → run_agent_loop → 丢弃会话
阶段间只保留：workspace 文件 + understanding 字符串（+ events 日志）
```

含义：

- 「UNDERSTAND / PLAN / VERIFY」只是**同一段 system 文案被反复使用**，不是固定角色。
- `reject_understanding` 再进理解阶段时，**看不到**该角色上次调研轨迹，只能看到 reject reason 摘要。
- consult 是另开短 loop，不是同一 UNDERSTAND 线程续聊。

### 1.2 目标诉求（已拍板）

1. **三个角色都常驻**：UNDERSTAND、PLAN_EXECUTE、VERIFY 各持有自己的会话生命周期。  
2. **每个角色只维护自己的记忆与上下文**。  
3. **角色之间不做会话共享**：不得把 A 的 messages 拷给 B，不得共享 transcript。

### 1.3 本方案解决什么

| 痛点 | 常驻后 |
|---|---|
| 打回理解 = 换一个临时工重写 | 同一 UNDERSTAND 续聊修订规格 |
| PLAN 反复轮次丢失自测经验 | 同一 PLAN 记得改过什么、测过什么 |
| VERIFY 每轮从零较真 | 同一 VERIFY 可积累已覆盖用例与未决点 |
| 误以为「有部门」实际是「合同工」 | 结构变量变为「三常驻角色 + 显式交接」 |

---

## 2. 设计原则

1. **角色 = 持久 `AgentSession`**，不是「阶段函数调用一次」。  
2. **记忆边界 = 会话边界**：角色记忆 ⊂ 该角色自己的 `messages`（及可选的角色私有 meta），不跨角色读取。  
3. **协作只通过显式交接物（handoff artifacts）**，不通过共享聊天记录。  
4. **世界状态仍是 workspace**（文件），所有角色可按工具权限读写/只读操作同一磁盘世界——这是**世界共享**，不是**会话共享**。  
5. **VERIFY 仍是唯一路由裁判**（pass / reject_execution / reject_understanding）。  
6. **循环外隐藏 oracle 不进 harness**（研究裁判规则不变）。  
7. **Solo 模式不变**（仍为单 loop）；本方案只改 multi。

---

## 3. 核心概念

### 3.1 AgentSession（角色会话）

每个角色一个实例，run 级存活：

```text
AgentSession:
  role: "UNDERSTAND" | "PLAN_EXECUTE" | "VERIFY"
  system: str                    # 固定人设，run 内不变
  messages: list[Message]        # 该角色私有，持久累积
  tools: list                    # 该角色工具集（含 terminal / 可选 consult）
  terminal_tools: set[str]
  meta: dict                     # 可选：轮次、上次 terminal 摘要等（非跨角色可见）
```

生命周期：

```text
run_multi 开始 → 创建 3 个 AgentSession（仅注入 system，messages 可为空或仅 system）
循环中多次 activate(role, handoff_user_message)
run_multi 结束 → 会话随 MultiResult/events 落盘后销毁（不跨 run 持久，除非另开研究项）
```

### 3.2 激活（activate），不是「新开 loop 从零」

**旧**：`run_agent_loop(system, user=全新)` → 无历史。  

**新**：

```text
activate(session, user_turn: str) → StageResult
  1. session.messages.append({role: user, content: user_turn})
  2. 从当前 session.messages 继续 tool loop，直到本轮停条件
  3. 本轮产生的 assistant/tool 消息全部 append 进 session.messages
  4. 返回本轮 terminal/产出；session 保留完整历史供下次 activate
```

「停」仍表示**本轮交接完成**，不是角色死亡。

### 3.3 共享 vs 不共享（硬边界）

| 共享？ | 内容 |
|---|---|
| **不共享** | 任一角色的 `messages` / 推理过程 / tool 回执全文 / 私有 meta |
| **共享（非会话）** | workspace 文件（世界状态） |
| **共享（显式交接）** | 见 §4 handoff 对象；只以**结构化/文本交接包**形式出现在**接收方本轮 user_turn** 中 |
| **编排层可见** | 全部 events、成本、handoff 副本（用于日志与状态机；**不**注入非目标角色会话，除非作为 handoff 字段） |

**禁止**：

- 把 UNDERSTAND 的 messages 拼进 PLAN  
- VERIFY 读取 PLAN 的 transcript  
- 「为了省事」把完整 events 塞进某角色上下文  

**允许**：

- 编排根据 VERIFY 的 verdict **生成一小段 handoff 文本**，写入下一角色的 **user_turn**（这是交接，不是共享会话）。

---

## 4. 交接协议（Handoff）——唯一跨角色通道

角色之间**只通过编排层转发的 handoff 包**协作。Handoff 进入接收方时，表现为该角色会话里的 **一条（或少量）user 消息**，进入后即成为该角色自己的记忆；发送方会话不因此获得接收方内容。

### 4.1 交接对象一览

| 名称 | 生产者 | 消费者 | 内容（最小集） |
|---|---|---|---|
| `UnderstandingArtifact` | UNDERSTAND | PLAN、VERIFY、（编排） | 结构化四字段文本（summary / requirements / constraints / done_criteria）；可含 clarifications 附录 |
| `ReadyArtifact` | PLAN | VERIFY、（编排） | notes：做了什么、如何自测；**不**含完整实现散文强制要求（实现以 workspace 为准） |
| `VerdictArtifact` | VERIFY | 编排（路由） | status + reason |
| `RejectToUnderstanding` | 编排（源自 Verdict） | UNDERSTAND | reason + 可选：当前 UnderstandingArtifact 快照提示「请修订」 |
| `RejectToPlan` | 编排（源自 Verdict） | PLAN | reason + 最新 UnderstandingArtifact（规格未变时仍附上，避免 PLAN 只靠旧记忆偏离） |
| `ConsultRequest` / `ConsultAnswer` | PLAN或VERIFY → UNDERSTAND → 原角色 | 见 §6 | 问题与答复；答复可晋升进 UnderstandingArtifact |

### 4.2 UnderstandingArtifact（规范真源 L1）

与现网一致的推荐序列化：

```text
## Summary
...
## Requirements
...
## Constraints
...
## Done-criteria
...
## Clarifications   # 可选，consult 累积
**Q:** ...
**A:** ...
```

- **系统内「完成」的合同真源**仍是该 artifact（+ workspace），不是隐藏 oracle。  
- 编排层持有一份 **canonical understanding**（最新版）；VERIFY/PLAN 每次被激活时，handoff 中带上**当前 canonical** 全文或「自你上次所见后的 diff 摘要」。  
  - **推荐 MVP**：每次 activate PLAN/VERIFY 时 user_turn 附带 **完整最新 UnderstandingArtifact**（简单、防漂移）。  
  - 后续可优化为 diff，以省 token。

### 4.3 不把「对方会话」塞进 handoff

Handoff **禁止**包含：

- 对方 tool 轨迹全文  
- 对方 assistant 长推理  
- 对方 messages JSON  

Handoff **可以**包含：

- 结构化字段  
- 短 notes / reason（有长度上限建议，如 reason ≤ 2k 字符，超出截断并写 events）  
- workspace 文件清单（由编排生成，非对方记忆）

---

## 5. 状态机（编排层，不变拓扑、改变激活语义）

### 5.1 拓扑（与现网相同）

```text
state = UNDERSTAND
loop while rounds < MAX_ROUNDS:
  UNDERSTAND  → 产出/更新 UnderstandingArtifact → state = PLAN_EXECUTE
  PLAN_EXECUTE → 产出 ReadyArtifact 且本轮有交付物变更 → state = VERIFY
  VERIFY → VerdictArtifact:
      pass                 → DONE
      reject_execution     → state = PLAN_EXECUTE; rounds += 1
      reject_understanding → state = UNDERSTAND;   rounds += 1
耗尽 rounds 或角色本轮无法收口 → ESCALATED
```

VERIFY 仍是**唯一路由裁判**。

### 5.2 激活时 user_turn 拼装（每角色私有历史 + 本轮交接）

#### UNDERSTAND 首次

```text
# Handoff: NewMission
# Original task
{task}

# Workspace files
{listing}

请建立 UnderstandingArtifact，完成后调用 submit_understanding。
```

#### UNDERSTAND 再次（reject_understanding）

```text
# Handoff: RejectUnderstanding
# Original task
{task}

# Your previous understanding (canonical)
{canonical_understanding}

# Verifier rejection
{reason}

# Workspace files
{listing}

请在既有理解上修订（尤其 done-criteria），完成后再次 submit_understanding。
你记得自己先前的调研与结论；不要无视历史重写无关部分，除非 rejection 要求。
```

（「你记得…」依赖**同一 session.messages 仍在**；user 只补充 handoff。）

#### PLAN 首次 / 再次

```text
# Handoff: ExecuteAgainstUnderstanding
# Understanding (canonical, source of truth)
{canonical_understanding}

# Workspace files
{listing}

# 若有执行驳回：
# Verifier rejection
{reason}

请实现并自测；完成后 submit_ready。
```

**不含** Original task（保持「规格合同制」；任务原意由 UNDERSTAND 吸收进 L1）。  
若未来要允许 PLAN 见 L0，单独立项，默认 **不见 L0**。

#### VERIFY 每次

```text
# Handoff: VerifyAgainstUnderstanding
# Understanding (canonical, source of truth)
{canonical_understanding}

# Workspace files
{listing}

# 可选：Implementer notes（ReadyArtifact.notes，短）
{notes}

请独立验收；submit_verdict。
```

**不含** PLAN 会话、**不含** UNDERSTAND 会话。  
notes 可选：若担心污染独立性，MVP 可 **不传 notes**，只传 understanding + listing（与现网最接近）。

**推荐 MVP**：VERIFY handoff = understanding + listing；**不传** ready notes（独立性优先）。

---

## 6. Consult（常驻模型下的改写）

### 6.1 旧行为

PLAN/VERIFY 调工具 → 另开临时 UNDERSTAND 子 loop（无主 UNDERSTAND 历史）→ 答案字符串返回，并 append 进 understanding。

### 6.2 新行为（与「UNDERSTAND 常驻」一致）

```text
PLAN 或 VERIFY 调用 consult_understanding(question)
  → 编排（或工具 handler）暂停当前角色本轮 tool 回合的语义：
  → activate(UNDERSTAND_session, user_turn=ConsultRequest)
  → UNDERSTAND 在自己历史中回答，以自然语言终稿或专用 submit_clarification 收口
  → 编排将答案：
       (a) 作为 tool result 写回**调用方**会话（进入调用方记忆）
       (b) 晋升进 canonical UnderstandingArtifact
  → 调用方继续自己的 loop
```

要点：

- Consult **复用常驻 UNDERSTAND 会话**，不再 spawn 无历史临时工。  
- UNDERSTAND 因 consult 被激活时，**不得**把 PLAN/VERIFY 的 transcript 塞进去，只给 question + 当前 canonical understanding + 原任务。  
- 调用方只看到 **答案字符串**（tool 回执），看不到 UNDERSTAND 内部 tool 轨迹。  
- 计数：`consults` = 成功完成的 consult 次数；失败单独记 `consult_errors`。

### 6.3 Consult 与主状态机的交错

- Consult 是**同步嵌套激活**：VERIFY 未 submit_verdict 前可多次 consult。  
- 嵌套深度：禁止 consult 内再 consult（MVP 硬限制 depth=1）。  
- UNDERSTAND 在 consult 激活中 **不应**调用「结束整场 mission」的语义；只回答问题。可用同一 `messages` 但 system 已固定——user_turn 写明「本轮是 clarification，不要 submit_understanding 除非规格必须变更」。  
  - **规格变更**：若 UNDERSTAND 在 consult 中发现必须改 done-criteria，允许调用 `submit_understanding` 更新 canonical；编排刷新 artifact 后再把答案返回调用方。

---

## 7. 停止条件与门闩（每轮 activate）

每轮 `activate` 仍使用与现网类似的停条件，但绑定在**本轮**而非「角色一生」：

| 角色 | 本轮成功收口 | 本轮失败 → 整场 |
|---|---|---|
| UNDERSTAND | `submit_understanding` 校验通过；或自然停 + extract 成功 | max_steps 无产出 / extract 失败 → ESCALATED |
| PLAN | `submit_ready` 或自然停 + **本轮 workspace 有非空交付变更** | 无变更 / max_steps → ESCALATED |
| VERIFY | `submit_verdict` 合法；或自然停 + router 合法 | max_steps 且 router 失败 → 默认 reject_execution 或 ESCALATED（二选一，MVP：**默认 reject_execution 并计一轮**，与「不假 pass」一致；连续默认 reject 耗尽 rounds 再 escalate） |

**角色会话在 escalate/done 前不销毁**；失败只结束 run。

### 7.1 max_steps 语义

- `max_steps` = **单次 activate 的步数上限**（不是角色一生上限）。  
- 另设 run 级硬预算（与 M4 对齐，本方案强制）：`max_calls` / token / 墙钟 — **三角色共享同一 run 预算**，耗尽 → ESCALATED 并写 summary。

### 7.2 上下文膨胀

常驻必然导致 messages 变长。MVP 规则：

1. **先不自动压缩**，只记录每角色 `message_count` / 估算 tokens。  
2. 若单角色 prompt 侧超过阈值（如 100k tokens），触发 **角色内压缩**（只总结该角色历史为一条 system/user 备忘，**绝不**用其他角色历史）。压缩算法另文；未实现前 → 该次 activate 可 ESCALATED 并标记 `context_overflow`。  
3. 禁止用「把历史丢给另一个角色」当压缩手段。

---

## 8. 工具与权限（保持分离）

| 角色 | 工具 |
|---|---|
| UNDERSTAND | read / list / bash（禁 write_file/edit_file）+ `submit_understanding` +（被 consult 时）回答 |
| PLAN | 全量 + `submit_ready` + `consult_understanding` |
| VERIFY | 禁 write_file/edit_file + `submit_verdict` + `consult_understanding` |

bash 写盘旁路（`echo > file`）仍是已知张力；本方案不假装已解决，记入风险（§12）。

---

## 9. Prompt 策略（角色 system 常驻）

### 9.1 原则

- **system 在 session 创建时写入一次**，activate 时不重置 system（除非显式「角色重置」研究臂，默认不做）。  
- **每轮差异只进 user_turn（handoff）**。  
- system 中明确：「你是长期任职的某角色；你保有自己的对话记忆；你看不到其他角色的对话；你只通过 handoff 与世界（workspace）协作。」

### 9.2 System 要点（草案，实现时可迭代文案）

**UNDERSTAND**

- 常驻规格官；禁止写方案代码。  
- 产出/更新可检查的 done-criteria。  
- 打回与 consult 时基于**自己的历史**修订，而非假装失忆。  
- （研究可选开关）是否鼓励「合理未写明边界」——默认与题库策略绑定，本文不锁死。

**PLAN**

- 常驻实现者；canonical understanding 为真源。  
- 歧义 → consult，不猜。  
- 交付物落盘并自测后 submit_ready。

**VERIFY**

- 常驻验收官；只依据 understanding + 自己验收历史 + workspace。  
- 不见实现者会话。  
- 真跑证据；submit_verdict 三态路由。

### 9.3 与 Solo 的关系

Solo 仍为单会话；**不要**把三角色 system 拼进 solo。  
对比实验时：multi = 三常驻会话；solo = 一会话；预算 run 级对齐。

---

## 10. 数据落盘与可观测性

每个 run 目录建议：

```text
runs/<id>/
  events.jsonl           # 全局：stage_activate, tool_call, handoff, verdict, consult...
  summary.json
  workspace/
  sessions/
    understand.jsonl     # 该角色完整 messages（或按轮 snapshot）
    plan_execute.jsonl
    verify.jsonl
  handoffs.jsonl         # 每次跨角色交接包（审计用）
```

`summary.json` 增补：

```json
{
  "mode": "multi",
  "session_model": "persistent",
  "outcome": "done|escalated",
  "rounds": 1,
  "consults": 0,
  "understanding": "...",
  "verdict": {},
  "per_role": {
    "UNDERSTAND": {"activates": 1, "calls": 0, "prompt_tokens": 0, "messages": 0},
    "PLAN_EXECUTE": {},
    "VERIFY": {}
  },
  "per_stage": []
}
```

成本：每次 activate 的 loop 增量累加到角色与 run；**禁止**再对共享 client 累计值重复求和（沿用现网 delta 修法）。

---

## 11. 实现要点（相对现网改动面）

### 11.1 新模块建议

| 模块 | 职责 |
|---|---|
| `harness/session.py` | `AgentSession`、append、序列化 |
| `harness/activate.py` 或扩展 `agent_loop` | `run_agent_turn(session, ...)`：在已有 messages 上续跑至本轮停 |
| `harness/handoff.py` | 拼装 user_turn、记录 handoffs.jsonl |
| `harness/orchestrator.py` | 状态机改为 activate 三 session；去掉「每阶段全新 system+user 冷启动」 |

### 11.2 `run_agent_loop` 演进

两种等价实现（选一）：

**A. 扩展现有 loop**

```text
run_agent_loop(..., messages=session.messages | None)
  if messages is None:  # solo / 旧行为
      messages = [system, user]
  else:
      messages.append(user_turn)
  ... 跑到停 ...
  return LoopResult，且 caller 写回 session.messages = messages
```

**B. 新函数 `continue_agent_session(session, user_turn, ...)`**  
solo 仍走旧 `run_agent_loop`。

推荐 **A**，少分叉。

### 11.3 终端工具与历史

- terminal 成功 → 本轮停，但 **不 clear messages**。  
- 下次 activate 时模型能看到自己上次 submit_* 的 tool 回执——这是角色记忆的一部分，符合诉求。  
- 若担心模型重复 submit 干扰：user_turn 写明「这是新一轮 handoff，请基于新情况再次提交」。

### 11.4 兼容与开关

- CLI：`--session-model cold|persistent`（默认实现完成后改为 `persistent`，或显式双臂实验）。  
- 旧 cold 模式保留一段时间，便于消融「常驻 vs 冷启动」本身。

---

## 12. 风险与非目标

### 12.1 风险

| 风险 | 缓解 |
|---|---|
| 上下文膨胀、成本上升 | run 预算；后续角色内压缩；handoff 限长 |
| VERIFY「记得」上轮太松/太紧 | 独立 handoff 不含 PLAN 会话；system 强调每轮重跑关键检查 |
| 角色记忆与 canonical understanding 不一致 | 每次 handoff 附最新 canonical；以 artifact 为准覆盖口头记忆 |
| bash 绕过禁写 | 已知；沙箱增强另项 |
| 实现复杂度 | MVP 不做压缩、不做跨 run 持久 |

### 12.2 非目标（本方案不做）

- 三角色并行（仍串行状态机）  
- 共享 blackboard 聊天  
- 把隐藏 oracle 注入 VERIFY  
- 自动多模型分角色  
- Solo 拆成三角色  

---

## 13. 验收标准（实现完成定义）

### 13.1 行为验收

1. 同一 run 内：`reject_understanding` 两次进入 UNDERSTAND 时，**第二次 messages 长度 > 第一次结束时**，且含第一轮 tool/assistant 记录。  
2. PLAN 会话中 **不出现** VERIFY 的 tool 轨迹；反之亦然（用 sessions 落盘断言）。  
3. 跨角色唯一文本通道为 handoffs.jsonl 中记录的包；抽查 PLAN messages 无 UNDERSTAND 的 list_dir 回执原文（除非被错误地写进 handoff——应失败）。  
4. consult 使用**同一** UNDERSTAND session id / 同一 messages 链，而非新 session。  
5. 状态机三边 + max_rounds escalate 单测全绿。  
6. PLAN 无本轮交付变更 → 不进 VERIFY。  
7. run 级 `max_calls` 耗尽 → outcome=escalated，summary 落盘，进程不崩。

### 13.2 回归

- solo 行为与单测不变。  
- cold 模式（若保留）行为与现网多阶段一致或快照兼容。

### 13.3 研究后续（非本方案阻塞）

- 臂对比：cold multi vs persistent multi vs solo（统一预算）。  
- 验证「常驻」是否单独贡献质量/稳定性。

---

## 14. 分阶段落地

| 阶段 | 内容 | 完成标志 |
|---|---|---|
| **P0** | `AgentSession` + `run_agent_loop` 支持续跑；orchestrator 三 session；handoff 拼装；sessions 落盘 | 单测 13.1.1–13.1.6 |
| **P1** | consult 改走常驻 UNDERSTAND；summary.per_role；run 级 max_calls→escalated | live smoke 1 题 |
| **P2** | handoffs.jsonl 审计；reason 截断；context 指标 | 文档 + 单测 |
| **P3** | `--session-model cold\|persistent`；统一 calls/token/协作式墙钟预算；实验协议 | 默认 persistent；cold 快照测试；不实现自动压缩 |

---

## 15. 与现网概念对照

| 概念 | 冷启动（现网） | 常驻（本方案） |
|---|---|---|
| 角色 | 文案标签 | 持久 AgentSession |
| 阶段进入 | 新 loop、空历史 | activate，追加 user_turn |
| 角色记忆 | 无 | 私有 messages |
| 跨角色信息 | understanding 字符串为主 | 显式 handoff 包（仍可含 understanding） |
| consult | 临时子 loop | 激活常驻 UNDERSTAND |
| 世界状态 | workspace | workspace（不变） |
| 路由 | VERIFY verdict | 不变 |

---

## 16. 决策摘要（给实现者）

1. **三角色全程常驻**，run 内不销毁。  
2. **会话严格隔离**；协作 = 编排转发 handoff + 共享磁盘世界。  
3. **状态机拓扑不变**；变的是激活与记忆。  
4. **Canonical understanding** 由编排持有，每次给 PLAN/VERIFY 的 handoff 附带最新版。  
5. **VERIFY MVP 不接收 PLAN notes**，降低会话外泄漏。  
6. **Consult 并入常驻 UNDERSTAND**。  
7. **Solo 不动**；预算 run 级对齐后再做科学对比。

---

## 17. 待拍板小项（实现前确认）

| ID | 问题 | 默认建议 |
|---|---|---|
| Q1 | VERIFY handoff 是否带 ReadyArtifact.notes？ | **否**（MVP） |
| Q2 | PLAN 是否可见 Original task？ | **否**（保持 L1 合同） |
| Q3 | UNDERSTAND extract「勿 invent」是否保留？ | 保留实现能力；文案是否鼓励扩边由题库策略另定 |
| Q4 | 默认 `--session-model`？ | **persistent**；cold 仅作显式消融 |
| Q5 | VERIFY 自然停默认 reject 是否占 round？ | **是**，防空转 |

（若无异议，实现按默认建议执行。）

---

## 18. 实现状态

- P0：三个 run 级 `AgentSession`、私有 messages、activate 续跑与原状态机回归已完成。
- P1：consult 复用常驻 UNDERSTAND；per-role 计量与预算耗尽收口已完成。
- P2：`sessions/*.jsonl`、`handoffs.jsonl`、reason 2k 截断与上下文指标已完成。
- P3：`cold|persistent` 开关已完成，默认 persistent；cold 只清空角色历史，其他变量不变。
- 自动上下文压缩未实现；当前只测量 `message_count/message_chars`，达到真实溢出后再立项。
- `max_seconds` 是进程内协作式门闩，无法强杀在途 API/shell；正式实验仍需外层 300 秒硬超时。
