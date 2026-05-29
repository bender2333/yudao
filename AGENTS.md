你正在做一套 MISSION System（AI/Agent 原生任务平台），实现 `docs/superpowers/specs/2026-05-27-ai-agent-native-mission-platform-design-zh.md`。

> **技术栈**：TypeScript（ESM）/ pnpm / Vitest / Playwright / Hono / Vite + React 19 / Node child_process。


## 三份控制文件（先读它们）

| 文件 | 作用 | 能改吗 |
|---|---|---|
| `NORTH_STAR.md` | 终极目标 + done 的定义（验收门） | 只读，禁改 |
| `LOOP.md` | 长任务自动闭环协议（循环体/硬边界/git/subagent） | 偶尔补充 |
| `NEXT.md` | 跨 session 交接（focus/last/next/BLOCKs） | 每次更新 |

长任务自动模式（用户说"自动推进/闭环做完"或 `/loop`）一律按 `LOOP.md` 执行。

## Session Startup Protocol

每个 session，动手写代码前：

1. 读 `NORTH_STAR.md` — 终极目标，永不修改。
2. 读 `NEXT.md` — 上一个 session 留给你的交接。
3. 读今天的 `docs/journal/YYYY-MM-DD.md`，没有就创建。
4. 跑 `git status`。不干净就先看清是什么，再决定（自动模式下按 LOOP.md §5 处理工作分支）。
5. 用 `todowrite` 基于 NEXT.md 的 "Next Action" 排计划。
6. 往今天 journal 追加一行 `HH:MM - Session start`。

## Session Shutdown Protocol

暂停、context 将满、或做完一块时：

1. 往今天 journal 追加进度。
2. 更新 `NEXT.md`：current focus / last action / next action / open BLOCKs。
3. 把完成的工作 commit + push 到工作分支（自动模式见 LOOP.md §5）。
4. 不要为多撑一会儿而疯狂压缩 context——干净收尾，让下一轮从 NEXT.md 续上。

## Journal（每日日志）— 强制，必须用中文写

为每个有意义的动作写一条 `docs/journal/YYYY-MM-DD.md`，时间精确到分钟（`HH:MM`）。

"有意义"包括：
- Session 开始 / 结束
- 一次 build / test / e2e 运行（带结果 PASS/FAIL/SKIP）
- 对某条 NORTH_STAR / Task 验收门的验证结果
- 一个值得记的发现（bug、测量、假设）
- 一个决策（若是阻塞级，同时进 `docs/decision.md`）
- 一次 subagent 派发及其结论

格式：

```
# Journal 2026-05-29

## 14:32 - Session start
- 读 NORTH_STAR.md, NEXT.md
- Focus: Task 1 脚手架 + 契约

## 14:50 - Task 1 单测
- cmd: pnpm test src/shared
- result: PASS (12 passed)
- commit: <hash>

## 15:10 - 发现
- planSeed 不应带 nodeRuns 字段，见 decision.md Q-1
```

条目要短，用 bullet，不写散文。链接产物（日志路径、commit hash），不要复述。

---

## Subagents — 尽量用，保持主上下文干净

长任务最大的敌人是 context 被原始材料塞满。规则：

- **扇出型工作一律派 subagent**：读多个文件、跨目录搜索、调研某模块、跑多组验证、
  审查一片代码。主上下文只接收**结论**，不接收被读文件的原文。
- **探索用只读 subagent**（Explore 类）：定位"X 在哪、谁调用 Y、命名约定是什么"，
  让它返回 file:line 和结论，不要把整文件拉回主上下文。
- **本项目有 CodeGraph + Serena**：结构性问题（谁调谁、改 Z 会炸什么、X 签名）优先用
  `codegraph_*`，比 grep 快且准；不要为查一个符号先 grep。
- 每次 subagent 派发 + 它的结论，记一行 journal。
- 实现类工作（要改代码、连续编辑同一批文件）留在主线做，别派出去——派出去反而对不上账。

## Commit Guidelines（自动 commit + push）

自动循环里，每个**验证通过**的小块就提交一次。用 conventional commits（`fix:`/`feat:`/`docs:`/`chore:`）。
有具体验证产物时带 `Verified-By:` trailer：

```
feat(planner): emit WorkflowIntent without nodeRuns

Verified-By: pnpm test src/server/planner (8 passed)
```

- 工作分支：禁止直接提交 `main`。自动模式切到 `work/v01a` 提交（见 LOOP.md §5）。
- 每次 commit 后 push 到 origin 工作分支（已配 SSH）。首次 `git push -u origin work/v01a`。
- 纯文档改动可省 `Verified-By`。
- 不自动开 PR、不自动并 main——等人。
- 不用交互式 git（`-i`），不加 `--no-verify`，不动 git config。

---

## 卡住时怎么办（对齐 LOOP.md §3 硬边界）

1. 重读 `NEXT.md` 与当前 Task 的"验收门槛"。
2. 重读 NORTH_STAR 对应的 NS 条目和 done 定义。
3. 自查设计稿 / tasks-detailed / 验收门三份文档，答案多半在里面。
4. 仍然卡住，且属于 LOOP.md §3 的硬边界（真歧义 / 不可逆操作 / 同问题失败 2 次）：
   在 journal 和 NEXT.md 的 open BLOCKs 写清"卡在哪、试过什么、要什么决定"，然后**停**。不要猜。

---

## 编码规则

### 1. 先想再写
不假设、不藏困惑、把权衡摆出来。实现前：说清假设；有多种解释就都列出来别默默选；有更简单的路就说；不清楚就停下指明困惑点再问。

### 2. 简单优先
能解决问题的最小代码，不写投机性的东西。不加没要求的特性/抽象/可配置；不为不可能的情况写错误处理。写了 200 行但 50 行能搞定，就重写。

### 3. 外科手术式改动
只动必须动的。改既有代码时：不"顺手优化"邻近代码/注释/格式；不重构没坏的东西；匹配既有风格即使你有别的偏好；看到无关死代码——提一句，别删。你的改动产生的孤儿（import/变量/函数）才清理。每一行改动都能追溯到当前需求。

### 4. 目标驱动执行
把任务变成可验证的目标："加校验"→"为非法输入写测试再让它过"；"修 bug"→"先写复现测试再让它过"。多步任务先列简短计划，每步带 verify。强 success criteria 才能独立循环；弱的（"让它能用"）会逼出反复澄清。

### 5. 确定性的事不用 LLM
LLM 用于：分类、起草、摘要、从非结构化文本抽信息。**不要**用 LLM 做：路由、重试、状态码处理、确定性转换。状态码已经能回答的问题，就让普通代码回答。

### 6. 暴露冲突，不要折中
两个既有模式矛盾时：选一个（偏向更新/更经过测试的），说明理由，把另一个标记为待清理。同时满足两套矛盾规则的代码比任一种都糟。

### 7. 先读再写
往文件加代码前：读它的导出、直接调用方、明显共享的工具。不理解既有结构为什么这样就先问，别硬加。"这跟我没关系吧"是代码库里最危险的一句话。

### 8. 测试要编码意图，不只是行为
每个测试要编码"为什么这行为重要"，不只是"它做了什么"。`expect(getUserName()).toBe('John')` 在函数收到硬编码 ID 时一文不值。写不出一个"业务逻辑变了就会失败"的测试，说明函数本身有问题。不要从"只验证函数返回了点东西"的测试里宣称信心。

### 9. 长任务设检查点
多步任务每步后小结：做了什么、验证了什么、还剩什么。丢失进度就停下重述现状再继续。步骤 4 的错误被 5、6 接着建，比重来更贵。

### 10. 约定优于新意
代码库用 `snake_case` 你偏好 `camelCase`，就用 `snake_case`。真觉得某约定有害，明说，别默默 fork 出第二套模式。一套一致的模式好过两套（哪怕第二套更好）。

### 11. 大声失败，绝不静默
看起来像成功的失败最贵。别在 30 条记录被静默跳过时说"迁移完成"；别在有测试被跳过时说"测试通过"；别在没验证边界时说"功能可用"。不确定就说不确定。

### 12. 黑盒验收测试是规格，不是变量 ★本项目铁律
`docs/superpowers/plans/2026-05-29-integration-test-children-story-site.md` 的验收门是 done 的定义。
测不过 = 系统有缺陷 → **修系统，绝不改测试、绝不放宽断言、绝不删用例**。

---

## 文档与语言

- 后续所有文档和注释用**中文**。
- 代码标识符、commit type 前缀、API 字段名保持英文（对齐既有代码）。

## 真实命令速查

```bash
pnpm test                         # Vitest 全量
VITE_FAKE_RUNNER=1 pnpm test:e2e  # 第 1 层 fake runner
ACCEPTANCE=1 pnpm test:e2e        # 第 2 层黑盒验收门
pnpm build                        # tsc + vite build
pnpm api / pnpm dev               # 后端 / 前端
```


