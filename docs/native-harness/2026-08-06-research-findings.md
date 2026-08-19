# 2026-08-06 三波研究调研记录

> 背景：围绕"三部门工单闭环系统如何在 LLM 无状态、上下文有限的约束下支撑长程演化产品"这一主线，分三波调研学术文献与工业实践。每波调研独立成题，结论互相支撑，最终收敛到同一架构方向。

---

## 调研一 · 返工循环中部门会话记忆管理

**问题**：三部门（需求/开发/质检）工单系统的返工循环中，部门私有会话如何在"保留足够错误记忆避免重复踩坑"和"限制上下文体积避免污染"之间平衡？

### 五个候选模式

1. **MemGPT / Letta — OS 式两级记忆，agent 自编辑**
   - 来源：MemGPT [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
   - 核心：上下文窗口当物理内存、外部库当磁盘，agent 用 function call 换页
   - 裁决：对固定三角色系统过重；自编辑管理决策本身会出错，调试困难；可作参照系，不建议照搬。

2. **Claude Code compaction + notes — 先记笔记，到点清零重启**
   - 来源：[Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[Claude Code best practices](https://code.claude.com/docs/en/best-practices)
   - 关键证据："**对同一问题纠错超过两轮，上下文已被失败尝试污染，应当 /clear 后用一条吸收了教训的全新 prompt 重启**"
   - 裁决：贴合场景，但解决的是"任务级"记忆，不解决跨工单的教训沉淀。

3. **Reflexion / ExpeL — 失败后蒸馏为自然语言规则**
   - 来源：Reflexion [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)、ExpeL [arXiv:2308.10144](https://arxiv.org/abs/2308.10144)（AAAI-24）
   - 核心证明：**防重复犯错不需要完整失败历史，只需要蒸馏后的规则**
   - 裁决：规则蒸馏方向正确，但规则质量无验证机制，可能把叙事当因果。

4. **Anthropic multi-agent research system — 子 agent 烧一万 token 只回 1-2k 结论**
   - 来源：[How we built our multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system)
   - 核心：scratchpad 子 agent 是消耗品；大产物写文件系统只回引用，避免"传话游戏"
   - 关键工程事实：多 agent 总消耗约为单 agent 聊天的 **15 倍**，链式约 4 倍。

5. **Mem0 / Zep — 记忆必须支持 UPDATE/DELETE/失效，不能 append-only**
   - 来源：Mem0 [arXiv:2504.19413](https://arxiv.org/abs/2504.19413)、Zep [arXiv:2501.13956](https://arxiv.org/abs/2501.13956)
   - 核心：片面追加的记忆不但浪费 token，还会主动降低决策质量（lost-in-the-middle + context rot）
   - Zep 双时态模型：事实三元组带 `valid_at/invalid_at`，过期事实被失效而非删除。

### 推荐机制：事件触发的 Lessons Store

- **写入触发**：QA 拒单 → 编排层确定性触发蒸馏子 agent（fresh context），输出 lesson card，主会话只收 ≤200 token 确认。
- **注入触发**：新一轮开工 → 编排层按工单 scope 检索 top-k（≈5，总量 ≤1.5k token）active cards，置顶注入。
- **失效**：QA 翻案（release）→ 对应卡片置 `invalidated`。

**Lesson Card Schema**：
```json
{
  "id": "eng-0142",
  "type": "avoid | require",
  "scope": "work_order_type:api_change",
  "rule": "改动对外接口签名时必须同步更新契约测试，否则 QA 必拒",
  "evidence": "WO-2026-031, qa_reject#2, scratchpad://eng/031attempt2.md",
  "source_cycle": {"work_order": "WO-2026-031", "reject_round": 2},
  "status": "active | superseded | invalidated",
  "created_at": "2026-08-01",
  "last_confirmed_at": "2026-08-04"
}
```

### 三个陷阱与对策

| 陷阱 | 对策 |
|---|---|
| ego 蒸馏者把"我错了"写成"QA 标准变了" | 蒸馏者必须是 fresh context 子 agent；卡片强制带 evidence 指针 |
| false reject 教歪规则 | 卡片记录 source reject round；QA 翻案编排层置 invalidated |
| top-k 注入失准、lost-in-the-middle | 写入时合并去重；注入前 scope 精确匹配优先于向量相似度；总量 ≤1.5k token |

### 学界没解决的三个开放问题

1. 蒸馏规则的因果性无验证手段（Generative Agents [arXiv:2304.03442](https://arxiv.org/abs/2304.03442) 观察到错误记忆经反思复利放大）。
2. 程序性知识的遗忘曲线没有原则性方案（MemoryBank [arXiv:2305.10250](https://arxiv.org/abs/2305.10250) 用艾宾浩斯，Zep 用时间戳衰减，均启发式）。
3. 何时派子 agent 没有可靠策略（所有生产系统靠手写规则）。

---

## 调研二 · 演化历史放不放进上下文

**问题**：产品需求随时间演化（A→B→C 每次更替都有原因），把演化历史放进 LLM 上下文是帮助还是污染？人脑适合时序-因果结构，LLM 是否反而被历史中的矛盾拖累？

### 核心裁决

> **原始演化历史放上下文 = 污染；因果摘要放上下文 = 帮助。两者必须分开裁决。**

人脑的"时序-因果叙事"优势恰恰建立在它已丢弃原始事件的前提下；LLM 若拿到原始旧版本全文，表现反而不如人脑，因为它没有"来源标记 + 当前态覆盖"机制，这部分要由你替它外置实现。

### 关键实证证据

1. **知识冲突（Xie et al., ICLR 2024 Spotlight, [arXiv:2305.13300](https://arxiv.org/abs/2305.13300)）**：模型面对并列矛盾信息表现出**强确认偏误**——只要其中一条与既有信念一致就抓住那条忽略其余。并列旧版本不会被当成"历史"，而会被当成"候选事实"参与采信竞争，竞争结果受无关表层特征摆布。

2. **ConflictBank（[arXiv:2408.12076](https://arxiv.org/abs/2408.12076)）**：把 temporal discrepancy 单列为冲突成因——**时间错位被实证认定为独立于错误信息的性能损伤源**。

3. **信念追踪容量竞争（Prakash & Shah, [arXiv:2410.17490](https://arxiv.org/abs/2410.17490)）**："知道真实世界状态"和"追踪他人错误信念"挤在同一组注意力头上互相干扰——机制层面的容量争夺，不是 prompt 能完全解决的。

4. **FreshLLMs（[arXiv:2310.03214](https://arxiv.org/abs/2310.03214)）**：显式标注日期 + 按新旧排序 + 对旧前提显式否定（"this premise is outdated…"），显著反超基线。**裸日期标注本身不够，必须配套"排序 + 旧态显式失效"语义**。

### "折中混合"问题的裁决

- **没有文献直接量化证明**"LLM 面对冲突约束倾向折中而非显式报告冲突"；
- 但存在机制性证据链足以支持当作设计假设：
  1. 知识冲突文献证明事实选择时会择一（不折中），但**生成阶段**两个约束都进 attention，会在概率场里插值——语言生成本性，不可开关；
  2. Abstention 研究表明"显式报告冲突"需要专门训练，**默认行为是沉默择一或沉默混合**；
  3. Anthropic 官方工程实践直接把"上下文混入过时/无关信息导致产出漂移"作为要求清零的理由。
- **裁决：按"折中会发生"设计。永远不要让两套平权并列的约束同时出现在上下文里。**

### 三个独立阵营的收敛（非巧合）

- **Anthropic context engineering**：just-in-time 检索而非预加载；工具要返回"当前态综合视图"而非原始日志列表（[Writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents)）;
- **Zep/Graphiti**：双时态图，事实带 valid_at/invalid_at；
- **Mem0**：每条新信息走 ADD/UPDATE/DELETE/NONE 四选一，UPDATE 让唯一活状态覆盖旧状态。

**三方收敛点完全一致：上下文内 = 唯一活态 + 极薄因果注记；历史 = 外置事件化存储，按需检索。**

### 三种呈现方式的裁决

| 方案 | 污染风险 | 因果保留 | token 成本 |
|---|---|---|---|
| (i) 完整版本陈列（v1+v2+v3 全文） | 高（三重叠加） | 高 | 3N |
| **(ii) 当前态 + 因果更替链，旧全文外置** | **低** | **中高** | **N + ε** |
| (iii) 只有当前态 | 最低 | 零（返工时会把 B 改回 A） | N |

**选 (ii)**。落地规则：
- 上下文内永远只有**当前态全文 + ≤10 行更替因果链**；
- 旧版本全文入事件化存储，附 `invalid_at` 和失效原因；
- 需要考古时走检索工具，结果必须带显式失效注记（复用 FreshPrompt 手法）。

---

## 调研三 · 无状态 LLM 能否引入"纸带"

**问题**：LLM 本质是无状态的——每次调用都是独立的一帧。我们想要的是连贯的长程"视频"。能否借鉴计算机基础原理（纸带 / 分层抽象 / 检查点），把长程过程分解成可检验的中间状态表示？

### 三条独立收敛路径（学术 / 系统 / 工程各自独立得出同构结论）

1. **Voyager（终身学习）[arXiv:2305.16291](https://arxiv.org/abs/2305.16291)**：成功行为压缩为可执行代码写入技能库，"缓解灾难性遗忘"；对比 SOTA 获 3.3 倍物品、科技树里程碑解锁快至 15.3 倍。**LLM 始终无状态，"记忆"全部表现为外部可组合工件。**

2. **AIOS（OS 隐喻）[arXiv:2403.16971](https://arxiv.org/abs/2403.16971)**：把 LLM 形式化为内核、agent 为进程、上下文窗口为内存配额——调度、换页、隔离都是一级机制。

3. **LangGraph Persistence（工程容错）[官方文档](https://docs.langchain.com/oss/python/langgraph/persistence)**：每个 super-step 落盘 StateSnapshot（values、next、metadata、pending_writes），支持从任意 checkpoint 恢复/回放/编辑。

**同构断言：LLM 是 CPU，上下文是指令窗口，一切超过单窗口的东西都必须落到外部显式状态。**

### 结构性缺陷：长程一致性必须外置

- **The Illusion of Diminishing Returns（[arXiv:2509.09677](https://arxiv.org/abs/2509.09677)，ICLR 2026）**：model 的 per-step 精度随步数退化，存在 **self-conditioning 效应**——一旦历史里出现过自己的错误，后续犯错概率显著上升，**不随模型规模消失**。错误不是被记住，是被条件化，逐轮复利。
- **ACL 2024 text-based world simulator（[arXiv:2406.06485](https://arxiv.org/abs/2406.06485)）**：GPT-4 在受控文本游戏上"不是可靠的世界模拟器"，动作后状态追踪不可靠。

### "视频"的正确表示

**状态转移日志（state-as-artifact），不是帧串（state-as-history）。**

三个定型样本：
- Zep 双时态知识图谱（valid_at/invalid_at）；
- Voyager 技能库（成功行为沉淀为代码而非过程描述）；
- LangGraph checkpoint（每步 channel 状态版本化）。

因果性靠转移链表达（X→Y 因为 Z），不是靠保全文。

### 分层决策频率：检查点事件驱动

- **Plan-and-Act（ICML 2025, [arXiv:2503.09572](https://arxiv.org/abs/2503.09572)）**：Planner 低频决策、Executor 高频执行，WebArena-Lite 57.58% 刷新 SOTA；
- **Anthropic Building Effective Agents**：workflow（预定义代码路径）与 agent（动态自主）对立，从最简单方案出发；
- **Anthropic multi-agent research**：阶段完成即摘要、派生全新子 agent。

**裁决：触发器采用领域里程碑事件为主 + 护栏为辅；固定步数切是最差的。**

---

## 三波调研的收敛统一

三波调研从三个不同角度切入，最终收敛到**同一个架构**：

1. **上下文内只保留唯一活态 + 极薄因果注记**；
2. **历史（错误、演化、状态）全部外置为显式、事件化、可失效的工件**；
3. **检查点触发 = 领域里程碑事件（QA 拒单、工单交接、阶段完成），不是固定步数**；
4. **规则教训要蒸馏为结构化卡片，支持失效，不能 append-only**。

映射回三部门系统：acceptance / defect / lesson card 应统一为**部门级 state artifact**，返工循环建模为检查点驱动。

## 开放科学问题

> 什么样的状态转移表示能在十年尺度持续服务一个部门而不腐化迭代的因果链——目前无人给出最终答案。
