# 场景 3 · Yudao 一侧评测报告

## 一、基本信息

| 项目 | 取值 |
| --- | --- |
| 场景 | scenario-3 |
| 材料版本 | scenario-3@2 |
| 评分器版本 | scorer-3@2 |
| 被测模型 | auto |
| Yudao 提交号 | 2959f3fd |
| 计入结果的运行次数 | 3 |

## 二、宿主环境

| 项目 | 版本 |
| --- | --- |
| system | Windows 11 (AMD64) |
| python | 3.14.7 |
| uv | uv 0.11.14 (3fdfdc7d4 2026-05-12 x86_64-pc-windows-msvc) |
| node | v24.14.0 |
| opencode | 1.18.33 |
| git | git version 2.53.0.windows.1 |

## 三、联网

不联网。Yudao 的评测项目不登记取回来源与 MCP 服务器，运行中也没有这两类工具的调用。

## 四、过程检查点

| 检查点 | yudao-q38f-start-1 | yudao-q38f-start-2 | yudao-q38f-start-3 |
| --- | --- | --- | --- |
| run 在限额内结束，状态为放行 | 未通过 | 未通过 | 未通过 |
| 质检的放行绑定最后提交的交付树 | 未通过 | 未通过 | 未通过 |
| 重放结果与记录一致 | 通过 | 通过 | 通过 |
| 质检没有误放行 | 通过 | 通过 | 通过 |
| 放行记录附检验覆盖比例、模型阅读条件数与开环条件数 | 通过 | 通过 | 通过 |

### yudao-q38f-start-1 的检查点依据

- run 在限额内结束，状态为放行：运行未通过放行判定：运行到时间上限，被运行器结束；阶段不是 DONE（实际为 FAILED）；停止原因不是 released（实际为 cancelled）；没有当前交付快照的质检放行
- 质检的放行绑定最后提交的交付树：没有质检提交或没有封存的交付
- 重放结果与记录一致：重放结果与记录一致
- 质检没有误放行：本次没有放行，不存在误放行；隐藏检查的失败条目：unit_2_5
- 放行记录附检验覆盖比例、模型阅读条件数与开环条件数：本次没有放行，本项不适用

### yudao-q38f-start-2 的检查点依据

- run 在限额内结束，状态为放行：运行未通过放行判定：运行到时间上限，被运行器结束；阶段不是 DONE（实际为 FAILED）；停止原因不是 released（实际为 cancelled）；没有当前交付快照的质检放行
- 质检的放行绑定最后提交的交付树：没有质检提交或没有封存的交付
- 重放结果与记录一致：重放结果与记录一致
- 质检没有误放行：本次没有放行，不存在误放行；隐藏检查的失败条目：cmd_0_1、unit_2_5
- 放行记录附检验覆盖比例、模型阅读条件数与开环条件数：本次没有放行，本项不适用

### yudao-q38f-start-3 的检查点依据

- run 在限额内结束，状态为放行：运行未通过放行判定：运行到时间上限，被运行器结束；阶段不是 DONE（实际为 FAILED）；停止原因不是 released（实际为 cancelled）；没有当前交付快照的质检放行
- 质检的放行绑定最后提交的交付树：没有质检提交或没有封存的交付
- 重放结果与记录一致：重放结果与记录一致
- 质检没有误放行：本次没有放行，不存在误放行；隐藏检查的失败条目：cmd_0_1、unit_2_5
- 放行记录附检验覆盖比例、模型阅读条件数与开环条件数：本次没有放行，本项不适用

## 五、指标汇总

| 指标 | 平均值 | 最小值 | 最大值 | 有效样本数 | 未知样本数 |
| --- | --- | --- | --- | --- | --- |
| 循环次数 | 4.6667 | 3 | 7 | 3 | 0 |
| 返工次数 | 0 | 0 | 0 | 3 | 0 |
| 部门之间询问次数 | 0.3333 | 0 | 1 | 3 | 0 |
| 模型请求数 | 117.3333 | 1 | 210 | 3 | 0 |
| 输入用量 | 未知 | 未知 | 未知 | 0 | 3 |
| 输出用量 | 未知 | 未知 | 未知 | 0 | 3 |
| 总用量 | 12154938.3333 | 10034931 | 15819250 | 3 | 0 |
| 费用 | 未知 | 未知 | 未知 | 0 | 3 |
| 耗时（秒） | 5402.4 | 5402 | 5403.2 | 3 | 0 |

未知样本不进均值、最小值与最大值。缺失的原因：

- 输入用量：模型服务未上报输入用量
- 输出用量：模型服务未上报输出用量
- 费用：模型服务未上报费用，或材料版本未登记单价

## 六、逐次运行

### yudao-q38f-start-1

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | time_limit |
| 停止原因 | cancelled |
| 循环次数 | 3 |
| 返工次数 | 0 |
| 部门之间询问次数 | 0 |
| 模型请求数 | 141 |
| 输入用量 | 未知 |
| 输出用量 | 未知 |
| 总用量 | 10034931 |
| 费用 | 未知 |
| 耗时（秒） | 5403.2 |
| 封存的交付文件数 | 13 |
| 成功但没有输出项的模型调用 | 0 |
| 完成度 | 0.8571 |
| 正确性 | 0.9583 |
| 未做的隐藏检查数 | 0 |
| 出错的隐藏检查数 | 1 |

失败条目：

- 要求 R3：0/1 通过
- 隐藏检查 unit_2_5（wrong）：Tiananmen East->Zhongguancun preferred ['Line 10']: path does not run on Line 10: ['Line 1', 'Line 1', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4']; Fengtai East Street->Xidan preferred ['Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']; Fengtai East Street->Xidan preferred ['Line 2', 'Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']

### yudao-q38f-start-2

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | time_limit |
| 停止原因 | cancelled |
| 循环次数 | 7 |
| 返工次数 | 0 |
| 部门之间询问次数 | 1 |
| 模型请求数 | 1 |
| 输入用量 | 未知 |
| 输出用量 | 未知 |
| 总用量 | 10610634 |
| 费用 | 未知 |
| 耗时（秒） | 5402 |
| 封存的交付文件数 | 13 |
| 成功但没有输出项的模型调用 | 0 |
| 完成度 | 0.8413 |
| 正确性 | 0.9167 |
| 未做的隐藏检查数 | 0 |
| 出错的隐藏检查数 | 2 |

失败条目：

- 要求 R3：0/1 通过
- 要求 R7：8/9 通过
- 隐藏检查 cmd_0_1（wrong）：the program starts without an input prompt describing the query format
- 隐藏检查 unit_2_5（wrong）：Tiananmen East->Zhongguancun preferred ['Line 10']: path does not run on Line 10: ['Line 1', 'Line 1', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4']; Fengtai East Street->Xidan preferred ['Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']; Fengtai East Street->Xidan preferred ['Line 2', 'Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']

### yudao-q38f-start-3

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | time_limit |
| 停止原因 | cancelled |
| 循环次数 | 4 |
| 返工次数 | 0 |
| 部门之间询问次数 | 0 |
| 模型请求数 | 210 |
| 输入用量 | 未知 |
| 输出用量 | 未知 |
| 总用量 | 15819250 |
| 费用 | 未知 |
| 耗时（秒） | 5402 |
| 封存的交付文件数 | 15 |
| 成功但没有输出项的模型调用 | 0 |
| 完成度 | 0.8413 |
| 正确性 | 0.9167 |
| 未做的隐藏检查数 | 0 |
| 出错的隐藏检查数 | 2 |

失败条目：

- 要求 R3：0/1 通过
- 要求 R7：8/9 通过
- 隐藏检查 cmd_0_1（wrong）：the program starts without an input prompt describing the query format
- 隐藏检查 unit_2_5（wrong）：Tiananmen East->Zhongguancun preferred ['Line 10']: path does not run on Line 10: ['Line 1', 'Line 1', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4']; Fengtai East Street->Xidan preferred ['Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']; Fengtai East Street->Xidan preferred ['Line 2', 'Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']


## 七、不计入结果的运行

无：每次运行都计入结果。

## 九、起点缺口与运行条件

- 起点：按 #324 的写法经 project.create 的 initial_directory 带入题目的 subway_data.json（起始文件夹只含这个文件，在运行目录之外），事项文字去掉了请工程自己写出数据文件的一段；这一处由补跑脚本替换，运行器代码没有改。

原始证据（事件日志导出、交付副本、评分日志）在 `.yudao/evals/` 下，不进入 Git。
