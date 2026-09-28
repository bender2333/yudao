# 评测场景选题调研

日期：2026-09-28。用途：保存为 [评测场景设计](../design/evaluation-scenarios.md) 选题时核对过的事实，供用户审阅与实施时查证。调研时下载的仓库与数据在会话容器中，没有进入本仓库；这里记录来源、版本与结论。

## 1. 选题要求

- 需求以自然语言给出，有一定篇幅；交付一个功能或一个多文件的小项目。
- 隐藏检查对被测方不可见，检查运行结果，不只看退出码；可以按条统计完成度。
- 至少一个带界面、需要操作的任务，能评价完成的丰富程度。
- 成本可控：每个版本每个场景运行 3 次。
- 模型 DeepSeek V4.1 Flash 能力较强（2026-09-10 发布，模型卡修订 `dba1be0`：配 OpenCode 的 Terminal-Bench 2.1 为 85.0，DeepSWE v1.1 为 65.5，NL2Repo-Bench 为 64.0），接近满分的评测区分不出差别。

## 2. 选用的三个任务

### 2.1 WebGen-Bench 000080 待办清单

- 来源：arXiv 2505.03733（2025-05）；github.com/mnluzimu/WebGen-Bench `c89e074`；数据 HF `luzimu/WebGen-Bench` `c061fe8`，MIT（GitHub 仓库没有许可证文件）。
- 评测共 101 题，647 条人工校对的用例，每题 4 至 11 条；原评测由 WebVoyager 界面智能体（Qwen2.5-VL-32B，每条最多 15 步）执行，给出 YES/PARTIAL/NO，与人工一致率 86.1% 至 94.4%；外观由 GPT-4o 看首页截图按四项 1 至 5 分打分。运行环境 Node.js 加 pm2，Selenium 驱动 Chrome。
- 000080：新建、编辑、删除、标记完成、筛选、搜索，淡紫色背景、靛蓝色组件，441 个字符；8 条用例：新建、编辑、标记完成、删除、搜索、按完成状态筛选、导航、配色。
- 公开成绩（全部 101 题）：Bolt.diy 加 DeepSeek-R1 准确率 27.8%、外观 2.5 分；加 DeepSeek-V3 为 20.8%、2.0 分。
- 选它而没有选 000013（2048 游戏）：2048 的「游戏结束」用例需要大量随机移动，界面智能体 15 步内不稳定。

### 2.2 丰富程度清单：ArtifactsBench

- 来源：arXiv 2507.04952（2025-07）；github.com/Tencent-Hunyuan/ArtifactsBenchmark `88c968b`；HF `tencent/ArtifactsBenchmark` `40e5597`。许可证两处不一致：GitHub 为 CC BY 4.0，HF 为 CC BY-NC 4.0。
- 每题 10 项清单，每项 10 分：前 4 项是题目专属条目，后 6 项为健壮性、创新功能、冗余功能、工程质量、界面视觉、动态交互。裁判 Gemini-2.5-Pro 看 3 张截图加代码，与前端工程师的成对一致率 90.95%（换成 Qwen2.5-VL-72B 为 71.34%），与 WebDev Arena 排名一致性 94.4%。
- 公开代码在页面加载后每隔 1 秒截图，全程没有点击（`src/utils.py` 第 162 至 173 行）；本项目改为截取功能用例执行中的关键状态。
- 1278 号题（待办清单）的清单借用给场景 1：功能扩展（优先级与分类、持久化存储、截止提醒与重复任务）、创新功能（统计、自然语言录入、模板、成就）、视觉（主色不超过 3 种、间距为 8px 的倍数、正文不小于 14px）、交互（标记完成的即时反馈、增删的过渡动画、拖拽排序）。该题 Gemini-2.5-Pro 62 分，DeepSeek-R1-0528 55 分。
- 回归评分的依据：Vibe Code Bench（arXiv 2603.04601）的方差分解显示 73.5% 至 92.5% 的方差来自生成端，同一产物重复评分的标准误为 1 至 3 个百分点，所以每个版本运行 3 次、每次评分 1 次。

### 2.3 FeatBench openai__openai-agents-python-842

- 来源：arXiv 2509.22237（v2 2026-02-18）；github.com/TsinghuaISE/FeatBench `8157fef`，`dataset/featbench_v1_0.json`（156 条）；HF `PGCodeLLM/FeatBench`（main `e2c97e45`，标签 v1.0 `0cb7fc2e`，两者与 GitHub 数据一致）；MIT。论文统计 73.6% 的失败来自智能体擅自扩大改动范围，破坏了已有功能。
- 842：openai-agents-python v0.0.18（2025-06-16）；仓库 363 个文件，包代码 12,657 行；需求 2179 个字符：ModelSettings 新增 `extra_args`，透传给 OpenAI 与 LiteLLM 的调用，多层设置合并时字典合并、覆盖方优先。标准答案改 4 个文件，增加 21 行。
- F2P 8 条：`extra_args` 序列化；resolve 合并（覆盖方优先、一方为空、两方都为空）；LiteLLM 与 Chat Completions 收到透传参数；参数为空的情况。P2P 331 条，分布在 44 个文件。
- Harbor 的 Oracle 验证：pytest 13.0 秒，验证全程 66 秒。镜像 `ghcr.io/kndy666/featbench_openai_openai-agents-python:842`（压缩后 911 MB，Python 3.9，只含依赖；构建时从 GitHub 克隆仓库，验证时 `pip install -e .`，pip 源为 pypi.tuna.tsinghua.edu.cn）。
- 单个 agent 通过情况：论文 8 组运行通过 3 组，Harbor（`harborframework/parity-experiments` `9e2aebde`）9 轮通过 4 轮。8 条用例因缺少 API key 或 pydantic 版本不符而失败，不在清单内。
- 同档另外两个候选：starlette-2671（仓库 6.7 千行，F2P 2 条，通过 1/8 与 2/9，偏难）；pyjwt-886（9 条 F2P 依赖需求里没有给出的属性名 `algorithm_name`，通过 0/8）。

### 2.4 PRDBench 44 Beijing Subway Fare Calculation System

- 来源：arXiv 2510.24358（v3 2026-03-23，AAMAS 2026）；github.com/AGI-Eval-Official/PRDBench `050bbcb`；数据 HF `AGI-Eval/PRDbench` `9eaa708`（与 GitHub 逐个文件一致）；MIT。50 个任务，检查项 408 单元、732 命令行、119 文件比对（论文写 118）。原设定会把 `detailed_test_plan.json` 交给被测方；命令行项由微调的 PRDJudge 判分，固定接口模式与人工一致率 91.75%。公开成绩只有平均值：DeepSeek-V3.2 配最简智能体 40.11%，Claude Code 56.65%，Codex 62.09%。
- 44：读取 `subway_data.json`（293 个站、339 条连接），Dijkstra 计算最短距离、最少换乘、综合最优，支持最大换乘数与线路偏好，分段票价，命令行连续输入「起点;终点」，导出文本与 JSON，检查数据完整性。PRD 125 行、1409 个英文单词。
- 检查 23 条：单元 11、文件比对 2、命令行 10（全部是「起点;终点」输入，没有菜单）。例：`Sum_money(6000)==4`、`Sum_money(52000)==8`；天安门东到西单 2142 米、到中关村 13771 米；`max_transfers=0` 时没有路径；丰台东大街到西单的文本导出为 11451 米、4 元、22 分钟、换乘 1 次。期望值已用题目数据重新计算，全部成立。
- 缺陷：10.1、10.2 只检查题目自带的数据文件；`test_line_preference` 用「 1」匹配线路名，是翻译留下的问题。
- 需要附加约 12 条接口约定（见设计文档第 2.3 节）。只用标准库。
- 同档另外两个候选：23 PyCombinator 解释器（PRD 39 行，接口与报错原文和 UC Berkeley CS61A 实验骨架一致，模型可能凭记忆作答）；35 固定资产管理（需要附加 40 条以上的约定，测试的登录密码与 PRD 不一致）。

## 3. 没有选用的评测

| 评测 | 原因 |
| --- | --- |
| Terminal-Bench 2.0（harbor-framework/terminal-bench-2 `2fd12b8`，89 题，Apache-2.0） | DeepSeek V4.1 Flash 配 OpenCode 在 2.1 上为 85.0，接近满分；从空目录开始的 9 个候选都不含错误输入的要求；最接近的 openssl-selfsigned-cert 主要是 openssl 命令；测试只有全部通过与不通过 |
| Harbor（harbor-framework/harbor `a38eb54`，0.23.0） | 内置 OpenCode、测试在 agent 结束后上传、支持本地任务目录与重复运行；Yudao 按平时入口运行、交付物交给自己的评分器更简单，没有采用 |
| E2EDev（SCUNLP/E2EDev `d280dd1`） | 需求写明 `data-testid` 并禁止额外组件，没有外观评分 |
| WebRISE（IIGROUP/WebRISE `78aa930`） | 评分方式可取（状态迁移图加浏览器智能体），裁判型号未核实，没有 DeepSeek 成绩；WebGen-Bench 的固定用例更简单 |
| SWE-Dev、FEA-Bench、FeatureBench | 输入给出函数签名或接口，属于补写代码 |
| NL2Repo-Bench | 规格约 1.9 万词元且写明 API，任务按公开库命名，污染风险高；DeepSeek V4.1 Flash 已得 64.0 |
| Commit0、DevBench、ProjectEval、ProjDevBench、ProgramBench | 允许查看测试、输入已含设计、任务太少、隐藏测试在外部平台或属于行为复刻 |
| SWE-bench Verified/Pro/Live、Multi-SWE-bench、SWE-Lancer | 以 issue 为输入修复已有仓库，区分度低；OpenAI 2026-02 停止报告 Verified |
| Web-Bench、WebApp1K、FrontendBench、Vibe Code Bench、WebCraftBench、WebCoderBench、WebGameBench、WebCompass、Cookie-Bench、RealDevWorld、WebDev Arena、DesignBench、Interaction2Code、UI2App | 规定元素 id、输入是测试文件或截图、数据未公开、用例由评估智能体现场生成，或是社区投票 |
