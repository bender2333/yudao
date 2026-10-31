# 运行配置

solo 执行者与架构师循环用到的机器、账号、路径、命令、模型与参数都写在这里，[工作方式](workflow.md)、`CLAUDE.md`、`AGENTS.md` 与技能只写流程。换机器、换模型、换路径、换账号、调整参数时只改这份文件、`omp-print-runs.yml` 与 main 的规则定义 `main-ruleset.json`。

## 1. 机器与路径

### 1.1 Hermes 的机器

doctor（Hermes）在这台 Windows 电脑上运行 solo 执行者与集成层。

| 用途 | 路径 |
| --- | --- |
| 工单的 worktree | `D:\codes\yudao-worktrees\issue-<编号>`，分支 `issue-<编号>` |
| 集成层的 worktree | `D:\codes\yudao-worktrees\integration` |
| 架构师循环的 worktree | `D:\codes\yudao-worktrees\architect`，不建分支，每次启动前检出 main 的当前提交 |
| 较长的评论（`--body-file`） | 工单 worktree 的 `.tmp\` 下，文件名带工单号，`--body-file` 给这个绝对路径 |

集成层与架构师循环的 worktree 长期保留，不存在时在主工作区用 `git worktree add --detach <路径> origin/main` 建立。工单的 worktree 在工单关闭以后删除（第 3 节）。除这三类以外不另建目录。

### 1.2 架构师的 Windows 电脑

| 用途 | 路径 |
| --- | --- |
| 工单的 worktree | `C:\project\yudao-worktrees\issue-<编号>`，分支 `issue-<编号>` |
| 集成层的 worktree | `C:\project\yudao-worktrees\integration` |
| 架构师循环的 worktree | `C:\project\yudao-worktrees\architect`，不建分支，每次启动前检出 main 的当前提交；架构师循环长期占用这一个 worktree |
| 较长的评论（`--body-file`） | `C:\project\yudao-worktrees\issue-<编号>\.tmp\` 下，文件名带工单号，`--body-file` 给这个绝对路径 |
| 真实评测 | `C:\project\yudao-worktrees\eval-<提交前 8 位>`：检出被测的提交，运行期间不切换，结束以后删除；运行目录与原始证据在仓库之外；长时间运行用 `Start-Process pwsh -File <脚本>` 启动，不用会话里的后台命令（会话空闲、内存不足时会被结束） |
| OMP（oh-my-pi） | `C:\project\codes\oh-my-pi` |
| OpenCode | `C:\project\codes\opencode` |
| semantica | `C:\project\codes\semantica` |
| 外部设计研究库（Obsidian） | `C:\Users\BA_H3C_Pad\Documents\Obsidian Vault\Obsidian\项目研究\Yudao` |

### 1.3 两台机器共同的约束

两台机器把 `PYTHONUTF8=1` 设成用户环境变量（Windows：`setx PYTHONUTF8 1`，之后新开的终端生效），任何终端与 harness 里的 Python 及其测试子进程都输出 UTF-8；pytester 的子进程输出按 UTF-8 读取。

共享的 `C:/code/yudao/.venv` 是 editable 安装，它的 `harness` 指向最近一次 `uv sync` 的那个 worktree，会随别的会话的同步而变。工人在自己的 worktree 里跑「导入 `harness` 的脚本」或嵌套起子进程的用例时，带 `PYTHONPATH=<worktree 根>`，否则导入会落到别人那一份上；报错形态是「莫名 import 错」或与本单无关的怪失败。

各角色只使用第 1 节列出的目录。架构师在会话中临时建的 worktree，会话结束之前删除。

机器上同时运行着多个 solo 工人与集成层测试。只能结束自己启动、并且记下了进程号的进程（`kill <进程号>`），不允许按进程名结束进程（例如 `taskkill /IM python.exe`），也不允许结束不是自己启动的进程。

## 2. 账号与令牌

| 身份 | 谁用 | 在仓库上的权限 |
| --- | --- | --- |
| `bender2333` | 用户、架构师（包括架构师循环）、solo 执行者、审查子代理 | 仓库所有者，main 规则唯一可以豁免的身份；solo 执行者只在合并自己范围内的 PR 时使用（`solo-worker` 技能），架构师用它直接推送文档与日记 |

`gh` 用 `gh auth login` 登录的 `bender2333`。`scripts/github-app/` 里的 `gh.exe` 与 `git.exe` 入口能让进程以 GitHub App 的身份运行（设置 `YUDAO_GH_APP_ID` 与 `YUDAO_GH_APP_KEY_FILE`，并把这个目录放在 `PATH` 最前面）；两个变量都不设时入口原样运行真正的 `gh` 与 `git`，参数与退出码原样传递。改 `make_entries.py` 以后运行 `uv run python scripts/github-app/make_entries.py` 重新生成，`harness/tests/test_github_app_entries.py` 核对提交的入口与生成的逐字节相同。

## 3. 命令

命令里的时长取自第 7 节的参数表，调整时两处一起改。

- 启动架构师循环（用户不在场时接住 solo 交回的工单、子工单已关闭的父工单、已经达到的薄片，做法见 [`/next`](../../.claude/skills/next/SKILL.md)）：在架构师循环的 worktree 里开一个不需要逐条确认权限的会话，设置提交的署名 `GIT_AUTHOR_NAME`、`GIT_COMMITTER_NAME` 为 `claude-架构师`，`GIT_AUTHOR_EMAIL`、`GIT_COMMITTER_EMAIL` 为 `noreply@anthropic.com`，然后在会话里起循环：

  ```bash
  git fetch origin main
  git checkout --detach origin/main
  claude --model <架构师模型> --effort <架构师 effort> --dangerously-skip-permissions
  # 会话里输入（范围写法与 solo 相同）：
  /loop 30m /next <范围> --循环
  ```

  循环跑在这个会话里，会话关掉就停；重新打开会话、再输入一次启动命令即接着做，状态全在 GitHub 与 `.ralph/architect/heartbeat.json`。宿主没有 `/loop` 时用它的定时机制按第 7 节的间隔叫起同一个技能，间隔与上下文换法不变。

- 启动 solo 执行者（用户指定 solo 范围时，在主工作区或工单的 worktree 中运行；设置署名 `GIT_AUTHOR_NAME`、`GIT_COMMITTER_NAME` 为 `solo-<模型 ID>`；`gh` 用 `bender2333` 登录的身份）：
  - Claude Code 的循环：会话里输入 `/solo <范围>`（[`/solo`](../../.claude/skills/solo/SKILL.md)）。
  - 单独运行：`claude -p --model <solo 模型> --dangerously-skip-permissions --output-format json "你是 solo 执行者，按 .claude/skills/solo-worker/SKILL.md 逐张处理范围 <范围> 内的工单"`。一次启动处理到范围内没有可以领取的工单为止，或者到第 7 节一轮的时长。
  - 用 omp 运行时，配置是 [omp-print-runs.yml](omp-print-runs.yml)：关闭后台命令，命令都在前台运行，测试结果能交回。
- 在本机运行集成层（在集成层的 worktree 中后台运行）。平时集成层由 CI 在每次合并以后运行（第 5 节）；本机运行用于和 CI 的结果对照，或者 CI 不可用的时候：

  ```bash
  git fetch origin main
  git checkout --detach origin/main
  uv sync --frozen
  uv run python -m pytest -m integration -n 4 --junitxml=.tmp/test-results/integration.xml
  ```

- 导出里程碑的工单记录（复盘时，`/milestone-retro`）。`<短名>` 例如 `phase1-1`；有上一个里程碑的记录时加 `--previous`：

  ```bash
  uv run python evals/baseline/milestone.py collect --milestone "<里程碑标题>" --data docs/evaluation/milestones/<短名>.json
  uv run python evals/baseline/milestone.py report --data docs/evaluation/milestones/<短名>.json     --report docs/evaluation/milestones/<短名>.md --previous docs/evaluation/milestones/<上一个短名>.json
  ```

- 清理工单的 worktree（`/solo` 循环里由 `solo.mjs gc` 清；单独运行的 solo 与架构师在会话结束前清）。在主工作区运行，不要在要删的目录里运行；`<worktree 目录>` 是第 1 节工单 worktree 的上级目录，例如 `D:/codes/yudao-worktrees`。只删已经关闭的工单，分支保留。Windows 上有进程占用目录时，`git worktree remove` 只删掉内容、留下空目录，所以接着删除目录本身：

  ```bash
  for dir in <worktree 目录>/issue-*; do
    number=${dir##*issue-}
    [ "$(gh issue view "$number" --json state --jq .state)" = CLOSED ] || continue
    git worktree remove --force "$dir" 2>/dev/null
    rm -rf "$dir"
  done
  git worktree prune
  ```

  删除失败（文件被占用）的目录留到下一次。重新领取同一张工单之前，先清掉它的残留目录：只剩 `.tmp` 与 `.venv` 的目录会被当作已有工作区，工人会在空目录里运行。

## 4. 模型

| 角色 | 模型 | 说明 |
| --- | --- | --- |
| solo 执行者 | 启动时用 `--model` 指定，署名里带模型 ID | 用 omp 运行时取 omp 配置的默认模型，当前 `9router ag/gemini-3.8-flash-high` |
| 审查子代理（内核 PR） | 与这张工单的 solo 执行者不同的模型 | 判断才独立 |
| 架构师循环与它的子代理 | `claude-opus-5-5`，effort `xhigh` | 这一层做设计判断，判断错了比多用的量贵；它与 solo 执行者用不同的模型，判断才独立 |
| 试用的两个模型 | model1 `wb/cn:deepseek-v4.1-flash` 给产品与工程；model2 `ag/gemini-3.8-flash-high` 给质检、找问题与看图 | 分工见 [`/trial`](../../.claude/skills/trial/SKILL.md)第 1 节的表；地址与凭据取下面的 `YUDAO_EVAL_*` |
| 备用链 | `9router/ds`| 写在机器上 omp 全局配置的 `retry.fallbackChains` 中 |
| 真实模型测试与评测 | `qhub/Qwen3.8-Flash`（9router，Chat Completions） | 见下面；评测的界面智能体与裁判见[评测场景设计](../design/evaluation-scenarios.md)「丰富程度（场景 1）」 |

用 omp 运行时，`task` 子代理请求会让工人停滞，任务评论里写明不使用子代理。

需要真实模型的测试、真实模型 smoke 与评测工作线使用同一套设置，放在运行机器的用户环境变量中（用户提供）：

| 变量 | 内容 |
| --- | --- |
| `YUDAO_EVAL_BASE_URL` | 9router 的地址 |
| `YUDAO_EVAL_API_KEY` | 凭据，不写进仓库、工单、PR、日志与日记 |
| `YUDAO_EVAL_MODEL` | 模型名，与上表一致；换模型时两处一起改 |

会话进程里可能没有 `YUDAO_EVAL_API_KEY`（用户级有、这个进程没继承），`YUDAO_VISION_API_KEY` 也没有；`vision.mjs` 在没有 `SOLO_VISION_*` 时沿用 `YUDAO_EVAL_API_KEY`，所以看图只缺这一样。用到凭据的命令，先在本进程里补一行再跑，值只在进程里存在，不写进文件、评论与日记：

```powershell
$env:YUDAO_EVAL_API_KEY = [Environment]::GetEnvironmentVariable('YUDAO_EVAL_API_KEY', 'User')
```

- 不用 9router 上 `cc/` 分组的模型。
- 不放进 CI：CI 没有这三个变量，需要模型的测试在 CI 中不运行。
- 用户级的环境变量只对设置以后启动的进程生效；修改以后，重新启动 solo 与架构师循环的会话。

## 5. CI

- 定义：`.github/workflows/ci.yml`，由用户在场时的架构师维护，solo 执行者与架构师循环不修改。
- 每个 PR 与 main 的每次推送在 GitHub 提供的 `windows-latest` 上并行运行四个作业：① 单元层、② 模块层（各含一项固定检查）、评测工具（`evals/tests`，`real_model` 的用例默认不选）、客户端（类型检查与单元测试，逐场景回放测试除外，按 `AGENTS.md` 单独运行；编译页面与 wheel）。汇总作业 `check` 在四项都成功时成功，是 main 的规则要求的检查，并在运行摘要里写出各层的表。PR 上另有「用例变化」：合并前后各层用例的增减，只显示，不挡合并（[测试分层设计说明](../design/test-pyramid.md)「CI 中的分层」与「用例的变化」）。
- main 的每次推送（每次合并以后）另外运行 ③ 集成层（作业 `integration`）：集成层全部（`-n 4`，在 main 上约 15 分钟），每个合并提交各自运行，不互相取消。它不是合并必须通过的检查，PR 上不运行，失败由 solo 执行者按 `solo-worker`「main 上的 CI」处理。带 `touches-core` 的工单例外：solo 执行者在交付前对自己的分支手动触发一次（`solo-worker` 第 8 步）。结果文件作为运行的附件 `integration-results` 保存，用 `gh run download <运行编号> -n integration-results` 取回。
- 手动触发（`check` 与 `integration` 都运行）：`gh workflow run CI --ref <分支>`，例如工单要在 GitHub 的运行机上验证集成层时 `gh workflow run CI --ref issue-<编号>`；之后用 `gh run list --workflow CI --branch <分支> --limit 1` 找到运行，`gh run watch <运行编号>` 等结果。
- main 上的结果：`gh run list --workflow CI --branch main --event push --limit 10`；某次运行的失败项：`gh run view <运行编号> --log-failed | grep FAILED`。
- 查看 PR 的结果：`gh pr checks <PR>`；重新运行失败的作业：`gh run rerun <运行编号> --failed`。

## 6. main 的规则

- 定义：[main-ruleset.json](main-ruleset.json)，GitHub 上的规则名为 `main`，只由 `bender2333` 修改：
  `gh api --method PUT repos/bender2333/yudao/rulesets/<规则编号> --input docs/agents/main-ruleset.json`。规则编号用 `gh api repos/bender2333/yudao/rulesets --jq '.[] | [.id, .name, .enforcement] | @tsv'` 查。
- 仓库设置：只允许 squash 合并，允许自动合并，合并以后删除分支。
- 豁免记录（架构师每次会话开始时查，`/next`「每次开始」）：

  ```bash
  gh api "repos/bender2333/yudao/rulesets/rule-suites?rule_suite_result=bypass&time_period=week" \
    --jq '.[] | [.pushed_at, .actor_name, .after_sha] | @tsv'
  gh api repos/bender2333/yudao/commits/<after_sha>/pulls --jq '.[].number'
  ```

  第二条命令有输出的，是经豁免合并的 PR：用 `gh pr view <PR 编号> --json body --jq .body` 看正文里有没有 `Solo:` 行（`solo-worker` 技能第 7 步要求写），有的是 solo 的合并，记入 `claude_jour.md`，其余的告诉用户。没有输出的，是架构师直接推送的文档与日记（架构师循环的提交作者是 `claude-架构师`）。

## 7. 参数

规则文件只写不随数字变化的句子，数字写在这里。调整参数只改这张表（第 3 节命令里的时长一起改），记入 `docs/CHANGELOG.md`，下一次启动起生效。

| 参数 | 当前值 | 用在哪里 |
| --- | --- | --- |
| solo 执行者一轮的时长 | 4 小时 | 第 3 节；`AGENTS.md` 共同要求 |
| 工单大小的上限 | 「只改」清单中手写文件 15 个；生成的客户端类型、接口快照、事件序列基准与日记不计 | `docs/agents/ticket-spec.md`；`solo-worker` 第 3 步 |
| 核心文件 | 工具定义：`harness/tools.py`、`harness/definitions/`；控制核心：`harness/` 下的 `orchestrator.py`、`engine.py`、`recording.py`、`assembly.py`、`context.py`、`compaction.py`、`adjudication.py`、`validation.py`、`write_path.py`、`event_store.py`、`projection.py`、`decisions.py`、`runtime.py`；执行环境：`harness/` 下的 `environment.py`、`actions.py`、`workspace.py`；事件序列基准：`harness/tests/event_sequences/`、`harness/tests/prompt_snapshot.json`；接口合同：`harness/tests/openapi/openapi.json`、`client/src/renderer/src/api/generated/`；可信内核：`harness/definitions/kernel-manifest.json` 里 `kind` 为 `module` 的路径 | `touches-core`（[工作方式](workflow.md)第 4 节）；`docs/agents/ticket-spec.md` |
| 架构师循环 | 开 | `/next --循环` 每一轮先读，关着时整轮不做；solo 运行期间保持开。用户在场的会话做大的设计修改时改为关，做完改回开 |
| 架构师循环的间隔 | 30 分钟 | 第 3 节启动命令；一轮只做一件，做完结束回合 |
| 同一张工单分诊的上限 | 2 次，第 3 次直接交给用户 | [`/triage`](../../.claude/skills/triage/SKILL.md) |
| 一个薄片交给用户之前的缺陷修复上限 | 2 轮，第 3 轮连同两轮的证据交给用户 | [`/trial-intake`](../../.claude/skills/trial-intake/SKILL.md)「薄片推进」 |
| 后台长运行算作失败的超时 | 各自预算加 1 小时，重跑一次，再失败交给用户 | [`/next`](../../.claude/skills/next/SKILL.md)「长运行与心跳」 |
