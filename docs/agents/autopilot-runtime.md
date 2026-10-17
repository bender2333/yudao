# 自主推进的运行配置

自主推进用到的机器、账号、路径、命令、模型与参数都写在这里，`CLAUDE.md`、`AGENTS.md` 与[派发者规则](dispatcher.md)只写流程。换机器、换模型、换路径、换账号、调整参数时只改这份文件、`omp-print-runs.yml` 与 main 的规则定义 `main-ruleset.json`。

## 1. 机器与路径

### 1.1 派发的机器

doctor（Hermes）在这台 Windows 电脑上担任派发者，执行者、审查者、被唤醒的架构师与集成层也在这里运行。

| 用途 | 路径 |
| --- | --- |
| 工单的 worktree | `D:\codes\yudao-worktrees\issue-<编号>`，分支 `issue-<编号>` |
| 集成层的 worktree | `D:\codes\yudao-worktrees\integration` |
| 被唤醒的架构师的 worktree | `D:\codes\yudao-worktrees\architect`，不建分支，每次启动前检出 main 的当前提交 |
| 较长的评论与审查（`--body-file`） | 工单 worktree 的 `.tmp\` 下，文件名带工单号，`--body-file` 给这个绝对路径 |

### 1.2 架构师的 Windows 电脑

Claude 担任派发者时使用这里的路径。

| 用途 | 路径 |
| --- | --- |
| 工单的 worktree | `C:\project\yudao-worktrees\issue-<编号>`，分支 `issue-<编号>` |
| 集成层的 worktree | `C:\project\yudao-worktrees\integration` |
| 被唤醒的架构师的 worktree | `C:\project\yudao-worktrees\architect`，不建分支，每次启动前检出 main 的当前提交 |
| 较长的评论与审查（`--body-file`） | `C:\project\yudao-worktrees\issue-<编号>\.tmp\` 下，文件名带工单号，`--body-file` 给这个绝对路径 |
| OMP（oh-my-pi） | `C:\project\codes\oh-my-pi` |
| OpenCode | `C:\project\codes\opencode` |
| semantica | `C:\project\codes\semantica` |
| 外部设计研究库（Obsidian） | `C:\Users\BA_H3C_Pad\Documents\Obsidian Vault\Obsidian\项目研究\Yudao` |

### 1.3 两台机器共同的约束

PowerShell 的测试终端先设置 `$env:PYTHONUTF8='1'`，让 Python 及其测试子进程统一输出 UTF-8；pytester 的子进程输出按 UTF-8 读取。

机器上同时运行着多个执行者、审查者与集成层测试。只能结束自己启动、并且记下了进程号的进程（`kill <进程号>`），不允许按进程名结束进程（例如 `taskkill /IM python.exe`），也不允许结束不是自己启动的进程。

## 2. 账号与令牌

| 身份 | 谁用 | 在仓库上的权限 |
| --- | --- | --- |
| 开发 App（`yudao-dev`） | 执行者 | Contents、Pull requests、Issues：读写；Actions：读写（重新运行失败的 CI）；Checks、Commit statuses：只读；没有 Workflows 权限，推送不了 `.github/workflows` |
| 审查 App（`yudao-review`） | 审查者 | Pull requests：读写（提交审查）；Contents、Issues、Actions、Checks、Commit statuses：只读 |
| `bender2333` | 用户、架构师（包括被唤醒的架构师）、派发者 | 仓库所有者，main 规则唯一可以豁免的身份 |

- 两个 App 只安装在 `bender2333/yudao`。私钥文件放在派发的机器上仓库以外的目录。
- 执行者与审查者的进程启动前设置 `YUDAO_GH_APP_ID`（App 编号）与 `YUDAO_GH_APP_KEY_FILE`（私钥文件路径），并把仓库的 `scripts/github-app/` 放在 `PATH` 的最前面。之后进程里的 `gh` 与 `git push` 以这个 App 的身份运行，令牌快到期时自动换新（#513）。
- `scripts/github-app/` 下的 `gh.exe` 与 `git.exe` 是入口，由同目录的 `make_entries.py` 生成并提交（#526）。入口用 `PATH` 上的第一个 `python` 运行 `yudao_github_app.py`，它在 `PATH` 上跳过本目录找到真正的 `gh` 与 `git`，换取安装令牌后转过去。入口是真正的可执行文件，参数不经过 `cmd` 重新解析，`|`、`&`、`^`、`(`、`)`、`%`、引号、空格与中文原样到达；`cmd`、PowerShell、Git bash 与 `gh` 自己调用 `git` 都命中入口。修改 `make_entries.py` 以后运行 `uv run python scripts/github-app/make_entries.py` 重新生成，`harness/tests/test_github_app_entries.py` 核对提交的入口与生成的逐字节相同。
- `PATH` 的写法（`<仓库>` 是仓库的位置，例如 `D:\codes\yudao`）：
  - `cmd`：`set "PATH=<仓库>\scripts\github-app;%PATH%"`，例如 `set "PATH=D:\codes\yudao\scripts\github-app;%PATH%"`。
  - PowerShell：`$env:PATH = "<仓库>\scripts\github-app;" + $env:PATH`。
  - Git bash：盘符写成 `/d/` 的形式，用冒号分隔，例如 `export PATH="/d/codes/yudao/scripts/github-app:$PATH"`。写成 `D:/codes/...` 时 Git bash 把 `D:` 后面的冒号当作分隔符，`which gh` 仍然得到 `C:\Program Files\GitHub CLI\gh`。
  - 设置以后 `which gh`（Git bash）或 `where gh`（`cmd`）的第一行应当是 `scripts/github-app` 下的入口。
- 令牌换取按需进行：安装令牌一小时过期，缓存放在 `%LOCALAPPDATA%\yudao\github-app-token-<App 编号>.json`，剩余有效时间不到 10 分钟时换新，否则复用。缓存只写令牌与过期时刻，私钥与令牌的内容不出现在命令输出、日志与提交中。
- 安装编号由 App 编号与仓库所有者自动查到，不另外配置。
- 两个变量都没有设置时，入口直接运行原来的 `gh` 与 `git`，参数与退出码原样传递。私钥文件不存在或不可读时报错写明是哪个变量、哪个路径，不回退到其他身份。
- 派发者与被唤醒的架构师使用 `gh auth login` 登录的 `bender2333`，不设置这两个变量。
- 角色之间靠配置分开：同一台机器上，一个角色的进程读得到另一个角色的私钥。需要更严格时，让每个角色用不同的系统用户运行。

## 3. 命令

omp 的配置是 [omp-print-runs.yml](omp-print-runs.yml)：关闭后台命令，执行者与审查者的命令都在前台运行，测试结果能交回。

命令里的时长取自第 7 节的参数表，调整时两处一起改。

- 派发执行者（在工单的 worktree 中后台运行，进程环境按第 2 节设置开发 App）：
  `omp -p --mode json --auto-approve --max-time 4h --config docs/agents/omp-print-runs.yml "你是执行者，按 AGENTS.md「执行者」一节处理工单 #<编号>"`
- 派发审查者（同一个 worktree，进程环境按第 2 节设置审查 App）：
  `omp -p --mode json --auto-approve --max-time 4h --no-prewalk --config docs/agents/omp-print-runs.yml --model <审查者模型> "你是审查者，按 AGENTS.md「审查者」一节以及两类角色共同遵守的内容工作，忽略「执行者」一节。审查工单 #<编号> 的 PR（issue-<编号> 分支）"`
- 启动被唤醒的架构师（在架构师的 worktree 中后台运行，记下进程号；进程环境不设置第 2 节的 App 变量，设置提交的署名 `GIT_AUTHOR_NAME`、`GIT_COMMITTER_NAME` 为 `claude-架构师`，`GIT_AUTHOR_EMAIL`、`GIT_COMMITTER_EMAIL` 为 `noreply@anthropic.com`）：

  ```bash
  git fetch origin main
  git checkout --detach origin/main
  claude -p --model <架构师模型> --effort <架构师 effort> --dangerously-skip-permissions --output-format json \
    "你是被唤醒的架构师，按 CLAUDE.md「被唤醒的架构师」一节处理全部带 needs-architect 标签的工单" \
    > .tmp/architect-<日期时刻>.json
  ```

- 打开自动合并：`gh pr merge <PR> --auto --squash`；关掉：`gh pr merge <PR> --disable-auto`。
- 集成层（在集成层的 worktree 中后台运行）。派发者在交付以后、审查以前检出 PR 的合并提交；架构师在试用之前改为检出 main 的当前提交（`git fetch origin main` 以后 `git checkout --detach origin/main`）：

  ```bash
  git fetch origin pull/<PR>/merge
  git checkout --detach FETCH_HEAD
  uv sync --frozen
  uv run python -m pytest -m integration -n 4 --junitxml=.tmp/test-results/integration.xml
  ```

工单合并以后，派发者删除工单的 worktree（`git worktree remove`）。重新派发同一张工单之前先清掉残留目录（只剩 `.tmp` 与 `.venv` 的目录会被当作已有工作区，执行者会在空目录里运行）。

## 4. 模型

| 角色 | 模型 | 说明 |
| --- | --- | --- |
| 执行者 | omp 配置的默认模型，当前 `9router/oro` | 按配置使用 prewalk |
| 审查者 | `9router/gemini` | 用 `--model` 指定，与执行者的模型不同 |
| 被唤醒的架构师 | `claude-opus-5-5`，effort `xhigh` | Claude Code，用 `--model` 与 `--effort` 指定 |
| 备用链 | `9router/ds`、`9router/gemini` | 写在机器上 omp 全局配置的 `retry.fallbackChains` 中 |

`task` 子代理请求会让执行者停滞，任务评论里写明不使用子代理。

## 5. CI

- 定义：`.github/workflows/ci.yml`，由架构师维护，修改前经用户确认。
- 每个 PR 与 main 的每次推送在 GitHub 提供的 `windows-latest` 上运行检查 `check`：安装依赖，单元层与模块层（包括两项固定检查），客户端的类型检查与单元测试（逐场景回放测试除外，按 `AGENTS.md` 单独运行），编译页面与 wheel。
- 查看结果：`gh pr checks <PR>`；重新运行失败的运行：`gh run rerun <运行编号> --failed`。

## 6. main 的规则

- 定义：[main-ruleset.json](main-ruleset.json)，GitHub 上的规则名为 `main`，只由 `bender2333` 修改：
  `gh api --method PUT repos/bender2333/yudao/rulesets/<规则编号> --input docs/agents/main-ruleset.json`。规则编号用 `gh api repos/bender2333/yudao/rulesets --jq '.[] | [.id, .name, .enforcement] | @tsv'` 查。
- 仓库设置：只允许 squash 合并，允许自动合并，合并以后删除分支。
- 豁免记录（架构师每次会话开始时查）：

  ```bash
  gh api "repos/bender2333/yudao/rulesets/rule-suites?rule_suite_result=bypass&time_period=week" \
    --jq '.[] | [.pushed_at, .actor_name, .after_sha] | @tsv'
  gh api repos/bender2333/yudao/commits/<after_sha>/pulls --jq '.[].number'
  ```

  第二条命令有输出的，是经豁免合并的 PR；没有输出的，是架构师直接推送的文档与日记（被唤醒的架构师的提交作者是 `claude-架构师`）。

## 7. 参数

规则文件只写不随数字变化的句子，数字写在这里。调整参数只改这张表（第 3 节命令里的时长一起改），记入 `docs/CHANGELOG.md`，下一次派发起生效。

| 参数 | 当前值 | 用在哪里 |
| --- | --- | --- |
| 执行者一轮的时长 | 4 小时 | 第 3 节派发执行者的 `--max-time`；`AGENTS.md` 共同要求 |
| 审查者一轮的时长 | 4 小时 | 第 3 节派发审查者的 `--max-time` |
| 同一个 PR 要求修改的上限 | 3 次，第 3 次时搁置 | 派发者规则第 3 节第 4、5 步 |
| 工单大小的上限 | 「只改」清单中手写文件 15 个；生成的客户端类型、接口快照、事件序列基准与日记不计 | `CLAUDE.md`「工单规范」；`AGENTS.md` 执行者第 2 步 |
| 同时进行的 `touches-core` 工单 | 1 张（`in-progress` 与 `needs-review` 合计） | 派发者规则第 3 节第 1 步 |
| 核心文件 | 工具定义：`harness/tools.py`、`harness/definitions/`；控制核心：`harness/` 下的 `orchestrator.py`、`engine.py`、`recording.py`、`assembly.py`、`context.py`、`compaction.py`、`adjudication.py`、`validation.py`、`write_path.py`、`event_store.py`、`projection.py`、`decisions.py`、`runtime.py`；执行环境：`harness/` 下的 `environment.py`、`actions.py`、`workspace.py`；事件序列基准：`harness/tests/event_sequences/`、`harness/tests/prompt_snapshot.json`；接口合同：`harness/tests/openapi/openapi.json`、`client/src/renderer/src/api/generated/` | `CLAUDE.md`「工单规范」 |
| 唤醒架构师 | 开 | 派发者规则第 3 节第 7 步；用户在场的会话做大的设计修改时改为关，做完改回 |
| 被唤醒的架构师一次运行的时长 | 4 小时 | 派发者规则第 3 节第 7 步 |
| 同一张工单唤醒架构师的上限 | 2 次，第 3 次直接交给用户 | `CLAUDE.md`「被唤醒的架构师」 |
