---
name: next
description: 子架构师在用户在场时的入口：从 GitHub 读整个项目的状态，按固定顺序找到第一件能做的事（等用户的事、交接点、达到的薄片、设计未写的桶、等拆的父工单、Discussions 的想法），把对应技能的步骤抄进待办做完，留下证据评论，一次做一件、先出一张等用户的卡。交接点（到期的 waiting、needs-triage、解除阻塞的 ready-for-human、子工单全关的父工单）按架构师循环技能做。接手一条工作线、一个模块或一个里程碑时用；总架构师讨论总图、规则与理念时不用。
argument-hint: "[范围：里程碑名 | 里程碑编号 | 标签 | 全部]"
---

# 下一件事

流程的正本是[工作方式](../../../docs/agents/workflow.md)。这个技能只管三件事：读状态、挑下一件、把它交给对应的技能做完。每一件做完都留下证据：工单上的评论，没有工单的设计与原型靠提交与变更记录；下一次读得到，不靠上下文传递。

## 何时用 / 何时不用

- 用：用户在场时，子架构师接手一条工作线、一个模块或一个里程碑。
- 不用：总架构师讨论总图、规则与理念；solo 执行者做工单（那是 `/solo`）；用户不在场时处理交接点（那是 [`/architect-loop`](../architect-loop/SKILL.md)）。

## 权限

权限表见[工作方式](../../../docs/agents/workflow.md)第 9 节，谁改什么见第 1 节。`/next` 只在用户在场时用，子架构师与用户在同一个会话里。

- 意图（目的、判据、基础规则的意思，判据含评价标准：评测的隐藏检查、参考解法、评分器、发布检查）与总图由用户定，总架构师改。要定的开一张 `architecture` 工单写清，相关工单标 `ready-for-human`。
- 设计说明、ADR、需求记录（不改用户已确认的需求与验收标准）、`CONTEXT.md`、原型，以及工单正文、子工单、依赖、评论，都直接改、直接推送 main，每处写进 `docs/CHANGELOG.md`、`docs/decision.md` 与 `claude_jour.md`。
- 阶段工单与里程碑（建、关、改名）只由总架构师改。拆出的子工单沿用原工单的里程碑。
- 试用工单与里程碑由用户确认后关闭，做法见[验收证据规则](../../../docs/agents/acceptance-evidence.md)「试用工单与里程碑的关闭」。
- 架构师不改 `harness/` 的代码与测试，要改的拆成工单。

仓库是公开的，只采信用户、执行者与架构师的评论。

**验收不放松。** 验收标准可以拆到别的工单，也可以换成能得出同一结论的判据，不能删、不能放松；需要放松的写清要用户定什么，标 `ready-for-human`。

**改设计时的冻结。** 里程碑开始执行以后（里面有工单因交付关闭、带 `in-progress` 或 `needs-review`、或有负责人），它的工单依据的设计说明只做一致性修正：让设计说明与总图、ADR、决策记录和用户确认过的内容一致，影响到已放出的工单时同时更新它们的「依据」与任务评论。要改设计本身，先把受影响的工单改回 `needs-triage`，改完、更新「依据」以后放回。新想法注明生效的里程碑。

## 先读什么

[工作方式](../../../docs/agents/workflow.md)第 4 至 7 节；`CLAUDE.md`「子架构师」。其余由挑中的那件事的技能决定。

## 每次开始

1. **豁免记录**：按[运行配置](../../../docs/agents/autopilot-runtime.md)「main 的规则」的命令查一周内的豁免。PR 正文有 `Solo:` 行的是 solo 的合并，记入 `claude_jour.md`；没有对应 PR 的是架构师直接推送的文档与日记；其余告诉用户。完成：豁免各有归属。
2. **main 的 CI**：`gh run list --workflow CI --branch main --event push --limit 5`。`check` 红了，先查是不是架构师推的提交，是就先修；是 solo 的合并，由 solo 按 `solo-worker`「main 上的 CI」处理。完成：知道 main 现在是不是绿的。
3. **记录归档**：`node .claude/skills/next/scripts/rotate-records.mjs`。有移动时改动已经暂存好，提交并 `git push origin HEAD:main`，不用另写变更记录与日记。完成：日记、决策记录与变更记录都没有超过上限。

## 找下一件事

按顺序找第一件，范围条件写在查询里。

| 先后 | 哪一件 | 怎么认 | 交给 |
| --- | --- | --- | --- |
| 1 | 等用户的事（只在用户在场时） | `ready-for-human`；`architecture`；试用工单最后一条是 `TRIAL: 导游卡` | 先出一张不超过 10 行的卡：每条一句话，写要用户定什么、建议、不定会怎样；`architecture` 的列出来交总架构师 |
| 2 | 交接点 | 到期的 `waiting`；`needs-triage`；`ready-for-human` 且没有架构师的 `TRIAGE:` 评论、或 `TRIAGE:` 评论写的 `architecture` 工单已关闭；`parent` 且子工单全部关闭、自己还开着 | [`/architect-loop`](../architect-loop/SKILL.md)，按它的转换做这一件 |
| 3 | 薄片推进 | 薄片里除试用工单以外都已关闭、没有「设计未写」的行，试用工单还有下一步 | [`/trial-intake`](../trial-intake/SKILL.md)「薄片推进」 |
| 4 | 设计未写的桶 | 阶段工单的薄片清单里写着「设计未写」的行 | [`/to-design`](../to-design/SKILL.md) |
| 5 | 还没拆的父工单 | `parent`，没有子工单 | [`/to-children`](../to-children/SKILL.md) |
| 6 | 等分诊的想法 | Discussions 的 Ideas 里没有处理结果回复的帖子 | [`/triage`](../triage/SKILL.md)「想法与外部报告」 |

```bash
gh issue list --state open --limit 300 --json number,title,labels,milestone \
  --jq '.[] | "\(.number)\t\(.milestone.title // "-")\t\([.labels[].name]|join(","))\t\(.title)"'
gh api graphql -f query='query { repository(owner:"bender2333", name:"yudao") { issue(number:<编号>) { state subIssuesSummary { total completed } } } }'
gh issue view <编号> --json comments --jq '.comments[-5:][] | "\(.author.login)\t\(.body[0:80])"'
```

都没有：告诉用户范围内没有要做的。

交接点的做法（含放回到期的 `waiting` 工单）在 [`/architect-loop`](../architect-loop/SKILL.md)，这里不重复。用户在场时，用户的会话是架构师：取证派取证层模型（运行配置第 7 节「取证层的模型」，当前 `claude-haiku-5-5`）的子代理，判断自己做。

## 做一件事

1. 打开挑中的技能，把它的步骤原样抄进待办；决定不做的步骤留在待办里，写一行「skip：原因」。
2. 按技能做。自己做。
3. 收结论：证据评论在工单上（`TRIAGE:`、`VERDICT:`、`TRIAL:`），状态标签改好；没有工单的设计与原型，提交与变更记录就是证据。同类还有别的，下一次接着做。

## 长运行

长运行（agent 试用、场景 3）用 `Start-Process` 起独立进程，不放在会话的后台命令里：会话空闲或内存不足时会连它一起结束。提示词写进文件，用 `Get-Content -Raw` 传；直接塞进 `-ArgumentList` 的长中文提示词会被截断。

- 起之前把进程号、开始时间、预算与日志路径告诉用户，也写进对应工单的评论。
- 超时看「预算加一小时」（运行配置「参数」）。超时先看进程在不在：在就再等，不在按失败处理，重跑一次，再失败交给用户，附运行记录的位置。
- 判「还活着」看三样：进程在；累计 CPU 在涨；它该写的地方有新写入（数据目录的 `events.sqlite-wal`、浏览器的启动批次、日志最后一行）。一次长模型回合可以二十分钟没有新文件，只有 CPU 在涨。

## 交给用户

只在这几种时候：试用工单的导游卡写好；薄片修缺陷到第三轮；长运行两次失败；同一张工单分诊满两次；要改规则、放宽验收或执行环境挡住。都做同样的事：工单上写清要用户定什么（一句话一条，带建议与不定的后果），标 `ready-for-human`，当场告诉用户；要改规则的开 `architecture` 工单。

## 常见借口

| 借口 | 为什么不行 |
| --- | --- |
| 「这一项上一轮看过，结论还记得」 | 每一轮从 GitHub 重读；交回评论写的是那一刻，main 可能已经变了 |
| 「顺手把下一件也做了」 | 一次一件；做完留下证据再看下一件，证据才对得上 |
| 「意图这里明显不对，先改了」 | 意图与总图由用户定，开 `architecture` 工单 |
| 「这份设计也开张工单记一下」 | 设计与原型不走工单，提交与变更记录就是记录 |

## 危险信号

- 同一张工单在 `needs-triage` 与 `ready-for-agent` 之间来回超过两次。
- 同一张工单在 `waiting` 与 `ready-for-agent` 之间来回超过两次。
- 工单状态变了，却没有对应的证据评论。

## 交付

每做完一件：挑中的是哪一件、交给了哪个技能、留下的证据评论链接、改了的状态标签。
