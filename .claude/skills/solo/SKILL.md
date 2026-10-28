---
name: solo
description: 以 solo 模式把一组工单做完：自己领取、实现、自测、开 PR、发交付说明、自我核对、合并；每一轮都在一个全新的子代理上下文里执行，轮与轮之间只靠 .ralph/<循环>/ 的账本传递。范围与并发都是参数，范围按外部工单每轮重算（工单会进出里程碑，里程碑会改名）；一轮最多并发 N 张，每张一个 worktree，带 `@exclusive` 标记的互斥（`touches-core` 不互斥）。设计问题与连续三轮失败交回后台架构师（needs-triage），执行环境挡住转用户（ready-for-human）。
argument-hint: "[范围：里程碑名 | 里程碑编号 | 标签 | 全部] [--并发 N] [--互斥 N] [--续 <循环名>]"
---

# solo

把一组工单一张一张做完：每一轮用一个全新的子代理上下文执行，轮与轮之间只靠工作区里的账本传递进度。solo 指的是**角色**上的 solo——范围内没有派发者、没有审查者，工单由你自己领取、实现、自测、合并；设计问题仍然有后台架构师裁定，执行环境的问题仍然转给用户。

```
编排者（本会话）                     账本                           工人（每张一个全新上下文）
  读账（state/tasks）  ───────────►  .ralph/<循环>/state.json
  算范围（refresh/sync/next） ─────►  tasks.md
  建 worktree、派活  ─────────────►   <worktreeRoot>/issue-<编号>
  收账（check/finish） ◄────────────────────────────────────  STATUS/SUMMARY/FILES/NEXT
```

## 四个角色

| 谁 | 负责 | 在哪 |
| --- | --- | --- |
| 编排者：就是本会话 | 读账、算范围、挑活、建 worktree、派活、收账、判停 | 主工作区（只读代码，不改） |
| 工人：每次派活一个子代理 | 只做任务书上的那一张工单：领取 → 实现 → 自测 → PR → 交付说明 → 自我核对 → 合并 → 清理 | 自己那张的 worktree |
| 后台架构师 | 设计、需求、范围上的裁定；交回的工单分诊、父工单验收、薄片达到以后的试用准备 | 另一个会话；用户不在场时是[架构师循环](../architect-loop/SKILL.md)，随时在改工单与里程碑 |
| 用户 | 执行环境、规则文件、验收标准 | 工单评论 |

设计问题不自己拍板，但也不要停下来等：**把问题写成评论、交回架构师、接着做别的工单**。这与 `AGENTS.md`「Solo 模式」是同一份规矩（任何 harness 的 solo 执行者都按它与 `docs/agents/triage-labels.md` 做事）；工人逐步的做法在 [`/solo-worker`](../solo-worker/SKILL.md)。

## 三条通道

| 情况 | 命令 | 标签 |
| --- | --- | --- |
| 同一张工单连续三轮没有通过（一轮一次 `finish` 报 failed 或 blocked） | `solo.mjs escalate --task T-004 --reason "..."` | `needs-triage` |
| 工单里遇到架构、需求、设计的问题 | `solo.mjs question --task T-004 --comment-file <文件>` | `needs-triage` |
| 执行环境挡住了（凭据、权限、CI、依赖、网络） | `solo.mjs askhuman --task T-004 --comment-file <文件>` | `ready-for-human` |

三条通道都做同样三件事：把这张从候选里拿掉、把流程标签换成上面那一个（先摘掉其它流程标签）、把说明发到工单上并署名。外部处理完、标签回到 `ready-for-agent`，下一次 `refresh` 把它放回候选，失败次数清零。转给用户的单子要在收账时**主动告诉用户**：哪一张、缺什么、要他做什么。

## 账本

```
.ralph/
  active.json                 # 指向当前循环；循环结束才删
  <循环名>/
    goal.md                   # 总目标、验收标准、顺序、范围与并发（人可改）
    tasks.md                  # 任务清单：- [ ] / - [x] / - [~]
    progress.md               # 每轮追加的短日志
    handoff.md                # 机器相关的值：路径、gh 身份、环境坑、solo 约定
    state.json                # 机器可读状态
    notes/round-<n>.md        # 长说明
    escalations/<任务号>-*.md # 交回外部时的评论正文
    workers/<会话号>.md       # 工人这一轮的原始输出
    .lock                     # 写账本时的锁
```

`.ralph/` 已在 `.gitignore` 里：账本不进仓库，规则与脚本才进仓库。

`tasks.md` 的三种标记，加上行尾的范围与等待标记：

| 记号 | 含义 |
| --- | --- |
| `- [ ]` | 待做 |
| `- [x]` | 已完成（合并进主线，或者外部已经关掉） |
| `- [~]` | 已交回架构师，循环不再自动重试 |
| 行尾 `（不在范围）` | 这张单已经不在范围里：不派，但行保留，回到范围时自动去掉 |
| 行尾 `（waiting）` | 前提条件没满足 |
| 行尾 `（等用户）` | 转给用户了 |
| 行里 `#<编号>` | 对应的工单号 |
| 行里 `@exclusive` | 互斥任务，同一时刻最多 `concurrency.exclusiveLimit` 张 |
| 行里 `touches-core` | 改核心文件：合并前在分支上多跑一次集成层；不互斥 |
| 行里 `(after T-030)` 或 `依赖 T-030` | 前面那张完成才派 |

`state.json` 里要紧的字段：

| 字段 | 含义 |
| --- | --- |
| `status` | `running` / `paused` / `blocked` / `done` |
| `iteration` / `maxIterations` | 连续工作的段数与预算 |
| `scope` | 范围规则：`milestoneIds`（编号）、`labels`、`prefixes`；空就是全部开放工单 |
| `concurrency` | `max`、`exclusiveLimit`、`active`（正在跑的任务） |
| `escalation` | 连续失败几次交回（默认 3）与目标标签 |
| `signature` | 署名，工人每处产出都带它 |
| `self` | 本机 `gh` 登录名，用来分清「我们的单」与「别人在做」 |
| `taskState` | 每张的失败次数、`interrupted`、`external`、`blockedBy`、`history` |
| `worktrees` | worktree 根目录、分支前缀、起点提交 |
| `flight` | 在跑的每张：开派分钟数、最近一次提交、工作区改动数；`state` 直接打印成「在跑: …」 |
| `waitMode` | 无人值守靠什么收账：`hook`（Claude Code 的 Stop hook）或 `notify`（宿主通知，派完就结束回合）。`resume --wait notify` 写 |

**不手改 JSON。**所有改动走命令（脚本路径相对仓库根）：

```
node .claude/skills/solo/scripts/solo.mjs <命令> [选项]

state | tasks | summary | note --text "..."
refresh | sync [--apply] | next [--max N] [--concurrency N] [--exclusive N] [--dry-run]
claim --task T-004 | worktree --task T-004 [--remove] | start --task T-004 [--session <id>]
finish --task T-004 --status done|failed|blocked [--summary "..."] [--raw-file <文件>]
check --task T-004
escalate --task T-004 [--reason "..."] | question --task T-004 --comment-file <文件>
askhuman --task T-004 --comment-file <文件> | handover --task T-004 | reap [--task T-004] [--stale 90]
gc [--task T-004] [--keep N] [--force] [--from <旧根目录>] | worktrees --root C:/w
pause | resume [--no-auto] [--wait hook|notify] | auto on|off | budget --iterations 120 | concurrency --max 4 --exclusive 1
```

## 机器配置（开循环之前配一次）

| 项 | 配在哪 | 值 |
| --- | --- | --- |
| worktree 根目录 | `state.json` 的 `worktrees.root`，用 `solo.mjs worktrees --root <路径>` 改 | Windows 用短路径 **`C:/w`**（`C:/w/issue-559` 比 `C:/project/yudao-worktrees/issue-559` 少 20 多个字符，`node_modules` 的深路径才不会撞 260 的上限）；类 Unix 用 `/tmp/w` |
| 这个目录的写权限 | `.codebuddy/settings.json` 的 `permissions.allow` | `Edit(//C:/w/**)` 与 `Read(//C:/w/**)`（`//` 开头表示文件系统绝对路径）。沙箱默认只允许写当前工作目录，不放行的话 subagent 在 worktree 里写文件、删临时文件都会被拦——**这是 subagent 报“权限不够”的最常见原因** |
| 依赖 | 写进 `handoff.md`，任务书里带一句 | Python 复用主仓库的环境：`UV_PROJECT_ENVIRONMENT=C:/code/yudao/.venv`。客户端的依赖不共用：要运行客户端测试或接口合同检查的 worktree 自己 `npm ci`，不建指向主仓库 `client/node_modules` 的链接（通过链接共用时，任何一处的 npm 安装改的都是同一个目录） |
| 账本保护 | `hook.mjs` 已内置 | `state.json`、`tasks.md`、`active.json`、`.lock`、`.owner.json`、`.stop-guard.json` 只由命令改；`goal.md`、`handoff.md`、`notes/` 人可以改 |

换过根目录以后，旧目录里的 worktree 用 `solo.mjs gc --from <旧根目录>` 清（按已关闭工单逐张删，正在跑的跳过）。

## 起一个循环，或者接一个循环

先看 `.ralph/active.json`：有活动循环就接着跑，不要重建（重建会丢掉台账）。

**范围和并发都是参数，不是写死的。**用户说的话换成交给 `next` 的参数：

| 用户说 | 怎么落 |
| --- | --- |
| 「把阶段一的工单做完」 | `next --milestone "阶段一"`（脚本按标题换成里程碑编号存进 `scope`） |
| 「M0 的」 | `next --label M0` |
| 「[M0] 开头的」 | `next --prefix "[M0]"` |
| 「都做」/ 没说范围 | `next --all` |
| 「一次做两张」 | `next --concurrency 2`，或者 `concurrency --max 2` |

三个范围条件是**并集**：里程碑里的、带那个标签的、标题带那个前缀的，都算。开循环时把用户的原话抄进 `goal.md` 的「范围」一节，之后每轮不再问。

**范围是每轮重算的，不是开工时的快照。**工单会进出里程碑、会被架构师改挂到别的里程碑、会新开，里程碑本身也会改名：

- 里程碑按**编号**认，改名不影响；用户给标题时脚本换成编号，标题找不到会列出候选。
- 每轮 `next` 会把新进入范围的工单收进台账、把离开范围的标成 `（不在范围）`（行保留，进度不丢），并在输出里写明收进几张、离开几张。
- `sync` 只报告：外部多少张、台账里有没有漏、标签对不对、有没有已经离开范围的。
- 正在做的工单不因为离开范围被中断：它做完才算完。

新建账本时写五个文件：`goal.md`（总目标、范围的原文、验收标准、顺序、并发）、`tasks.md`（可以只写标题，工单靠 `next` 收）、`progress.md`（标题行即可）、`state.json`（字段见上，`iteration` 从 0 开始，`status` 写 `running`）、`.ralph/active.json`（`{"loop": "<循环名>"}`）。`maxIterations` 给一个保守值（默认 20）。机器相关的值（worktree 根目录、gh 身份、环境坑）写进 `handoff.md`，不要写进技能。

## 每轮十二步

一轮 = 一段连续的工作，不是「同时派出的一批」：谁先结束就立刻收账，空出的位置当场补下一张，一直到没有可派的或者用户叫停。

0. **读 `handoff.md`**：worktree 根目录、gh 身份、这台机器的环境坑，每轮都以它为准。
1. **读账**：`solo.mjs state`。以文件为准，不以记忆为准。
2. **回收停住的位置**：`state` 报「可能停住的并发位置」时，先 `solo.mjs reap`，再对每张 `solo.mjs handover --task T-004`，把「上一次做到哪」写进新任务书。被取消的子会话不等于进程已停：`handover` 会看远端分支、PR、未提交改动与没解决的 merge。
3. **刷新**：`solo.mjs refresh`。关掉的标完成，交回的标 `[~]`，等条件的标 waiting，别人领走的记成 `external`；**我们自己的 `in-progress` / `needs-review` 记成「待续」，不会当成别人的**。
   刷新也会报「同时带多个流程标签」：一张工单挂两个流程标签时，`claim` 只会顺手修，之前没人发现。
4. **对账**：`solo.mjs sync`。看外部有没有台账没覆盖的、标签对不对、有没有已经离开范围的。报「外部 0 张」时先怀疑 `scope` 过期（里程碑改过名）。
5. **看 main 的健康**：`gh run list --workflow CI --branch main --event push --limit 5`。`check` 红了就停下先修（重新打开引起失败的工单），不要继续领新活。
6. **挑活**：`solo.mjs next --max <并发数>`。它已经排掉：已完成、已交回、正在跑、别人在做、被外部依赖挡着、依赖没满足、互斥超额、不在范围。挑不到就跳到第 12 步。
7. **建 worktree**：一张一张建（并行建会撞 git 的锁）。`solo.mjs worktree --task T-004` 打印目录与分支；先 `fetch --prune origin`，已存在的复用。
8. **领取**：`solo.mjs claim --task T-004`。负责人改成 `@me`、流程标签换成 `in-progress`。这一步不能省：`refresh` 靠标签与负责人判断「谁在做」。
9. **记账**：`solo.mjs start --task T-004 --session <子会话号>`。第一个 `start` 把 `iteration` 加一并写这一段的标题。
10. **派活**：每张一份**新的**子代理调用（不要复用上一轮的子会话），同一条回复里发 N 个。任务书用下面的模板，写清它自己的 worktree。
11. **收账**：逐个收结果，收一个记一个，收完立刻用 `next` 补一个。
    - 先 `solo.mjs check --task T-004`：工作区干净、没有未推送的提交、分支含 `origin/main`、PR 开着没冲突、检查全绿、有 `DELIVERY:` 交付说明且带署名、标签是 `needs-review`。有一条 ✗ 就不许合并。
    - 再 `solo.mjs finish --task T-004 --status done`：`done` 会自己核对工单已关、PR 已合并、检查全绿，不成立就退出、不写 `[x]`。父工单随子单被 GitHub 关闭（没有分支也没有 PR）时直接认，不必加 `--no-verify`。记完 done 会顺手 `gc --task` 清这一张的 worktree（先归档 `.tmp` 证据；删不掉只提示，不拦收账）。
- `check` 认得「工单已关闭 + PR 已合并」这种形状：它按正文里的 `Closes #<编号>` 认本单那张 PR。
    - 工人报 `ERROR` 行带前缀时按前缀分流：`[环境]` → `askhuman`，`[设计]` → `question`，没有前缀 → 算一次失败。
    - 顺手核对资源有没有释放（进程、浏览器）；**worktree 不在这里逐张删**：收账以后跑 `solo.mjs gc` 统一清——它先把 `.tmp/` 的证据归档到 `.ralph/<循环>/evidence/<编号>/`，再删；删不掉的重试，还不行就留在残留清单里，不影响工单。
    - `refresh` 报「工单正文在工作中被改过」时，让下一轮的工人按最新正文重核。
12. **判停**：见「停止条件」。长说明写 `solo.mjs note --text "..."`，`progress.md` 只留每段那几行。

## 任务书模板

每张一份，把 `<...>` 换成这次的实际内容：

```
【循环】<循环名> 第 <N> 轮（并发 <M> 个里的第 <k> 个）
【总目标】<goal.md 里的一句话>
【本轮任务】<工单号 + 一句话>
【验收标准】<1-3 条可检查的条件，从工单正文抄>
【工作目录】<worktree 绝对路径>（分支 <分支>）。文件读写都用这里的路径，命令先切到这个目录；不要动主工作区。
【规则】先读 <仓库>/.claude/skills/solo-worker/SKILL.md，按「在 /solo 循环里」那一栏做；工单正文、评论与链接的设计说明是验收标准的唯一来源。
【通道】设计问题：写 .tmp/<编号>-question.md，收尾 blocked + [设计]；执行环境：写 .tmp/<编号>-env.md，收尾 blocked + [环境]。
【署名】<signature>：六处都要署（提交信息末行、PR 正文末行、工单每条评论末行、交付说明末行、日记记录行首、变更记录条目行首）。
【历史】本上下文是全新的。前几轮在 <循环目录>/progress.md，需要时自己读。<这里写 handover 的输出：上一轮做到哪、还差什么>
【收尾格式】严格按四行输出：
STATUS: done | blocked
SUMMARY: 一句话，不超过 120 字
FILES: 本轮改动的文件路径，逗号分隔；没有写 none
NEXT: 建议的下一轮任务；没有写 none
```

任务书只写这几样：文件内容、diff、上一轮的日志一律不给——给路径，让工人自己读。派活返回子代理并发上限时按上限少派。

## 一张工单的完整链路

工人按 [`/solo-worker`](../solo-worker/SKILL.md)「一张工单的完整做法」做，编排者收账时按它的步骤核对：领取与 `in-progress`（第 1 步）、三项核对（第 3 步）、PR 正文带 `Solo:` 一行（第 7 步）、CI 与 `touches-core` 的分支集成层（第 8 步）、`DELIVERY:` 交付说明与 `needs-review`（第 9 步）、合并前五项核对（第 10 步）、`--admin --squash` 合并（第 11 步）、工单关闭与去标签（第 12 步）、清理但不删 worktree（第 13、14 步）。
## UI 工单

界面工单多两步：**对着原型核**、**留机器可查的证据**。无人值守时没有人替你看页面，所以「看起来对」不算完成。

1. 开工读 `docs/prototypes/CHANGELOG.md` 的「当前定稿」与工单链接的原型；工单说法与原型冲突时按工单做，冲突写进工单评论。
2. **验证分四层，从便宜到贵，能用便宜的就别用贵的**：

   | 层 | 用什么 | 什么时候够 |
   | --- | --- | --- |
   | 纯函数单测 | 把视图里的判断抽成纯函数（这个仓库的 `floorModelOf`、`page-version.ts` 就是这么做的），`cd client && npm test` 跑相关文件 | 状态→文案/可见性的映射：**优先全部放这一层**，快、能并发 |
   | 构建 | `npm run build:pages` | 改到视图文件就必须过一次（页面能编译） |
   | 端到端 | `npx playwright test tests/e2e/<相关>.spec.ts` | 需要真实渲染、交互、事件流驱动画面时；**只跑相关 spec** |
   | 截图 | `page.screenshot()` 存 `.tmp/<编号>-shots/` | 给人看，不作为判据 |

3. **端到端是贵操作，当一个互斥资源用**：每个 spec 会自己启动真后端、占端口与数据目录（`workers: 1` 是文件内串行），后端在负载下要 60–75 秒。所以同一时刻只让一个 worktree 跑 e2e——编排者安排时不要同时派两张都要跑 e2e 的 UI 单；同一张单里也别重复起后端，把要验的场景放进同一个 spec。
4. **像素判断用「区域差」，不用截图基线**：这个仓库的做法是读画布的内容签名/逐格 RGB 差（#900：只有工程房间那一片最大差 61.7，其余为 0）。**不要引入 `toHaveScreenshot` 基线**——跨机器字体与抗锯齿会让它变成不稳定测试的主要来源。
5. **收账前跑一次识图**（`scripts/vision.mjs`）：把关键截图交给视觉模型，按这张工单的验收条目逐条问。
   ```
   node .claude/skills/solo/scripts/vision.mjs --image <截图> --image <截图> \
     --ask "按这张工单的验收条目逐条回答，每条写「对得上/对不上/看不到」：1) … 2) … 3) …"
   ```
   端点与凭据走 `SOLO_VISION_BASE_URL` / `SOLO_VISION_API_KEY`（没有就沿用 `YUDAO_EVAL_*`），模型用 `--model` 或 `SOLO_VISION_MODEL`，**默认 `gemini`**——`YUDAO_EVAL_MODEL` 的 `ds` 没有视觉，网关会把图换成占位符 `[image omitted: model has no vision support]`。
   这个仓库里楼层画面是 PixiJS 画的，「成果库」「大厅」「信箱」这些牌子只存在于画布像素里，DOM 断言读不到——识图是唯一能读出它们的手段。
   没有凭据时跳过这一步，但要在交付说明与收尾里写「未识图」，不能默认它过了。
6. 断言只落在可判定的东西上：某段文案出现/不出现、某个元素可见/不可见、某个状态词被换掉、某片区域的像素有没有变。工单只写「看起来不对」这类没法判的要求，按设计问题交回架构师，不要自己猜。
4. **截图放 worktree 的 `.tmp/<编号>-shots/`**，文件名写清页面与状态；收账时 `solo.mjs evidence --task T-004` 把它们归档到 `.ralph/<循环>/evidence/<编号>/`，交付说明里列路径。`gc` 删 worktree 前也会自动归档一次。
5. 收尾给用户的总结里**单列一段「UI 待肉眼确认」**：哪几张工单、截图在哪、你据什么判定它对了。不要把「看起来没问题」写成交付结论——那一步只能由人做。

## 硬规则

1. **每次派活都是一次新的子代理调用**，不要复用上一轮的子会话，也不要追加到旧子会话上。
2. **不复制历史**：上一轮的输出、diff、日志不要粘进任务书，给路径。
3. **账本要薄**：每轮只往自己的上下文里放几行摘要，细节落盘。
4. **只走命令改账本**；`tasks.md` 的条数变少时脚本会拒绝写入（历史上有过丢 28 条任务的事故）。
5. **并发位置最多 `concurrency.max` 个**，并且以宿主返回的并发上限为准。
6. **一个任务一个 worktree**，主工作区不改代码、不跑测试、不提交。
7. **派了就一定要收**：每派一个就有一次 `finish`；收一个立刻补一个。
8. **失败的活不换名字重派**；连续三轮交回架构师，不要自己试第四轮。
9. **派活前先刷新再对账**（`refresh` + `sync`），用旧台账派活会派到已经关掉的单子上，或者与别的执行者撞车。
10. **不在 `check` 没有通过的提交上合并**；测试不稳定时重新运行失败的作业，通过再合。
11. **别的执行者在跑同一台机器**：不回退别人的提交、不合并别人的 PR、不改别人的工单、不按进程名批量杀进程。
12. **署名是 `solo-<模型 ID>`，六处都要署，提交信息的署名单独成行**（正文 → 空行 → `— solo-xxx`）；署名值存在 `state.signature`，换模型用 `solo.mjs signature --value solo-<模型 ID>` 改。
13. **循环的记录只写 `.ralph/`**：`progress.md` 与 `notes/`。仓库里的 `agents_jour/<编号>.md` 与 `docs/CHANGELOG.md` 由**工人**按工单写，编排者不写——那两处的记录属于工单，不属于循环。

## 无人值守

`solo.mjs auto on`（或者 `resume` 不加 `--no-auto`）以后，循环不再需要人每轮说「继续」：

- 一轮结束时 **Stop hook** 会看账本：还有工人在跑 → 把会话叫回来收账；没有工人但还有待办 → 叫回来派下一批。实现是 `.claude/skills/solo/scripts/hook.mjs`，在 `.claude/settings.json` 的 `hooks` 里注册（`SessionStart`、`SubagentStart`、`PreToolUse`、`SubagentStop`、`Stop`）。
- 同一个会话最多续 **200** 次，计数器在 `.ralph/<循环>/.stop-guard.json`；续到上限就停下，不会无声死循环。
- 同时被 hook 挡住的两件事：**写 `.ralph/**`**（账本只由命令改）、**`task_append`**（会复用子会话上下文）。派活超过并发上限、任务书过长时会给提醒。
- 停下：`solo.mjs pause`（同时关掉无人值守），或者用户直接打断。跑到没有可派的、预算用尽、全部完成时自己停。
- 没有生效时的查法：新的会话开头应当看到 `[solo] 本工作区有一个…循环` 那段注入；看不到就是宿主没执行项目 hooks，这时退回手动模式——每轮结束时由用户说「继续」。需要 `node` 在 `PATH` 上。

### 宿主没有 Stop hook 时（DSH / OpenCode / Hermes 等）

先把收账方式记进台账：`solo.mjs resume --wait notify`，`state` 会写「无人值守 开（收账靠 宿主通知：派完就结束回合）」。

hook 是 Claude Code 的机制。没有它的宿主上，编排者**不要用 sleep 轮询**：那会把主会话卡在等待里，白烧上下文，人也插不进话。做法是：

1. 派完活、写完 `start`、把这一轮几行摘要记进 `progress.md` 以后，**直接结束回合**。
2. 宿主的子代理跑完会自己把结果送回来（DSH 是会话里的完成通知），那一刻再收账：`check` → `finish` → `next` → 派下一批。
3. 收账一律以账本与 GitHub 为准（`solo.mjs state`、`gh pr list`），不以「上一次看到的」为准。
4. 确实要主动等（例如等 CI）就用**一条带超时**的命令等：`gh pr checks <PR> --watch`，或者把等待放在工人那一侧；不要把等待写进编排者自己的循环。一条命令超过执行上限，就先结束回合，下次收账再查。
5. 一个回合只收一个工人的账：先到的先收，收完立刻补一张，其余继续跑。

无人值守只省掉「说继续」这一步，不改变任何核对：`check`、`finish` 的证据要求照样成立，`maxIterations` 是唯一的预算闸，跑之前把它设成你能接受的轮数。

## 停止条件

| 情况 | 动作 |
| --- | --- |
| 全部做完 | `status` 改 `done`，删 `.ralph/active.json`，给用户一份来自 `progress.md` 的总结 |
| 只剩 `（waiting）` / `（等用户）` | `pause`，写给用户在等什么、还剩几张 |
| 预算用尽（`iteration >= maxIterations`） | `pause`，说明还剩多少 |
| 同一张连续失败到上限 | 交回架构师，循环接着做别的 |
| 需要用户裁决（范围、接口、规则文件、验收标准） | `blocked`，把问题写进 `progress.md` 并问用户 |
| 工人报 blocked | 先看任务书里是不是漏了信息，能补就补一轮，不能就问人 |
| main 的 `check` 红了 | 停下先修，不再领新活 |
| 无人值守续到上限（200 次） | 停下，把进度与卡点告诉用户 |

## 收尾

给用户一份来自 `progress.md` 的总结：做了几轮、每轮改了什么、哪些交回架构师了（失败几次、卡在哪）、哪些在等用户、还剩什么、下一步建议。不要把每一轮的原始输出重新复述一遍。**主动点出等用户处理的那几张**：哪一张、缺什么、要他做什么。

## 与旧的 ralph-loop 插件的关系

这个技能是 `ralph-loop` 插件的重写，装在仓库里（有版本、能 review、能回滚），不再依赖 `~/.minimax/plugins/ralph-loop`：账本命令、工人契约、无人值守的 hooks 都在 `.claude/` 下。主要差别：领取工单进流程；`check` 与 `finish` 带合并前核对；被中断的单子能接着做（区分「我们的」与「别人在做」）；`reap` 回收停住的并发位置；范围每轮重算并且认里程碑编号；并发是参数；账本有锁、写前比条数；删 worktree 前检查未提交与未推送。
