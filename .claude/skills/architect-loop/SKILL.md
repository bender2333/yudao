---
name: architect-loop
description: 架构师循环：一个单独的、可重复运行的状态转换。从 GitHub 读状态，对四种工单（子工单全关的父工单、needs-triage、到期的 waiting、等总架构师的 ready-for-human）各往前推一步：脚本放回到期的、核对证据，检查模型取证写证据包，架构师模型只做判断。定时唤醒与用户在场时的 /next 都按它做。
argument-hint: "[--dry-run]"
---

# 架构师循环

流程的正本是[工作方式](../../../docs/agents/workflow.md)第 4、5、9 节；验收与分诊的判断标准在 [`/verify`](../verify/SKILL.md) 与 [`/triage`](../triage/SKILL.md)，到期放回的规矩在本文「放回到期的 waiting」。这个技能不依赖 solo，也不是 `/next` 的一种用法：它只认下面四种输入状态，各推一步。AI 是无状态的，状态全在 GitHub，每次都从 GitHub 读，重跑不出错。

## 何时用 / 何时不用

- 用：定时唤醒（桌面应用的定时任务）；用户在场时 `/next` 走到下面四种状态之一。
- 不用：改意图、总图、规则文件、技能、CI；关闭试用工单与里程碑；写新的设计说明；拆还没拆的父工单；处理 Discussions 的想法。碰到这些开 `architecture` 工单，或标 `ready-for-human`，写清要谁定什么。
- 例外（属于转换本身，可以做）：`/verify` 第 6 步把自定的边界写进已有的设计说明；`/triage` 表里「设计没写到」那一行补设计说明。推送 main，记入 `docs/CHANGELOG.md`。

## 先读什么

[工作方式](../../../docs/agents/workflow.md)第 4、5、9 节；[运行配置](../../../docs/agents/autopilot-runtime.md)第 3、4 节（提交署名、取证层与判断层各用哪一档模型）；然后按手头这一层读：取证读本文「取证」，判断读 `/verify` 或 `/triage`。

## 转换表

| 输入状态 | 转换 | 输出 |
| --- | --- | --- |
| 父工单（`parent`）的原生子工单全部关闭，标题不含「工作线跟踪」，至少有一张子工单，并且最近一张子工单关闭以后没有 `VERDICT:` 评论 | 取证 → 判断（按 `/verify`） | 关闭父工单；或保持打开并补缺口子工单 |
| `needs-triage` | 取证（交回评论里每条前提在当前 main 上还成不成立）→ 判断（按 `/triage`） | `ready-for-agent`、`waiting`（带 `WAITING: 日期`）或 `ready-for-human` |
| `waiting` 到期：不带 `parent`/`stage`/`trial`，最后一条 `WAITING:` 评论第一行的日期不晚于今天 | 脚本直接放回，不用模型；来回满两次的交给用户 | `ready-for-agent`（或 `ready-for-human`） |
| `ready-for-human`，它的 `TRIAGE:` 评论点名的 `architecture` 工单已关闭，且那以后没有新的 `TRIAGE:` | 取证（读 architecture 工单的结论，核对前提）→ 判断（按 `/triage`「交给用户的工单」） | 同分诊 |

### 放回到期的 waiting

只做机械的一步，不替分诊判断，由脚本做：

1. 只认最后一条 `WAITING:` 评论，并且它的第一行是 `WAITING: 日期 YYYY-MM-DD`；放回时写的不带日期的那条不算。日期晚于今天（本机时间）的不动。
2. 等的条件改了（继续等别的东西、日期改了），写一条新的 `WAITING:` 评论写清现在等什么、等到哪天；脚本只看最后一条，不读别的评论猜条件。等别的工单的用原生依赖，不写日期。父工单、阶段工单、试用工单不放回。
3. 放回：去 `waiting` 加 `ready-for-agent`，留一条评论，第一行 `WAITING: 已放回`，写日期已到、到期以后第一件要核对的事见上一条 `WAITING:` 评论，末行署名 `— 架构师循环（脚本）`。
4. 同一张工单已经有两条 `WAITING: 已放回`，不再放回，改 `ready-for-human`，写 `TRIAGE: 交给用户`，按[工作方式](../../../docs/agents/workflow.md)第 7 节「同一张工单分诊满两次」交给用户。

完成：到期的都放回了，每张有一条 `WAITING: 已放回` 评论；交给用户的每张有一条 `TRIAGE: 交给用户`。

## 三层

1. **脚本层**（不花 token）：扫状态、放回到期工单、核对证据包、唤醒入口。顺手报两类提醒，只报不改：`ready-for-agent` 的工单不在范围里的任何里程碑里；打开的工单被范围以外的工单挡着。
2. **取证层**（检查模型，便宜的一档，按运行配置）：为每一件要判断的事写一条证据包评论。不下结论，不改标签，不关工单。
3. **判断层**（架构师模型，贵的一档，按运行配置）：一次只判一件，全新上下文，只读这张工单的正文与评论、它的证据包与脚本核对结果、依据指到的设计说明的「验收」一节；按 `/verify` 或 `/triage` 写 `VERDICT:` 或 `TRIAGE:`，改状态，需要时按 [`/to-children`](../to-children/SKILL.md) 的模板补缺口子工单。只信脚本核对为 ok 的证据行；「对不上」与「未核对」的一律当没找到。

## 脚本（`scripts/`，只用 node 标准库）

| 脚本 | 做什么 |
| --- | --- |
| `scan.mjs --milestone <标题或编号>` | 读范围内的打开工单，输出 JSON：`due`、`handToUser`、`verify`、`triage`、`unblocked`、`warnings`；拉不全就报错退出 |
| `release.mjs [--dry-run]` | 按 `due` 放回（去 `waiting` 加 `ready-for-agent`，评论第一行 `WAITING: 已放回`），按 `handToUser` 改 `ready-for-human` 并写 `TRIAGE: 交给用户` |
| `check-evidence.mjs <工单号>` | 核对最后一条 `EVIDENCE:` 评论，逐行输出 ok / 对不上 / 未核对，并判过期 |
| `wake.mjs` | 唤醒入口，见下「唤醒与运行」 |

测试：`node --test ".claude/skills/architect-loop/scripts/test/*.test.mjs"`。

配置在运行它的 worktree 的 `.ralph/architect/config.json`（`.ralph/` 被 git 忽略），格式见 `config.example.json`：`enabled`、`worktree`、`scope.milestones`、`lockMinutes`。模型不在配置里，调用方按运行配置选。

## 唤醒与运行

**定时唤醒**：桌面应用的定时任务每次醒来是一个会话，用便宜的默认模型，这个会话就是取证层（检查模型）。它按下面的步骤做，不下结论、不改状态标签、不关工单；这些只由架构师子代理做。

1. 在架构师循环的 worktree 里跑 `node .claude/skills/architect-loop/scripts/wake.mjs`。配置没有或 `enabled` 为假：脚本只写心跳，结束。有活锁：脚本打印一句，结束。完成：脚本打印摘要，写好 `.ralph/architect/next.json`；没有要做的事时脚本已自己写心跳并解锁，结束。
2. 读 `next.json`。`evidence` 里的每一件，按下面「取证」自己写证据包评论（件数多时可以派同一档模型的子代理并行，默认自己做）。完成：每一件有一条 `EVIDENCE:` 评论。
3. 对这些件跑 `check-evidence.mjs <号>`，再跑 `wake.mjs --pick` 重新挑。完成：`next.json` 的 `judge` 是证据有效里按 triage、unblocked、verify 先后、编号小的先挑出的一件，或为空。
4. `judge` 有一件：派一个子代理当架构师会话，模型用运行配置里判断层的那一档。任务书：工单号、核对结果（`check-evidence.mjs <号> --json` 的输出文件路径）、「按本技能『判断』做这一件，做完结束」、署名与提交作者（运行配置第 3 节架构师循环的写法，`claude-架构师`）。子代理收尾写 `STATUS / SUMMARY / FILES / NEXT` 四行。一轮只判一件。
5. 跑 `wake.mjs --finish [--judged <号> --result <一句话>] [--evidenced <号,号>]`：写心跳与日志 `.ralph/architect/runs/<时间>.log`，解锁。会话中途崩了，锁按 `lockMinutes` 过期。

**用户在场时 `/next`**：走到这几种状态时，用户的会话就是架构师。按同样的步骤跑 `wake.mjs`，取证派一个便宜模型的子代理做（模型按运行配置里取证层那一档），判断自己做，不再派子代理。

`--dry-run`：`wake.mjs --dry-run` 不改 GitHub、不切 worktree、不写锁，只打印会放回、取证、判断哪些。

## 取证

对 `next.json` 的 `evidence` 里的每一件：

1. **读**：工单正文、最近的评论、「依据」指到的设计说明。验收取父工单的验收标准逐条编号；父工单与设计说明「验收」不一致时以设计说明为准并写明。分诊取交回评论（`ARCHITECT:`）里的每条前提；解挡取 architecture 工单的结论。完成：每条标准或前提有编号。
2. **在当前 main 上找**：`git fetch origin`，用 `origin/main` 的提交；用例在 main 的文件里存在，提交在 main 上，CI 取 main 上这个提交的运行（`gh run list --workflow CI --branch main --event push`）。本地跑过的命令写出结果。完成：每条后面有证据行，找不到的写 `none:` 与没找到什么。
3. **写证据包评论**，第一行 `EVIDENCE: <验收 | 分诊> @ <main 短提交>`。重做的在这一行末尾加「（重做）」。完成：评论发出，跑 `check-evidence.mjs` 看每行 ok / 对不上。
4. 落款：`— 架构师循环（取证，<模型>）`。

验收的证据包：

```
EVIDENCE: 验收 @ <短提交>
CI: <main 上这个提交的 CI 运行号>
1. <标准原文>
   - test: <文件路径>::<用例名>（<层>）
   - commit: <短提交>
   - local: <命令>（本地跑过：passed/failed）
   - none: <没找到什么>
2. ...
```

分诊的证据包：交回评论里的每条前提一行，下面跟证据行：

```
EVIDENCE: 分诊 @ <短提交>
- 前提：<原文> → 还成立 | 已经变了
  - test: <文件路径>::<用例名>（<层>）
  - commit: <短提交>
  - local: <命令>（本地跑过：passed/failed）
  - none: <没找到什么>
```

取证模型是便宜的一档，写错或编造的证据行由脚本核对挡住：格式不对的行、不存在的文件或用例名、不在 main 上的提交、没有一行核对过证据却写「还成立」的前提，都标「对不上」。脚本核对：头部提交是 `origin/main` 的祖先；`test:` 的文件在那个提交上存在、文件里有这个用例名；`commit:` 存在且在 `origin/main` 上；用例名要整词出现在文件里；`CI:` 的运行结论是 success、它的提交是头部提交或其祖先；`local:` 与 `none:` 标「未核对」。

## 判断

只对 `judge` 指定的一件做：

1. 读这张工单的正文与评论、证据包与 `check-evidence.mjs` 的结果、设计说明的「验收」一节。「对不上」与「未核对」的证据行当没找到，不当证据。
2. 验收：按 `/verify`；全过关闭父工单，否则补缺口子工单。分诊与解挡：按 `/triage`，去向是 `ready-for-agent`、`waiting`（评论第一行 `WAITING: 日期`）或 `ready-for-human`。验收不放松；同一张工单分诊满两次，第三次交给用户（`/triage`）。
3. 写 `VERDICT:` 或 `TRIAGE:` 评论，改标签。落款：`— 架构师循环（判断，<模型>）`。提交署名 `claude-架构师`。
4. 做了设计说明或边界的改动：推送 main，记入 `docs/CHANGELOG.md`。

完成：评论、标签与（需要时）缺口子工单都在 GitHub 上。

## 重跑的规矩

- 证据包的提交早于最近一张子工单关闭时的那次 main，或脚本核对不过（头部提交不在 main、CI 缺或不是 success、过期、没有条目）：取证重做。
- 有对不上的行：重做一次，重做的包第一行带「（重做）」；重做后仍对不上的行，判断层当没找到，不再重做。
- 证据包之后已经有 `VERDICT:` 或 `TRIAGE:`：跳过。
- `needs-triage` 的工单最近一条交回类评论已经是 `TRIAGE:`：标签没改过来，脚本报成提醒，不再取证，交给人看。
- 放回满两次的 waiting 工单：脚本交给用户，不再放回。

## 常见借口

| 借口 | 为什么不行 |
| --- | --- |
| 「子工单都关了，就是过了」 | 子工单关闭说明有人交付了，不说明父工单的标准成立 |
| 「CI 是绿的」 | CI 跑的是已有的测试，未必覆盖这一条标准；每条标准各自要证据 |
| 「交付说明里写了做到了」 | 交付说明是执行者的话；证据要在 main 上能重新找到 |
| 「这一项上一轮看过，结论还记得」 | 每次从 GitHub 重读；交回评论写的是那一刻，main 可能已经变了 |
| 「交回评论说了怎么改，照着改就行」 | 评论写的是那一刻；先在当时的 main 上核对前提 |
| 「先放回去让 solo 再试一次」 | 不改正文、不补设计就放回，下一轮还会卡在同一处 |
| 「取证时顺手把结论也写了」 | 取证不下结论；判断是另一层、另一个上下文 |
| 「这条说不清，先算过」 | 说不清不算过，补成缺口工单 |

## 危险信号

- 取证评论里有「过了」「没过」「建议放行」这类结论。
- 每条的证据都是同一个 CI 运行链接。
- 验收标准被改写得比设计说明的「验收」松。
- 同一张工单在 `needs-triage`（或 `waiting`）与 `ready-for-agent` 之间来回超过两次。
- 锁一直在、心跳不更新。
- 工单状态变了，却没有对应的证据评论。

## 交付

每次运行：脚本摘要（放回了哪些、取证了哪些、判了哪件与结果、提醒）、心跳 `.ralph/architect/heartbeat.json`；每一件判断在工单上有一条 `EVIDENCE:` 与一条 `VERDICT:` 或 `TRIAGE:`，状态标签已改。
