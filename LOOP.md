# LOOP - native-harness 长任务协议

> 触发：用户说“自动推进 / 闭环做完 / 进入长任务模式”或使用 `/loop`。
> 当前状态看 `NEXT.md`，研究约束看其中列出的活动协议。

## 1. 循环

```text
loop:
  1. 定位：读 NEXT 的 Next Action，只取一个可验证目标。
  2. 分类：
     - correctness：确定性实现/测量缺陷
     - experiment：协议、题库、运行或分析
  3. 执行：
     correctness -> 先写复现测试 -> 最小修复 -> 定向测试
     experiment  -> 冻结协议 -> 成对运行 -> 循环外 oracle -> 汇总全部样本
  4. 验证：共享边界变化跑 harness 全量测试；实验核对 run 数、失败数和原始产物。
  5. 记账：只记录测试、实验、决策和影响结论的发现。
  6. 提交：明确路径 add，验证通过后 commit + push 当前分支。
  7. 更新 NEXT；当前目标完成则进入下一项，否则回到 3。
```

## 2. 当前阶段顺序

1. 修复会污染实验的确定性缺陷：工具授权、workspace 边界、计数、退出码、门禁。
2. 冻结复杂任务协议、题库、oracle、预算和评分。
3. 跑不计入正式样本的 pilot，只验证 wiring 与预算是否可执行。
4. 协议再次冻结后跑正式成对批次。
5. 循环外评分，报告质量、成本、收敛率、false-pass、方差和所有失败。
6. 得出“支持 / 不支持 / 证据不足”，不以 multi 必须获胜为终止条件。

## 3. 硬边界

只在以下情况停下：

- **协议污染**：正式样本开始后需要改题、oracle、预算、prompt 或评分；停止该批并开新版本。
- **隔离不成立**：agent 能访问 hidden oracle、provider key 或非授权 workspace。
- **外部成本未授权**：`NEXT.md` 未明确本次 live batch 的模型、题数、重复数和最大调用预算。
- **不可逆操作**：批量删除、重写历史、force push、生产或密钥变更。
- **同一根因连续失败两次**：停止补丁叠加，写明根因和替代路线。
- **真实歧义**：不同选择会改变研究问题或结论，且活动协议没有答案。

普通代码选择、测试修复和可逆文档编辑不构成硬边界。

## 4. 验证

```bash
# 确定性回归
python -m pytest harness/tests -q

# live smoke / batch
python -m harness.run_solo "<task>" --run-dir runs/<cell>
python -m harness.run_multi "<task>" --run-dir runs/<cell>
```

PASS 必须写清：命令、通过数、skip 数、run 数、oracle 结果和产物路径。缺任一项就标 FAIL 或 INCOMPLETE。

## 5. Git

- 只提交到当前 `exp/native-harness`，不自动切分支。
- 每个验证通过的小块 commit + push。
- 只暂存明确路径；不用 `git add .`。
- 不开 PR、不合并、不 force push、不跳过 hooks、不改 git config。

## 6. Subagent 与 context

- 扇出读取、批量运行和独立评分用 subagent；实现留主线。
- 主上下文只保留结论、路径和数字，不搬运大段原始日志。
- context 临近上限时更新 `NEXT.md` 并干净收尾，不用压缩质量换时间。
