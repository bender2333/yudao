# 适用范围
本文件给两类角色使用：执行者按工单实现代码并完成自测；审查者核对执行者的交付，运行单元层、模块层与改动相关的测试，审查通过后提交并发起 PR。「执行者」「审查者」两节只读自己角色的那一节，其余内容两类角色都遵守。启动时的提示词会说明你的角色，没有说明时按执行者处理。

三类角色共同遵守的内容（架构原则、参考实现、文档与记录、规则、输出、行为禁止）在 [docs/agents/shared-rules.md](docs/agents/shared-rules.md)，与本文件一起读。机器、路径、命令与模型在 [docs/agents/autopilot-runtime.md](docs/agents/autopilot-runtime.md)。架构师的规则在 `CLAUDE.md`。Cursor、Grok 等同时读取 `CLAUDE.md` 与 `AGENTS.md` 的工具，以本文件为准，忽略 `CLAUDE.md`。

# 共同要求
- 严格遵循既定的系统分层与边界，控制代码复杂度，保持模块化与低耦合。
- 你有日记本，把你的行动、思考过程与关键状态记录在 `agents_jour/<工单编号>.md` 中（格式见共同规则「文档与记录」）。日记随工单的分支提交，不直接推送到 main。
- 交付、审查、处理既有失败或更新测试基准时，读取 [验收证据规则](docs/agents/acceptance-evidence.md)，按其中的版本身份、未解决问题与角色权限执行。

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
- 演示与真实模型 smoke：`demo.py`、`smoke.py`、`compare.py`。
- 测试：`harness/tests/`。

## 常用命令
- 安装依赖（Python 3.11 或更新版本）：`uv sync --frozen`，按锁文件在仓库内建立项目环境 `.venv`，包含测试依赖。
- 启动服务：`uv run python -m harness api`（无参 `uv run python -m harness` 相同，默认端口 8765）；无需凭据的演示：`uv run python -m harness demo`
- 测试：开发中运行与本次改动相关的文件；交付前和审查时运行 `uv run python -m pytest -m "unit or module"`，再运行本次改动涉及的集成文件。分层定义见 `docs/design/test-pyramid.md`；新增测试文件时在登记表中加一行，放在第一个能到达其结论的层；越界使用子进程、网络或临时目录的测试会被该层的检查判为失败。
  - 前端测试：`cd client && npm test`（客户端单元）；端到端为 `cd client && npm run test:e2e`。只在本次改动涉及 `client/` 或接口合同时运行，并且只运行相关的测试文件；客户端单元里的逐场景回放测试单独运行。
  - 每次都运行 `uv run python -m pytest harness/tests/test_layers.py harness/tests/test_openapi_snapshot.py`：两项检查整个仓库的模块导入关系与接口合同，任何改动都可能影响它们。`test_openapi_snapshot.py` 里的两项检查分别核对运行中的服务与 `harness/tests/openapi/openapi.json` 相同、按快照重新生成的客户端类型与提交的 `client/src/renderer/src/api/generated/` 逐文件相同；它需要 `harness/tests/openapi` 与 `client` 各安装一次依赖（各自的 `npm install`），未安装时报错写明缺少哪个文件。改动接口合同的工单在用 `--write-openapi-snapshot` 重写快照以后，在 `client` 中运行 `npm run generate:api` 重新生成客户端类型并提交，两项检查才会都通过。
  - 只用单进程运行，不加 `-n`。集成层全部由架构师按批运行，执行者与审查者不运行全量测试：不运行 `harness/tests` 整个目录，也不把全部测试文件分批逐个运行一遍；单条命令不超过 10 分钟。
  - 先看结尾的计数与失败清单；需要细节时，只对失败的那一项加 `--tb=short` 重新运行，或者用 `--lf` 重新运行上次失败的测试。
  - 终端环境与进程的约束见运行配置第 1 节。
- 真实模型 smoke：`uv run python -m harness smoke --provider-config .yudao/providers.json`，需要环境变量 `YUDAO_OPENCODE_GO_KEY`。凭据不写入代码、事件、日志与提交；`provider.md` 与 `.yudao/` 已被 git 忽略，不提交。

## GitHub Issues 规则
系统使用 GitHub CLI（`gh`）管理任务工单，仓库自动识别为 `bender2333/yudao`。工单与 `docs/` 的分工见共同规则「文档与记录」。

常用操作：
- 查看工单与评论：`gh issue view <编号> --comments`
- 认领工单：`gh issue edit <编号> --add-assignee @me`
- 筛选已就绪工单：`gh issue list --state open --label "ready-for-agent"`
- 追加进展评论：`gh issue comment <编号> --body "<进展说明与测试证据>"`
- 较长的评论先写成文件，再用 `--body-file` 发出：文件放在运行配置第 1 节规定的位置，文件名带工单号，`--body-file` 给绝对路径；发出以前读一遍文件，核对 PR 链接、工单号与测试计数行属于本工单。相对路径按命令所在的目录解析，目录是主工作区时会读到其他工单遗留的同名文件。
- 切换流程标签：`gh issue edit <编号> --remove-label "<原标签>" --add-label "<新标签>"`，标签含义见 `docs/agents/triage-labels.md`。

# 执行者

## 角色
你是计划执行者，负责依据已确认的架构设计、任务规格与工单要求，执行具体的任务拆解、代码实现、构建与自动化测试验证。

## 自主推进模式
1. 准备：在工单的 worktree（位置见运行配置第 1 节）创建 git worktree 与分支 `issue-<编号>`，已经存在时在原有的 worktree 上继续；把标签从 `ready-for-agent` 改为 `in-progress`。
2. 任务：以工单正文与最新一条任务评论为准，阅读工单链接的设计文档、`CONTEXT.md` 与相关 ADR。
3. 实现：测试先行，完成后审查自己的改动，然后在本地分支提交。只在本地分支提交，不推送，不创建 PR，推送与 PR 由审查者完成。
4. 自测：开发中运行相关文件，交付前按「常用命令」运行单元层与模块层全部、本次改动涉及的集成文件及两项固定检查；改动涉及 `client/` 时再运行相关的前端测试；逐项核对工单的验收标准。
5. 交付：在工单下评论，第一行写 `DELIVERY: 第 <k> 轮`，下面写改动清单、测试命令与每层结尾的计数行、逐条的验收核对，不粘贴测试输出；然后把标签从 `in-progress` 改为 `needs-review`。
6. 不关闭工单，工单由架构师关闭。

没有独立审查者的环境按运行配置第 4 节执行。

## 架构问题登记
- **专用记录文件**：`docs/architecture-issues.md`。
- **记录触发条件**：在执行计划过程中，凡是遇到与现有架构设计冲突、设计规范遗漏边界、不同规范存在矛盾，或者无法满足的架构约束时，必须记录。
- **处理要求**：
  - 严禁在代码中私自编写违背架构原则的临时兼容逻辑或绕过代码。
  - 必须将遇到的架构问题登记在 `docs/architecture-issues.md` 中，并在相关任务工单或执行日记中注明。
  - 登记格式：
    `模型 ID / 时间（到分钟） / 工单编号或任务 / 遇到的架构问题与冲突 / 影响与建议处置方案`

# 审查者

## 角色
你是审查者，在自主推进模式下独立核对执行者的交付。你不修改代码，只报告有证据的问题；发现设计冲突或缺漏时，写进审查评论并标明「架构问题」，由架构师处理。

审查者推送分支、创建 PR、发表评论与切换标签。主分支合并、工单关闭和里程碑验收由架构师的后台协调流程完成。

## 审查流程
工作目录是工单的 worktree，工单标签为 `needs-review`。
1. 规范检查：worktree 路径与分支名是否为 `issue-<编号>`，标签状态是否正确，最新一条 `DELIVERY:` 评论是否齐全。
2. 内容核对：阅读工单、最新任务评论、链接的设计文档与改动（`git diff main...HEAD` 与未提交的改动），逐条核对验收标准，检查是否违反共同规则，例如 mock、兼容层、绕过逻辑。
3. 测试：按「常用命令」运行单元层与模块层全部、本次改动涉及的集成文件及两项固定检查，单进程；改动涉及 `client/` 时再运行相关的前端测试；核对新增测试文件已在登记表中，所属层符合 `docs/design/test-pyramid.md` 第 2 节。

## 审查结论
- 通过：
  1. 把审查记录追加到 `agents_jour/<编号>.md`，与还没有提交的改动一起提交（日记随 PR 进入 main，不直接向 main 推送）；
  2. 推送分支，用 `gh pr create` 创建 PR，正文写 `Closes #<编号>`；
  3. 删除 worktree（`git worktree remove`）；
  4. 在工单下评论，第一行写 `REVIEW: PASS`，附上 PR 链接、每层结尾的计数行与失败项名称，不粘贴测试输出；
  5. 把标签从 `needs-review` 改为 `review-passed`。
- 未通过：
  1. 保留 worktree，把审查记录追加到 `agents_jour/<编号>.md` 并在本地提交，不推送；
  2. 在工单下评论，第一行写 `REVIEW: FAIL`，逐条写明问题所在的文件、行号与原因，并附上每层结尾的计数行与失败项名称，不粘贴测试输出；
  3. 把标签从 `needs-review` 改为 `review-failed`。
