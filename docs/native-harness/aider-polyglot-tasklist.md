# Aider Polyglot 题清单（Pilot）

> 状态：**pilot**（不得直接作为正式科学结论题库）  
> 语言：Python only  
> 来源：`third_party/polyglot-benchmark`（Aider polyglot）  
> 协议：`docs/native-harness/aider-polyglot-protocol.md`

冻结正式批时：记录 polyglot **git SHA**，并将状态改为 formal；pilot 用过的题若曾调 prompt，正式批应替换。

| slug | difficulty | notes |
|---|---|---|
| list-ops | med | 函数式列表操作，无第三方依赖 |
| grade-school | med | 班级花名册 |
| wordy | med | 文字算术 |
| phone-number | med | 电话号码清洗/校验 |
| pig-latin | med | 字符串变换 |

## 使用

```bash
# 题库（若尚未克隆）
git clone --depth 1 https://github.com/Aider-AI/polyglot-benchmark third_party/polyglot-benchmark

# 离线打通流水线（不调用 LLM，用 .meta/example.py）
python scripts/aider_polyglot_runner.py \
  --batch-id dry-pilot-1 \
  --tasklist docs/native-harness/aider-polyglot-tasklist.md \
  --arms S \
  --reps 1 \
  --dry-run

# 真实 solo vs multi（需 provider.md）
python scripts/aider_polyglot_runner.py \
  --batch-id pilot-001 \
  --tasklist docs/native-harness/aider-polyglot-tasklist.md \
  --arms S,P \
  --reps 1 \
  --max-calls 60 \
  --max-tokens 200000 \
  --max-seconds 300
```
