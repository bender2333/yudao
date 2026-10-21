---
name: trial
description: 试用 Yudao：以经验丰富的 agent 使用者的标准，从产品流、性能与成本、上手与使用方便、功能够不够用、稳定性与恢复、可观测与可诊断、文档与实际一致、数据与安全八个维度实际使用一个从 main 打包安装的 Yudao 实例，把发现的问题按四档分级、写清复现步骤与证据，合成一篇帖子发到 GitHub Discussions 的 General 分类。试用的过程不改被测对象。
argument-hint: "[附加任务或备注，例如「只跑产品流」「加一个自己的任务」]"
---

# 试用

试用是一次读数：把 Yudao 当成一个要被用起来的东西，从试用者的位置走一遍，看它在什么地方绊住人，把绊人的地方记成带证据的问题，把结论写成一篇别人能照着核对的帖子。读数要能被下一次读数比较，所以任务固定、指标同名、提交号写在最前面。

试用的对象是试用者自己从 main 打包并安装的实例，不是发布版，也不是源码直跑。试用由 agent 全程执行，人提供环境与凭据。

试用过程只读被测对象：不改 Yudao 源码、不改仓库工作树、不提交、不当场修缺陷。允许改试用者自己环境的配置（Provider、凭据、部门 Prompt），因为那是试用者的环境，不是被测对象。缺陷只记录与发帖，改动走工单。

## 1. 准入

逐项查，缺项降级并写明，**不假装测过**。

| 需要什么 | 怎么查 | 缺了怎么办 |
| --- | --- | --- |
| 模型服务地址、凭据、模型名 | 环境变量，或试用者的 Provider 配置 | 停在这里。没有真实模型就没有任何读数 |
| Python ≥ 3.11、uv | `python --version`、`uv --version` | 停 |
| Node ≥ 22.12 | `node --version` | 降级：不能构建 wheel，界面维度不测，帖子写明 |
| Git | `git --version` | 停 |
| `gh` 已登录 | `gh auth status` | 降级：帖子停在草稿，给出命令，不代发 |
| 检出干净、且在 main 上 | `git status --porcelain`、`git rev-parse --abbrev-ref HEAD` | 停：构建脚本要求工作区干净 |
| 时间与费用预算 | 默认整次 ≤ 60 分钟，单个任务 ≤ 15 分钟 | 按试用者自己的服务方案 |

时间与费用是真实支出。开始前告诉试用者这次大概要花多久、要调用多少次模型；超了就少跑几个任务，在读数里写明哪些任务没跑，不要硬跑。

## 2. 按什么标准看

试用者是做过 agent 运行时的人，看的是这些：

- **上下文有没有带够事实。** 部门开始一轮工作时拿到的材料，够不够它做对事；压缩以后关键事实还在不在。
- **工具调用有没有真的推进。** 调了工具但工作区没变化，是空转；工具有效但方向错了，是判断问题。
- **契约与放行有没有绑在真实证据上。** 质检说通过，通过的是不是它实际检查过的那份交付。
- **失败以后能不能恢复。** 出错、中断、限流、重启之后，状态是不是还讲得通，能不能接着做。
- **一次尝试花了多少。** 墙钟、模型请求数、用量、费用。一个任务花掉多少，是产品成本的直接读数。
- **交付能不能被第三方核验。** 拿到交付物与记录的人，能不能不信任作者也核对出同一结果。

不评论代码风格、命名与目录结构；那是工单审查者的范围，不是试用者的。

## 3. 试用实例

### 3.1 默认：隔离安装

先记下试用者已有的安装，以便恢复：

```bash
yudao --version
uv tool list
```

从 main 构建 wheel（官方路径，需要工作区干净、Node ≥ 22.12；只构建，不发布）：

```bash
git rev-parse HEAD
uv run python scripts/release.py
```

脚本输出 wheel 的路径与 SHA-256。装进仓库外的独立虚拟环境，不覆盖试用者已有的安装：

```bash
uv venv <仓库外目录>/trial-venv
uv pip install --python <仓库外目录>/trial-venv/Scripts/python.exe <wheel 路径>
```

Windows 的解释器在 `Scripts\`，其他系统在 `bin\`。

用独立数据目录与空闲端口启动。默认数据目录是用户数据目录（Windows `%LOCALAPPDATA%\Yudao`），试用不要用它：

```bash
<venv>/Scripts/python.exe -m harness api --data-dir <仓库外目录>/trial-data --port 8766
```

页面在 `http://127.0.0.1:8766`。浏览器打开它，页面文件由 wheel 随包提供。

模型配置在页面的「模型管理」里做：连接 → 候选列表 → 建立访问定义 → 模型测试准入 → 三个部门各选一个模型。部门没绑模型时建事项会被拒。凭据只从进程环境或数据目录内的 `.env` 解析；页面填的 Key 默认只对本进程有效，勾了持久化才写进 `.env`。Key 不回填，也不进日志、事件与导出。

### 3.2 想按真实用户方式装

有人愿意把 main 构建的 wheel 当成自己平常那个 Yudao 来用，那就覆盖安装，并在动手前记下旧版本以便回退：

```bash
uv tool install --python 3.12 <wheel 路径>
```

回退：`uv tool install --reinstall --python 3.12 <上一个版本的 wheel 路径>`，或者 `uv tool uninstall yudao` 后装回原来的版本。默认数据目录里的数据不会因为覆盖安装而消失，但试用产生的数据会留在那里，用独立 `--data-dir` 就不受影响。

### 3.3 降级：源码实例

构建失败（没有 Node、工作区不干净、构建报错）时，从源码起一个只有接口的实例：

```bash
uv run python -m harness api --data-dir <仓库外目录>/trial-data --port 8766
```

源码直跑没有页面文件，页面只回「没有页面文件」。这时候界面相关的维度（上手与使用方便、文档与实际一致）记「降级：没有页面文件」，其余维度照走。帖子与环境与前提里都要写明这次是降级。

## 4. 走查：八个维度

每个维度写一个结论：能不能用，绊在哪里，证据是什么。

1. **产品流**——从「新建项目」到「交付并放行」走通一遍：建项目 → 登记检查命令 → 建事项 → 看三个部门工作 → 追加输入 → 质检放行 → 取回交付物。结论写「能不能一次走通，卡在哪一步」。
2. **性能与成本**——每个任务的墙钟、模型请求数、用量、费用、循环次数、返工次数、询问次数（第 6 节）。结论写「一次典型任务花多少，和第 9 节的上一次比如何」。
3. **上手与使用方便**——安装、配置模型、找入口、关掉再启动、报错能不能看懂。界面走查用试用环境里能操作浏览器的工具；没有浏览器工具时这一项记「降级：没有浏览器工具」。
4. **功能够不够用**——当前阶段承诺的能力是不是真的能用。承诺看[总体路线图](../../docs/program-roadmap.md)与[当前验收基线](../../docs/current-baseline.md)。main 上还没承诺的能力（未开工的工单、M2/M3 之类），不算问题，进第 8 节的「观察」。
5. **稳定性与恢复**——故意让它失败一次（见 T3）；事项进行中停掉服务再启动，看状态讲不讲得通、能不能接着做；`run.recovery` 与 `replay.check` 的结果。结论写「出问题时人能不能自己走出来」。
6. **可观测与可诊断**——`project.attempts`、`run.attempt`、`run.asks`、`department.workspace` 能不能把原因定位到具体一步；事件里有没有人话。结论写「出问题时查得到吗，要查多久」。
7. **文档与实际一致**——[README](../../README.md) 与试用指南里写的步骤、命令、路径，在实际页面上是不是还对得上；对不上是文档问题，记问题。
8. **数据与安全**——凭据有没有漏进日志、事件、导出；数据目录是不是只在试用者自己的机器上；导出的事件里有没有不该出现的东西（见 T5）。

## 5. 轻量任务

任务集在 [docs/trial/tasks.md](../../docs/trial/tasks.md)，是带版本的数据文件：方法在本文，任务在那里。默认跑完那里的五个任务，每个任务几分钟。试用者可以按参数增补自己的任务，增补的任务在帖子里单独标出，不与固定任务混在一起算读数。

任务的目标文本要原样提交给 Yudao，不要替它改写、不要加提示。给 Yudao 的输入就是试用者给的输入。

## 6. 读数

每个任务跑完，从 `GET /api/queries/run.export?run_id=<run id>` 的导出里算，口径与 `evals/runner/yudao_metrics.py` 一致（`projection` 与 `events` 两个部分）：

| 读数 | 取法 |
| --- | --- |
| 结束状态 | `projection.phase` 与 `projection.stop_reason`；放行 = phase 是 `DONE` 且 stop_reason 是 `released` |
| 循环次数 | `projection.cycle_count` |
| 返工次数 | `projection.rework_count` |
| 部门之间询问次数 | 事件里 `ask_started` 的条数；每次询问的内容用 `run.asks` 读 |
| 模型请求数 | 从导出的调用尝试统计 |
| 用量 | `usage.totals` 的 `input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_write_tokens`、`total_tokens`、`cost`；服务没上报时写「未知」，**不算 0**，也不进平均值 |
| 模型延迟 | `usage.totals` 的 `latency_ms` |
| 耗时 | 墙钟秒数 |
| 空响应 | `empty_model_responses` |

每个任务另外记两件：质检有没有放行；有没有产生缺陷记录。

全部任务合计：总耗时、总模型请求数、总用量、总费用、问题按四档的条数。

接口的请求体形状以 `GET /api/openapi.json` 与 `GET /api/capabilities` 为准，不要凭记忆写。常用的几条：

- 命令（`POST /api/commands/<名称>`，每条带客户端生成的 `command_id`，重试用同一个值）：`project.create`、`work_item.create`、`work_item.append_input`、`guidance.send`、`work_item.cancel`、`department_settings.save`。
- 查询（`GET /api/queries/<名称>`）：`project.overview`、`project.flow`、`work_item.inputs`、`department.workspace`、`project.attempts`、`run.attempt`、`run.asks`、`run.export`、`run.recovery`、`replay.check`、`delivery.file`、`project.usage`。

## 7. 问题怎么记

四档：

- **阻断**——做不下去。试用者没法继续用。
- **绕行**——能继续，但得绕。找得到替代办法，代价看得见。
- **烦人**——不挡路，但干扰。反复出现、每次都要多想一下。
- **建议**——不是缺陷，是偏好或改进方向。

每条问题写全这六样，缺一条就不要写进问题列表：

1. 编号与一句话标题
2. 属于哪个维度
3. 复现步骤（从哪个界面或哪条命令开始，做了什么）
4. 期望什么
5. 实际什么
6. 证据：run id、事件 id、截图路径、日志片段、命令与其输出。证据要能被别人打开核对。

猜测、没复现过的、和纯偏好不进问题列表。偏好、猜测与 main 上尚未承诺的能力进第 8 节的「观察」。

## 8. 帖子

一次试用一篇，发到 GitHub Discussions 的 **General** 分类（仓库 `bender2333/yudao`，仓库 id `R_kgDOSpFnRw`，General 分类 id `DIC_kwDOSpFnR84DIxLV`）。Announcements 只有维护者能发，不要往那里发。

标题：`试用：<一句话结论> — <main 提交短号> <版本>`。

正文顺序：

```
本帖由 Yudao 仓库的 /trial skill 自动生成与发布，试用过程由 agent 执行。

## 环境与前提
机器、系统、Python、Node、Yudao 版本与 main 提交号、模型与档位、耗时、用量、费用、是否降级（降级写明原因）

## 读数
各任务与合计的指标表

## 八个维度
每个维度一节：结论 + 证据

## 问题
按四档分组，每条带第 7 节的六样

## 观察
偏好与猜测、main 上尚未承诺的能力（标明对应工单或阶段）、本次没能测到的部分

## 与上一次试用对比
同名指标的对照；没有上一次就写「没有上一次」
```

### 发帖前逐条过（脱敏）

公开发言撤不回，这一步是机械检查，不靠眼力：

- 绝对路径（`C:\Users\…`、`/Users/…`、`/home/…`）换成 `<数据目录>`、`<仓库>`、`<运行目录>`。
- 用户名、机器名、主机名：不出现。
- 凭据、Key、`.env` 内容、请求头里的 Authorization：不出现。
- 试用者自己的代码与材料：只贴与问题直接相关的最小片段（不超过 20 行），其余写「省略」。
- 模型名与服务方案名可以留；内网地址、私有主机名去掉。
- 截图：检查地址栏、通知、标签页标题、路径、账号名，需要时裁剪。
- 保留：提交号、run id、事件 id、版本号。它们是别人核对用的锚点。

### 发帖

用试用者自己的 `gh` 账号发。PowerShell 下查询要写成变量形式，内联的双引号会被 shell 吃掉：

```bash
# 找上一篇「试用：」帖子
gh api graphql -F owner='bender2333' -F name='yudao' -F first=50 \
  -f query='query($owner:String!,$name:String!,$first:Int!){ repository(owner:$owner,name:$name){ discussions(first:$first, orderBy:{field:CREATED_AT, direction:DESC}){ nodes { number title url createdAt author { login } category { name } } } } }' \
  --jq '.data.repository.discussions.nodes[] | select(.category.name=="General" and (.title|startswith("试用："))) | "\(.number)\t\(.url)\t\(.title)\t\(.author.login)"'
```

发帖。标题写进 `title.txt`，正文写进 `body.md`，两个文件都是 UTF-8 无 BOM（PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会写 BOM，标题会多出一个看不见的字符）：

```bash
gh api graphql -f query='mutation($repo:ID!,$cat:ID!,$title:String!,$body:String!){ createDiscussion(input:{repositoryId:$repo, categoryId:$cat, title:$title, body:$body}) { discussion { number url } } }' \
  -f repo='R_kgDOSpFnRw' -f cat='DIC_kwDOSpFnR84DIxLV' -F title=@<草稿目录>/title.txt -F body=@<草稿目录>/body.md
```

发完读回核对标题、分类与正文长度：

```bash
gh api graphql -F owner='bender2333' -F name='yudao' -F n=<编号> \
  -f query='query($owner:String!,$name:String!,$n:Int!){ repository(owner:$owner,name:$name){ discussion(number:$n){ id number title url category { name } body } } }'
```

要改正文时取回正文、改完写回：

```bash
gh api graphql -f query='mutation($id:ID!,$body:String!){ updateDiscussion(input:{discussionId:$id, body:$body}) { discussion { url } } }' -f id=<讨论的 id> -F body=@<草稿目录>/body.md
```

`gh` 没登录或者发帖失败时，帖子停在草稿，把标题、正文与上面这条命令交给试用者，不代发、不用别的账号发。

发完把帖子链接与编号回报，并说明帖子可以自己改或删。

## 9. 与上一次试用对比

用第 8 节那条查询找上一篇「试用：」开头的帖子，读它的「读数」一节，比同名指标：耗时、模型请求数、用量、费用、循环次数、返工次数、询问次数、是否放行。模型服务没上报的项写「未知」，不与 0 比。

上一次不是同一个任务集或者用了不同模型，就写明「不可比」，不要硬比数字。差别能由一两处变化解释的，写「看不出差别」。

## 10. 不做的事

- 不改 Yudao 源码，不改仓库工作树，不提交，不当场修缺陷。
- 不建工单。帖子只做公开记录；维护者读帖子以后把确认的问题转成工单，排在队列最前。
- 不动规则文件（`CLAUDE.md`、`AGENTS.md`、`docs/agents/`）、CI 工作流与设计说明。
- 不发到 Announcements，不在其它分类发帖。
- 不替试用者登录账号，不处理凭据的存储位置以外的事。

## 11. 本地归档

试用的原始材料留在仓库外，不进版本控制：`.yudao/trial/<提交短号>-<年月日-时分>/`（`.yudao/` 已被忽略）。里面放：草稿（`title.txt`、`body.md`）、每个任务的 `run.export` 导出、读数表、截图、日志片段、发帖回执。

试用结束清理试用实例时，只删这次建的虚拟环境与数据目录；试用者原有的安装不动。
