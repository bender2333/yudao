# 自主推进的运行配置

自主推进用到的机器、路径、命令与模型都写在这里，`CLAUDE.md` 与 `AGENTS.md` 只写流程。换机器、换模型、换路径时只改这份文件与 `omp-print-runs.yml`。

## 1. 机器与路径（架构师的 Windows 电脑）

| 用途 | 路径 |
| --- | --- |
| 工单的 worktree | `C:\project\yudao-worktrees\issue-<编号>`，分支 `issue-<编号>` |
| 集成层的 worktree | `C:\project\yudao-worktrees\integration` |
| 较长的工单评论（`--body-file`） | `C:\project\yudao-worktrees\issue-<编号>\.tmp\` 下，文件名带工单号，`--body-file` 给这个绝对路径 |
| OMP（oh-my-pi） | `C:\project\codes\oh-my-pi` |
| OpenCode | `C:\project\codes\opencode` |
| semantica | `C:\project\codes\semantica` |
| 外部设计研究库（Obsidian） | `C:\Users\BA_H3C_Pad\Documents\Obsidian Vault\Obsidian\项目研究\Yudao` |

PowerShell 的测试终端先设置 `$env:PYTHONUTF8='1'`，让 Python 及其测试子进程统一输出 UTF-8；pytester 的子进程输出按 UTF-8 读取。

这台机器上同时运行着多个执行者、审查者与集成层测试。只能结束自己启动、并且记下了进程号的进程（`kill <进程号>`），不允许按进程名结束进程（例如 `taskkill /IM python.exe`），也不允许结束不是自己启动的进程。

## 2. 命令

omp 的配置是 [omp-print-runs.yml](omp-print-runs.yml)：关闭后台命令，执行者与审查者的命令都在前台运行，测试结果能交回。

- 派发执行者（在工单的 worktree 中后台运行）：
  `omp -p --mode json --auto-approve --max-time 4h --config docs/agents/omp-print-runs.yml "你是执行者，按 AGENTS.md「执行者」一节处理工单 #<编号>"`
- 派发审查者（同一个 worktree）：
  `omp -p --mode json --auto-approve --max-time 4h --no-prewalk --config docs/agents/omp-print-runs.yml --model <审查者模型> "你是审查者，按 AGENTS.md「审查者」一节以及两类角色共同遵守的内容工作，忽略「执行者」一节。审查工单 #<编号>"`
- 集成层（在集成层的 worktree 检出 main 的当前提交，`uv sync --frozen` 以后后台运行）：
  `uv run python -m pytest -m integration -n 4 --junitxml=.tmp/test-results/integration.xml`

审查者通过后会删除工单的 worktree；重新派发同一张工单之前先清掉残留目录（只剩 `.tmp` 与 `.venv` 的目录会被当作已有工作区，执行者会在空目录里运行）。

## 3. 模型

| 角色 | 模型 | 说明 |
| --- | --- | --- |
| 执行者 | omp 配置的默认模型，当前 `9router/oro` | 按配置使用 prewalk |
| 审查者 | `9router/gemini` | 用 `--model` 指定，与执行者的模型不同 |
| 备用链 | `9router/ds`、`9router/gemini` | 写在这台机器 omp 全局配置的 `retry.fallbackChains` 中 |

`task` 子代理请求会让执行者停滞，任务评论里写明不使用子代理。

## 4. aipro 板子环境（Leela，无独立审查者）

仅适用于：主机名 `orangepiaipro` 这台 aipro 板子上、由 Leela（Hermes Agent）执行、且没有另一个独立 agent 实例可接手审查的场合。满足这三个条件才按本节执行，其余环境仍按 `AGENTS.md` 的自主推进模式，执行者与审查者分离。

本节下 Leela 一人身兼执行者与审查者，流程：
1. 准备、任务、实现与自测：同 `AGENTS.md`「自主推进模式」第 1、2、3 步，但第 3 步的「本地分支提交、不推送、不创建 PR」不适用，允许本地提交。
2. 交付：写 `DELIVERY:` 评论，标签改 `needs-review`。
3. 自我审查：紧接着按 `AGENTS.md`「审查流程」第 2、3 步核对自己的交付（内容核对、测试），不等待另一个 agent 实例。核对通过后，直接在工单下评论 `REVIEW: PASS`（附改动清单、测试命令与计数行），把标签从 `needs-review` 改为 `review-passed`。核对不通过时如实记录问题并继续修复，不跳过这一步、不为了流程走完而放过未通过的检查。
4. 提交、推送、创建 PR（`gh pr create`，正文写 `Closes #<编号>`）。
5. 确认 CI（如果仓库配置了）通过后，直接合并 PR 并关闭工单，不等待人工确认。没有 CI 时，以本地测试结果为准直接合并。
6. 工单关闭后不等待用户下一句话：立刻用 `gh issue list --label ready-for-agent` 查找下一个没有阻塞方（`blocked-by` 为空或全部已关闭）、未分配的工单，按优先级（`bug` 标签优先，其次按阻塞其他工单数量多的优先，其余按工单编号从小到大）选一个接上，重复第 1 步。没有符合条件的工单时才停下汇报「当前没有可接的工单」，不能不检查就假定没有、也不能检查完找到了却仍然停下等待。用户的消息（新指令、纠正、暂停）随时可以打断这个循环，打断优先于继续找下一个工单。
