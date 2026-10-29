# 工单系统：GitHub Issues

本仓库的工单与规格都是 GitHub Issues，全部操作用 `gh` 命令行。仓库 `bender2333/yudao`，`gh` 在仓库目录内运行时自动从 `git remote -v` 识别。

## 常用写法

- 创建工单：`gh issue create --title "..." --body "..."`，多行正文用 `--body-file`。
- 读取工单：`gh issue view <编号> --comments`，需要时用 `--json` 与 `jq` 取标签与评论。
- 列出工单：`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`，按需加 `--label` 与 `--state`。
- 评论：`gh issue comment <编号> --body "..."`
- 加减标签：`gh issue edit <编号> --add-label "..."` / `--remove-label "..."`
- 关闭：`gh issue close <编号> --comment "..."`

## 执行者与审查者常用

- 读工单的 PR（交付说明与审查）：`gh pr view issue-<编号> --comments`；只取最近一次审查：`gh pr view issue-<编号> --json reviews --jq '.reviews[-1]'`
- 等 CI 的结果：`gh pr checks issue-<编号> --watch`
- 在 GitHub 的运行机上运行集成层（工单带 `touches-core`、工单要求，或要修的失败只出现在运行机上时）：`gh workflow run CI --ref issue-<编号>`，再用 `gh run list --workflow CI --branch issue-<编号> --limit 1` 找到运行，`gh run watch <运行编号>` 等结果，失败项用 `gh run view <运行编号> --log-failed | grep FAILED` 读取。一次约 15 分钟。
- 认领工单：`gh issue edit <编号> --add-assignee @me`
- 筛选已就绪工单：`gh issue list --state open --label "ready-for-agent"`
- 切换流程标签：`gh issue edit <编号> --remove-label "<原标签>" --add-label "<新标签>"`，标签含义见 [triage-labels.md](triage-labels.md)。
- 较长的评论与审查先写成文件，再用 `--body-file` 发出：文件放在运行配置第 1 节规定的位置，文件名带工单号，`--body-file` 给绝对路径；发出以前读一遍文件，核对 PR、工单号与测试计数行属于本工单。相对路径按命令所在的目录解析，目录是主工作区时会读到其他工单遗留的同名文件。

## 工单与 `docs/` 的分工

两个地方各管一样，不合并：

- **GitHub Issues**：工作队列。哪些打开、谁领取、被什么阻塞、是否完成。技能发布的内容都放这里。
- **`docs/`**：设计与证据。需求记录（`docs/requirements/`）、模块设计与架构（`docs/design/`）、路线图与当前验收基线（`docs/program-roadmap.md`、`docs/current-baseline.md`）。长篇论证留在这里，工单只链接，不复制。日记：架构师的 `claude_jour.md` 在仓库根目录，执行者与审查者的在 `agents_jour/<工单编号>.md`（2026-10-06 之前的日记已归档为 `docs/archive/agents_jour.md`）。

## PR 是否作为分诊入口

**否。**（本仓库不把外部 PR 当作功能请求；`/triage` 读取这个标记。）

设为「是」时，PR 走与工单相同的标签与状态，命令换成 `gh pr` 的对应形式：`gh pr view <编号> --comments`、`gh pr diff <编号>`；列出外部 PR 时用 `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`，只保留 `authorAssociation` 为 `CONTRIBUTOR`、`FIRST_TIME_CONTRIBUTOR` 或 `NONE` 的；评论、标签与关闭用 `gh pr comment`、`gh pr edit --add-label`/`--remove-label`、`gh pr close`。工单与 PR 共用一个编号空间，裸写的 `#42` 两者都可能是：先 `gh pr view 42`，再退回 `gh issue view 42`。

## 技能说「发布到工单系统」时

创建一个 GitHub Issue。

## 技能说「取相关工单」时

运行 `gh issue view <编号> --comments`。

## `/wayfinder` 的操作

**地图**是一张工单，**子工单**是它的子项。

- **地图**：一张带 `wayfinder:map` 标签的工单，正文放 Notes、Decisions-so-far、Fog 三段。`gh issue create --label wayfinder:map`。
- **子工单**：作为 GitHub 子工单（sub-issue）挂在地图下（用 `gh api` 调 sub-issues 接口）。不能用子工单时，在地图正文的任务清单里列出，子工单正文开头写 `Part of #<地图编号>`。标签 `wayfinder:<类型>`（`research`、`prototype`、`grilling`、`task`）。领取后分配给负责的开发者。
- **阻塞**：用 GitHub 原生的工单依赖，界面可见。加一条依赖：`gh api --method POST repos/<owner>/<repo>/issues/<子工单>/dependencies/blocked_by -F issue_id=<阻塞方的数据库 id>`，其中数据库 id 用 `gh api repos/<owner>/<repo>/issues/<n> --jq .id` 取得（既不是 `#编号` 也不是 `node_id`）。GitHub 在 `issue_dependencies_summary.blocked_by` 里只报告未关闭的阻塞方。不能用依赖时，退回在子工单正文开头写一行 `Blocked by: #<n>, #<n>`。所有阻塞方关闭后子工单解除阻塞。
- **前沿查询**：列出地图下打开的子工单（`gh issue list --state open`，限定在地图的子工单或任务清单内），去掉有未关闭阻塞方（`issue_dependencies_summary.blocked_by > 0`，或 `Blocked by` 行里有打开的工单）或已有负责人的，按地图顺序取第一个。
- **领取**：`gh issue edit <n> --add-assignee @me`，是会话的第一次写入。
- **结束**：`gh issue comment <n> --body "<答案>"`，然后 `gh issue close <n>`，再把上下文指针（gist 与链接）追加到地图的 Decisions-so-far。
