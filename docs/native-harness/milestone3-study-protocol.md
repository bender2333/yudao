# 里程碑 3 — solo vs multi 循环外对比研究（研究者协议）

> 状态：**SUPERSEDED / HISTORICAL**
> 新方案：`three-department-work-order-validation-design.md`
> 旧命令仅用于解释历史结果，当前运行时已移除。

> 这是**循环外裁判**的工作，不进 harness。harness 只跑题、吐产物+指标；
> 出题、隐藏 oracle、评分、量化对比都在这里，harness 与被试 agent **绝不可见本文件与 oracle**。

## 研究问题
显式认知结构（multi：理解→计划执行→验证）相对裸 loop（solo），在**正确性**与**成本**上是否有边际价值？

## 被试
- `solo` = `python -m harness.run_solo "<task>"`
- `multi` = `python -m harness.run_multi "<task>"`
- 同模型（gemini-2.5-flash）、同工具集、同 loop 原语。唯一自变量 = 编排结构。

## 方法（防 false-pass，继承旧 EXPERIMENT 唯一硬资产）
1. 每题有一段**给 agent 的任务描述**（放进 run 命令）——只说要什么，**不含**测试代码、不含隐藏边界清单。
2. 每题有一套**隐藏 oracle**（pytest，本研究者预写，agent 全程看不到）：黑盒 subprocess 调用产物，
   断言正常路径 + **精心设计的边界/陷阱**（第一次很可能做错的地方）。
3. 跑完后，在**循环外**对每个 run 的 workspace 跑该题 oracle：
   - `outcome=done/self-pass` 但 oracle FAIL → **false-pass**（自以为对，实际错）
   - 未收敛 但 oracle PASS → missed-win
4. 指标：oracle 通过与否、false-pass、calls、prompt/completion/reasoning tokens、墙钟、
   （multi 额外）rounds、退回边触发。

## 题库（难度梯度；入口/命令面/退出码全部钉死以便 oracle 断言）

### T1 — wordcount（低-中；校准地板）
任务给 agent：「创建 wc.py：接一个文件路径参数，输出三个数字，用单空格分隔，一行：行数 词数 字符数（字符含换行）。文件不存在时打印 'error: file not found' 到 stderr 并退出码 2。」
隐藏陷阱：字符数**含换行符**；空文件 → `0 0 0`；不存在文件走 stderr+exit2；词按空白分割（多空格不算多词）。

### T2 — 罗马数字（中；第一次很可能做错）
任务给 agent：「创建 roman.py：接一个 1..3999 的整数，输出其罗马数字表示。超出范围打印 'error: out of range' 到 stderr 退出码 1。」
隐藏陷阱：减法记法 4=IV,9=IX,40=XL,90=XC,400=CD,900=CM；边界 1=I,3999=MMMCMXCIX；0/4000 越界；非整数/负数处理。

### T3 — 括号匹配（中；状态+边界）
任务给 agent：「创建 balance.py：接一个字符串参数，判断其中 ()[]{} 是否正确配对嵌套，是则打印 'balanced' 退出0，否则 'unbalanced' 退出1。非括号字符忽略。」
隐藏陷阱：空串=balanced；类型交叉 `([)]`=unbalanced；只开不闭/只闭不开；嵌套正确 `([{}])`；含其它字符 `a(b)c`=balanced。

### T4 — CSV 列求和（中-高；格式+脏数据）
任务给 agent：「创建 sumcol.py：接两个参数 <csv文件> <列名>，对该列数值求和，输出 'sum: N'（整数和则无小数，否则保留两位小数）。列不存在打印 'error: no such column' 到 stderr 退出码3。空数据行跳过。」
隐藏陷阱：首行表头；整数和 vs 浮点和的格式差异；缺失/空单元格跳过不报错；列名不存在走 exit3；负数。

## 执行计划
- 每题每模式跑 **2 个 run**（seed 感：同题重复，看稳定性），共 4题×2模式×2 = 16 run。
- run 全部落 `runs/m3/<task>__<mode>__r<n>/`。
- **跑批由 subagent 做**（不看 oracle）；**oracle 判定由研究者主线做**（或派一个只拿到 oracle+workspace、拿不到题库设计意图的 subagent）。
- 产出 `runs/m3/report.md`：每格 oracle 结果 + false-pass + 成本，两模式聚合对比。

## 纪律
- oracle 与本文件**永不进** run 命令、永不进 workspace、永不让跑题 subagent 看到。
- 密钥永不外泄。
- 如实报告：false-pass 是**最有价值的信号**，出现了就是出现了，不掩饰。
