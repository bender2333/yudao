# 场景 3 · OpenCode 一侧评测报告

## 一、基本信息

| 项目 | 取值 |
| --- | --- |
| 场景 | scenario-3 |
| 材料版本 | scenario-3@2 |
| 评分器版本 | scorer-3@2 |
| 被测模型 | yudao-eval/cbcn/deepseek-v4.1-flash |
| OpenCode 版本 | 1.18.33 |
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

两边都不联网。任务来自公开仓库，联网取回可能直接取回上游的答案。
OpenCode 的运行配置中取回与搜索工具（webfetch、websearch）关闭；运行器检查 JSON 输出中没有这两类工具的调用。

## 四、指标汇总

| 指标 | 平均值 | 最小值 | 最大值 |
| --- | --- | --- | --- |
| 模型请求数 | 64.3333 | 51 | 88 |
| 输入用量 | 807382.6667 | 750766 | 907335 |
| 输出用量 | 35872.6667 | 30009 | 46560 |
| 缓存读取用量 | 5429973.3333 | 3599488 | 7806720 |
| 缓存写入用量 | 0 | 0 | 0 |
| 费用 | 0 | 0 | 0 |
| 耗时（秒） | 1089.5557 | 835.024 | 1242.286 |

## 五、逐次运行

### baseline-1

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | stop |
| 超时 | 否 |
| 模型请求数 | 54 |
| 输入用量 | 764047 |
| 输出用量 | 30009 |
| 耗时（秒） | 1242.286 |
| 完成度 | 0.8571 |
| 正确性 | 0.9583 |
| 这次运行是否作废 | 否 |

需求条目得分：

| 条目 | 通过 | 总数 | 得分 |
| --- | --- | --- | --- |
| R1 | 5 | 5 | 1 |
| R2 | 3 | 3 | 1 |
| R3 | 0 | 1 | 0 |
| R4 | 3 | 3 | 1 |
| R5 | 1 | 1 | 1 |
| R6 | 2 | 2 | 1 |
| R7 | 9 | 9 | 1 |

失败条目：

| 检查 | 条目 | 分类 | 详情 |
| --- | --- | --- | --- |
| unit_2_5 | R3 | 做了但结果不对 | Tiananmen East->Zhongguancun preferred ['Line 10']: path does not run on Line 10: ['Line 1', 'Line 1', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4']; Fengtai East Street->Xidan preferred ['Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']; Fengtai East Street->Xidan preferred ['Line 2', 'Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1'] |

### baseline-2

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | stop |
| 超时 | 否 |
| 模型请求数 | 51 |
| 输入用量 | 750766 |
| 输出用量 | 31049 |
| 耗时（秒） | 835.024 |
| 完成度 | 0.546 |
| 正确性 | 1 |
| 这次运行是否作废 | 否 |

需求条目得分：

| 条目 | 通过 | 总数 | 得分 |
| --- | --- | --- | --- |
| R1 | 3 | 5 | 0.6 |
| R2 | 1 | 3 | 0.3333 |
| R3 | 0 | 1 | 0 |
| R4 | 3 | 3 | 1 |
| R5 | 0 | 1 | 0 |
| R6 | 2 | 2 | 1 |
| R7 | 8 | 9 | 0.8889 |

失败条目：

| 检查 | 条目 | 分类 | 详情 |
| --- | --- | --- | --- |
| unit_12_1 | R5 | 没有做 | missing symbol: pathfinding |
| unit_2_3 | R1 | 没有做 | missing symbol: pathfinding |
| unit_2_4 | R2 | 没有做 | missing symbol: pathfinding |
| unit_2_5 | R3 | 没有做 | missing symbol: pathfinding |
| unit_5_2 | R2 | 没有做 | missing symbol: pathfinding |
| unit_8_2 | R7 | 没有做 | missing symbol: pathfinding |
| unit_9_1 | R1 | 没有做 | missing symbol: pathfinding |

### baseline-3

| 项目 | 取值 |
| --- | --- |
| 结束状态 | ended |
| 结束原因 | stop |
| 超时 | 否 |
| 模型请求数 | 88 |
| 输入用量 | 907335 |
| 输出用量 | 46560 |
| 耗时（秒） | 1191.357 |
| 完成度 | 0.7698 |
| 正确性 | 0.875 |
| 这次运行是否作废 | 否 |

需求条目得分：

| 条目 | 通过 | 总数 | 得分 |
| --- | --- | --- | --- |
| R1 | 5 | 5 | 1 |
| R2 | 3 | 3 | 1 |
| R3 | 0 | 1 | 0 |
| R4 | 3 | 3 | 1 |
| R5 | 1 | 1 | 1 |
| R6 | 1 | 2 | 0.5 |
| R7 | 8 | 9 | 0.8889 |

失败条目：

| 检查 | 条目 | 分类 | 详情 |
| --- | --- | --- | --- |
| cmd_0_1 | R7 | 做了但结果不对 | the program starts without an input prompt describing the query format |
| file_11_1 | R6 | 做了但结果不对 | the text export does not match the agreed layout |
| unit_2_5 | R3 | 做了但结果不对 | Tiananmen East->Zhongguancun preferred ['Line 10']: path does not run on Line 10: ['Line 1', 'Line 1', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4', 'Line 4']; Fengtai East Street->Xidan preferred ['Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1']; Fengtai East Street->Xidan preferred ['Line 2', 'Line 4']: path does not run on Line 4: ['Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 9', 'Line 1', 'Line 1', 'Line 1', 'Line 1'] |


## 六、不计入结果的运行

没有作废的运行，也没有因为模型服务故障结束的运行。

原始证据（交付副本、输出、评分日志）在 `.yudao/evals/` 下，不进入 Git。
