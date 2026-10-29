---
name: flow
description: 架构师会话开始的三项检查（架构问题、豁免记录、达到检查），以及需求从讨论到交付的七步。
---

# 架构师的流程

## 会话开始

开始其他事情之前做完这三项。

1. 架构问题：执行者把执行中遇到的设计冲突与缺漏登记在 `docs/architecture-issues.md`。查看其中未处理的条目，处理结论写入对应设计文档或 ADR，并在该条下追加一行 `处理：<结论与文档位置>`；带处理行的条目定期移到 `docs/archive/` 下的已处理记录。
2. 豁免检查：查一次 main 规则的豁免记录（命令见[运行配置](../../../docs/agents/autopilot-runtime.md)第 6 节）。架构师自己直接推送文档与日记属于豁免，不用报告；有经豁免合并的 PR 时，记入 `claude_jour.md` 并告诉用户。
3. 达到检查：读打开的阶段里程碑对应的阶段工单（置顶）里的薄片清单，用 `gh issue list --milestone "<标题>" --state open --json number,title,labels` 对照。
   - 某个薄片只剩试用工单和子工单已全部关闭的父工单时，先按第 6 步核对并关闭这些父工单，再按第 7 步办理。
   - 试用工单上已有用户确认评论的，按[验收证据规则](../../../docs/agents/acceptance-evidence.md)第 5 节补写关闭评论，再关闭试用工单（最后一个薄片连同里程碑）。
   - 用户不在场时这几件事由[架构师循环](../architect-loop/SKILL.md)做，做到「导游卡」为止；用户在场的会话开始时先看试用工单上循环留下的评论，把停在用户这一步的地方接上。

完成：三项各有结论，没有要处理的写「无」。

## 七步

需求从讨论到交付经过以下步骤。工单相关的技能来自 Matt Pocock 技能集，多数只能由用户输入命令调用，架构师在合适的时机提醒用户调用哪一个。

1. 讨论：`/grill-with-docs` 逐项追问需求与边界，同时更新 `CONTEXT.md`，需要时新增 ADR。需要查证的问题用 `/research`，需要看到效果才能判断的界面或逻辑问题用 `/prototype`。原型定稿时，修改 `docs/prototypes/CHANGELOG.md` 开头的「当前定稿」一行，并把开放的工单中引用旧版本代码的路径改为新版本。
2. 设计：先在总图里找到位置（哪一节、哪个方框或哪道缝），写在设计说明开头一行（总图位置与依据）；总图里没有位置的，先与总架构师定。然后按[设计说明规范](../../../docs/agents/design-spec.md)在 `docs/design/` 编写设计文档，并在新增时更新 `docs/design/README.md` 索引；有成熟做法可以参照时，先查阅 OMP 与 OpenCode 的实现（见共同规则「参考实现」）。
3. 父工单：`/to-parents`（[skill](../to-parents/SKILL.md)，代替 Matt 的 `/to-spec`）把一个里程碑、一个阶段、一个模块或一段讨论按总图的缝与路线图的道归桶，给相关旧工单定去向（关闭、归并、推迟），每个桶发一张父工单。
4. 子工单：`/to-children <父工单>`（[skill](../to-children/SKILL.md)，代替 Matt 的 `/to-tickets`）改写归并进来的旧工单，把父工单拆成可以独立验证的立缝与切片，写明阻塞关系与标签。
5. 执行：执行者按 `AGENTS.md` 领取子工单，实现、自测、推送并开 PR，CI 通过以后交付；审查者在 PR 上批准或要求修改，GitHub 在 main 的规则满足时合并。
6. 验收：子工单全部关闭后，架构师核对父工单的验收标准，关闭父工单；需求索引（`docs/requirements/README.md`）与设计索引（`docs/design/README.md`）只在新增或改名时改，不记状态。
   - 一个薄片的工单全部关闭时，把总图缝的已定、未定有哪些变化告诉总架构师，由总架构师改；接着按第 7 步办理。
   - 一个阶段的里程碑关闭时，总架构师按路线图第 2 节该阶段的「结束时总图」与第 5 节那张表逐列核对 main，核对做法与记录见[验收证据规则](../../../docs/agents/acceptance-evidence.md)第 6 节，不过的格补成缺口工单，过了总架构师再改缝的已定、未定；过门（可迭代状态的五条判据）在阶段二结束时按这些读数核对。
7. 试用：一个阶段一个里程碑（GitHub Milestone），阶段里每个薄片一张试用工单（[工单规范](../../../docs/agents/ticket-spec.md)），在薄片达到之前标 `waiting`。
   - 薄片达到以后，先用 `/milestone-retro <里程碑标题与薄片>` 复盘（[复盘 skill](../milestone-retro/SKILL.md)），报告发在 GitHub Discussions 的 Announcements 分类；提出的改动中，参数与规则句子的修改先经用户确认。
   - 接着跑一次 agent 试用（[`/trial`](../trial/SKILL.md)）：另一个模型按真实用户的路子用一个从 main 打包的实例，只读、不建工单，帖子发在 General；明确缺陷按 [`/trial-intake`](../trial-intake/SKILL.md) 的 A 类建成工单，由 solo 修完，这一道筛子把机器能发现的问题挡在用户的时间之前。
   - 然后架构师发布版本并按试用指南走查，再把试用工单改为 `ready-for-human` 交给用户；步骤见 `docs/design/web-interface-and-release.md` 第 6.4 至 6.6 节。
   - 用户试用并确认以后，架构师按[验收证据规则](../../../docs/agents/acceptance-evidence.md)第 5 节在试用工单写关闭评论，再关闭试用工单，最后一个薄片的试用工单关闭时一起关闭里程碑；用户不在场时它们保持打开，被唤醒的架构师、派发者与 solo 执行者不关闭它们。
   - 用户不在场时，复盘、agent 试用、缺陷工单、发布与走查由[架构师循环](../architect-loop/SKILL.md)做完，导游卡写在试用工单上；「试用通过」仍只由用户给。
   - 试用期间继续推进下一个薄片，不等试用结论。

第 1 至 4 步在同一个上下文窗口中完成，`/to-children` 完成之前不清空、不压缩上下文。

其他入口：外部报告的问题用 `/triage` 分诊；方向尚不清楚、一次会话处理不完的大工作用 `/wayfinder`；难以定位的缺陷用 `/diagnosing-bugs`。
