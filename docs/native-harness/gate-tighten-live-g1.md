# 门闩收紧后 — G1 live 对照（solo vs multi）

> **成本勘误（2026-07-10）**：本文保留历史质量结果，但 multi calls/token 存在重复累计，`duration_ms` 也不是真实墙钟。原成本倍数不得继续作为证据；纠正值与原因见 `milestone4-complex-study-protocol.md#12-历史成本勘误`。

> 日期：2026-07-09  
> commit：`8834d92` fix(harness): tighten stage gates…  
> 数据：`runs/gates/`（G1 normalize_date，solo/multi 各 2 run）  
> 模型：gemini-2.5-flash @ provider.md  
> oracle：`runs/m3/_oracle/grade_g1.py`（agent 不可见）  
> 配置：`--max-steps 50`，multi `--max-rounds 3`

## 1. 原始结果

| run | mode | harness outcome | score | base | robust | errors | quality | calls | prompt tok | 墙钟 ms |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| g1__solo__r1 | solo | natural stop | **94** | 40 | 24 | 20 | 10 | 8 | 9,891 | 27,073 |
| g1__solo__r2 | solo | natural stop | **94** | 40 | 24 | 20 | 10 | 19 | 28,504 | 66,047 |
| g1__multi__r1 | multi | **done** (1 round) | **94** | 40 | 24 | 20 | 10 | 107 | 256,318 | 211,465 |
| g1__multi__r2 | multi | **escalated** (PLAN max_steps) | **94** | 40 | 24 | 20 | 10 | 60 | 147,942 | 171,708 |

全部 4 跑的唯一扣分项相同：

```text
robust: surrounding whitespace not handled   (−6 → robust 24/30)
```

即：` 2026-3-5 ` 前后空白未 strip。base / errors / quality 四跑满分持平。

## 2. 均值与成本

| | solo 均值 | multi 均值 | multi/solo |
|---|---:|---:|---:|
| score | 94.0 | 94.0 | **1.00×（无质量差）** |
| robust | 24.0 | 24.0 | 1.00× |
| calls | 13.5 | 83.5 | **6.2×** |
| prompt tokens | 19,198 | 202,130 | **10.5×** |
| 墙钟 ms | 46,560 | 191,586 | **4.1×** |

## 3. multi 阶段行为（门闩是否生效）

### multi r1（done）

| stage | stop | terminal | steps | 备注 |
|---|---|---|---:|---|
| UNDERSTAND | terminal | `submit_understanding` | 2 | 结构化四字段成功；**无 write 工具**仍完成 |
| PLAN_EXECUTE | terminal | `submit_ready` | 30 | 有 `normalize_date.py` 交付物，门闩通过 |
| VERIFY | terminal | `submit_verdict` pass | 41 | **无 write/edit**；用 bash 跑检查；仍判 pass |

- consults = **0**（未触发跨阶段咨询）  
- understanding 的 done-criteria **只覆盖任务明文例子**（2026-3-5 / 斜杠 / 紧凑 / 已是 ISO / invalid），**未写入空白 strip**  
- VERIFY 对照 understanding 验通过 → 假「全绿」，相对隐藏 oracle 仍缺 whitespace

### multi r2（escalated）

| stage | stop | terminal | steps | 备注 |
|---|---|---|---:|---|
| UNDERSTAND | terminal | `submit_understanding` | 5 | 结构化成功；constraints 甚至提到闰年/日历合法性 |
| PLAN_EXECUTE | **max_steps** | null | 50 | 已写出 `normalize_date.py` 且 oracle=94，但未 `submit_ready` / 自然停 → **按设计 escalate** |

说明：

1. **PLAN 门闩在工作**：max_steps 无终态 → escalate，不会假 done。  
2. 产物仍可能「其实够好」（grade 94）——harness outcome 与 oracle 分数解耦是对的（裁判在循环外）。  
3. multi 仍可能把 step 预算烧在 PLAN 的反复改/测上而交不了卷。

## 4. 与门闩改前（m3g，各 3 run）对照

| 指标 | m3g 改前 | gates 改后 (n=2) |
|---|---|---|
| solo 均分 | 92.0 | **94.0** |
| multi 均分 | **98.0** | **94.0** |
| multi−solo 质量差 | **+6**（全在 robust） | **0** |
| multi/solo prompt | ~17× | ~10.5× |
| multi 收敛 | 1/3 escalated | 1/2 escalated |
| consult | 0 | 0 |
| 共同失败点 | （改前 multi 常拿满 robust） | 本批 **两边都缺 whitespace** |

> n 小、模型随机性大；不能说「门闩让 multi 变差」，只能说 **本批未复现 multi 的 robust 优势**。

## 5. 分析（诚实口径）

### 能说的

1. **门闩/结构化在 live 上基本按设计工作**  
   - UNDERSTAND 两次均走 `submit_understanding`（结构化）  
   - multi r1 三阶段均 terminal 收场并 done  
   - multi r2 PLAN 无终态 → escalate（不是静默当成功）  
   - VERIFY 无 write 工具仍能判 pass（bash 检查路径可用）

2. **质量：本批 solo=multi=94，结构未买到分数**  
   唯一缺口相同（前后空白）。VERIFY 的「较真」被 **understanding 的 done-criteria 天花板** 卡住：判据里没有 whitespace，VERIFY 不会为了隐藏 oracle 去加测。

3. **成本铁律仍在**  
   multi ≈ solo 的 **6× 调用 / 10× prompt / 4× 墙钟**，与历史方向一致；相对 m3g 的 17× 略低，可能因 n 小 + r2 早 escalate。

4. **consult 仍为 0**  
   晋升机制本批无机会验证；模型在 G1 上仍不主动咨询。

5. **VERIFY 禁写未阻止「假 pass」**  
   假 pass 相对的是 **隐藏 oracle**，不是 understanding。系统内一致性：understanding→实现→verify 闭环成立；**循环外质量**仍取决于 understanding 是否覆盖 robust 边界。

### 不能说的

- 不能说门闩「提高了」或「毁掉了」multi 质量（n=2，且与 m3g 差 6 分可能是种子噪声）。  
- 不能说 escalate 的 r2 实现差——oracle 仍 94，是**过程未收口**不是**产物归零**。

### 对假设的修正

| 原假设 | 本批证据 |
|---|---|
| multi 验证阶段买 robust | **未显现**；VERIFY 只验 understanding 明文 |
| 结构化 understanding 改善判据 | 有结构，但字段内容仍贴任务例子，**未自发扩 robust** |
| PLAN 交付物门闩 | **有效**（有文件才 ready；max_steps 无终态 escalate） |
| consult 晋升 | **未触发**，待另设强制歧义题 |

## 6. 下一步候选

1. **理解阶段显式鼓励「合理未写明边界」**（不列 oracle 清单，只要求 agent 自拟 3–5 条边界进 done-criteria）——测 understanding 是否成为 robust 杠杆。  
2. **PLAN 预算**：max_steps 50 时 r2 仍撞顶；可对 PLAN 单独步数或「已有交付+自测通过则应 submit_ready」更强 prompt。  
3. **强制 consult 题**：出一道任务故意留歧义的题，验证晋升路径。  
4. **再跑 n≥3** 同题，看 94 平台是否稳定、是否再现 multi robust 优势。

## 7. 产物路径

```
runs/gates/
  _progress.log
  g1__{solo,multi}__r{1,2}/
    summary.json, events.jsonl, grade.json, workspace/
```
