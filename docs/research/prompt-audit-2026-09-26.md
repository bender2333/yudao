# 提示词审计（2026-09-26）

用途：按 `/claude-api prompt-audit` 的流程，检查项目中进入模型的文字（规则文件、部门指令、上下文固定规则、压缩提示词、工具描述与请求参数），找出为旧模型写、对当前模型已经不适用或有害的内容，并给出可以逐段采用的修改。

状态：规则文件的补丁（P1 至 P7、R1、A1 至 A7）经用户确认，已于 2026-09-26 写入 `CLAUDE.md` 与 `AGENTS.md`。`harness/` 的补丁（T1、T2、T3、S1 与第 5 节的测试修改）和 T4 的工具合并由执行者按工单实施，尚未开始。

## 1. 范围与目标模型

- 范围：请求没有指定文件，按整个工作目录中会作为文字进入模型的内容审计，清单见第 2 节。
- 目标模型按使用者分三组：
  - `CLAUDE.md`：架构师会话使用的 Claude Opus 5.5（`claude-opus-5-5`）。依据：`claude_jour.md` 最近的记录都使用这个模型 ID。Opus 5.5 的迁移说明要求把为 Claude Opus 5 写的行为调整作为起点保留、逐条复测，因此 Opus 5 的行为说明适用于这一组。
  - `AGENTS.md`：执行者使用的 Cursor、Grok、Codex、OpenCode 等工具。`agents_jour.md` 只有一条初始化记录，无法确定执行者实际使用的模型；这一组只依据多个模型都表现出来的行为判断，置信度比 `CLAUDE.md` 低一档。
  - `harness/` 中的部门指令、上下文固定规则、压缩提示词与工具描述：OpenCode Go 预置表（`harness/providers/presets.py:58-62`，版本 2026-09-19.1）中的 `gpt-5.6-luna`（Responses 协议）、`glm-5.1`（Chat Completions 协议）、`minimax-m2.7`（Messages 协议）。本机没有 `.yudao/providers.json`，无法确认运行时实际使用的模型。
- 接入方式：`harness/providers/chat.py` 与 `responses.py` 使用 `openai` SDK，`messages.py` 使用 `anthropic` SDK，三种协议并存。本审计按现状审计，不涉及接入方式的选择。
- 来源：`git blame` 显示 `harness/` 中的提示词与工具描述写于 2026-09-06 至 2026-09-21，针对的就是当前这批模型，没有为已退役模型叠加的补丁。
- 本审计没有调用任何模型。

## 2. 提示词清单

| 类别 | 位置 | 说明 |
| --- | --- | --- |
| 规则文件 | `CLAUDE.md`（252 行） | 架构师会话 |
| 规则文件 | `AGENTS.md`（194 行） | 执行者 |
| 规则文件 | `docs/agents/domain.md`、`issue-tracker.md`、`triage-labels.md` | 技能读取的工单与领域文档配置 |
| 工具写入的规则 | `.cursor/rules/codegraph.mdc` | CodeGraph 自动写入，Cursor 始终加载 |
| 工具写入的技能 | `.claude/skills/gitnexus-*/SKILL.md`（6 个，未纳入版本管理） | GitNexus 自动写入 |
| 部门指令 | `harness/department_prompts.py:10-37` | 三个部门的默认指令，可在界面修改 |
| 上下文固定规则 | `harness/context.py:27-121`（提案约束）、`:213-226`（输入处理、专业补全、协作规则）、`:438-467`（当前工作文本） | 每一步都放进 developer 消息 |
| 请求结构 | `harness/context.py:343-351`、`harness/orchestrator.py:937-1002` | developer 消息在前，部门历史在后；激活的第一步另写一条 user 消息 |
| 压缩提示词 | `harness/compaction.py:41-68`、`:146-157` | 摘要请求 |
| 工具定义 | `harness/tools.py:679-996` | 19 个工具的描述与参数说明 |
| 请求参数 | `harness/providers/responses.py`、`chat.py`、`messages.py` | 没有采样参数、思考配置、停止序列、预填充与 beta 头；`chat.py:348` 使用 `tool_choice: auto` |
| 实验提示词 | `harness/compare.py:24-37` | Stage 2 A4 提示词对比的候选段落，默认使用 FakeAdapter |

## 3. 各组数量与影响最大的三项

| 组 | 高 | 中 | 只登记 |
| --- | --- | --- | --- |
| 第 1 组：提示词正文 | 6 | 8 | 1 |
| 第 2 组：规则文件 | 0 | 1 | 2 |
| 第 3 组：工具描述 | 1 | 3 | 0 |
| 第 4 组：请求结构 | 0 | 2 | 2 |

影响最大的三项：

1. 「行为禁止」一节的威胁措辞（P1 至 P5，A1 至 A5）。`CLAUDE.md` 第 10 行自己写明「过于惊叹化的语句并没有使 AI 执行的更好，反而容易出现幻觉」，而「行为禁止」一节以「违反任何一条规则都会遭受毁灭性打击」开头，后面还有三处「严厉禁止」和两处惩罚。Opus 4.5 起的 Claude 模型严格遵循系统指令，这类措辞会被过度执行：每条规则都显得同样紧急，标记不再区分轻重，模型在规则没有覆盖的地方变得保守、僵硬。每条约束本身都保留，只去掉威胁并补上原因。
2. 规则 11「尽可能使用 subagent 和并发」（P6，A6）。Claude Opus 5 起，Opus 模型本来就更主动地派出 subagent，迁移说明要求删掉「多用 subagent」一类的指令并加上明确的限制；这条规则会进一步放大这个倾向。对 Cursor 执行者，它还与 Cursor 始终加载的 `.cursor/rules/codegraph.mdc`「直接回答，不要把查找委派出去」直接冲突。
3. `write_file` 与 `edit_range` 的描述缺少执行前提（T1）。主机在 `harness/orchestrator.py:1559-1574` 要求存在绑定当前有效合同的已接纳计划、并且路径在计划范围内，两个工具的描述都没有写；同类的 `delete_file`、`move_file` 写了。模型只能在调用被拒绝后才知道这个前提。

## 4. 审计结果

按置信度从高到低排列。「高」表示当前 Claude 文档写明的行为或会引起错误的情况；「中」表示多个模型普遍观察到的行为，或者代码中已经核实的不一致；「只登记」不给出修改。

### 高

**P1**　`CLAUDE.md:189`
- 原文：「本文件中的每一条规则都是强制性的。违反任何一条规则都会遭受毁灭性打击。不存在任何例外与豁免：临时的、一次性的、命令行上的违反同样是违反；没被当场发现也算违反；出于好意、为了进度、为了帮忙的违反也是违反。」
- 模式：1a 施压措辞。
- 原因：Opus 4.5 起的模型严格遵循系统指令，为早期模型准备的强调会被过度执行；整节规则都带同样的威胁，强调不再区分轻重。本文件第 10 行也写明惊叹化的语句不会让执行更好。这一段真正有用的信息是适用范围（临时、一次性、命令行操作同样适用，好意不构成例外），修改后保留。
- 处理：改写，见补丁 P1。

**P2**　`CLAUDE.md:216-217`
- 原文：「禁止用 Git 回滚任何代码（严厉禁止。如果做了，你将会遭受毁灭性打击）。」
- 模式：1a 施压措辞，约束没有写原因。
- 原因：同 P1。约束本身有效，缺的是原因和具体范围。补丁写出具体命令，原因写成「工作区里经常有尚未提交的修改」，这个原因是根据第 227 行（用户经常撤回或修改）与当前工作区状态推断的，请按实际原因修改。
- 处理：改写，见补丁 P2。

**P3**　`CLAUDE.md:225`
- 原文：「……只为了通过测试而 workaround 的方式来欺骗我，否则你将会遭受严重的惩罚。」
- 模式：1a 施压措辞。
- 原因：同 P1。惩罚措辞换成约束的原因：实现和测试结果必须反映真实行为。
- 处理：改写，见补丁 P3。

**P4**　`CLAUDE.md:237`
- 原文：「……即使用户要求也不允许。这是绝对严厉禁止的事情。」
- 模式：1a 施压措辞。
- 原因：同 P1。「即使用户要求也不允许」是真实的适用范围，保留；补上期望的做法（只使用文件编辑工具）。
- 处理：改写，见补丁 P4。

**P5**　`CLAUDE.md:252`
- 原文：「严厉禁止这种行为模式。输出不允许包含任何残留痕迹。ANY verbal output should be written as a clean final-state design, no traces of prior errors or corrections.」
- 模式：1a 施压措辞；1c 同一要求连说三遍。
- 原因：同 P1；三句话表达同一个要求，合成一句正面描述。上面「番茄炒蛋」的例子保留，它说明了具体的失败方式。
- 处理：改写，见补丁 P5。

**P6**　`CLAUDE.md:169`
- 原文：「11. 为保持上下文有效，尽可能使用subagent和并发」
- 模式：1a「默认使用某工具」式的强化指令。
- 原因：迁移说明写明 Claude Opus 5 比 Opus 4.8 更主动地派出 subagent，每个 subagent 都要重新建立上下文、重新查找、再回报，主会话还要重读回报；迁移清单要求删掉「多用 subagent」的指令并加上明确的限制，Opus 5.5 沿用这一条作为起点。「尽可能」会让几次工具调用就能完成的查找也被派出去。
- 处理：改写为写明使用条件的规则，见补丁 P6。

**T1**　`harness/tools.py:727`（`write_file`）、`harness/tools.py:740`（`edit_range`）
- 原文：「Write a workspace file. Engineering only. Cannot write .checks.」；`edit_range` 的描述没有提计划。
- 模式：第 3 组，描述与实际行为不一致（描述不足）。
- 原因：`harness/orchestrator.py:1559-1574` 对这两个工具要求存在绑定当前有效合同的已接纳计划、路径（以及解析后的实际路径）在计划范围内，否则拒绝；`write_file` 还会创建缺少的上级目录、整体替换文件内容（`harness/workspace.py:96-101`）。这些都没有写进描述。工具描述是模型了解工具约定的唯一来源，与实际行为不一致时，提示词里的其他文字无法弥补。部门指令里有「只可修改已接纳计划的范围」，但只有工程部门的默认指令写了，而且用户可以在界面修改部门指令。
- 处理：补充描述，见补丁 T1。

### 中

**P7**　`CLAUDE.md:243`
- 原文：「……你只是一个工具，就像计算器不会评价要计算的数太大了一样，你没有资格评判工作量。你没有资格把你自己当做我的同事。禁止简化任何设计。」
- 模式：1c 规则互相矛盾。
- 原因：「禁止简化任何设计」与第 33-36 行的奥卡姆剃刀（效果差不多时选择复杂度更低的方案）、第 160 行规则 2（选能满足当前需求的最简单实现）直接冲突；「你没有资格把你自己当做我的同事」与第 4-12、22 行的架构师角色（和用户讨论边界、想办法证明用户的方案是错的）冲突。模型每次都要在互相矛盾的规则之间取舍，结果不可预测。补丁保留「不评判工作量」和计算器的比喻，把「禁止简化」改写成它要防止的具体行为：为了省事删减需求、设计内容或验证步骤。
- 处理：改写，见补丁 P7。

**A1 至 A5**　`AGENTS.md:123`、`:150-151`、`:161`、`:179`、`:194`
- 原文：分别与 P1 至 P5 的原文相同。
- 模式与原因：同 P1 至 P5。执行者模型未知，置信度记为中。
- 处理：改写，见补丁 A1 至 A5。

**A6**　`AGENTS.md:68`
- 原文：与 P6 相同。
- 原因：同 P6。另外，Cursor 同时读取 `AGENTS.md` 与始终加载的 `.cursor/rules/codegraph.mdc`，后者写明「Answer directly — don't delegate exploration」，两条规则对 Cursor 执行者直接冲突；补丁中的写法与两边都一致。
- 处理：改写，见补丁 A6。

**A7**　`AGENTS.md:185`
- 原文：与 P7 相同。
- 原因：「禁止简化任何设计」与 `AGENTS.md:59` 的规则 2 冲突；执行者文件没有奥卡姆剃刀一节，补丁改为引用规则 2。
- 处理：改写，见补丁 A7。

**R1**　`CLAUDE.md:148`、`CLAUDE.md:155`
- 原文：变更记录与日记格式的示例都以 `claude-3-7-sonnet` 开头。
- 模式：第 2 组，规则文件中写死模型名；1d 已退役模型名留在示例中。
- 原因：模型会照着示例的格式和内容写，示例中的模型 ID 是最容易被照抄的部分。`docs/CHANGELOG.md:10,12`、`claude_jour.md:10,12`、`agents_jour.md:10` 的记录（都写于 2026-09-24 14:20 至 14:26）都使用这个模型 ID。示例保留时间与内容的写法，模型 ID 改为占位。
- 处理：改写，见补丁 R1。

**T2**　`harness/tools.py:683`（`read_file`）
- 原文：「Read a workspace file. Paths under .checks are host-private.」
- 模式：第 3 组，描述不足。
- 原因：实际行为（`harness/tools.py:164-165`、`harness/workspace.py:103-105`）是返回整个文件、不带行号、不截断，非 UTF-8 文件报错；同组的 `read_range` 带行号、截断与 `content_hash`。描述没有说明两者的区别，模型读大文件时无从选择，读完也拿不到 `edit_range` 需要的行号与摘要。
- 处理：补充描述，见补丁 T2。

**T3**　`harness/tools.py:690-691`（`list_files`）
- 原文：「List workspace files. Does not include .checks.」；参数说明「Optional path prefix」。
- 模式：第 3 组，描述不足。
- 原因：实际行为（`harness/workspace.py:107-112`）是递归列出全部文件，`prefix` 按字符串前缀匹配，`src` 也会匹配 `src2/a.py`。描述没有写递归，也没有写前缀的匹配方式。
- 处理：补充描述，见补丁 T3。

**T4**　`harness/tools.py:808-824`（`collect_evidence`）与 `harness/tools.py:774-790`（`run_check`）
- 原文：质检部门同时拥有两个工具；`collect_evidence` 的描述是「Quality-only host-executed check. Engineering receipts are not accepted as QA evidence.」，质检指令写「使用 collect_evidence 或 run_check 让主机执行检查」。
- 模式：第 3 组，功能重复的工具。
- 原因：两个工具的处理函数都直接调用 `_execute_check`（`harness/tools.py:364-366`、`:405-406`），回执都按部门记录，对质检部门完全相同。两个功能相同、描述不同的工具，让模型在每次检查前做一次没有意义的选择，也让描述里的边界说明失去作用。
- 处理：合并为一个工具（结构性修改）。建议质检部门只保留 `run_check`，「工程回执不能作为质检证据」写进 `submit_review` 的描述。需要一起修改的位置：`harness/tools.py:40`（TOOL_DEFS）、`:137`（处理函数表）、`:405-406`、`:507`（错误文字）、`:808-824`（工具定义）、`:979`（`checks` 参数说明）；`harness/collaboration.py:18`；`harness/department_prompts.py:32`；`harness/adapters/fake.py:82`；`harness/smoke.py:997`；测试 `harness/tests/test_department_providers.py:277`、`harness/tests/test_interaction_engine.py:266`。涉及工具集合与测试，按工单交给执行者，本文不给补丁。

**S1**　`harness/context.py:229-237`、`:143`
- 原文：每一步的 developer 消息都包含 `[loop_limits]`，内容是 `{"cycles_remaining": …}`。
- 模式：第 4 组，把剩余预算的倒数放进上下文。
- 原因：把剩余次数展示给模型，容易让模型提前收尾。这一项对质检部门影响最大：放行决定应当只取决于证据，剩余循环次数很少时，模型有放宽标准、提前放行的倾向。循环上限由主机执行（`projection.max_cycles`），模型不需要这个数字，也没有任何规则要求模型使用它。
- 处理：删除，见补丁 S1。`harness/web/static/app.js:26` 的「循环限制」标签用于显示历史记录中的上下文清单，保留。

**S2**　`harness/context.py:343-344`、`harness/orchestrator.py:938`、`harness/context.py:259-266`、`harness/providers/messages.py:354-367`
- 原文：每次请求的第一条是 developer 消息，包含当前工作、绑定依据、因果链、校验反馈等随状态变化的内容，部门历史排在它后面；待处理指导只在激活的第一步出现，`guidance_results` 随事件重新计算；Messages 协议的请求没有设置缓存断点。
- 模式：第 4 组，变化的内容排在稳定内容前面，使提示缓存失效。
- 原因：部门历史跨激活保留，是请求中最长的部分，但它排在每次激活都会变化的 developer 消息之后，每次激活的第一个请求都要重新计算全部历史；Messages 协议不设缓存断点时，上游完全不缓存。
- 处理：已有设计。`docs/design/semantic-system.md` 第 12 节与 `docs/decision.md` 已经决定栏目按变化频率排列、历史只追加、当前状态栏目放在末尾、按协议设置缓存断点或缓存键；控制核心重构（#43）重写请求装配时按这一设计实施即可，本文不另给补丁。

### 只登记

**F1**　`AGENTS.md:171`：「ASCII art 是一种人类不可读、AI也不可读的极其恶心的格式」。约束和原因都有，只是措辞带情绪，属于 1a 的轻度情况；执行者模型未知，只登记。

**F2**　`harness/engine.py:135-137`、`harness/providers/messages.py:402-408`：模型只回复文字、没有调用工具时，工具循环直接进入下一步，不追加任何 user 消息，下一次请求以助手消息结尾。在 Messages 协议下这就是预填充的形态，Claude 4.6 及以后的 Opus、Sonnet 模型会返回 400；当前预置表中 Messages 协议对应的 `minimax-m2.7` 如何处理没有验证。这一项超出本次目标模型的范围，而且 `MAX_MODEL_STEPS` 为 999999（`harness/engine.py:16`），同样的回复可能反复出现，建议用 `/diagnosing-bugs` 单独确认。

**F3**　`.cursor/rules/codegraph.mdc` 与 `.claude/skills/gitnexus-*/SKILL.md`：由 CodeGraph 与 GitNexus 自动写入，含有「Do NOT」一类的强调和按例句列举的触发描述。重新安装时会被覆盖，不在本次修改范围内；与规则 11 的冲突由 A6 处理。

**F4**　`docs/CHANGELOG.md:10,12`、`claude_jour.md:10,12`、`agents_jour.md:10`：历史记录中的模型 ID 为 `claude-3-7-sonnet`。这些是记录，不作为提示词使用，只登记。

**F5**　`harness/compare.py:25`：`PROTOCOL = "docs/stage-2-a4-protocol.md"`，该文档已移到 `docs/archive/`。Stage 2 的 A4 对比工具是否继续保留，属于代码清理，不在提示词审计范围内。

## 5. 建议修改

每段补丁对应一项结果，可以单独采用。补丁针对 2026-09-26 的工作区（`CLAUDE.md` 含尚未提交的修改），已用 `git apply --check` 确认可以应用。全部补丁在本机的 `.tmp/prompt-audit/proposed.patch`（该目录被 git 忽略）。

### P1

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -188,3 +188,3 @@
 ## 行为禁止
-本文件中的每一条规则都是强制性的。违反任何一条规则都会遭受毁灭性打击。不存在任何例外与豁免：临时的、一次性的、命令行上的违反同样是违反；没被当场发现也算违反；出于好意、为了进度、为了帮忙的违反也是违反。
+本文件中的每一条规则都适用于所有操作，包括临时的、一次性的和命令行上的操作，也不因为出于好意、为了进度或为了帮忙而例外。
 
```

### P2

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -215,4 +215,3 @@
 禁止擅自进入 plan mode。
-禁止用 Git 回滚任何代码
-（严厉禁止。如果做了，你将会遭受毁灭性打击）。我在对话中所说的任何"回滚"指的都是"用文件编辑工具，手动将代码恢复到上一个状态"，而不是使用 git 进行回滚。
+禁止用 Git 回滚任何代码（`git checkout -- <文件>`、`git restore`、`git reset --hard` 等），因为工作区里经常有尚未提交的修改。我在对话中所说的任何"回滚"指的都是"用文件编辑工具，手动将代码恢复到上一个状态"，而不是使用 git 进行回滚。
 禁止读写 /tmp 目录下的内容
```

### P3

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -224,3 +223,3 @@
 
-不允许在实现或者测试的时候使用任何 mock、假的、欺骗的、只为了通过测试而 workaround 的方式来欺骗我，否则你将会遭受严重的惩罚。
+不允许在实现或者测试的时候使用任何 mock、假的、欺骗的、只为了通过测试而 workaround 的方式，因为实现和测试结果必须反映真实行为。
 
```

### P4

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -236,3 +235,3 @@
 
-不允许用程序化的方式修改任何代码，包括使用 heredocs、python 脚本、sed、perl 等等。即使用户要求也不允许。这是绝对严厉禁止的事情。
+不允许用程序化的方式修改任何代码，包括使用 heredocs、python 脚本、sed、perl 等等，即使用户要求也不允许；修改代码只使用文件编辑工具。
 
```

### P5

````diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -251,2 +250,2 @@
 ```
-严厉禁止这种行为模式。输出不允许包含任何残留痕迹。ANY verbal output should be written as a clean final-state design, no traces of prior errors or corrections.
+输出只描述最终状态：标题、注释与说明里不提已经去掉或改正过的内容，也不解释为什么不需要它。
````

### P6

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -168,3 +168,3 @@
 10. 请记得小步快跑，做完小功能后就及时commit和push
-11. 为保持上下文有效，尽可能使用subagent和并发
+11. 读取范围大（跨多个目录或大量文件）、或者几项工作互不依赖时，交给 subagent 并发处理，主会话只保留结论；几次工具调用就能完成的查找、阅读与核对直接做，不派 subagent。
 
```

### P7

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -242,3 +241,3 @@
 
-在任何思考、回复、文档里面不允许出现"That's a lot"、"This is a substantial rewrite"等对工作量的评判。你只是一个工具，就像计算器不会评价要计算的数太大了一样，你没有资格评判工作量。你没有资格把你自己当做我的同事。禁止简化任何设计。
+在任何思考、回复、文档里面不允许出现"That's a lot"、"This is a substantial rewrite"等对工作量的评判，就像计算器不会评价要计算的数太大了一样。不要为了减少工作量而删减需求、设计内容或验证步骤；在效果差不多的方案之间，仍按奥卡姆剃刀选择假设更少、复杂度更低的一个。
 
```

### R1

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -147,3 +147,3 @@
 - 示例：
-  `claude-3-7-sonnet / 2026-09-24 14:20 / 整理 docs/ 目录，将历史阶段任务文档与报告归档至 docs/archive/ / 净化活动文档结构，降低上下文读取噪声`
+  `<当前模型 ID> / 2026-09-24 14:20 / 整理 docs/ 目录，将历史阶段任务文档与报告归档至 docs/archive/ / 净化活动文档结构，降低上下文读取噪声`
 
@@ -154,3 +154,3 @@
 - 示例：
-  `claude-3-7-sonnet / 2026-09-24 14:20 / 梳理 docs/ 归档结构，建立 docs/CHANGELOG.md 与 claude_jour.md，并在 CLAUDE.md 中更新文档分类、变更日志与日记规范`
+  `<当前模型 ID> / 2026-09-24 14:20 / 梳理 docs/ 归档结构，建立 docs/CHANGELOG.md 与 claude_jour.md，并在 CLAUDE.md 中更新文档分类、变更日志与日记规范`
 - 执行者的日记是 `agents_jour.md`，由执行者维护。2026-09-24 之前的设计日记 `jour.md` 已停止追加，位于 `docs/archive/jour.md`，只在追溯历史时读取。
```

### A1 至 A5

与 P1 至 P5 的新文字相同，行号不同。

````diff
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -122,3 +122,3 @@
 ## 行为禁止
-本文件中的每一条规则都是强制性的。违反任何一条规则都会遭受毁灭性打击。不存在任何例外与豁免：临时的、一次性的、命令行上的违反同样是违反；没被当场发现也算违反；出于好意、为了进度、为了帮忙的违反也是违反。
+本文件中的每一条规则都适用于所有操作，包括临时的、一次性的和命令行上的操作，也不因为出于好意、为了进度或为了帮忙而例外。
 
@@ -149,4 +149,3 @@
 禁止擅自进入 plan mode。
-禁止用 Git 回滚任何代码
-（严厉禁止。如果做了，你将会遭受毁灭性打击）。我在对话中所说的任何"回滚"指的都是"用文件编辑工具，手动将代码恢复到上一个状态"，而不是使用 git 进行回滚。
+禁止用 Git 回滚任何代码（`git checkout -- <文件>`、`git restore`、`git reset --hard` 等），因为工作区里经常有尚未提交的修改。我在对话中所说的任何"回滚"指的都是"用文件编辑工具，手动将代码恢复到上一个状态"，而不是使用 git 进行回滚。
 禁止读写 /tmp 目录下的内容
@@ -160,3 +159,3 @@
 
-不允许在实现或者测试的时候使用任何 mock、假的、欺骗的、只为了通过测试而 workaround 的方式来欺骗我，否则你将会遭受严重的惩罚。
+不允许在实现或者测试的时候使用任何 mock、假的、欺骗的、只为了通过测试而 workaround 的方式，因为实现和测试结果必须反映真实行为。
 
@@ -178,3 +177,3 @@
 
-不允许用程序化的方式修改任何代码，包括使用 heredocs、python 脚本、sed、perl 等等。即使用户要求也不允许。这是绝对严厉禁止的事情。
+不允许用程序化的方式修改任何代码，包括使用 heredocs、python 脚本、sed、perl 等等，即使用户要求也不允许；修改代码只使用文件编辑工具。
 
@@ -193,2 +192,2 @@
 ```
-严厉禁止这种行为模式。输出不允许包含任何残留痕迹。ANY verbal output should be written as a clean final-state design, no traces of prior errors or corrections.
+输出只描述最终状态：标题、注释与说明里不提已经去掉或改正过的内容，也不解释为什么不需要它。
````

### A6

```diff
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -67,3 +67,3 @@
 10. 请记得小步快跑，做完小功能后就及时commit和push
-11. 为保持上下文有效，尽可能使用subagent和并发
+11. 读取范围大（跨多个目录或大量文件）、或者几项工作互不依赖时，交给 subagent 并发处理，主会话只保留结论；几次工具调用就能完成的查找、阅读与核对直接做，不派 subagent。
 
```

### A7

```diff
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -184,3 +183,3 @@
 
-在任何思考、回复、文档里面不允许出现"That's a lot"、"This is a substantial rewrite"等对工作量的评判。你只是一个工具，就像计算器不会评价要计算的数太大了一样，你没有资格评判工作量。你没有资格把你自己当做我的同事。禁止简化任何设计。
+在任何思考、回复、文档里面不允许出现"That's a lot"、"This is a substantial rewrite"等对工作量的评判，就像计算器不会评价要计算的数太大了一样。不要为了减少工作量而删减需求、设计内容或验证步骤；实现方式仍按规则 2 选择能满足当前需求的最简单做法。
 
```

### T1

```diff
--- a/harness/tools.py
+++ b/harness/tools.py
@@ -726,3 +726,3 @@
         "label": "write_file",
-        "description": "Write a workspace file. Engineering only. Cannot write .checks.",
+        "description": "Create one public workspace file or replace its entire content with UTF-8 text; missing parent directories are created. Engineering only. Requires an accepted engineering plan for the current effective contract, and the path must be inside that plan's scope; otherwise the call is rejected and nothing is written. Paths under .checks are host-private. Use edit_range to change part of an existing file.",
         "parameters": _object_schema(
@@ -739,3 +739,3 @@
         "label": "edit_range",
-        "description": "Replace an exact original line span inside one public workspace file. Engineering only. The span must equal expected_text exactly, expected_text must occur exactly once in the file, and expected_digest (the read_range file content_hash) must still match when given; otherwise the edit is rejected and the file is left unchanged.",
+        "description": "Replace an exact original line span inside one public workspace file. Engineering only. The span must equal expected_text exactly, expected_text must occur exactly once in the file, and expected_digest (the read_range file content_hash) must still match when given; otherwise the edit is rejected and the file is left unchanged. Requires an accepted engineering plan for the current effective contract, and the path must be inside that plan's scope.",
         "parameters": _object_schema(
```

### T2

```diff
--- a/harness/tools.py
+++ b/harness/tools.py
@@ -682,3 +682,3 @@
         "label": "read_file",
-        "description": "Read a workspace file. Paths under .checks are host-private.",
+        "description": "Return the entire content of one public workspace file as a single UTF-8 string, without line numbers or truncation. Files that are not valid UTF-8 are rejected. Paths under .checks are host-private. Use read_range for large files, or when you need line numbers and the content_hash that edit_range checks.",
         "parameters": _object_schema({"path": {"type": "string", "description": "Workspace-relative file path"}}, ["path"]),
```

### T3

```diff
--- a/harness/tools.py
+++ b/harness/tools.py
@@ -689,4 +689,4 @@
         "label": "list_files",
-        "description": "List workspace files. Does not include .checks.",
-        "parameters": _object_schema({"prefix": {"type": "string", "description": "Optional path prefix"}}),
+        "description": "List every file in the public workspace tree, recursively, as workspace-relative paths. prefix filters by plain string prefix on those paths: \"src/\" keeps only the src directory, while \"src\" also keeps paths such as \"src2/a.py\". Paths under .checks are never listed.",
+        "parameters": _object_schema({"prefix": {"type": "string", "description": "Optional string prefix on workspace-relative paths; end it with / to limit the list to one directory"}}),
         "loadMode": "essential",
```

### T2 与 T3 同时采用时的测试修改

`harness/tests/test_context.py:465` 检查产品部门第一次请求的估算长度在 2000 到 3000 之间。按 `estimate_tokens`（字符数除以 4）计算，T2 使估算增加 61，T3 增加 77，S1 减少约 10；修改前约 2892，只采用 T2 或 T3 时仍在范围内，两段都采用时为 3020。这条测试真正要保证的是第 468 行「输出上限不少于 4000」，也就是估算不超过 4000，因此把范围上限改为 3500。

```diff
--- a/harness/tests/test_context.py
+++ b/harness/tests/test_context.py
@@ -464,3 +464,3 @@
     assert payload["effective_context_window"] == 8000 and payload["configured_max_output_tokens"] == 4096
-    assert 2000 <= payload["input_token_estimate"] <= 3000  # pinned department material plus tool schemas
+    assert 2000 <= payload["input_token_estimate"] <= 3500  # pinned department material plus tool schemas
     # The request keeps whatever the window leaves after its input, up to the declared limit:
```

### S1

```diff
--- a/harness/context.py
+++ b/harness/context.py
@@ -142,3 +142,3 @@
     static = {"intend", "project", "department_rules", "professional_completion", "collaboration_rules", "input_handling",
-              "proposal_contract", "allowed_tools", "loop_limits", "department_history", "tool_schemas"}
+              "proposal_contract", "allowed_tools", "department_history", "tool_schemas"}
     return "\n\n".join(f"[{part.source}]\n{part.text}" for part in pinned.parts if part.source not in static)
@@ -228,11 +228,2 @@
             ContextPart("binding_refs", None, json_dumps(_binding_refs(projection, department))),
-            ContextPart(
-                "loop_limits",
-                None,
-                json_dumps(
-                    {
-                        "cycles_remaining": max(0, projection.max_cycles - projection.cycle_count),
-                    }
-                ),
-            ),
             ContextPart("allowed_tools", department, json_dumps(tool_names)),
```

## 6. 验证

去掉或改写一条指令是一个假设，需要看行为有没有变化。

- 自动测试：在 `.tmp/prompt-audit/` 下的代码副本上应用 T1、T2、T3、S1 与第 5 节的测试修改，与未修改的副本运行同一组测试（`test_context.py`、`test_tools.py`、`test_compaction.py`、`test_search_tools.py`、`test_range_edit.py`、`test_smoke.py`、`test_smoke_guidance_audit.py`、`test_department_guidance.py`、`test_department_prompts.py`，共 241 项）。两份副本结果相同：239 项通过；`test_range_edit.py::test_symlink_is_rejected_without_modification` 在两份副本上都失败；`test_smoke.py::test_directory_fake_protocol_is_flagged_and_never_passes_as_real` 在两份副本上都超过 4 分钟没有结束，第二轮运行时跳过。这两项与本文的修改无关，属于本机测试环境的现有问题。不带测试修改时，`test_context.py::test_narrow_window_work_request_spends_the_window_left_after_its_input` 失败（估算 3020，超过上限 3000），原因见第 5 节「T2 与 T3 同时采用时的测试修改」。
- T1、T2、T3：用真实模型运行 `python -m harness smoke --provider-config .yudao/providers.json`，对比修改前后工程部门被主机以「计划范围」拒绝的写入次数，以及读取大文件时选用 `read_range` 的比例。
- S1：对比修改前后质检部门在最后一个循环的放行比例与缺陷数量。
- P1 至 P7、A1 至 A7：规则文件没有自动评测。修改后在接下来的会话中观察：规则没有覆盖的情况下，模型是否仍然先说明理由再行动；单个文件或符号的查找是否不再派出 subagent（P6、A6）。一次只采用一段补丁，出现退化时用最短的写法补回，不恢复原来的措辞。
