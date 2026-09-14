# A4 真实比较结论

日期：2026-09-14。协议 [stage-2-a4-protocol.md](stage-2-a4-protocol.md)。原始报告 `.yudao/s2-3-a4-20260914/`。应用当时 HEAD 含 B3 外壳（比较器报告里仍写了协议冻结身份 `4c5cde4`；内核交接未改）。Provider：`agnes-3.0-flash` / Responses / 任务窗 32000。未用 fake。凭据未进本文件。

## 结论：保留原版

不把候选写入系统默认，也不把工程三段追加提升为以后项目的默认配置。候选项目上已保存的 v1 只是该次比较的配置，不推广。

## 事实

| 任务 | 基线 | 候选 |
| --- | --- | --- |
| 1 逐行文本 | DONE / adopted / 检查 pass | DONE / adopted / 检查 pass |
| 2 CSV | DONE / adopted / 检查 not_run | PAUSED `max_cycles` / 未结算 / 检查 not_run |
| 3 澄清 | DONE / adopted / 检查 pass | DONE / adopted / 检查 pass |
| 4 空行回归 | DONE / adopted / 检查 pass | DONE / adopted / 检查 pass |

两侧都没有「计划接纳前写文件」。校准里看到的那类错误在这四份确认材料上没有复现，因此候选没有证明收益。

用量（报告中的 token 合计，请求计数字段为 0 是比较器展示缺陷，不以 0 请求为准）：基线约 58 万，候选约 157 万。候选在任务 2 上循环耗尽，token 约 110 万。成本更高、质量未更好。

失败 `run_bbacdca62d374995` 保留。

## 不改什么

`department_prompts.py` 不动。没有改善，不缩小范围再加跑。B4 仍用默认 Prompt。
