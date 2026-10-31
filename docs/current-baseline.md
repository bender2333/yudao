# 当前验收基线

状态：区分真实项目验收的当前版本、历史基线与尚待执行的验收；最近一次改动 2026-10-31，真实项目（openai-agents-python）已接入并放行一次事项（工单 #139，报告 [docs/evaluation/2026-10-31-57835530.md](evaluation/2026-10-31-57835530.md)）。本页统一报告口径，不代替真实运行报告，也不代替用户的试用结论；路线以 [总体路线图](program-roadmap.md) 为准，总体意图见 [D38](requirements/system-intent.md)。

## 1. 版本身份（当前）

| 项目 | 取值 |
| --- | --- |
| Yudao 提交 | `57835530`（工单 #1360：建档结束与确认请求同时发生时不再把运行判作废） |
| 运行日期 | 2026-10-31（建档 12:35:50 起，事项 13:48:59 采纳，UTC+8） |
| 模型 | `gemini-3.8-flash-n`（网关实际服务名；请求按 `YUDAO_EVAL_MODEL` 传 `ag/gemini-3.8-flash-medium`，9router，Chat Completions），三个部门同一模型 |
| 场景 | 场景 2（模型设置透传参数），材料 `scenario-2@1`，评分器 `scorer-2@1` |
| 宿主环境 | Windows 11 (AMD64)、Python 3.13.16、uv 0.13.4、Node v24.13.1、git 2.49.0.windows.1 |
| 结果 | 建档完成（59 次模型请求 / 1,381,762 tokens / 1500.5 秒，初始 PRD 在界面决定卡片确认）；事项 `end_status=released`、完成度 1.0000、正确性 1.0，F2P 8/8、P2P 331/331，192 次模型请求 / 6,452,654 tokens / 2495 秒；采纳链「建档基线 → 事项采纳」 |
| 证据 | 报告 [2026-10-31-57835530.md](evaluation/2026-10-31-57835530.md)（带事件编号与文件路径）、结果文件 `C:/yudao-eval-runs/139-scenario2.json`、事件库 `C:/yudao-eval-runs/yudao-run-1/data/events.sqlite`、确认截图 [139-prd-confirm-57835530.png](evaluation/139-prd-confirm-57835530.png) |

每份结果只证明它记录的版本与场景：上表的身份与证据属于 2026-10-31 的这一次运行，不是对之后代码的结论。

## 2. 这条基线说明了什么

- 接入已有项目（3.8）：真实项目 openai-agents-python（FeatBench `openai__openai-agents-python-842` 基准提交 `8dfd6ff3`，363 个文件）经 `project.onboard` 建档完成，初始 PRD（9 条要求、2 条边界）在浏览器的决定卡片中确认并被采纳，基线核验 9 条要求全部核实；快照记录带 git 提交，采纳成果的 `code_tree_digest` 等于快照摘要。
- 随后的事项（issue 842）：从建档基线开始，交付、质检按变更后的完整 PRD 核验并采纳；5 条过程检查点全部通过（其中 2 条由运行器标「未核实」的，按事件库实际读数补齐为通过）；质检覆盖比例 7/7=1.0、模型阅读条件 0 条、开环条件 0 条；原有功能 331 条 P2P 无失败。
- 建档基线中的现有缺陷如实记录：`full_pytest`（裸 `uv run pytest`）exit=2，缺 litellm/voice 可选依赖与 `OPENAI_API_KEY`；`test_all_extras` 414 条全部通过。该缺陷不影响事项的评分结果。

## 3. 尚待执行的验收

- 工单 #198：同场景的三次对照运行与对照报告（本页只记录 1 次成功运行）。
- 界面端到端用例 `client/tests/e2e/onboarding.spec.ts` 与 `onboarding-prd.spec.ts` 在提交 `57835530` 上的运行：由该提交所在 PR 的 CI 核对，#139 的验收运行没有重新执行它们。
- 版本回归（评测场景设计第 6 节）：每个里程碑交给用户试用之前，与上一次发布的读数对照；场景 3 的最近读数见 [评测报告](evaluation/)（历史证据，本页不重写）。
- 用户的试用结论：未给出。真实运行成功是系统侧的证据，「试用通过」只有用户能写（验收证据规则第 5 节）。

## 4. 历史基线

- [current-baseline-2026-10-29.md](archive/current-baseline-2026-10-29.md)：阶段一「换骨架」为止的能力表与证据边界，2026-10-29 归档；其中的能力状态在本页不复制，仍以归档页为准。
- [current-baseline-3.0-contract.md](archive/current-baseline-3.0-contract.md)：3.0 合同时期的历史基线。
