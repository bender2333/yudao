# bender2333/yudao CI 设计方案（GitHub Issues + GitHub Actions）

> 状态：调研草案，只在本地，没有写入 GitHub（没有建分支、工单、评论、标签或 workflow）。
> 依据：origin/main（2026-10-13 拉取）的 AGENTS.md、CLAUDE.md、docs/agents/*、docs/design/test-pyramid.md，再加上下文列出的 GitHub 官方文档。
> 标【未验证】的是推断或没有实测的内容。

## 0. 先确认的事实

| 事实 | 依据 |
|---|---|
| 仓库是**私有**的 | `gh repo view bender2333/yudao --json visibility` 返回 `{"visibility":"PRIVATE"}` |
| 仓库属于个人账户，类型是 User | `gh api repos/bender2333/yudao -q .owner.type` 返回 `User` |
| 仓库里还**没有** `.github/` 目录，也就是没有任何 workflow | 在 origin/main 上执行 `ls .github` 报“不存在” |
| Actions 已经启用，允许使用所有 action | `gh api repos/bender2333/yudao/actions/permissions` 返回 `{"enabled":true,"allowed_actions":"all"}` |
| **分支保护和规则集在这个仓库上用不了** | `gh api .../branches/main/protection` 和 `.../rulesets` 都返回 403：“Upgrade to GitHub Pro or make this repository public to enable this feature.” |
| 有 `uv.lock`（200K）和 `client/package-lock.json` | 本地克隆 |
| 测试登记表 `harness/tests/layers.toml`：unit 19 个文件、module 42 个、integration 94 个、desktop 0 个 | 用 grep 统计 |
| Python 版本要求 `>=3.11`；dev 依赖组里有 pytest、pytest-xdist、pytest-timeout、import-linter 等 | pyproject.toml |

**额度要更正一下**：按官方计费页，GitHub Free 的私有仓库每月包含 **2,000 分钟**（不是 500），制品存储 500 MB，缓存每个仓库 10 GB；公共仓库使用标准 runner 完全免费。官方页面现在不再写“Windows 2x / macOS 10x”这种倍率，改成按每分钟单价计费：Linux 2 核 $0.006、Windows 2 核 $0.010、macOS $0.062、Linux 1 核（ubuntu-slim）$0.002。2,000 分钟的包含额度在不同 runner 之间怎么折算，页面没有写清楚【未验证】，下面的估算一律按 Linux 2 核、1 分钟扣 1 分钟来算。

**并发上限**：Free 计划使用标准 runner 时，总并发 20 个 job，macOS 最多 5 个。这个上限不分公共和私有仓库。

## 1. 规则原文（作为依据）

AGENTS.md：
- 第 2 行：「执行者按工单实现代码并完成自测；审查者核对执行者的交付，运行单元层、模块层与改动相关的测试，审查通过后提交并发起 PR。」
- 第 31 行：「每次都运行 `uv run python -m pytest harness/tests/test_layers.py harness/tests/test_openapi_snapshot.py`：两项检查整个仓库的模块导入关系与接口合同……」
- 第 32 行：「只用单进程运行，不加 `-n`。集成层全部由架构师按批运行，执行者与审查者不运行全量测试……单条命令不超过 10 分钟。」
- 第 56 行：「3. 实现：测试先行，完成后审查自己的改动，然后在本地分支提交。只在本地分支提交，不推送，不创建 PR，推送与 PR 由审查者完成。」
- 第 58 行：「5. 交付：在工单下评论，第一行写 `DELIVERY: 第 <k> 轮`……然后把标签从 `in-progress` 改为 `needs-review`。」
- 第 76 行：「你是审查者……你不修改代码，只报告有证据的问题……」
- 第 78 行：「审查者推送分支、创建 PR、发表评论与切换标签。主分支合并、工单关闭和里程碑验收由架构师的后台协调流程完成。」
- 第 84 行：「3. 测试：按「常用命令」运行单元层与模块层全部、本次改动涉及的集成文件及两项固定检查，单进程；改动涉及 `client/` 时再运行相关的前端测试；核对新增测试文件已在登记表中……」
- 第 88–92 行（通过）：「1. 把审查记录追加到 `agents_jour/<编号>.md`……2. 推送分支，用 `gh pr create` 创建 PR，正文写 `Closes #<编号>`；3. 删除 worktree……4. 在工单下评论，第一行写 `REVIEW: PASS`……5. 把标签从 `needs-review` 改为 `review-passed`。」
- 第 94 行（未通过）：「1. 保留 worktree，把审查记录追加到 `agents_jour/<编号>.md` 并在本地提交，不推送；」

CLAUDE.md：
- 第 16 行：「修改规则文件（`CLAUDE.md`、`AGENTS.md`、`docs/agents/`）或调整已有设计文档之前，先向用户说明修改内容，确认后再修改。」
- 第 141 行（收尾）：「标签为 `review-passed` 且已有 PR：Claude 检查 issue 评论、标签与 PR 内容是否齐全……不重复运行测试。核对通过后执行 `gh pr merge --squash --delete-branch`，关闭工单……」
- 第 143 行：「4. 集成层：上次 `INTEGRATION: PASS` 以后合并满 5 个 PR……在集成层的 worktree 检出 main 的当前提交，按运行配置的命令后台运行集成层。」
- 第 146 行：「5. 搁置：同一工单 3 轮审查仍未通过……Claude 给工单加上 `ready-for-human` 标签……」

docs/agents/autopilot-runtime.md 第 53 行（aipro 单人流程）：「5. 确认 CI（如果仓库配置了）通过后，直接合并 PR 并关闭工单……没有 CI 时，以本地测试结果为准直接合并。」这说明规则里已经给 CI 留了位置。
docs/agents/triage-labels.md 第 78 行：「同一时间一个工单只带其中一个，切换时去掉原标签。」（指 in-progress、needs-review、review-passed、review-failed 这四个流程标签）

## 2. 核心约束：现在 CI 只能在“审查者推送”之后才会触发

执行者只在本地提交（第 56 行）。分支第一次出现在 GitHub 上，是审查**通过**以后审查者推送的时候（第 89 行）；审查**未通过**的分支不推送（第 94 行）。所以按现行规则：

- CI 帮不上执行者自测，也帮不上审查者在审查过程中跑测试，因为那时代码还不在远端。
- 在现行规则下，CI 只能当作 PR 合并前的一道**复核**（第二意见），给架构师在第 141 行“收尾”时看。

可选方案：

| 方案 | 做法 | 要不要改规则 | 优点 | 缺点 |
|---|---|---|---|---|
| **A. 保持现状，CI 只做 PR 门禁**（推荐先做） | 审查者照旧推送并 `gh pr create`；CI 在 `pull_request` 上运行；架构师合并前看 `gh pr checks` | AGENTS.md 不用改；CLAUDE.md 第 141 行建议加一句“合并前确认 CI 通过”，要用户确认（第 16 行） | 改动最小，每个 PR 只跑一次，最省额度 | 审查者还是要在本地跑一遍测试；CI 失败时工单已经是 review-passed，要退回 |
| B. 审查者先推送、等 CI、再下结论 | 审查第 3 步改成：推送分支→开草稿 PR→等 `gh pr checks --watch`→用 CI 结果代替本地测试 | 要改 AGENTS.md 第 84、88–96 行（未通过也要推送，和第 94 行冲突），要用户确认 | 审查者不用在本地重跑 module 层（每次约 3.5 分钟），并能直接引用 CI 链接作为证据 | 每轮审查都消耗额度；未通过的分支也会出现在远端 |
| C. 执行者交付时推送分支 | 执行者第 5 步推送 `issue-<n>`（push 触发 CI），审查者读 CI 结果 | 要改 AGENTS.md 第 56 行，要用户确认 | 审查开始时 CI 结果已经出来 | 额度消耗最大（每轮交付都跑）；和“推送与 PR 由审查者完成”的分工相冲突 |

推荐：**先上 A**，跑一两周，量出 Linux runner 上的真实耗时以后，再决定要不要升级到 B。B 和 C 都要改规则文件，必须先由用户确认。

## 3. workflow 文件结构（草案，没有提交）

```
.github/workflows/
  ci.yml            # PR 门禁：fixed-checks + unit-module + related-integration（+ client 按路径）
  integration.yml   # 集成层批量运行：只用 workflow_dispatch 手动触发（见第 6 节，建议默认不启用）
```

### 3.1 ci.yml 触发条件与要点

```yaml
name: ci
on:
  pull_request:
    branches: [main]
    paths-ignore:
      - 'docs/**'
      - '**/*.md'
      - 'agents_jour/**'
  workflow_dispatch:
concurrency:
  group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
  cancel-in-progress: true
permissions:
  contents: read
jobs:
  python:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    env: { PYTHONUTF8: '1' }
    steps:
      - uses: actions/checkout@<固定 SHA>
        with: { fetch-depth: 0 }          # 需要和 main 比较，算出改动文件
      - uses: astral-sh/setup-uv@<固定 SHA>
        with: { enable-cache: true }      # 缓存键跟 uv.lock 走
      - run: uv sync --frozen
      - uses: actions/setup-node@<固定 SHA>   # test_openapi_snapshot 要用 npm 依赖（见风险 R3）
        with: { node-version: '24', cache: npm, cache-dependency-path: |
                  client/package-lock.json
                  harness/tests/openapi/package-lock.json }
      - run: npm ci --prefix harness/tests/openapi && npm ci --prefix client
      - name: 两项固定检查
        run: uv run python -m pytest harness/tests/test_layers.py harness/tests/test_openapi_snapshot.py
      - name: 单元层与模块层
        run: uv run python -m pytest -m "unit or module" --junitxml=.tmp/test-results/unit-module.xml
      - name: 改动涉及的集成文件
        run: |
          files=$(git diff --name-only origin/main...HEAD -- 'harness/tests/test_*.py' 'harness/tests/**/test_*.py' \
                 | python scripts/ci_pick_integration.py)   # 只挑 layers.toml 里登记为 integration 的文件（脚本待写）
          [ -z "$files" ] || uv run python -m pytest $files
      - if: always()
        run: python scripts/ci_summary.py >> "$GITHUB_STEP_SUMMARY"   # 每层的计数行，格式和 REVIEW 评论一致（脚本待写）
  client:
    if: 只在 client/** 或 harness/tests/openapi/** 有改动时运行   # 用 dorny/paths-filter 或 git diff 判断
    runs-on: ubuntu-latest
    steps: [checkout, setup-node, "cd client && npm ci && npm test"]
```

说明：
- `pull_request` 默认在 PR 的 merge 分支（`refs/pull/N/merge`）上测试，也就是“合并以后的结果”；PR 有合并冲突时不会触发运行（官方文档 events-that-trigger-workflows）。
- `paths-ignore` 让纯文档 PR 不跑 CI。不过没有分支保护时，“必需检查一直卡在 Pending”的问题不存在，所以可以放心用路径过滤。
- `concurrency` 加 `cancel-in-progress`：同一个 PR 又推送了新提交时，取消旧的运行，省额度。
- **“改动相关的集成文件”只能取改动或新增的测试文件**，这和 test-pyramid.md 第 4 节「本次改动或新增的集成层测试文件在 PR 中运行」一致。哪些源码对应哪些集成测试，现在没有映射表，CI 推不出来。现在审查者是靠人判断的（比如 #469 加跑了 `test_event_sequence.py`）。要补上，可以在 DELIVERY 或 PR 正文里约定一行 `CI-INTEGRATION: <文件列表>`，由 CI 解析。这需要改规则，要用户确认。
- 单进程运行，不加 `-n`，遵守第 32 行。
- 在 Linux 上运行的差异：现在执行者和审查者都在 Windows 上跑（autopilot-runtime.md 第 17 行写了 PowerShell 和 UTF-8 的设置），审计钩子对 ProactorEventLoop 有特殊的放行逻辑（test-pyramid.md 第 2.1 节）。Linux 上的结果可能和 Windows 不一致，所以第一周要并行比对【未验证】。

### 3.2 权限

默认 `contents: read`。CI 本身**不改标签、不写评论**，标签由审查者和架构师切换（triage-labels.md 第 80–87 行）。要让 CI 把结果写到工单评论里的话，可以给单独的 job 加 `issues: write` 和 `pull-requests: write`（官方文档 workflow-syntax 的 permissions 一节）。不过这会让 CI 也成为写标签或评论的一方，和“一个流程标签由谁加上”的规定冲突，所以**不推荐**。

注意官方文档：用 `GITHUB_TOKEN` 创建或更新的 PR，触发的 `pull_request` 运行需要人工批准；其他由 `GITHUB_TOKEN` 触发的事件根本不会产生运行。审查者用的是本人 `gh` 登录的身份，不受这个限制。

## 4. 标签和 CI 状态的对应

| 工单标签 | 远端状态（方案 A） | CI 状态 | 由谁读 |
|---|---|---|---|
| ready-for-agent / in-progress | 没有分支 | 没有 | — |
| needs-review | 没有分支（审查在本地） | 没有 | — |
| review-failed | 不推送（第 94 行） | 没有 | — |
| review-passed | 分支和 PR 都在 | **pending / success / failure** | 架构师：`gh pr checks <PR> --required=false` 或 `--watch` |
| 合并以后 | main | （可以选择在 push main 时不跑，省额度） | — |

CI 失败时的回路（方案 A）：
1. 架构师按第 141 行收尾时执行 `gh pr checks <PR>`，发现失败。
2. 按第 141 行「核对发现验收范围内的未解决问题时，写任务评论并按 `review-failed` 处理」：把失败的 job 名、失败项和运行链接写进任务评论，标签改回 `ready-for-agent`。
3. 执行者下一轮在原来的分支（`issue-<n>` 已经推送）上修复；审查通过后再推送，PR 自动更新，CI 重跑。
4. 按 test-pyramid.md 第 4.2 节和 acceptance-evidence.md 第 2 节：如果 CI 失败但在 Windows 本地能通过，就当作环境差异或测试不稳定处理，另建工单，不算在本工单头上。这条怎么判定要用户或架构师决定。

方案 B 下，审查者在 `REVIEW: PASS` 或 `REVIEW: FAIL` 里附上 CI 运行链接和计数行，代替本地计数。

**没有分支保护**：Free 计划的私有仓库不能把 CI 设成“必需检查”（已经用 API 实测到 403）。门禁只能靠流程自觉：架构师在 `gh pr merge` 之前必须先执行 `gh pr checks`。要强制的话，可以选：升级到 GitHub Pro，或者把仓库改成公开（公开仓库的标准 runner 也免费）。这两样都要用户决定。

## 5. 额度估算（GitHub Free 私有仓库，2,000 分钟/月）

实测数据（来自工单评论，都是在用户的 Windows 机器上，单进程）：

| 来源 | 单元层 | 模块层 | unit 加 module 合计 | 固定检查 | 相关集成 |
|---|---|---|---|---|---|
| #469 REVIEW（10-13） | 373 项 17.50s | 530 项 214.90s | — | 3 项 9.92s | test_event_sequence 43 项 80.88s |
| #480 DELIVERY（10-13） | — | — | 903 项 217.15s | — | 88 项 35.88s，47 项 77.74s |
| #479 DELIVERY（10-12） | — | — | 896 项 235.62s | 16 项 17.71s | test_event_sequence 85.75s |
| #464（10-12） | — | — | — | — | 20 项 31.07s，11 项 25.70s |
| 集成层全部 `-n 2`（#9，10-12） | — | — | — | — | 1150 项 1227.24s（20.5 分钟） |

PR 合并频率（`gh pr list --state merged`，最近 7 天）：10-07 22 个，10-08 2 个，10-09 6 个，10-10 12 个，10-11 6 个，10-12 8 个，10-13 到目前 4 个。**平均每天约 8.6 个**。

每次 CI 运行的估算（Linux 2 核，假设和 Windows 机器速度相当【未验证，可能慢 1–2 倍】）：
- 环境准备（checkout、uv sync 命中缓存、npm ci）：约 1.5–2 分钟【未验证】
- 固定检查：约 0.3 分钟
- unit 加 module：约 4 分钟
- 相关集成：0–1.5 分钟（取平均 1 分钟）
- **合计约 7 分钟/次**；如果 Linux runner 慢一倍，约 12 分钟/次。

| 场景 | 每月运行次数 | 每月分钟 | 占 2,000 分钟的比例 |
|---|---|---|---|
| 方案 A，每个 PR 跑 1 次，加 20% 重跑 | 8.6×30×1.2 ≈ 310 | 7 分钟时约 2,170；12 分钟时约 3,700 | **108%–185%，超额** |
| 方案 A，每天 5 个 PR | 180 | 1,260–2,160 | 63%–108% |
| 方案 B，平均 1.5 轮审查 | ≈ 390 | 2,700–4,700 | 超额 |
| 集成层在 Actions 上跑（每 5 个 PR 一次，`-n 2` 约 20.5 分钟以上） | ≈ 52 | ≈ 1,070 以上 | 单这一项就占一半 |

结论：**按最近的节奏，免费的 2,000 分钟只勉强够方案 A 本身，集成层放不下。** 省额度的办法：
1. 纯文档 PR 不跑（`paths-ignore`），只改 client 的 PR 跳过 Python job，只改 Python 的 PR 跳过 client job。
2. `cancel-in-progress` 取消同一 PR 的旧运行；main 上的 push 不跑（合并前已经测过 merge 结果）。
3. `setup-uv enable-cache` 和 npm 缓存，减少环境准备时间（缓存额度 10 GB/仓库，足够）。
4. 把 module 层拆成单独的 job 并行跑，**不省分钟，只省等待时间**（并发上限 20 个）。
5. **Self-hosted runner**：官方文档说 self-hosted runner 使用 Actions 免费。可以装在用户的 Windows 机器上（这样还和本地环境一致，但这台机器已经同时跑着多个执行者和审查者，见 autopilot-runtime.md 第 19 行），或者装在 aipro 板子上【未验证性能】。在私有仓库上用 self-hosted runner 时，要留意只有自己的 PR 能触发运行。
6. 改成公开仓库：标准 runner 免费、不限分钟，还能用分支保护。但这样代码就公开了，要用户决定。

## 6. 集成层 job（integration.yml）

- 现在的规则是由架构师在本地 `-n 4` 后台跑（autopilot-runtime.md 第 29–30 行、CLAUDE.md 第 143–145 行），结果写成 `INTEGRATION: PASS <sha>` 评论。
- 放在 GitHub 托管的 runner 上：每次 20 分钟以上，每月约 1,000 分钟以上，免费额度里放不下（见第 5 节）。**建议只在 self-hosted runner 上用**，或者只准备一个 `workflow_dispatch` 手动入口，在里程碑前用。
- 写法要点：`on: workflow_dispatch`（入参是 sha）；`concurrency: { group: integration, queue: max }`，排队运行、不互相取消；`uv run python -m pytest -m integration -n 2 --junitxml=...`；用 `actions/upload-artifact` 上传 junit（制品额度 500 MB，要设保留天数）；评论 `INTEGRATION: PASS` 仍然由架构师来发，CI 不发。
- 还可以用 `workflow_run` 在 ci 完成以后串联别的 workflow，但官方文档说最多串 3 层，而且有缓存投毒的风险。这里用不到，不推荐。

## 7. 风险与未决事项

- R1 **没有分支保护**（已实测 403）：CI 只能提示，不能拦住合并。
- R2 **额度紧张**：见第 5 节；Linux runner 的真实耗时要第一周量过才知道。
- R3 **test_openapi_snapshot 依赖 npm**：#469、#464、#457 的评论都提到，缺 `harness/tests/openapi/node_modules` 时会失败，所以 CI 必须先 `npm ci`。
- R4 **Windows 和 Linux 的差异**：审计钩子和事件循环的放行逻辑是按 Windows 写的；集成层已知有并发 SQLite 不稳定的情况（#457：`test_issue_317_onboarding_interruption...`、`test_busy_does_not_block...`）。
- R5 **秘钥**：真实模型 smoke 要用 `YUDAO_OPENCODE_GO_KEY`（AGENTS.md 第 35 行），CI **不跑** smoke，也不配置这个秘钥。
- R6 **执行者不推送**：用方案 A 时，CI 失败要退回整整一轮，代价高。这是方案 B 存在的理由。
- R7 **路径不一致**：运行配置写的 worktree 是 `C:\project\yudao-worktrees`，#469 的认领说明写的是 `D:\codes\yudao-worktrees`。这和 CI 无关，只记在这里。

**要用户拍板的事**：
1. 选方案 A、B 还是 C（B 和 C 要改 AGENTS.md，按 CLAUDE.md 第 16 行要先确认）。
2. 额度不够时怎么办：收紧触发条件、用 self-hosted runner（装在哪台机器）、升级 Pro（能用分支保护，3,000 分钟），还是把仓库公开。
3. 集成层要不要上 CI，还是继续在本地跑。
4. 要不要约定 `CI-INTEGRATION:` 这一行来声明相关集成文件。
5. CI 失败但 Windows 本地能通过时，算谁的问题。

## 8. 打开过的来源

- GitHub Actions 计费（Free 计划 2,000 分钟、各 runner 单价、self-hosted 和公共仓库免费）：https://docs.github.com/en/billing/concepts/product-billing/github-actions
- Actions 限制（Free 计划并发 20 个、macOS 5 个、job 最长 6 小时、缓存速率限制）：https://docs.github.com/en/actions/reference/limits
- 触发事件（pull_request 在 merge 分支上运行、有冲突时不运行、GITHUB_TOKEN 触发的限制、workflow_run 最多 3 层、push）：https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows
- Workflow 语法（paths 和 paths-ignore、跳过的检查停在 Pending、concurrency 和 queue、permissions、私有仓库 runner 规格：ubuntu-latest 2 核 8 GB）：https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions
- uv 在 GitHub Actions 中的用法（setup-uv、enable-cache、actions/cache 用 uv.lock 做键、`uv cache prune --ci`）：https://docs.astral.sh/uv/guides/integration/github/
- 本仓库通过 gh 实测：仓库可见性、分支保护和规则集返回 403、Actions 权限、合并的 PR 列表、REVIEW 和 DELIVERY 评论（#469、#479、#480、#464、#457、#355、#9）。
- 没有单独打开的官方页面：`gh pr checks` 的手册、Checks API 页面、GITHUB_TOKEN 专页、protected branches 的可用性页面。分支保护能不能用，是靠 API 的 403 实测的；GITHUB_TOKEN 权限引用的是 workflow 语法页的 permissions 一节。
