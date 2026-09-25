# Loop System 架构

极致实用主义版本。理论依据见《Loop System 原理》，本文档只回答"怎么建"，每个决策带一个落地优先级标签（P0 最先建，P8 最后甚至可以不建）。

## 0. 范围声明

**不做**：无界/同构递归、证明驱动自我修改（Gödel Machine / Tiling Agents 一类）、权威结构运行时可协商化、可学习性判断交给 LLM 直接做。这四条不是"暂时不做"，是设计边界，第 10 节重复列出以防止被后续迭代悄悄突破。

---

## 1. 不变量（组织闭包，任何模块都不能违反）

```
I-1  goal / constraints / acceptance_criteria 只能被用户显式批准修改
I-2  权威拓扑（谁能拒绝谁）是设计时常量，运行时不可协商
I-3  任何状态提交必须经过非 LLM 裁决（U ≠ f）
I-4  撞安全上限 = 记失败，不允许被自适应层放宽为"再试一次"
```

---

## 2. 分层总览

```
L4  Council / Scorer          —— 元层，只读 causal_chain 视图，无强制改写权
L3  Orchestrator / EventBus / Checkpoint(触发判定) / ProbeManager / Distiller(触发点) / Meta-Controller
L2  StateStore                —— StateArtifact 物化状态
L1  SessionFactory / ContextAssembler / Session(各部门 ReAct 循环) / ProbeTool(客户端桩)
L0  ToolRuntime                —— 沙箱执行 / ACI
```

依赖方向：结构/类型依赖只允许向下（L4 不依赖 L2 内部格式，只读固定视图）。调用允许通过预注册协议向上（Session 提交工单给 Orchestrator、调用 ProbeManager），但调用方不感知被调用方内部状态——这是依赖倒置，不是对分层规则的违反，落地时要在接口文档里显式写清楚，不要只留一句"只能向下"造成歧义。

---

## 3. 核心状态机

```
REQUIREMENTS ⇄ ENGINEERING → QUALITY → DONE
                                  │
                          rework → 回退到 REQUIREMENTS 或 ENGINEERING
```

停止原因闭合枚举（不允许自由字符串）：

```
done | max_reworks | stalled | no_change_stall | budget_exhausted
| provider_blocked | role_incomplete | system_error | aborted
```

---

## 4. 模块清单

| 模块 | 层 | 职责 | 硬约束 | 优先级 |
|---|---|---|---|---|
| Orchestrator | L3 | 计算 Sₜ₊₁，推进状态机 | 不含任何 LLM 调用；事件写入失败 = fail closed | P0 |
| EventBus | L3 | 原始事件日志，append-only | 可重放，是唯一真相来源 | P0 |
| StateStore | L2 | StateArtifact 物化状态 | 检索走 scope 精确匹配 + 新鲜度排序，第一版不接向量库 | P0 |
| SessionFactory | L1 | 创建/终止 Session | 被外部中止的 Session 事件保留，Snapshot 标记 aborted，不进入后续注入 | P0 |
| ContextAssembler | L1 | 每次调用从真实状态重新装配上下文 | 旧版本全文字段在 schema 层不存在，结构性不可能，不是运行时过滤 | P0 |
| Session（各部门） | L1 | 部门内 ReAct 循环 | 只产出工单/数据，不直接改物化状态 | P0 |
| ToolRuntime | L0 | 沙箱执行 | 本轮不改动 | P0 |
| Distiller | L3触发/独立执行 | 蒸馏 lesson card | fresh context，零共享部门历史，输出 ≤3 条 lesson，全文不进任何 Session 上下文 | P1 |
| Council | L4 | 审视 causal_chain，不参与日常工单 | 无强制改写权，只强制"必须回应" | P2 |
| Scorer | L4 | 抽样复核 QA 的 PASS 决定 | 5–10% 抽样，不直接否决，结果反馈给 Meta-Controller | P3 |
| ProbeManager | L3 | 探测配额/缓存/谱系 | 探测结果记入 EventBus，重放时复用而非重新派生 | P1 |
| Meta-Controller | L3 | 有界参数自适应调整 | 只调已注册参数，不产生新参数，单次调整幅度 ≤20% | P4 |
| 惊讶驱动检查点计算 | L3 | 用预测误差信号触发检查点 | code-computable，不需要真算负对数似然 | P5 |
| 动态深度触发 | L3 | 有界递归扩展 | 深度 ≤2，触发条件全部 code-computable | P6 |
| 可学习性追踪 | L2/L3 | 按 scope 追踪趋势 | Mann-Kendall/Spearman，样本不足显式返回"数据不足" | P7 |
| 巩固管线 | 独立、离线 | lesson→skill→权重 | 需 ConsolidationOrder + Council 审批，LoRA + 掺混重放 | P8 |

---

## 5. Schema（关键字段，非完整定义）

**WorkOrder**（验收单/交付单/返工单/澄清单统一结构）
```json
{
  "id": "...",
  "type": "acceptance | delivery | rework | clarification",
  "parent_hash": "...",
  "content_hash": "...",
  "status": "active | superseded | invalidated",
  "revision_of": "...",
  "reason": "...",
  "trigger": "..."
}
```

**StateArtifact**
```json
{
  "artifact_id": "...",
  "department": "...",
  "current_spec": {},
  "causal_chain": [{"from": "...", "to": "...", "reason": "...", "timestamp": "..."}],
  "defects": [{"id": "...", "severity": "...", "valid_at": "...", "invalid_at": "...", "resolution": "..."}],
  "lessons": [{"id": "...", "rule": "...", "status": "active|invalidated", "source": "...", "scope": "..."}],
  "superseded_snapshots": [{"snapshot_id": "...", "reason": "...", "full_log_ref": "...", "assembled_context_digest": "..."}]
}
```

**ProbeCall**（记入 EventBus，保证重放确定性）
```json
{ "question": "...", "scope": "...", "parent_role": "...", "answer": "...", "issued_at_run": "..." }
```

**ConsolidationOrder**（新增，P8）
```json
{
  "candidate_skill": "...",
  "evidence_refs": ["跨 run/跨 scope 的 lesson id 列表"],
  "council_approval": "pending | approved | rejected",
  "training_method": "lora",
  "replay_mix_ratio": 0.0
}
```

**NoveltyLearnabilitySignal**（新增，P7）
```json
{
  "scope": "...",
  "novelty_score": 0.0,
  "learnability_trend": "positive | flat | negative | insufficient_data",
  "sample_count": 0,
  "test_method": "mann_kendall | spearman"
}
```

---

## 6. 触发表（合并版，按优先级标注引入阶段）

| 条件 | 动作 | 阶段 |
|---|---|---|
| QA 判定 reject | Session fork + Distiller 蒸馏 + 旧会话标 superseded | P1 |
| acceptance.revision_count % N == 0 | council_review | P2 |
| run_stopped（任意 reason，含纯工程侧力竭） | 至少过一次 Distiller，不再无声消失 | P2（修复 v2 遗留缺口） |
| QA PASS 决定 | 5–10% 抽样进 Scorer | P3 |
| Scorer 与 QA 不一致率升高 | Meta-Controller 提升 council_review 频率 N | P3/P4 联动 |
| 预算/步数/失速 | run_stopped(reason)，事件记录但不改写 StateArtifact defects/lessons | P0 兜底，P5 后降级为安全网 |
| defect.severity + diff_size + 澄清轮次 加权超阈值 | 检查点触发（可能升级 council_review） | P5，替代固定预算表作为主要触发方式 |
| Session 自身预算耗尽未产出合法终态工单 | 动态深度触发 | P6 |
| 同一对部门澄清/返工往返超阈值 | 动态深度触发 | P6 |
| 改动 blast radius 超历史基线 k 倍标准差 | 动态深度触发 | P6 |
| novelty 高 且 learnability 趋势正 | 优先分配资源深挖 | P7 |
| novelty 高 且 learnability 趋势平/负 | 提前止损，引导失败退出，不等预算耗尽 | P7 |
| skill 候选跨 run/scope 验证通过 | 生成 ConsolidationOrder，需 Council 批准 | P8 |

---

## 7. Meta-Controller 具体参数

- 调整对象：Council 触发阈值 N（初始 3，允许区间 [2,5]）、probe 预算部门间分配比例、lesson card 检索 top-k。
- 调整依据：滑动窗口内的一致率/惊讶统计，不是 LLM 主观判断。
- 单次调整幅度上限 ±20%，防止震荡（对应控制论有界增益要求）。
- 每次调整本身是一条 Event，可审计、可回滚；调错了下个窗口的新数据会自动纠正，不需要人工介入。

---

## 8. 动态深度扩展具体规则

- 触发条件三选一，全部 code-computable（见第 6 节触发表）。
- 触发后由 Orchestrator（非 LLM）按固定模板生成子任务：同样的生成→检查双角色结构，独立预算，独立 EventBus 命名空间。
- **深度硬上限 = 2**，子循环不能再触发下一层。
- 子循环收敛后只允许向上冒泡结构化产物（子任务工单 + 一句话因果注记），原始过程日志不上浮，复用 Distiller 现有机制。

---

## 9. 巩固管线（P8，独立于主循环，最高风险，建议单独立项）

1. **准入门槛**：候选 skill 必须已在多次独立失效检验中存活（跨若干个不同 run 和 scope 依然成立），不是刚生成就拿去训练。
2. **门禁**：生成 ConsolidationOrder，走和状态提交同级别甚至更严格的审批——过 Council，不静默自动触发。
3. **训练方式**：LoRA / 低秩适配，不做全量微调；掺混一部分基础分布重放（EWC 风格惩罚项，限制对旧任务重要参数的扰动幅度）。
4. **诚实标注**：这套机制在小规模模型上的灾难性遗忘对策有经典实验支撑；在十亿参数级 transformer 上 LoRA/微调具体产生什么粒度的干扰，仍是活跃的实证研究方向，不是已证明安全的方案——这也是为什么门禁要设到最严。

---

## 10. 明确排除（重复列出，防止被后续迭代悄悄突破）

- 同构无界递归——深度硬上限 2，见第 8 节。
- 证明驱动自我修改（Gödel Machine / Tiling Agents 类）——当前无可落地的神经符号桥接方案，不纳入任何阶段。
- 权威结构运行时可协商化——Meta-Controller 的调整范围被写死在第 1 节不变量以内，不能被自己修改。
- 可学习性判断交给 LLM 直接做——必须落回 Mann-Kendall/Spearman 等非参数检验，LLM 只在事后生成候选解释，不裁决。

---

## 11. 落地优先级

```
P0  基础三部门工单闭环
    Orchestrator + EventBus + StateStore + WorkOrder schema + 状态机
    ↓ 这一版本本身应该已经能跑，不依赖后续任何一层

P1  检查点机制
    Session fork on QA reject + Distiller + lesson card + causal_chain

P2  Council 接入 + run_stopped 补蒸馏
    修复"纯工程侧力竭无声消失"这个已知缺口

P3  Scorer 抽样复核
    先小比例上线，观测抽样开销和不一致率基线

P4  Meta-Controller
    需要 P0-P3 跑出足够历史数据才有统计意义可调，不要提前上线

P5  惊讶驱动检查点
    替换固定触发表的主要触发方式，固定预算表降级为安全网
    需要 P0-P4 的历史数据校准阈值基线

P6  动态深度扩展
    复杂度最高的结构性变更，只在 P0-P5 稳定运行后引入

P7  可学习性追踪 + novelty/learnability 联合信号
    需要足够的 scope 级别历史样本，样本不足时必须显式返回"数据不足"

P8  巩固管线（skill → 权重）
    建议当作独立实验分支，不纳入主线迭代节奏，标准比其余七项都严
```

不建议跳级实现——P4 之后的每一层，判据都依赖前面若干层跑出来的真实历史数据（预算分配的统计基线、惊讶信号的阈值校准、可学习性趋势检验的最小样本量），提前实现会导致这些判据无数据可依，退化成拍脑袋常量。
