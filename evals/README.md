# 评测工具

本目录是与 `harness/` 分开的评测工具，只通过公开接口观察 Yudao（[评测场景设计](../docs/design/evaluation-scenarios.md)第 7 节）。场景 3 是从较长的 PRD 新建项目，场景 2 是在已有代码上加功能。

## 目录结构

```mermaid
flowchart TD
    M[scenarios/scenario-3/materials<br/>PRD、接口约定、条目表、起点] --> R[运行器]
    M --> S[scorer]
    C[scenarios/scenario-3/checks<br/>24 条隐藏检查与零件] --> S
    F[scenarios/scenario-3/files<br/>subway_data.json] --> R
    REF[scenarios/scenario-3/reference<br/>参考实现] --> S
```

场景 2 的材料来自公开数据集 FeatBench：交付的起点是 `openai/openai-agents-python` 在任务基准提交上的仓库，材料里记录提交号，运行器检出它并按锁文件建立 Python 3.13 环境。

- `scenarios/scenario-2/materials/`：需求原文（`requirement.md`，FeatBench 的 problem_statement 原文）、需求条目表（`requirement-table.json`）、材料来源与运行环境（`manifest.json`）。
- `scenarios/scenario-2/checks/`：8 条 F2P（`f2p.json`）、331 条 P2P（`p2p.json`）、登记的排除用例（`excluded.json`）、隐藏测试文件（`tests/`，按交付里的相对路径存放）与清单模块（`pytest_checks.py`）。
- `scenarios/scenario-2/reference/gold.patch`：参考实现，FeatBench 记录的 gold patch。
- `scenarios/scenario-2/validate.py`：核对材料本身——套上参考实现应当 8 条 F2P 全通过且 P2P 失败 0 条，原样的仓库 8 条全不通过且 P2P 失败 0 条。
- `scenarios/scenario-3/materials/`：需求原文（`prd.md`，PRD 的英文译本）、接口约定（`interface-agreement.md`）、需求条目表（`requirement-table.json`）、交给被测方的起点（`start/files/`）。这些是公开部分，运行时交给被测方。
- `scenarios/scenario-3/files/`：题目数据文件 `subway_data.json`，运行器放到起点。
- `scenarios/scenario-3/checks/`：隐藏检查。只有评分器读取，不进入被测方的运行目录，运行结束以后才复制到评分目录。
- `scenarios/scenario-3/reference/`：参考实现，只由评分器用来确认检查本身没有写错。
- `scorer/`：评分器，对一份交付运行隐藏检查并写出机器可读结果。
- `runner/`：OpenCode 一侧的运行器、指标收集与报告（`run_eval.py` 是入口）。它把材料起点复制到仓库之外的运行目录，运行 `opencode run`，从 JSON 事件流收集指标，再用评分器评分，最后写出机器可读结果与中文报告。
- `runner/yudao.py`、`yudao_metrics.py`、`yudao_report.py`：Yudao 一侧的运行器、指标收集与报告（`run_yudao_eval.py` 是入口）。运行器只经 HTTP 接口驱动 Yudao，只从 `run.export` 导出的事件日志观察它，不导入 `harness` 的任何模块，也不引用被测方内部文件的路径。它在仓库之外新建数据目录启动被测的 Yudao，写入被测模型并经模型测试准入，建立项目、绑定三个部门、登记场景 3 的命令（`run_cli` 与 `check_data`，按接口约定第 5 节的命令行入口），以用户原始意图提交需求原文加接口约定，到时间上限时经 `work_item.cancel` 结束并标记超时；运行结束以后导出事件日志，取最后一次封存的交付交给评分器，并计算过程检查点与指标。
- `baseline/`：omp 流程开发 Yudao 的基线数字。`collect.py` 抓取 Stage 3 里程碑下的工单、标签时间线与评论、合并请求、阶段父工单 #9 的集成层记录与运行目录里的运行输出，合成一个数据文件；`compute.py` 只读这个数据文件，算出每个工单的审查轮数、集成层失败归因、搁置原因、耗时与用量，写出中文报告。
- `tests/`：评分器与运行器自己的测试，全部运行真实代码，不使用 mock。基线工具的测试读录制的数据文件，同样不使用 mock。`test_yudao_runner.py` 用 `harness/tests/event_sequences/` 里的系统事件序列驱动同一套 `run.export` 形状的判定逻辑；这些序列的事件头是 `adapter: fake`，不是真实系统导出，凡是需要真实导出才能核实的项记「未核实」。`test_regen_scenario3.py` 用 `runner/regen_scenario3.py` 从仓库内固定的历史 JSON（`data/scenario-3-yudao-historical.json`，提交 `aaa91883` 的旧版原文，不可修改）重算 `docs/evaluation/scenario-3-yudao.json` 与 `.md`，与已提交的文件逐字节比对；以已提交的新 JSON 为输入重算同样逐字节一致（幂等）。`test_no_harness_paths.py` 用 `ast` 扫描并折叠字符串拼接与 `os.path.join` 字面量参数，再比对被测方内部文件路径。

## 材料版本

场景 3 的材料版本是 `scenario-3@2`，场景 2 的是 `scenario-2@1`。修改需求原文、需求条目表、隐藏检查、运行环境或参考实现中的任意一项，版本号加一，新旧版本的结果不直接比较。

## 需求条目与检查

场景 3 有 7 个需求条目与 24 条检查，对应见 `scenarios/scenario-3/materials/requirement-table.json`（评分器内的对应表在 `checks/command_checks.py` 的 `REQUIREMENT_TABLE`，两者一致）。检查分三类：单元 12 条、命令行 10 条、文件比对 2 条。

场景 2 有 6 个需求条目与 8 条 F2P 的对应，见 `scenarios/scenario-2/materials/requirement-table.json`。8 条 F2P 计入完成度与正确性；331 条 P2P 是原有功能测试，失败条数单独报告，不影响完成度（[评测场景设计](../docs/design/evaluation-scenarios.md)第 4.2 节）。隐藏测试文件以文件形态放在 `checks/tests/` 下，评分时盖掉交付里的同名文件，被测方改测试不改变评分。

## 运行评分器

```bash
uv run python evals/scorer/scorer.py --delivery <交付目录> --result <结果文件>
```

场景 3 的评分器把交付当作一个带 `src/` 子目录的项目。场景 2 的评分器针对一份仓库：`--delivery` 指向交付副本，评分器把隐藏测试文件盖上去，再用交付自带的 Python 3.13 环境运行 F2P 与 P2P 两份清单。

## 运行评分器自己的测试

```bash
uv run python -m pytest evals/tests
```

## 运行一次评测

模型服务的地址与凭据只从环境变量读，不写入代码、事件、日志与提交：

```bash
export YUDAO_EVAL_BASE_URL=<模型服务地址>
export YUDAO_EVAL_API_KEY=<凭据>
uv run python evals/runner/run_eval.py \
    --scenario scenario3 \
    --model yudao-eval/<模型名> \
    --runs 3 \
    --runs-root <Yudao 仓库之外的目录> \
    --result docs/evaluation/scenario-3-opencode.json \
    --report docs/evaluation/scenario-3-opencode.md
```

场景 2 用 `--scenario scenario2`，结果写到 `scenario-2-opencode.json` 与 `scenario-2-opencode.md`。它的运行目录就是检出好的仓库本身：建立环境需要 GitHub 与 PyPI，这一步发生在运行之前，评测运行本身不联网。
Yudao 一侧用同一个模型、同一个环境变量：

```bash
uv run python evals/runner/run_yudao_eval.py \
    --model <模型名> \
    --runs 3 \
    --runs-root <Yudao 仓库之外的目录> \
    --result docs/evaluation/scenario-3-yudao.json \
    --report docs/evaluation/scenario-3-yudao.md
```

Yudao 一侧的运行器保证下面这些：

- 只经 HTTP 接口与导出的事件日志观察 Yudao，不导入 `harness` 的模块（`tests/test_no_harness_import.py` 检查这一点），也不引用被测方内部文件的路径（`tests/test_no_harness_paths.py` 检查这一点）。
- 被测的 Yudao 在仓库之外的数据目录上启动，每次运行新建一个数据目录，用默认的执行位置（控制主机上的本机进程）。
- 三个部门的部门默认绑定与项目部门设置都使用被测模型；模型先经 `catalog.model.test` 准入，报告记录模型服务实际服务的模型名。
- 项目不登记取回的来源与 MCP 服务器，部门没有这两类工具。
- 到墙钟上限时经 `work_item.cancel` 结束事项，标记超时，按最后一次封存的交付评分；没有交付时全部检查记为「没有做」。
- 导出的事件日志里出现材料目录的路径时这次运行作废，写进报告。

### 五项过程检查点（第 5.1 节）

Yudao 一侧的过程检查点共五项，每项给通过 / 未通过 / 未核实三种取值：

1. 在冻结限额内以放行结束：阶段为 `DONE`，停止原因为 `released`，存在当前交付快照的质检放行，用量在冻结限额以内。`no_tool_call`、取消、超时、模型服务故障与进程退出都记未通过。
2. 质检放行绑定最后一次封存的交付：`qa.code_snapshot_hash` 等于最后封存的 `code_tree_digest`，`qa.delivery_spec_hash` 等于 `content_hash`，质检引用的每条回执 `activation_id` 在质检部门本次激活列表里；冻结的比例只在 `run_created` 的 `parameters_version` 可识别时按比例核对，导出中没有给出现值，读不到时本项记「未核实」。
3. 重放结果与记录一致：`replay.check` 返回一致；没有取到重放结果记未通过。
4. 质检没有误放行：放行而隐藏检查中存在失败条目记未通过；没有放行时本项不适用（放行不存在，隐藏检查的失败由评分报告单独写出）。
5. 放行记录附逐条覆盖、模型阅读与开环条件：放行记录缺逐条覆盖数据时写「未核实」不记未通过；覆盖比例小于 1.0、模型阅读条件数大于 0、开环条件数大于 0 记未通过。

### 用量的未知值

模型服务没有分项统计时，`usage.totals` 的那一项是 `None`，按「未知」写入报告，不进平均值、最小、最大与噪声，另计有效样本数与未知样本数及原因，只有来源明确上报的零才记零。取不到单价时费用同样是未知。

Yudao 一侧当前的起点缺口与模型行为记录在 `docs/architecture-issues.md`（本工单的登记）与报告的第八节：新建项目的空工作区没有放入题目数据文件的接口通道，题目提供的 `subway_data.json` 由被测工程按接口约定自行写出；被测模型在工程部门连续返回成功但没有输出项的调用，主机按 `no_tool_call` 暂停。

运行器保证下面这些：

- 运行目录在 Yudao 仓库之外，并且是 git 仓库。没有版本控制的目录被 OpenCode 当成全局目录，交付会落到系统临时目录而不是运行目录。
- 隐藏检查、条目表与参考实现不进入运行目录；它们在运行结束以后才复制到评分目录。场景 2 的运行目录是仓库，材料只把需求原文放进去，隐藏测试文件与两份清单都不进去。
- 取回与搜索工具（`webfetch`、`websearch`）在运行配置里关闭，运行器另外检查 JSON 输出里没有这两类工具的调用。
- 消息用短指示加上材料附件（`prd.md`、`interface-agreement.md`、`subway_data.json`），不把需求全文放进命令行。
- JSON 输出里出现材料目录的路径时这次运行作废（`void`），不计入结果；这类运行在报告的第六节列出。
- 到达墙钟上限时结束进程，按结束时的目录评分并标记超时，不因为没有跑完而作废。

原始证据（交付副本、输出、评分日志）在 `.yudao/evals/` 下，不进入 Git。

## 运行器自己的测试

```bash
uv run python -m pytest evals/tests/test_opencode_runner.py
```


其中三项标记 `needs_model`，真实运行模型（每次数分钟），凭据不在环境变量里时跳过。


## omp 基线数字

`baseline/` 建立 omp 流程开发 Yudao 的基线数字，分抓取与计算两步。抓取经 `gh` 导出 Stage 3 里程碑下的工单、标签时间线与评论、合并请求、阶段父工单 #9 的集成层记录，再读运行目录里 `omp-` 与 `rv-` 开头的运行输出，合成一个数据文件；计算只读这个数据文件，写出逐个工单的数字与中文报告。

```bash
uv run python evals/baseline/collect.py --stage-parent 9 --runs-root C:/project/yudao-worktrees/autopilot/runs --data docs/evaluation/baseline-omp-stage3.json
uv run python evals/baseline/compute.py --data docs/evaluation/baseline-omp-stage3.json --report docs/evaluation/baseline-omp-stage3.md
```

抓取一次约 15 分钟（大量 `gh` 调用），中断以后重跑按工单编号续抓。基线数据文件与报告在 `docs/evaluation/`，测试读录制的数据文件，不调用 `gh`。

## 运行环境

两个场景的运行环境都是 uv 管理的 Python 3.13。场景 3 的评分器与隐藏检查在被测交付的目录之外运行，不在交付目录中写入除导出文件与探测脚本以外的内容。场景 2 的评分器在交付副本的副本里运行，用交付自带的虚拟环境（`uv run --project <交付> --no-sync`），不重新建立依赖。
