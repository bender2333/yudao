# 圈复杂度与变异测试调研

日期：2026-09-29 至 2026-09-30；2026-10-07 补充 cosmic-ray 与 poodle 的实测（第 1.4 节），第 2 节改为在 Windows 上用 poodle。用途：Stage 3 结束之前用户与 Claude 手动进行圈复杂度与变异测试时的方法与依据（[D35](../requirements/self-hosting.md) 已确认第 5 条）；下一阶段研发工具的依据。

## 1. 本仓库的实测

2026-09-29 在 Linux 容器（4 核）中对 main 的提交 `6e83931` 测量。

### 1.1 复杂度

- 圈复杂度（radon 6.0.1）：`harness/`（不含测试）共 1322 个函数；不超过 5 的 982 个，6 至 10 的 185 个，11 至 20 的 109 个，21 至 30 的 27 个，超过 30 的 19 个。
- 最高的函数：`smoke._model_input_audit` 205、`projection.apply_event` 103、`ObservabilityQuery.department` 74、`ContextAssembler.assemble` 67、`LoopConsoleHandler._get_run` 58、`StepDriver._steps` 41。
- 认知复杂度（complexipy 8.0.1）：超过 15 的 113 个，排在最前面的是同一批函数。

### 1.2 变异测试（mutmut 3.8.0）

| 被测代码 | 使用的测试 | 变异数 | 结果 |
| --- | --- | --- | --- |
| `compaction.py` | `test_compaction.py`，37 项，1.4 秒 | 823，4 个进程 67 秒 | 发现 583，存活 240；其中 98 个在圈复杂度 37 的 `plan_compaction` |
| `collaboration.py` | `test_collaboration_rules.py`，59 项，0.6 秒 | 1534 | 536 个所在的函数没有单元测试调用；其余 998 个中发现 667，存活 331 |

- 存活的变异中，改字符串的占一半到三分之二。其中一部分是报错文字，由集成层的事件序列基准核对；另一部分是动作名、部门名、字段名这类业务取值，是真实的漏洞，例如把 `request.action == "revise_requirements"` 中的动作名改掉，没有单元测试失败。字符串不能整类排除。
- 其余存活的变异是边界比较（`>=` 改成 `>`）、`and` 与 `or`、数字、删除参数。例如预算正好用满的边界 `_request_tokens(...) >= material_budget` 没有测试；`max(1, context_window // 10)` 的下限没有测试，它要么是需求、要么是多余的代码。
- 同一次运行中，`definitions` 模块的读取代码被这些测试顺带执行，存活 200 多个变异：代码被执行与被检查是两回事。
- 同一行上的变异合并以后，`compaction.py` 存活与超时的 243 个落在 95 行上，`collaboration.py` 存活的 331 个落在 88 行上。

### 1.3 成本

- mutmut 对每个变异只运行执行过这个函数的测试，从快到慢，遇到第一个失败就停止；存活的变异要把这些测试全部运行完。
- 全量测试带逐项覆盖记录，在 Linux 上约 13 分钟。`apply_event` 被 442 项测试执行（合计 570 秒），`ContextAssembler.assemble` 被 437 项执行，`plan_compaction` 被 418 项执行，多数是运行完整三部门循环、顺带经过这些函数的测试。
- 整个 `harness/` 共 52,196 个变异。只计算 0.1 秒以内的测试，全量运行一次单核需要 15 分钟到 8 小时，但 42% 的变异所在函数没有这么快的测试；放宽到 1 秒以内，上限是单核 500 小时。
- 结论：变异测试要按模块进行，只使用这个模块的单元测试或模块测试，不能使用全部测试。

### 1.4 平台

- mutmut 依赖 fork，3.5.0 起在 Windows 上直接退出，只能在 Linux、WSL 或容器中运行。
- 可以在 Windows 上运行的变异测试工具（2026-09-30 核对，PyPI 标明不依赖操作系统）：
  - cosmic-ray 8.7.0（2026-08-09）：在这台 Windows 11 电脑上用一个小例子实际运行，23 个变异完成，没有测试的边界比较与数字共 5 个存活，结果正确，原文件在运行以后保持不变。
    - 它按 POSIX 规则拆分测试命令（`shlex.split`），反斜杠会被当成转义字符；命令中只写 `python` 时，Windows 找到的是没有装 pytest 的基础解释器。
    - 测试命令要写成虚拟环境中 python 的绝对路径，并用正斜杠。
    - 命令启动失败的变异记为 incompetent，不计入存活，所以报告中「存活 0」要同时核对 incompetent 的数量。
    - 2026-10-07 在另一个小例子上按 `init`、`baseline`、`exec`、`cr-report` 四步运行，22 个变异，存活 4 个（`>=` 改成 `>`、数字、`//` 改成 `/`），原文件保持不变；`local` 分发器一次只运行一个变异。
    - 内置的变异算子（2026-10-07 用 `cosmic-ray operators` 核对）没有替换字符串的一类，只有比较运算符、数字、二元与一元运算符、`and` 与 `or`、`True` 与 `False`、`break` 与 `continue`、异常类型、装饰器、变量、零次循环与加上 `not`。第 1.2 节存活的变异中改字符串的占一半到三分之二，其中有动作名这类真实的漏洞，cosmic-ray 找不出这一类。
  - poodle 1.3.4（2026-04-05）：2026-10-07 在这台电脑上用一个小例子运行，14 个变异，两个进程并行，存活 6 个：改掉动作名的字符串变异（在字符串两边加上 `XX`）、没有测试的边界比较（`>=` 改成 `>`）、数字、`//` 改成 `/`、返回 `None`；原文件保持不变。
    - 它把源文件夹复制到 `.poodle-temp` 下的工作目录，在那里运行测试。源文件夹要设成导入的根目录（本仓库是仓库根，`harness` 在它下面），并用 `file_copy_filters` 排除虚拟环境；只把包目录设为源文件夹时，测试导入的是原文件，全部变异都记为存活。
    - 测试命令按 `shlex.split` 拆分。开始之前先在没有变异的副本上运行一次，失败就停止；之后退出码 0 记为存活，其余退出码都记为发现。
    - 命令行参数里的通配符在 Windows 上会被展开，要变异的文件范围写在配置文件的 `only_files` 中。
  - mutatest 3.1.0（2022-02）与 MutPy 0.6.1（2019-11）已经停止维护。
- 圈复杂度与认知复杂度的工具都能在 Windows 上安装（2026-09-30 核对 PyPI）：complexipy 8.0.1 与 ruff 0.16.9 提供 Windows 的安装包，radon 6.0.1 是不依赖平台的纯 Python 安装包。
- Linux 上全量测试只有 17 项事件序列基准不一致，原因是 `harness/workspace.py` 第 71 行以文本模式写入文件，Windows 上把 `\n` 写成 `\r\n`；基准记录的是 Windows 的结果。#172 已改为整份写入文件不做换行转换，同一动作在任何执行位置写出相同的字节。

## 2. 手动进行的方法

在控制主机的 Windows 上用 poodle 进行（[决策记录](../decision.md) 2026-10-07「Stage 3 剩余的两个专题」一条）。工作目录放在仓库的 `.tmp/` 下（已被 git 忽略），poodle 在其中的 `.poodle-temp/` 下建立工作副本。

1. 取出要检查的提交，建立项目环境：`git archive <提交> harness pyproject.toml uv.lock | tar -x -C .tmp/mut`，在 `.tmp/mut` 中运行 `uv sync --frozen`，再用 `uv pip install poodle==1.3.4` 安装 poodle。
2. 圈复杂度：`uvx --from radon radon cc harness -j --exclude "harness/tests/*"` 输出每个函数的值；圈复杂度是静态分析，与平台无关，与第 1.1 节比较，列出新超过 10 的函数与值变大的函数。
3. 选择模块：优先选择复杂度高、并且有快速单元测试的模块，例如 `compaction.py`、`collaboration.py`、`adjudication.py`、`validation.py`。
4. 在 `.tmp/mut/poodle.toml` 中写配置，只变异一个模块，只用它的测试。源文件夹是导入的根目录 `.`，复制时排除虚拟环境与工作目录；测试命令写虚拟环境中 python 的绝对路径，用正斜杠（第 1.4 节）：

   ```toml
   [poodle]
   source_folders = ["."]
   only_files = ["harness/compaction.py"]
   file_copy_filters = ["__pycache__/**", ".venv/**", ".poodle-temp/**"]
   max_workers = 4

   [poodle.runner_opts]
   command_line = "<.tmp/mut 的绝对路径>/.venv/Scripts/python.exe -m pytest -x -q -p no:cacheprovider harness/tests/test_compaction.py"
   ```

5. 运行 `poodle -c poodle.toml --json <模块名>.json --html <模块名>-html`。poodle 先在没有变异的副本上运行一次测试，失败就停止；结束时列出存活的变异与每个变异的差异，JSON 中 `result.found` 为 `false` 的是存活的变异。全部变异都存活时先检查源文件夹的设置（第 1.4 节）。换一个模块时只改 `only_files` 与测试命令。
6. 第一次正式检查之前，先对 `compaction.py` 运行一次，把存活变异的种类与第 1.2 节 mutmut 的结果比较：改字符串、边界比较、`and` 与 `or`、数字都应当出现。缺少某一类时先查明原因，再检查其他模块。
7. 处理每个存活的变异，三种之一：增加测试（这处行为是需求要的，测试名写明检查的规则）；删除代码（这处行为不是任何需求要的）；写明理由（改动以后行为确实不变，或者由集成层的测试核对）。不添加排除标记（poodle 的 `# nomut`），不设分数目标。
8. 复杂度标出的函数：拆分出有独立含义与名字的函数，或者减少分支；不为降低数字而拆分函数。

## 3. 工具的事实

2026-09-30 核对。

- **mutmut 3.8.0**（2026-09-12）：
  - 先完整运行一次选中的测试，记录每个测试执行了哪些函数；每个变异只运行执行过这个函数的测试。
  - 再次运行时只重新测试源码改变过的函数；没有按 git 差异选择变异的功能。
  - `max_stack_depth` 只把一定调用深度以内执行到函数的测试算作相关，用来排除被大量测试顺带执行的情况。
  - 用 `# pragma: no mutate`（单行、整个缩进块或一段区间）与 `do_not_mutate_patterns` 排除；存活的变异不会让退出码变成非零。
- **radon 6.0.1**（2023-03）：按函数与方法计算圈复杂度，`radon cc -j` 输出 JSON。mccabe 与 ruff 的 C901 默认阈值是 10。
- **complexipy 8.0.1**（2026-09-07）：认知复杂度，默认阈值 15；`--diff <提交>` 只在新函数超过阈值、或原有函数的值上升并超过阈值时失败，已在临时克隆中验证。
- **三个 agent 的 skill 与 MCP**（omp 18.4.3、OpenCode 1.18.33、Claude Code 2.1.284）：
  - 三者都读取仓库中的 `.claude/skills/<名称>/SKILL.md`，无界面运行时同样加载；skill 按 Agent Skills 开放格式编写，`name` 与目录名相同、只用小写字母数字与连字符，`description` 必填。
  - MCP 的项目配置：omp 读取启动目录下的 `.omp/mcp.json`；OpenCode 读取仓库根的 `opencode.json`（本仓库的 `.gitignore` 忽略 `.opencode/` 下除 `agent/` 以外的文件）；Claude Code 读取仓库根的 `.mcp.json`。
  - omp 的 MCP 调用默认 30 秒超时，进度通知不会延长，长时间的调用必须在配置中设置 `timeout`；OpenCode 收到进度通知时重新计时；Claude Code 的工具超时很长，HTTP 空闲时有上限。

## 4. 成熟做法

- **Robert C. Martin**：2016 年的博客指出，把测试里的断言全部删掉，覆盖率不变，变异测试才能说明测试检查了什么。2026 年他用智能体编写代码时说自己不审查智能体编写的代码，只度量覆盖率、依赖结构、圈复杂度、模块大小与变异测试；他的多智能体仓库 swarm-forge 只对改动做变异，CRAP 阈值只检查改动过的文件。他的实验也显示，把分数压得很低会让程序更难阅读，变异测试会驱动出专门针对运算符的测试。swarm-forge 中 CRAP 与变异测试只写在角色提示词里，没有脚本运行或读取它们的结果。
- **Google 的变异测试**（ICSE-SEIP 2018、IEEE TSE 2021）：只变异代码评审中改动的行，每行一个变异，排除日志这类不值得变异的代码，结果作为评审意见，由评审者决定是否必须处理；开发者认为有用的比例从 15% 提高到 89%，每个改动的变异数中位数从 820 降到 7。
- **合并队列**（下一阶段多个写入者时参考）：GitHub 合并队列、bors、Zuul、GitLab merge train 都对合入以后的结果运行检查，再合入主干；Rust 的 bors 一次只运行一个构建，保证每个 PR 测试的正是它将要合入的状态。
- **可复用的检查结果**：Bazel 以命令、输入、环境变量与平台的摘要作为缓存键，输入不变的测试不重新运行。
- **用自己的产品开发自己**：GitLab 用 GitLab.com 管理 GitLab 的开发；Jenkins 在 ci.jenkins.io 上用 Jenkins 构建 Jenkins；rustc 用仓库中按 SHA256 固定的上一个版本编译当前源码。
