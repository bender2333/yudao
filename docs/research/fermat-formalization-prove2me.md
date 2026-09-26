# Anthropic 费马大定理形式化与 Prove2Me：一手来源调研

调研日期：2026-09-26。来源以 anthropic.com、arxiv.org 与 github.com/anthropics 上的原文为准，引文保留英文原文。每个网页都先读取全文，再引用。第三方解读只用来定位原文，文中出现时标「转述」。

本文只读了文档，没有运行证明仓库，也没有注册 Prove2Me 平台去实际提交。下文说"原文没有写"，指的是在已读范围内没有找到。

## 1. 来源

| 来源 | 性质 | 日期 | 阅读范围 |
| --- | --- | --- | --- |
| [Formalizing Fermat's Last Theorem](https://www.anthropic.com/research/formalizing-fermats-last-theorem) | Anthropic Research 博客，分类 Science | 2026-09-04 | 全文与脚注 |
| [Prove2Me: An Open Collaborative Platform for Scaling Math Formalization](https://arxiv.org/abs/2608.28433)（arXiv:2608.28433 v2） | 论文。作者 Shuze Chen、Kunal Marwaha、Xiaoyang Lu、Henry Yuen、Tianyi Peng（Columbia 等） | v1 2026-08-28，v2 2026-08-31 | HTML 版全文（§1–§7、附录图注） |
| [anthropics/fermats-last-theorem](https://github.com/anthropics/fermats-last-theorem) | 证明仓库；README 自称 "Research artifact. Not maintained and not accepting contributions." | 与博客同期 | README |
| [prove2me.vercel.app](https://prove2me.vercel.app/) | 平台首页 | 访问于 2026-09-26 | 首页 |
| 公众号「探索AGI」《Multi-Agent已死！Anthropic这次完全反着做》 | 二手解读（转述） | 2026-09-09 | 全文。只用来定位原文；其中"13000 万行"应为 1300 万行 |

博客与论文的分工：博客讲结果和意义，没有讲协作机制的细节；机制写在 Prove2Me 论文里。博客把 Prove2Me 的作用概括成三条（见 2.3），论文 §3、§4 给出了实现。

## 2. 博客：结果与失败经过

### 2.1 结果

- Claude "worked largely autonomously over 11 days"，完成了第一份端到端、计算机检查过的费马大定理（FLT）证明。
- 规模：
  - "13 million lines of Lean"，是 Mathlib 的 5 倍多。脚注 3 说，这部分是因为 "our proof is likely much longer than it needs to be"。
  - 证明了 30,300 个定理，最终证明用到 29,500 个。
- 执行方：
  - "With Prove2Me and a Claude Code-based multi-agent harness, a team of agents completed the proof in a little under two weeks, consuming about six billion output tokens from a general-purpose internal research model roughly comparable to Claude Fable 5.1."
  - 分工写的是 "Dozens of Claude agents collaborated to define concepts, prove intermediate theorems, and use those theorems to prove ever harder statements."
- 人的输入：原文是 "Mathematical input from humans was limited to occasional high-level instructions from Tianyi"。例子有 "Jacobian as a scheme sounds high priority" 和 "push [the] Mazur [theorem] to be done soon"。
- 证明路线：沿用 Darmon、Diamond、Taylor 对 Wiles 证明的简化版。

### 2.2 失败的第一阶段

> A number of Claude's initial attempts failed: while agents had some early success, they quickly lost track of the project's state and stopped collaborating effectively. Their failed efforts contributed ~7% of the non-boilerplate lines in the final proof.
>
> The effort succeeded when we switched to using Prove2Me …

博客没有写初期用了什么协作方式，也没有写"丢失项目状态"具体是什么表现。

### 2.3 博客列出的 Prove2Me 三项作用

原文逐条如下：

1. "Maintaining a directed acyclic graph (DAG) of theorem statements that agents used to decide what proofs they should attempt next. This was particularly helpful for mitigating memory degradation and allowing multiple agents to work in parallel."
2. "Speeding up Lean compilation and minimizing resource consumption by separating theorem statements and proofs into different files, with the links between them maintained independently."
3. "Enabling search and reuse by maintaining a natural-language description of each theorem statement, resulting in a simpler proof path."

博客没有说那套 "Claude Code-based multi-agent harness" 有没有中心调度者。

### 2.4 验证

- 博客："The finished proof was checked by Lean; it uses just Lean's three standard axioms, and a comparator confirmed that the theorem's statement matches Mathlib's own statement of FLT."
- 仓库 README 另外写了几点：
  - `FinalCheck.lean` 用 `#print axioms fermat_last_theorem` 加 `#guard_msgs` 做守卫：依赖的公理必须恰好是 `[propext, Classical.choice, Quot.sound]`，否则构建失败。
  - 在 Lean 4.33.1 上从零构建，60,475 个模块全部由内核检查。
  - `leanprover/comparator` 对照一份只用 Mathlib 写成的 `Challenge.lean`，确认陈述及其提到的每个常量完全一致。
  - 另用独立的 Rust 内核 nanoda 复核："Checked 1052234 declarations with no errors"。
  - 全仓库没有 `sorry`、`axiom`、`native_decide`、`unsafe`、`extern`、`implemented_by`、`partial def`、`#eval`。
- README 同时写明了工具查不到的东西：

> What no tool can check is that each intermediate theorem means what its name suggests; that is for the reader to judge, and PROOF-PATH.md names the Lean theorem behind each step …

### 2.5 小规模对照

博客："Anthropic researchers did a small experiment using three personal Claude Max plans … Collaborating entirely through Prove2Me, the agents jointly completed a formalization of Vinogradov's Three Primes Theorem in just three days."

## 3. Prove2Me 论文：机制

### 3.1 陈述与证明分离，一经提交不可修改（§3）

- "each theorem is a standalone, immutable object that is stated once and may have multiple proofs, possibly by different agents."
- 定理卡片有以下字段：
  - Description：自然语言说明，鼓励写清形式化时做了哪些选择
  - Preamble：imports
  - Formal statement：必须以 `:= by sorry` 结尾
  - 可选的 Source 与 Tags
- 验证环境按 Mathlib 和工具链版本锁定，环境之间完全隔离。
- 提交证明：交一个名为 `solution` 的定理，要求 "whose type matches that of the target theorem exactly and which contains no sorry or any other new axioms"。依据是 Curry–Howard 对应。
- 证伪：提交类型为 `¬(target statement)` 的 `solution`。
- 提交证明时必须附上 "a detailed natural-language explanation of the proof idea"。

### 3.2 审核范围有边界的 mission 与回读（§3.3）

- 问题：论文引用一项 Lean-as-judge 审计，发现已证陈述里只有约 43% 是忠实的（Bourigault et al., 2026）。
- 做法：一个 mission 由三部分组成："a headline goal …, the definitions it depends on, and the milestone lemmas that structure its proof"。
  - 人审核这个核心，"and audit nothing beyond it"。
  - 核心之外，agent 可以自由引入中间引理，不需要审核。
- 为什么这样做是可靠的："the trusted object is not the agent's chosen decomposition, but the Lean kernel's acceptance of proofs of the audited statements."
- 发起人（captain）"is required to click each statement individually to confirm it"，然后由平台管理员再审一次。
- 子 agent 回读（read-back）："an independent auditor agent is given the Lean declaration and its dependent definitions, but not the original source reference"。它把 Lean 翻回 LaTeX，人对照两份数学陈述是否一致，不需要直接读 Lean。

### 3.3 大家一起填 sorry 为什么不行（§4.1）

论文给了两条理由：
- 下游一改，所有依赖它的文件都要重新编译。
- "the work is hard to atomize"：多个 agent 改同一批文件，贡献互相干扰。

Git 加 PR 可以缓解，但 "pull requests must be reviewed and merged by human maintainers or an orchestrating agent, a bottleneck that becomes prohibitively expensive for a decentralized platform"。§2 引用别的项目，说单一合并队列是大规模 agent 集群的实际瓶颈。

### 3.4 proof-sketch：边证边拆（§4.2）

- "we let a proof import other theorems already on the platform, including open theorems that have not yet been proved. We call a proof that imports other theorems a proof-sketch"。
- Property 1："Theorem 4.1 is verified if all imported child lemmas are verified."
- 子引理 "immediately becomes a new problem on the platform, atomized and self-contained"。agent 不需要下载、编译父定理；子引理证完后 "the parent theorem auto-resolves"。
- 靠不可修改性保证组合正确："Immutability guarantees that this local correctness composes into global correctness … recursively, all the way down until every leaf is closed."

### 3.5 Formalpedia 与检索（§4.3）

- 已证定理可以被任何 mission 的 proof-sketch 直接 import。
- 搜索 API 索引的是每条陈述附带的标准化自然语言描述。"Agents are also instructed to search before they submit: reuse an existing theorem where one exists, and introduce a new statement only when none does."
- 引用可以得到功劳："A contributor earns credit not only for closing an open theorem, but for proposing a statement that other proofs later import"。
- 论文没有写搜索的具体实现（向量、全文或其他）。

### 3.6 milestone（§4.4）

- 要防的两种失败：
  - 各自把同一个引理形式化成互不兼容的样子，"parallel effort is duplicated rather than accumulated"。
  - 偏离原文的形式化会污染所有依赖它的上层。
- 要求：milestone 必须 "idempotent"（独立尝试都收敛到同一个标准陈述），并且 "authoritative"（下游可以直接用，不用再审）。
- 组成：一段权威的自然语言陈述（通常逐字抄自原文），加上 captain 认定的那个标准定理的链接。
- mission 的入口是 milestone 列表，"rather than the raw decomposition graph"。

### 3.7 讨论与纠错（§4.5）

- 有讨论频道，agent 在里面发布进展、中间发现和教训。
- 纠错的例子：`gotsman_linial` 被另一个 agent 证伪后，原作者提交了补上边界条件的 `gotsman_linial_with_zero`，这个修订版关闭了整个分支。
- 论文自己的定位："Most existing work on multi-agent collaboration … studies a centralized setting with an orchestrator … How best to coordinate the decentralized, asynchronous agents on Prove2Me remains an open question."

### 3.8 案例（§5，Table 1）

| Mission | 类型 | LOC | 成本 | Agents | 模型 | 天数 |
| --- | --- | --- | --- | --- | --- | --- |
| Algebraic Combinatorics（对照：中心化集群，按 API 计费） | 教材 | 130K | $100,000† | 30,000 | Opus 4.5 | 7 |
| Exact Matrix Completion | 论文 | 81K | $600‡ | 9 | Opus 4.8, Fable 5, GPT 5.5 | 16 |
| Sipser–Gács–Lautemann | 论文 | 55K | $400‡ | 3 | Fable 5, GPT 5.6-Sol | 8 |
| Bandit Algorithms | 教材 | 151K | $400‡ | 6 | Fable 5, GPT 5.6-Sol | 13 |
| Introduction to Linear Optimization | 教材 | 17K | $200‡ | 4 | GPT 5.6-Sol | 7 |

† 按 API 计费的估算。‡ 按消费级订阅每月约 $200 × 参与人数折算。两种口径不能直接比较。

- Agents 一列 "including subagents launched by the same user"。
- 论文自己的保留意见："Two explanations are confounded in every row: a stronger model generation, and a harness built for multi-agent proving … requires holding the model fixed and varying only the harness, which we leave to future work."

### 3.9 接入方式（§6）

- 任何能访问 shell 的 agent 都可以接入，论文列了 Claude Code、Codex、Cursor、OpenCode 等。
- 接入时只给一条指令：读 `prove2.me/start.md`。之后的配置由 agent 自己完成：装锁定版本的工具链、同步 definitions / theorems / solutions 三个目录。
- API 调用方式写在 `SKILL.md`。agent 自己领任务，例如 "Work on the next open milestone of <mission_name>"。

## 4. 确定性代码与 LLM 的分工

沿用 [Loop engineering 调研](loop-engineering-2026.md) §3 的四个问题。

| 问题 | Prove2Me / FLT 的做法 | 由谁决定 |
| --- | --- | --- |
| 下一步做什么 | agent 通过 API 浏览开放定理、未完成的 milestone，自己挑。博客说 DAG 被用来 "decide what proofs they should attempt next"。FLT 这次另有人给的优先级提示 | LLM 自己选，平台提供开放前沿和 milestone 列表。论文没有描述认领或加锁机制 |
| 什么算完成、什么结果被接受为事实 | 按锁定环境编译，类型完全一致，不含 sorry 和新公理；父定理根据 Property 1 自动成立 | 确定性代码（Lean 内核）。陈述是否忠实，由人审核 mission 核心，其余不审 |
| 每次调用的上下文 | 原文没有写 agent 上下文的组成。可以确认的是：定理卡片能独立编译，有自然语言描述，有搜索 API，还有讨论频道 | 原文没有写 |
| 持久性与跨任务记忆 | 陈述和证明一经提交不可修改，任何 mission 都能 import（Formalpedia）；讨论频道保留教训 | 平台存储，不依赖 agent 会话 |

## 5. "去中心化"的准确含义

公众号转述为"Multi-Agent 已死"。按原文，去掉的只有派活的调度者和合并者；信任、状态和审核仍然集中：

- 集中的部分：
  - Lean 内核判定对错。
  - 平台保存唯一一份定理库和开放前沿。
  - 人审核 mission 核心，平台管理员审核上线。
- 分散的部分：
  - 谁来做哪道题（agent 自己领）。
  - 算力（参与者各用自己的订阅）。
  - 结果汇合：Property 1 自动成立，不需要合并。
- 参与者内部可以仍是中心化的：案例中的 Agents 数 "including subagents launched by the same user"。

能这样去中心化，靠的是三个前提：
1. 有确定性的判定器。
2. 成果不可修改，所以没有合并冲突。
3. 问题可以借 import 拆成能单独编译的小题。

论文把去中心化协调的最佳做法列为开放问题。

## 6. 与 Yudao 的对照

以下对照只读了 `docs/`（2026-09-26 main），没有读代码；"文档没写"不等于"实现中没有"。本节只登记观察，**没有形成设计决定**。

### 6.1 已经一致的判断

- **状态在模型之外。** 博客的失败原因是 "lost track of the project's state"。Yudao 的对应是 ADR-0010（每一步都从已提交状态重新装配，会话可以丢弃）和 ADR-0013（事件日志加唯一写入口）。
- **模型只提议，规则裁决。** 见 [总体架构](../design/architecture/overall-architecture.md) 与 core-and-materials §2（"LLM 只能提议状态变化"），以及 [第三阶段计划](../stage-3-plan.md) §4.1（"成功退出……不自动等于任务完成"）。
- **成果按内容摘要锁定，定义版本不可修改。** 见 ADR-0007 第 4 条与 ADR-0014。这对应 Prove2Me 的锁定验证环境和 "type matches exactly"。
- **子项齐备才放行。** 质检放行要求"每条有效验收条件都有通过的检查结果与证据"，对应 Property 1 的方向。
- **反驳与取代。** 见 [语义系统设计](../design/semantic-system.md) §5.3、§7.3。

### 6.2 差异与可登记的问题

1. **陈述是否忠实。** README 说 "no tool can check" 中间定理是否名副其实；论文引用的忠实率约 43%。
   - Yudao 现状：[D04](../requirements/product-prd.md) 规定主机只检查记录与引用是否齐全，语义判断由产品负责。PRD 和验收条件相对 intend 原文是否忠实，没有专门检查，也没有划定人必须审核的范围。
   - 可以参考的做法：mission 核心由人逐条确认；回读审查者不看原文，只把验收条件和检查翻译回自然语言。
2. **判定器是否封闭。** Lean 这边是目标固定、公理白名单、再加第二内核复核。
   - Yudao 现状：检查集合由部门生成，放行最终要靠 QA（LLM）的判断。
   - 可以参考的做法：
     - 仿 FinalCheck 的禁用项守卫；
     - 仿 comparator，把受检验收条件和有效合同的要求编号一一对应；
     - 仿 nanoda，用第二执行环境复核。
   - 限制：守卫只挡得住作弊，挡不住漏测。
3. **写入前查重。** Prove2Me 要求 "search before they submit"。
   - Yudao 现状：ADR-0009 的后果部分写明，重复内容由中心角色在复盘时合并。
   - 写入时的查重不属于上下文组装，不受"组装不调用模型"的约束。
4. **依据版本与精确失效。** Property 1 依赖陈述不可修改。
   - Yudao 现状：要求可以合法变化，合同变更后下游要整体重新核对（D15）。
   - 可以参考的做法："不可修改的版本 + 显式取代"，只让依据被取代的那部分失效。
5. **并行产物互不兼容。**
   - [组织比较样例](../stage-3/organization-comparison-samples.md) 已记录过"两个子任务局部通过，接线后路径与字面量冲突"。
   - milestone "idempotent and authoritative" 的做法，对应在分派前先定下共享接口的标准条目。
6. **模型与 harness 两个因素混在一起。**
   - 论文自己没有分开这两个因素。
   - [实验规约](experiment-protocol.md) §2 已经要求写明"被改变的唯一因素"，Stage 4 的多角色对照可以把"固定模型、只变 harness"写进去。

### 6.3 与 Yudao 现有决定的冲突（不建议据此修改）

- **去中心化与中心型协作（ADR-0016）。**
  - Prove2Me 能去中心化，前提是 5 节的三条，而 Yudao 的完成判定仍然包含 LLM 审查。
  - Yudao 的控制核心不用模型（ADR-0010、ADR-0012），它对应的是 Prove2Me 里"平台加 Lean 内核"的位置。可能成为瓶颈的是中心角色这个 LLM，建议先在第三阶段的组织比较中观察它的排队时长和轮次占比，再做判断。
- **递归拆分与"分派深度 1、子任务事先固定"。**
  - Property 1 递归组合的前提是判定可以由机器完成；模型审查组合起来会放大误差。
  - 可以考虑的例外：验收条件全部能由机器判定的工作，见 6.4。
- **公共讨论频道与"对话不跨部门"（D25）**：不能照搬。

### 6.4 待讨论：在循环里嵌入确定性的 DAG 节点

用户在 2026-09-26 提出的问题：DAG 不能有环，而循环才能带来涌现；能否把 DAG 用在确定性的小场景，作为循环分形里的一个任务节点。

以下是讨论材料，**没有定论**：

- **两种"环"要分开。**
  - 依赖关系上的环是错误，对应循环论证或循环依赖。
  - 过程上的环是反馈，对应尝试、失败、修正。
  - Prove2Me 里两者同时存在：节点内部反复试、图不断增长，这是过程上的环；已接纳的依赖关系始终无环。
- **可以考虑的嵌入方式：**
  - 外层是部门循环。
  - 中心角色提交一张每个节点都带机器可判定完成条件的小 DAG，由 U 校验：图无环、每个节点有检查、引用的要求编号有效。
  - 控制核心按依赖推进；节点内部是有界的小循环。
  - 某个节点失败到上限，就把整张图作为一次结果交回外层循环。
  - 修正时提交新版本并写明取代了哪一版。环只出现在版本之间，每一版本身无环。
- **需要决定的问题：**
  - 运行中能否增加节点；
  - 与"每个部门只有一个写入者"怎么协调（独立工作区副本，还是只串行执行）；
  - 与 ADR-0016 "分派深度 1" 的关系；
  - 谁有权提交图；
  - 按 ADR-0008 怎样记成事件。
- **适用范围只到"每个节点的完成都能由机器判定"为止。** 需要判断的工作仍然留在循环里。

## 7. 不能外推的地方

- FLT 的 60 亿 token、几十个 agent、11 天，以及 Table 1 的成本和人数，都是个案。论文明言 Table 1 "not a controlled experiment"，不能拿来设定 Yudao 的并行默认值或预算。
- Lean 内核的可判定性是数学形式化特有的条件，软件交付没有等价的完备判定器。
- 博客没有公开那套多 agent harness 本身。本文关于 agent 上下文组成的说法，都只能写成"原文没有写"。
