# 技能使用说明

这个目录是开发 Yudao 仓库用的技能：架构师、solo 执行者与审查者在 Claude Code 里调用它们。流程本身的正本是[工作方式](../../docs/agents/workflow.md)：事实放在哪、工单的状态与证据评论、四个循环、出问题往哪交。这份说明只讲每个技能做什么、什么时候用、怎么调。

## 先记住三件事

1. **不知道该做什么时，用 `/next`。** 它读 GitHub 的状态，找到下一件该做的事，告诉你交给哪个技能。
2. **每做完一段，工单上都有一条证据评论**（`DELIVERY:`、`REVIEW:`、`TRIAGE:`、`VERDICT:`、`TRIAL:` 等）。下一个人读工单就能接上，不用回翻会话。
3. **用户只定三件事**：走向、规则、试用结论。其余由架构师与 solo 按标签流转。

## 谁用哪些

| 你是 | 平时用 |
| --- | --- |
| 用户 | `/module-sync` 与子架构师定模块走向；`/trial-intake 反馈` 交试用反馈；其余交给架构师 |
| 子架构师（用户在场） | `/next` 进来；按它的指引用 `/discuss`、`/to-design`、`/to-parents`、`/to-children`、`/triage`、`/verify`、`/trial-intake` |
| 架构师循环（用户不在场） | `/loop 30m /next <范围> --循环`，一轮做一件 |
| solo 执行者 | `/solo <范围>` 跑循环，每张工单按 `solo-worker` 做 |
| 审查子代理 | `reviewer`，只审改到内核代码的 PR，由 solo 在合并前派出 |
| 总架构师 | 不用 `/next`；需要时用 `/doc-scan`、`/seam-diff` 看文档与代码离总图多远 |

## 从想法到交付

```
想法 ──/discuss──► 结论 ──/to-design──► 设计说明 ──/to-parents──► 父工单 ──/to-children──► 子工单
                                                                                     │
                                                                         /solo（solo-worker）
                                                                    内核 PR 加 reviewer 审查
                                                                                     │
父工单的子工单全部关闭 ──/verify──► VERDICT ──没过──► 缺口子工单 ◄──────────────────────┘
                                         │过了
薄片达到 ──/trial-intake 推进──► 复盘 → agent 试用 → 修缺陷 → 发布 → 走查 → 导游卡 → 用户试用
                                                                                     │
                                       /trial-intake 反馈 ──► 缺陷成子工单 / /module-sync / architecture 工单
交回的工单、solo 转给用户的工单、Discussions 的想法 ──/triage──► 放回、拆小、补设计或交给用户
```

一个模块要定走向时，`/module-sync` 把「体检卡 → 选走向 → 归桶 → 拆子工单」在一次会话里做完。

## 技能一览

「用户调用」一列标「是」的，只能由用户在提示符里输入命令；其余的模型也能自己调用，`/next` 会把事交给它们。

### 入口与架构师的技能

| 技能 | 做什么 | 什么时候用 | 怎么调 | 用户调用 |
| --- | --- | --- | --- | --- |
| [`next`](next/SKILL.md) | 读 GitHub 状态，按固定顺序找下一件事，交给对应的技能；用户不在场时就是架构师循环 | 接手一条工作线、一个模块或一个里程碑；不知道该做什么 | `/next [范围] [--循环]` | 否 |
| [`discuss`](discuss/SKILL.md) | 把想法讨论成结论：先在总图上定位，再追问需求与边界，同时更新术语表与 ADR | 新想法、要先想清楚的问题 | `/discuss [想法或链接]` | 否 |
| [`to-design`](to-design/SKILL.md) | 把结论写成设计说明（第 3 行是总图位置），更新索引；放出等设计的父工单 | 讨论有了结论；父工单写着「设计先写」 | `/to-design [设计说明路径 \| 父工单编号]` | 否 |
| [`to-parents`](to-parents/SKILL.md) | 按缝与道把一个阶段或模块归桶，每桶一张父工单，旧工单定去向 | 一个里程碑、阶段或模块要开工 | `/to-parents [里程碑名 \| 缝或道]` | 是 |
| [`to-children`](to-children/SKILL.md) | 把一张父工单拆成立缝与切片的子工单 | 父工单有了设计说明 | `/to-children <父工单编号>` | 否 |
| [`module-sync`](module-sync/SKILL.md) | 和用户定一个模块的走向：体检卡、选择题，接着归桶与拆单 | 用户要定一个模块、一道缝或一条道往哪走 | `/module-sync <模块 \| 缝 \| 道>` | 是 |
| [`triage`](triage/SKILL.md) | 分诊交回的工单、solo 转给用户的工单、Discussions 的想法与外部报告，结论写 `TRIAGE:` | `needs-triage` 的工单；Ideas 里的帖子 | `/triage <工单编号 \| 帖子链接>` | 否 |
| [`verify`](verify/SKILL.md) | 父工单逐条在 main 上找证据，写 `VERDICT:`，过了关闭，没过补缺口 | 父工单的子工单全部关闭 | `/verify <父工单编号>` | 否 |
| [`trial-intake`](trial-intake/SKILL.md) | 薄片推进到用户手里（每步一条 `TRIAL:`），以及收用户的试用反馈 | 薄片达到；用户试完给了反馈 | `/trial-intake 推进 <试用工单>`；`/trial-intake 反馈 [原话]` | 否 |
| [`ticket`](ticket/SKILL.md) | 按工单规范建或改写任何一张工单 | 建阶段工单、试用工单、清理单，或单独改一张 | `/ticket` | 否 |
| [`milestone-retro`](milestone-retro/SKILL.md) | 复盘：重建经过、核对上一次改动的预期、提出带预期与撤回条件的改动 | 薄片达到以后；流程出了问题要查 | `/milestone-retro [里程碑 \| 工单 \| 起止]` | 否 |

### 执行与审查

| 技能 | 做什么 | 什么时候用 | 怎么调 | 用户调用 |
| --- | --- | --- | --- | --- |
| [`solo`](solo/SKILL.md) | 编排一组工单：每轮一个全新子代理做一张，账本在 `.ralph/<循环>/` | 用户指定 solo 范围 | `/solo <范围> [--并发 N]` | 否 |
| [`solo-worker`](solo-worker/SKILL.md) | 做完一张工单：领取、核对、实现、PR、交付说明、合并前核对、合并 | `solo` 派活时；任何 harness 单独跑一张 | 由 `solo` 派出，或按启动命令运行 | 否 |
| [`reviewer`](reviewer/SKILL.md) | 独立审查改到内核代码的 PR，写 `REVIEW:` | solo 合并内核 PR 之前 | 由 `solo-worker` 第 10 步派出 | 否 |

### 核对、试用与记录

| 技能 | 做什么 | 什么时候用 | 怎么调 | 用户调用 |
| --- | --- | --- | --- | --- |
| [`trial`](trial/SKILL.md) | agent 当真实用户，用从 main 打包的实例跑任务、写试用报告 | `/trial-intake` 推进到「agent 试用」；发布前走查 | `/trial [试用工单号]` | 否 |
| [`seam-diff`](seam-diff/SKILL.md) | 按十三道缝核对代码，出一页差异报告 | 里程碑或阶段结束看缝立住没有 | `/seam-diff [提交号]` | 否 |
| [`doc-scan`](doc-scan/SKILL.md) | 全量扫描文档与总图、路线图、术语表、规则是否一致 | 要一次核对全部活动文档 | `/doc-scan [范围]` | 是 |
| [`discussion-note`](discussion-note/SKILL.md) | 把一段只读工作的结果写成 Discussions 帖子 | 扫描、复现、走查、查证、想法做完 | `/discussion-note <种类> <范围>` | 否 |

### 外部积木

装在用户级的 `~/.claude/skills/`，来自 Matt Pocock 的技能集。上面的技能直接调用它们，不复制进来。

| 积木 | 被谁用 |
| --- | --- |
| `grilling`、`domain-modeling` | `discuss`、`triage` |
| `research`、`prototype` | `discuss` |
| `codebase-design` | `module-sync`、`to-design` |
| `tdd`、`diagnosing-bugs` | `solo-worker` |
| `code-review` | `reviewer` |
| `wayfinder` | 方向看不清、一次会话做不完的大事：开一张决策图，一次解一张票 |

## 常见用法

**接手阶段二。**
```
/next 阶段二
```
先给你一张「等你定的」卡，再挑第一件能做的事。

**有一个新想法。**
```
/discuss 质检要能看懂网页上的报错
```
讨论出结论以后，`/to-design` 写成设计说明，再 `/to-parents`、`/to-children` 拆单。

**开 solo，自己离开。**
```
/solo 阶段二 --并发 3
/loop 30m /next 阶段二 --循环
```
两个会话分开开：solo 做工单，架构师循环接住交回的工单、该验收的父工单和达到的薄片。启动命令与署名的环境变量见[运行配置](../../docs/agents/autopilot-runtime.md)「命令」。

**薄片做完了，要交给用户试用。**
```
/trial-intake 推进 #184
```
用户试完说了问题：
```
/trial-intake 反馈 设置页改了模型以后，项目页还显示旧的
```

**一个模块要定走向。**
```
/module-sync 装配
```

**一张工单被交回来了。**
```
/triage #1423
```

## 写或改一个技能

- 目录名就是技能名，`SKILL.md` 第 2 行 `name:` 与目录名相同。
- 用同一副骨架：何时用与何时不用、先读什么、步骤（每步带「完成：」）、常见借口、危险信号、交付（[工作方式](../../docs/agents/workflow.md)「技能」）。
- 只写一段流转怎么做；流程、标签、权限引用工作方式，不复述。
- 要人在场才能做的（要用户选、要用户批），在 frontmatter 加 `disable-model-invocation: true`；否则不加，`/next` 才能把事交给它。
- 技能是规则文件的一部分：用户在场的会话改，改完记入 `docs/CHANGELOG.md` 与 `claude_jour.md`，新增或删掉技能时同时改这份说明。
- 写法参考用户级的 `writing-for-agents` 技能。
