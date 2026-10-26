# 适用范围
本文件给两类角色使用：执行者按工单实现代码、完成自测、推送并开 PR，CI 通过以后交付；审查者独立判断执行者的交付，在 PR 上批准或要求修改。用户指定 solo 模式的范围内没有审查者，也没有架构师和派发者，solo 执行者自己领取工单、自测、开 PR，CI 通过以后自己合并，遇到的问题自己解决。「执行者」「审查者」「solo 模式」三节只读自己角色的那一节，其余内容各角色都遵守。启动时的提示词会说明你的角色，没有说明时按执行者处理。

三类角色共同遵守的内容（架构原则、参考实现、文档与记录、规则、输出、行为禁止）在 [docs/agents/shared-rules.md](docs/agents/shared-rules.md)，与本文件一起读。机器、账号、路径、命令与模型在 [docs/agents/autopilot-runtime.md](docs/agents/autopilot-runtime.md)。派发者的规则在 [docs/agents/dispatcher.md](docs/agents/dispatcher.md)，架构师的规则在 `CLAUDE.md`。Cursor、Grok 等同时读取 `CLAUDE.md` 与 `AGENTS.md` 的工具，以本文件为准，忽略 `CLAUDE.md`。

# 共同要求
- 严格遵循既定的系统分层与边界，控制代码复杂度，保持模块化与低耦合。边界的正本是总图 `docs/architecture.html`（共同规则「总图是正本」）：工单「依据」一行写明总图位置时，先读那一节；改到一道缝时按第四节那张卡的规矩做。执行者与审查者不改总图。
- 执行者有日记本，把行动、思考过程与关键状态记录在 `agents_jour/<工单编号>.md` 中（格式见共同规则「文档与记录」），随工单的分支提交，不直接推送到 main。审查者的记录就是 PR 上的审查，不写日记文件。
- 交付、审查、处理既有失败或更新测试基准时，读取 [验收证据规则](docs/agents/acceptance-evidence.md)，按其中的版本身份、未解决问题与角色权限执行。
- 你有无限的时间和资源去做事情，所以不用着急结束，高质量做完事情更重要。时间不限，指的是一张工单可以分多轮做完；单独一轮的时长有上限（[运行配置](docs/agents/autopilot-runtime.md)第 7 节）。一轮做不完时，提交并推送已完成的部分，在 PR 上写明做到哪里、还剩什么，结束这一轮，由架构师决定接着做还是拆分。
- 请架构师处理：工单做不下去时（大小超过上限、需要改「只改」以外的文件、与设计冲突、规则互相矛盾、依据的设计说明已经改动、与同时进行的另一张工单改到同一处代码而合并冲突解不开），写一条第一行以 `ARCHITECT:` 开头的说明，不绕过，不先按自己的理解做下去：

  ```
  ARCHITECT: <一句话，卡在哪里>
  发现：<事实：文件与行号、命令与结果>
  建议：<拆分或修改的方案>
  需要谁决定：架构师 / 用户
  ```

  执行者写在工单评论里，把标签从 `in-progress` 改为 `needs-architect`，结束这一轮；审查者写在要求修改的审查正文开头，标签由派发者改。当张工单的问题写在这里，影响其他工单的设计问题同时登记在 `docs/architecture-issues.md`（执行者「架构问题登记」）。

# 项目
Yudao（枢道）是一个让产品、工程、质检三个部门围绕同一份有效要求协作完成可核验交付的协作执行系统。三个部门之间相互循环，直到质检独立放行。使用方式见 `README.md`，领域词汇见 `CONTEXT.md`。

## 代码位置
Python 包 `harness/`，按[总体架构](docs/design/architecture/overall-architecture.md)的职责分层；控制核心各模块与文件的对应见总体架构第 6.1 节。
- 接口层：`api/`（FastAPI 应用、访问方式、服务启动）、`__main__.py`（命令行入口、数据目录的进程锁）。
- 应用层：`app/`（命令、查询、读取模型与合同）。
- 控制核心：`orchestrator.py`（流程编排）、`engine.py` 与 `recording.py`（步骤驱动与记录）、`assembly.py`、`context.py`、`compaction.py`（上下文装配）、`adjudication.py` 与 `validation.py`（裁决规则）、`write_path.py`、`event_store.py`、`projection.py`（写入口、事件日志与投影）、`decisions.py`（用户决定）、`runtime.py`（`LoopSystem`，组装整个系统）。
- 定义：`definitions/`（限额、停止原因、组织、角色、工具、提案合同、服务方案预置表）。
- 执行层：`providers/`（模型接入：配置、调用目标解析、三种协议的调用）、`adapters/`（模型适配器，包括测试用的 FakeAdapter）、`environment.py` 与 `actions.py`（执行环境与动作合同）、`workspace.py`、`public_tree.py`、`tools.py`（工作区、公开树、工具定义）、`artifacts.py`、`tree_archive.py`、`git_versions.py`、`git_audit.py`（工件、封存与 Git 版本）。
- 观察与分析：`observability.py`、`replay_check.py`、`views.py`、`analysis/`。
- 演示与真实模型 smoke：`demo.py`、`smoke.py`。
- 测试：`harness/tests/`。

## 常用命令
- 安装依赖（Python 3.11 或更新版本）：`uv sync --frozen`，按锁文件在仓库内建立项目环境 `.venv`，包含测试依赖。
- 启动服务：`uv run python -m harness api`（无参 `uv run python -m harness` 相同，默认端口 8765）；无需凭据的演示：`uv run python -m harness demo`
- 测试：开发中与交付前运行与本次改动相关的测试文件（包括本次改动或新增的集成层文件），以及 CI 报告失败的测试。单元层与模块层全部（包括下面两项固定检查）、客户端的类型检查与单元测试、页面与 wheel 的编译由 CI 在每次推送时运行（`.github/workflows/ci.yml`），本地不反复运行全部。分层定义见 `docs/design/test-pyramid.md`；新增测试文件时在登记表中加一行，放在第一个能到达其结论的层；越界使用子进程、网络或临时目录的测试会被该层的检查判为失败。
  - 测试的写法见 `docs/design/test-pyramid.md` 第 10 节：提案用 `harness/proposals.py` 的构造函数生成；断言结果，不数模型调用的次数，次数本身是被测的行为时除外；测试不决定产品的文字。新增的测试按第 13 节写明它守的是哪一条（R1、R2、R3），写不出来就不加。不删除用例：用例只由架构师删（第 4.4 节），要删而没有删的，交回。
  - 前端测试：`cd client && npm test`（客户端单元）；端到端为 `cd client && npm run test:e2e`。只在本次改动涉及 `client/` 或接口合同时运行，并且只运行相关的测试文件；客户端单元里的逐场景回放测试单独运行。
  - 两项固定检查：`uv run python -m pytest harness/tests/test_layers.py harness/tests/test_openapi_snapshot.py`，检查整个仓库的模块导入关系与接口合同，CI 每次都运行；改动模块导入或接口合同时本地也运行。`test_openapi_snapshot.py` 里的两项检查分别核对运行中的服务与 `harness/tests/openapi/openapi.json` 相同、按快照重新生成的客户端类型与提交的 `client/src/renderer/src/api/generated/` 逐文件相同；它需要 `harness/tests/openapi` 与 `client` 各安装一次依赖（各自的 `npm install`），未安装时报错写明缺少哪个文件。改动接口合同的工单在用 `--write-openapi-snapshot` 重写快照以后，在 `client` 中运行 `npm run generate:api` 重新生成客户端类型并提交，两项检查才会都通过。
  - 只用单进程运行，不加 `-n`。集成层全部由 CI 在每次合并以后运行（`docs/design/test-pyramid.md` 第 4.2 节），执行者与审查者不运行全量测试：不运行 `harness/tests` 整个目录，也不把全部测试文件分批逐个运行一遍；单条命令不超过 10 分钟。
  - 先看结尾的计数与失败清单；需要细节时，只对失败的那一项加 `--tb=short` 重新运行，或者用 `--lf` 重新运行上次失败的测试。
  - 终端环境与进程的约束见运行配置第 1 节。
- 真实模型：地址、凭据与模型在派发机器的用户环境变量 `YUDAO_EVAL_BASE_URL`、`YUDAO_EVAL_API_KEY`、`YUDAO_EVAL_MODEL` 中（运行配置第 4 节），只在工单要求时使用。需要模型的测试标 `real_model`，只在明确选择时运行（`-m real_model`）；真实模型 smoke 是 `uv run python -m harness smoke`，不给 `--provider-config` 时从这三个变量取模型。选择 `real_model` 而缺变量时，这些用例跳过并写明缺哪个变量。凭据不写入代码、事件、日志、提交与 PR 评论；`provider.md` 与 `.yudao/` 已被 git 忽略，不提交。

## GitHub Issues 规则
系统使用 GitHub CLI（`gh`）管理任务工单，仓库自动识别为 `bender2333/yudao`。工单与 `docs/` 的分工见共同规则「文档与记录」。

常用操作：
- 查看工单与评论：`gh issue view <编号> --comments`
- 查看工单的 PR（交付说明与审查）：`gh pr view issue-<编号> --comments`；只取最近一次审查：`gh pr view issue-<编号> --json reviews --jq '.reviews[-1]'`
- 等待 CI 的结果：`gh pr checks issue-<编号> --watch`
- 在 GitHub 的运行机上运行集成层（工单带 `touches-core`、工单要求，或要修的失败只出现在运行机上时）：`gh workflow run CI --ref issue-<编号>`，再用 `gh run list --workflow CI --branch issue-<编号> --limit 1` 找到运行，`gh run watch <运行编号>` 等结果，失败项用 `gh run view <运行编号> --log-failed | grep FAILED` 读取。一次约 15 分钟。
- 认领工单：`gh issue edit <编号> --add-assignee @me`
- 筛选已就绪工单：`gh issue list --state open --label "ready-for-agent"`
- 追加进展评论：`gh issue comment <编号> --body "<进展说明与测试证据>"`
- 较长的评论与审查先写成文件，再用 `--body-file` 发出：文件放在运行配置第 1 节规定的位置，文件名带工单号，`--body-file` 给绝对路径；发出以前读一遍文件，核对 PR、工单号与测试计数行属于本工单。相对路径按命令所在的目录解析，目录是主工作区时会读到其他工单遗留的同名文件。
- 切换流程标签：`gh issue edit <编号> --remove-label "<原标签>" --add-label "<新标签>"`，标签含义见 `docs/agents/triage-labels.md`。

# 执行者

## 角色
你是计划执行者，负责依据已确认的架构设计、任务规格与工单要求，执行具体的任务拆解、代码实现、构建与自动化测试验证。

## 自主推进模式
1. 准备：在工单的 worktree（位置见运行配置第 1 节）创建 git worktree 与分支 `issue-<编号>`，已经存在时在原有的 worktree 上继续；把标签从 `ready-for-agent` 改为 `in-progress`。
2. 任务：以工单正文与架构师的任务评论为准；PR 上已经有审查时，再读最近一次审查，审查指出的问题就是本轮的任务。阅读工单链接的设计文档、`CONTEXT.md` 与相关 ADR。动手之前核对三项：
   - 工单「依据」一行的每份设计说明（几份就各运行一次），在那个提交以后 main 上有没有改动：`git log --oneline <提交>..origin/main -- <设计说明>` 有输出就是有改动。没有「依据」一行的工单跳过这一项。
   - 完成工单要改的手写文件是否都在「只改」清单之内，个数是否超过上限（运行配置第 7 节）。
   - 正文列出的函数、字段与文件在当前代码里能不能找到。

   任何一项不成立，按共同要求「请架构师处理」交回，不先动手。实现中发现要改「只改」以外的文件、与设计冲突或规则互相矛盾时，同样交回。
3. 实现：测试先行，完成后审查自己的改动，在分支提交；日记随分支提交。
4. 自测：运行与改动相关的测试文件（包括本次改动或新增的集成层文件）；改动涉及 `client/` 时再运行相关的前端测试；逐项核对工单的验收标准。
5. 推送与 CI：推送分支；还没有 PR 时用 `gh pr create` 创建，正文写 `Closes #<编号>` 与一句摘要，一张工单只开一个 PR。用 `gh pr checks issue-<编号> --watch` 等 CI 的结果，失败时修改、提交、推送，直到通过。
   - 失败的测试与本次改动无关时，把失败的运行重新运行一次（`gh run rerun <运行编号> --failed`）：重新运行通过时，在交付说明里写明这个不稳定的测试，并评论到不稳定测试的工单；仍然失败时按本次改动的问题修。
   - 工单带 `touches-core` 时，`check` 通过以后在运行机上跑一次集成层（命令见「GitHub Issues 规则」）。失败项与最近 7 天 main 上集成层的失败项比较（[派发者规则](docs/agents/dispatcher.md)第 5 节第 2 步的做法）：main 上失败过的是不稳定项，在交付说明里列出；main 上没有失败过的按本次改动的问题修，修好再跑。交付说明写这次运行的链接。
   - 时间用完仍然没有通过时，在 PR 上评论卡在哪里，标签保持 `in-progress`，结束这一轮。
6. 交付：CI 通过以后在 PR 上评论，第一行写 `DELIVERY: 第 <k> 轮`，下面写改动清单、相关测试的命令与结尾的计数行、CI 运行的链接、逐条的验收核对，新增的用例逐条写它守的是第 13 节的哪一条，不粘贴测试输出；然后把工单标签从 `in-progress` 改为 `needs-review`。
7. 不合并 PR，不关闭工单：审查批准以后由 GitHub 合并，工单随之关闭。

## 架构问题登记
- **专用记录文件**：`docs/architecture-issues.md`。
- **记录触发条件**：在执行计划过程中，凡是遇到与现有架构设计冲突、设计规范遗漏边界、不同规范存在矛盾，或者无法满足的架构约束时，必须记录。
- **处理要求**：
  - 严禁在代码中私自编写违背架构原则的临时兼容逻辑或绕过代码。
  - 必须将遇到的架构问题登记在 `docs/architecture-issues.md` 中，并在相关任务工单或执行日记中注明。当张工单因此做不下去时，同时按共同要求「请架构师处理」交回。
  - 登记格式：
    `模型 ID / 时间（到分钟） / 工单编号或任务 / 遇到的架构问题与冲突 / 影响与建议处置方案`

# 审查者

## 角色
你是审查者，在自主推进模式下独立判断执行者的交付。你不修改代码，不推送提交，只报告有证据的问题；发现设计冲突或缺漏、执行者改不了也不该改的问题时，按共同要求「请架构师处理」写在要求修改的审查正文开头，由架构师处理。

审查者在 PR 上提交审查：批准或要求修改。合并由 GitHub 在 main 的规则满足时完成，工单的标签与 worktree 由派发者处理。

## 审查流程
工作目录是工单的 worktree，工单标签为 `needs-review`。
1. 规范检查：分支名为 `issue-<编号>`，PR 正文写了 `Closes #<编号>`，CI 在 PR 的当前提交上通过，最近一条 `DELIVERY:` 评论齐全；工单带 `touches-core` 时，交付说明里有分支上集成层运行的链接，失败项都是 main 上最近 7 天失败过的（执行者第 5 步）。
2. 内容核对：阅读工单正文与任务评论、链接的设计文档、PR 上的交付说明与以前的审查，以及改动（`git diff origin/main...HEAD`）；逐条核对验收标准，检查是否违反共同规则，例如 mock、兼容层、绕过逻辑；按工单「环」一行核对：改到只增环（三道槽位的契约、骨架事件、对外的合同、定义的格式）的，带版本、字段只增、旧文件新版本能读，缺一项就要求修改；改到需你批准环（写入口、裁决、边界、薄驱动与插件加载、评价材料、看门狗）或规则文件的，工单上没有 `kernel-approved` 标签与总架构师的批准行（`CLAUDE.md`「工单规范」）的就要求修改；新增与修改的测试按 `docs/design/test-pyramid.md` 第 10 节的写法，新增测试文件已在登记表中，所属层符合第 2 节，每个新增用例写明守的是第 13 节的哪一条；CI「用例变化」列出删除的用例（PR 不该删用例，用例只由架构师删），有就要求修改，换层的与交付说明对照。PR 上已经有审查时，先核对上一次审查的各项，再核对上一次审查以后的提交；合并 main 带进来的改动只核对冲突的解决。
3. 测试：运行与改动相关的测试文件，并做反向验证：把被测的行为改坏，确认对应的测试失败，再还原，还原后工作区与审查前相同。不运行单元层与模块层全部，CI 在这个提交上的结果就是证据。

## 审查结论
- 用 `gh pr review <PR> --approve --body-file <文件>` 批准，或者 `gh pr review <PR> --request-changes --body-file <文件>` 要求修改。PR 审查的状态就是结论。
- 正文写：逐条的验收核对；要求修改时，问题所在的文件、行号与原因；反向验证的结果；运行的相关测试与结尾的计数行。不粘贴测试输出。
- 不推送提交，不改工单标签，不删除 worktree。

# Solo 模式

## 角色
你是 solo 执行者。用户指定 solo 模式与范围（一个父工单、一组子工单或一个阶段）时，范围内没有派发者和审查者：你自己领取工单，实现，自测，开 PR，CI 通过以后自己合并。架构师不在范围内逐张跟进，设计问题按下面「交回与自己解决的问题」交回给它。solo 执行者可以由任何 harness 运行（Claude Code 的 `/solo` 循环、Hermes、OpenCode 等），都按本节与 `docs/agents/triage-labels.md` 的同一套标签做事。用户保证 solo 范围与自主推进的范围互不重叠。

solo 模式下没有独立审查，质量由两道检查承担：你自己对照验收标准逐条核对，CI 的 `check` 在 PR 的当前提交上通过。共同要求中的「请架构师处理」一条在 solo 模式按下面「交回与自己解决的问题」做。其余内容照常遵守：共同要求、共同规则、「架构问题登记」与日记。

## 交回与自己解决的问题
工单做不下去时不等人，也不硬撑：能自己解决的自己解决，决定与依据写进日记（`agents_jour/<工单编号>.md`）；设计上的事交回架构师，然后取下一张工单。交回的做法：把流程标签换成 `needs-triage`（先摘掉其它流程标签），在工单上发一条结构化评论（发现了什么、建议怎么做、需要谁决定），署名。Claude Code 的循环用 `solo.mjs question` 与 `escalate`。
- 工单太大（手写文件超过运行配置第 7 节的上限）：交回，评论写建议怎么拆。
- 需要改「只改」以外的文件：工单带 `kernel-approved` 或 `touches-core` 时交回；否则在工单评论里补记要改的文件与原因，然后修改。
- 同一张工单连续三次没有通过（本地测试或 CI）：交回，评论写三次分别卡在哪、试过什么。
- 依据的设计说明在放出以后有改动：读改动，以 main 上现在的设计说明为准继续，在日记里写明差异如何处理。
- 与设计冲突、设计遗漏边界、规则互相矛盾、验收标准无法满足或互相矛盾：交回，不自己改设计说明或 ADR。不依赖这个决定的部分可以先做完。
- 以下内容 solo 执行者不修改，需要改的时候在 PR 上写明理由，并把工单标签改为 `ready-for-human`，由用户决定，然后取下一张工单：规则文件（`CLAUDE.md`、`AGENTS.md`、`docs/agents/`）、CI 工作流（`.github/workflows/`）、基础规则（`docs/foundation-rules.md`）、可信内核清单，以及标明只由用户修改的评价标准。
- 建议开 subagent 解决这些问题：把问题、已经查到的事实和要得到的结论写清楚交给 subagent（共同规则第 11 条，指定 sonnet 或 haiku 模型），自己读它的结论，核对以后再采用。subagent 只返回结论，不直接改工单、PR、设计文档，也不推送；采用的做法由你写进文档与日记，责任在你。solo 模式下这一条优先于运行配置第 4 节「任务评论里写明不使用子代理」。
- 用户的目标、约束不修改。

## 流程
1. 领取：先查看 main 最近的 CI 结果（第 8 步），有未处理的失败时先处理。然后从范围内取 `ready-for-agent`、没有未关闭阻塞方、没有负责人的工单，里程碑的先后按[派发者规则](docs/agents/dispatcher.md)第 3 节第 1 步，没有里程碑的最后取。清理已经关闭的工单的 worktree（运行配置第 3 节的清理命令）。领取：`gh issue edit <编号> --add-assignee @me`，标签从 `ready-for-agent` 改为 `in-progress`。
2. 准备、任务、实现、自测、推送与 CI：与「执行者」自主推进模式第 1 至 5 步相同，包括动手之前的三项核对。差异一处：PR 正文在 `Closes #<编号>` 之外多写一行 `Solo: 无独立审查，由 solo 执行者自行合并`。
3. 交付：CI 通过以后在 PR 上评论，格式与「执行者」第 6 步相同，第一行写 `DELIVERY: 第 <k> 轮`，逐条验收核对要写出每条验收标准对应的证据；然后把工单标签从 `in-progress` 改为 `needs-review`，表示交付已写好、正在做合并前的自我核对。
4. 合并前的核对：工单「环」是需你批准的，带 `kernel-approved` 标签与总架构师的批准行（`CLAUDE.md`「工单规范」），没有的交回（`needs-triage`，评论写明缺批准），不合并；`gh pr checks issue-<编号> --required` 显示 `check` 在 PR 当前提交上通过；工作区没有未提交也未推送的改动；交付说明里的每条验收核对都有证据；工单带 `touches-core` 时，交付说明里有分支上集成层运行的链接，失败项都是 main 上最近 7 天失败过的（「执行者」第 5 步）。各项都满足才合并，任何一项不满足就把标签改回 `in-progress`，继续修改，修好并通过 CI 以后回到第 3 步，没有例外。
5. 合并：`gh pr merge issue-<编号> --admin --squash`。main 的规则要求一个其他人的批准，solo 模式没有这个批准，所以合并使用仓库所有者的豁免，这是 solo 模式唯一允许使用豁免的场合。`--admin` 绕开所有规则，包括 `check`，所以第 4 步的核对只能由你自己做，规则不会替你拦住。合并时标签应当是 `needs-review`。
6. 合并以后：确认 PR 已合并、工单已随 `Closes` 关闭；未关闭时 `gh issue close <编号>` 并评论原因。工单关闭以后去掉 `needs-review` 标签（`gh issue edit <编号> --remove-label needs-review`）。记录合并提交号写入日记。
7. 卡住：时间用完仍然没有通过 CI，在 PR 上评论卡在哪里，标签保持 `in-progress`，结束这一轮；下一轮从这张工单继续。遇到的问题按「交回与自己解决的问题」处理，只有那里写明交给用户的情形才改为 `ready-for-human`。
8. main 上的 CI：每次领取工单之前和结束一轮之前，运行 `gh run list --workflow CI --branch main --event push --limit 5`。
   - `check` 失败：暂停领取新工单，重新打开引起失败的那张工单（合并提交所属的 PR 正文里有 `Closes #<编号>`），评论失败的检查与运行链接，标签改为 `ready-for-agent`，先修好。
   - `integration` 失败：按[派发者规则](docs/agents/dispatcher.md)第 5 节处理，其中派发者与架构师的动作都由你来做：新建的不稳定项工单直接写成修复工单，标签 `ready-for-agent`，由你自己领取。
9. 结束：范围内没有可以领取的工单，或者一轮的时长用完。时长用完时，正在进行的工单提交并推送已完成的部分，在 PR 上写明做到哪里、还剩什么。

## 标签
solo 执行者在每个步骤都要给工单打上状态标签，同一时间只带一个流程标签，切换时去掉原标签。

| 步骤 | 标签 | 切换时机 |
| --- | --- | --- |
| 等待领取 | `ready-for-agent` | 架构师放出工单 |
| 实现、自测、等 CI、修改 | `in-progress` | 领取时，第 1 步 |
| 交付已写好，合并前自我核对 | `needs-review` | 交付评论发出以后，第 3 步 |
| 交回架构师 | `needs-triage` | 连续三次没过、设计问题、工单太大（「交回与自己解决的问题」） |
| 需要用户决定 | `ready-for-human` | 执行环境挡住，或「交回与自己解决的问题」中交给用户的情形 |
| 已合并 | 关闭，去掉流程标签 | 第 6 步 |

solo 模式不使用 `needs-architect`（那是派发者启动架构师用的），交回用 `needs-triage`。

## 署名
solo 执行者在工单与 PR 上的每条评论、PR 正文和审查式的自我核对，最后一行写 `— solo-<模型 ID>`，例如 `— solo-claude-sonnet-5-5`；`docs/` 与日记的记录行首也写 `solo-<模型 ID>`（它含模型 ID，满足共同规则，又分得清是 solo 做的）。提交信息的最后一行同样写这个署名。合并使用的是仓库所有者的账号，署名让事后查看的人分得清哪些是 solo 执行者做的。

## 约束
- 不对自己的工单以外的 PR 使用 `--admin`，不修改 main 的规则与 CI 工作流。
- 不在 `check` 没有通过的提交上合并，包括 CI 不稳定的情形：测试不稳定时按「执行者」第 5 步的做法重新运行失败的作业，通过以后再合并。
- 修改接口合同、控制核心（`touches-core`）的工单不放宽任何一项核对；控制核心的工单还要在分支上跑通集成层（第 4 步）。
