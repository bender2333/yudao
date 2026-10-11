# 场景 3 · Yudao 一侧评测报告

## 一、基本信息

| 项目 | 取值 |
| --- | --- |
| 场景 | scenario-3 |
| 材料版本 | scenario-3@2 |
| 评分器版本 | scorer-3@2 |
| 被测模型 | deepseek/deepseek-v4.1-flash |
| Yudao 提交号 | 84933d03 |
| 计入结果的运行次数 | 2 |

## 二、宿主环境

| 项目 | 版本 |
| --- | --- |
| system | Windows 11 (AMD64) |
| python | 3.14.7 |
| uv | uv 0.11.14 (3fdfdc7d4 2026-05-12 x86_64-pc-windows-msvc) |
| node | v24.14.0 |
| opencode | 1.18.33 |
| git | git version 2.53.0.windows.1 |

## 三、网络与取回来源

| 项目 | 取值 |
| --- | --- |
| 网络允许 | 否 |
| 说明 | Yudao 的评测项目不登记取回来源与 MCP 服务器，运行中也没有这两类工具的调用。 |

## 四、过程检查点（第 5.1 节）

| 检查点 | yudao-run2-1 | yudao-limit-1-1 |
| --- | --- | --- |
| 在冻结限额内以放行结束 | 未通过 | 未通过 |
| 质检放行绑定最后封存的交付 | 通过 | 通过 |
| 工程在计划被接纳后才写入文件 | 未核实 | 未核实 |
| 重放结果与记录一致 | 未核实 | 未核实 |
| 质检没有误放行 | 通过 | 通过 |
| 放行记录的逐条覆盖、模型阅读与开环条件 | 通过 | 通过 |

- **在冻结限额内以放行结束**
  - yudao-run2-1：运行未通过放行判定：阶段 PAUSED（实际为 PAUSED）；停止原因 no_tool_call（实际为 no_tool_call）；没有当前交付快照的质检放行；用量未超限额
  - yudao-limit-1-1：运行未通过放行判定：阶段 FAILED（实际为 FAILED）；停止原因 cancelled（实际为 cancelled）；没有当前交付快照的质检放行；用量未超限额
- **质检放行绑定最后封存的交付**
  - yudao-run2-1：本次没有放行，本项不适用
  - yudao-limit-1-1：本次没有放行，本项不适用
- **工程在计划被接纳后才写入文件**
  - yudao-run2-1：原始事件日志不在仓库内，工程是否在计划被接纳前写入待核实。
  - yudao-limit-1-1：原始事件日志不在仓库内，工程是否在计划被接纳前写入待核实。
- **重放结果与记录一致**
  - yudao-run2-1：原始事件日志不在仓库内，重放结果无法取回，按未核实。
  - yudao-limit-1-1：原始事件日志不在仓库内，重放结果无法取回，按未核实。
- **质检没有误放行**
  - yudao-run2-1：本次没有放行，不存在误放行；隐藏检查的失败条目：cmd_0_1、cmd_1_1、cmd_2_1、cmd_3_1a、cmd_3_1b、cmd_4_1、cmd_4_2、cmd_5_1a、cmd_7_1、cmd_8_1、file_11_1、file_11_2、unit_10_1、unit_10_2、unit_12_1、unit_2_2、unit_2_3、unit_2_4、unit_2_5、unit_5_2、unit_6_1、unit_6_2、unit_8_2、unit_9_1
  - yudao-limit-1-1：本次没有放行，不存在误放行；隐藏检查的失败条目：cmd_0_1、cmd_1_1、cmd_2_1、cmd_3_1a、cmd_3_1b、cmd_4_1、cmd_4_2、cmd_5_1a、cmd_7_1、cmd_8_1、file_11_1、file_11_2、unit_10_1、unit_10_2、unit_12_1、unit_2_2、unit_2_3、unit_2_4、unit_2_5、unit_5_2、unit_6_1、unit_6_2、unit_8_2、unit_9_1
- **放行记录的逐条覆盖、模型阅读与开环条件**
  - yudao-run2-1：本次没有放行，本项不适用
  - yudao-limit-1-1：本次没有放行，本项不适用

## 五、用量与耗时汇总（第 5.2 节）

| 指标 | 平均 | 最小 | 最大 | 有效样本 | 未知样本 | 未知原因 |
| --- | --- | --- | --- | --- | --- | --- |
| 循环次数 | 3.5 | 3.0 | 4.0 | 2 | 0 |  |
| 返工次数 | 0.0 | 0.0 | 0.0 | 2 | 0 |  |
| 部门之间询问次数 | 0.0 | 0.0 | 0.0 | 2 | 0 |  |
| 模型请求数 | 6.0 | 5.0 | 7.0 | 2 | 0 |  |
| 输入 tokens | 未知 | 未知 | 未知 | 2 | 2 | 模型服务未上报输入用量 |
| 输出 tokens | 未知 | 未知 | 未知 | 2 | 2 | 模型服务未上报输出用量 |
| 缓存读取 tokens | 未知 | 未知 | 未知 | 0 | 0 | 模型服务未上报该项 |
| 缓存写入 tokens | 未知 | 未知 | 未知 | 0 | 0 | 模型服务未上报该项 |
| 累计 tokens | 114151.5 | 77230.0 | 151073.0 | 2 | 0 |  |
| 费用 | 未知 | 未知 | 未知 | 2 | 2 | 模型服务未上报费用，或材料版本未登记单价 |
| 耗时（秒） | 284.85 | 150.8 | 418.9 | 2 | 0 |  |

## 六、逐次运行

### yudao-run2-1

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | no_tool_call |
| 停止原因 | no_tool_call |
| 循环次数 | 3 |
| 返工次数 | 0 |
| 部门之间询问次数 | 0 |
| 模型请求数 | 7 |
| 输入用量 | 未知 |
| 输出用量 | 未知 |
| 总用量 | 151073 |
| 费用 | 未知 |
| 耗时（秒） | 418.9 |
| 封存的交付文件数 | 0 |
| 成功但没有输出项的模型调用 | 4 |
| 完成度 | 0 |
| 正确性 | 0 |
| 未做的隐藏检查数 | 24 |
| 出错的隐藏检查数 | 0 |

失败条目：

- 要求 R1：0/5 通过
- 要求 R2：0/3 通过
- 要求 R3：0/1 通过
- 要求 R4：0/3 通过
- 要求 R5：0/1 通过
- 要求 R6：0/2 通过
- 要求 R7：0/9 通过
- 隐藏检查 cmd_0_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_1_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_2_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_3_1a（not_done）：the delivery has no src directory
- 隐藏检查 cmd_3_1b（not_done）：the delivery has no src directory
- 隐藏检查 cmd_4_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_4_2（not_done）：the delivery has no src directory
- 隐藏检查 cmd_5_1a（not_done）：the delivery has no src directory
- 隐藏检查 cmd_7_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_8_1（not_done）：the delivery has no src directory
- 隐藏检查 file_11_1（not_done）：the delivery has no src directory
- 隐藏检查 file_11_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_10_1（not_done）：the delivery has no src directory
- 隐藏检查 unit_10_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_12_1（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_3（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_4（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_5（not_done）：the delivery has no src directory
- 隐藏检查 unit_5_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_6_1（not_done）：the delivery has no src directory
- 隐藏检查 unit_6_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_8_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_9_1（not_done）：the delivery has no src directory


### yudao-limit-1-1

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | time_limit |
| 停止原因 | cancelled |
| 循环次数 | 4 |
| 返工次数 | 0 |
| 部门之间询问次数 | 0 |
| 模型请求数 | 5 |
| 输入用量 | 未知 |
| 输出用量 | 未知 |
| 总用量 | 77230 |
| 费用 | 未知 |
| 耗时（秒） | 150.8 |
| 封存的交付文件数 | 0 |
| 成功但没有输出项的模型调用 | 1 |
| 完成度 | 0 |
| 正确性 | 0 |
| 未做的隐藏检查数 | 24 |
| 出错的隐藏检查数 | 0 |

失败条目：

- 要求 R1：0/5 通过
- 要求 R2：0/3 通过
- 要求 R3：0/1 通过
- 要求 R4：0/3 通过
- 要求 R5：0/1 通过
- 要求 R6：0/2 通过
- 要求 R7：0/9 通过
- 隐藏检查 cmd_0_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_1_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_2_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_3_1a（not_done）：the delivery has no src directory
- 隐藏检查 cmd_3_1b（not_done）：the delivery has no src directory
- 隐藏检查 cmd_4_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_4_2（not_done）：the delivery has no src directory
- 隐藏检查 cmd_5_1a（not_done）：the delivery has no src directory
- 隐藏检查 cmd_7_1（not_done）：the delivery has no src directory
- 隐藏检查 cmd_8_1（not_done）：the delivery has no src directory
- 隐藏检查 file_11_1（not_done）：the delivery has no src directory
- 隐藏检查 file_11_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_10_1（not_done）：the delivery has no src directory
- 隐藏检查 unit_10_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_12_1（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_3（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_4（not_done）：the delivery has no src directory
- 隐藏检查 unit_2_5（not_done）：the delivery has no src directory
- 隐藏检查 unit_5_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_6_1（not_done）：the delivery has no src directory
- 隐藏检查 unit_6_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_8_2（not_done）：the delivery has no src directory
- 隐藏检查 unit_9_1（not_done）：the delivery has no src directory


## 七、不计入结果的运行

- 无

## 九、起点缺口与运行条件

- 起点缺口：Yudao 的接口没有把文件放进新建项目空工作区的命令，本运行的工作区里没有题目提供的 `subway_data.json`；运行器请工程按接口约定自行写出这份数据文件。工作区从空目录建立（Yudao 默认的执行位置是控制主机上的本机进程）。
- 被测模型有 5 次调用返回成功但没有任何输出项（`status=success`、`output_item_count=0`、无错误）。主机把这类调用当成一次正常的模型回复，连续多次以后按 `no_tool_call` 暂停，停止原因与真实原因不符；详见 docs/architecture-issues.md 中本工单的登记。
- 证据不可取回：原始 `evidence_dir` 指向 issue-192 worktree 下的 `.yudao/evals/`，本工单仓库内没有这些文件，无法重算检查点依据与 hidden_failures 取回；按设计要求标为「未核实」。
- 用量按新口径：input_tokens / output_tokens / cache_read_tokens / cache_write_tokens / cost 字段都记未知（None），不进均值、不进最小/最大、不进噪声。
- 三次运行的版本比较（#324）尚未开展，本次报告未提供版本比较段；同版本重复运行的离散由后续阶段补上。
- 交付到 `docs/evaluation/scenario-3-yudao.json` 的 `replay` / `qa_submitted` payload / `coverage` 等逐项未核实字段未补造。

原始证据（事件日志导出、交付副本、评分日志）在 `.yudao/evals/` 下，不进入 Git。
