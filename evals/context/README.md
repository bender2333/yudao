# 上下文装配的离线回放（#912）

把「每一步交给模型的上下文」当成事件日志上的纯函数 `view(events, rules) → request`，
用真实运行记录测它、改它、再证明改完不丢东西。设计说明见
[docs/design/context-assembly.md](../../docs/design/context-assembly.md)。

本目录只读事件库与工件库，不导入 `harness`，不调用模型（`counterfactual` 子命令除外，
它按需调一次真实模型）。所有数字来自 `%LOCALAPPDATA%\Yudao\events.sqlite` 与它旁边的
`artifacts\` 目录。

## 怎么用

```bash
# 1. 核对回放忠实：规则全关时，视图必须一字不差地还原记录下来的请求
python -m evals.context verify

# 2. 测现状：每一步的召回与浪费，按步、按部门、按窗口大小给分布
python -m evals.context measure --out docs/evaluation/context-assembly-2026-10-29

# 3. 用新视图重放同一批运行，比较用量、召回、浪费，并逐条规则做消融
python -m evals.context replay --out docs/evaluation/context-assembly-replay-2026-10-29

# 4. 扫一个参数的取值，给参数定默认值
python -m evals.context sweep --param tool_result_keep_tokens --values 40000,16000,8000,4000

# 5. 反事实回放：抽样若干步，旧视图与新视图各问一次模型，比动作是否一致
export YUDAO_EVAL_BASE_URL=<模型服务地址>
export YUDAO_EVAL_API_KEY=<凭据>        # 只从环境变量读，不写进文件
export YUDAO_EVAL_MODEL=<模型名>
python -m evals.context counterfactual --sample 24
```

事件库不在默认位置时用 `--db <events.sqlite>`，工件库不在默认位置时用 `--artifacts <目录>`
（默认取事件库同级的 `artifacts`）。在别人的数据目录上重跑，表与数字一样，只是样本不同。

依赖：只需要标准库（`sqlite3`、`urllib`）与项目已有的 `.venv`。`python` 指
`.venv\Scripts\python.exe`（Windows）或 `.venv/bin/python`（其它）。

## 每一步在测什么

| 概念 | 定义 | 代码 |
| --- | --- | --- |
| 视图 | 这一步请求里的全部条目与工具定义 | `items.normalize_request` |
| 真值集合 | 这一步模型的输出里抽出的引用（路径、标识符、散列、引用片段、调用编号） | `references.extract` |
| 召回 | 真值里「此前已经出现过」的记号有多少还在视图里 | `measure.score_view` |
| 浪费 | 视图里此后从未被引用的记号所在的条目，用量合计 | `references.attribute` |

启发式的误差写在 `references.py` 开头的说明与设计说明第 2 节：浪费是上界、召回是下界。

## 文件

- `store.py`：读事件库与工件库（只读），把 `model_request_serialized` 与 `context_assembled`
  配成一步，取出请求体、清单与这一步的输出。
- `items.py`：把请求体拆成条目（部门材料按 `[source]` 分段，工具结果按 `call_id` 配名字与参数）。
- `references.py`：抽引用、把引用记给最早持有它的条目。
- `measure.py`：逐步骤量与汇总表。
- `view.py`：`view(events, rules)`，规则集 `Rules` 与规则版本。
- `rule-set.json`：规则清单（默认值 + 四项记录 + 数据来源），既是代码的输入，也是设计说明第 4 节的机器可读版本。
- `replay.py`：用新视图重放并做逐条规则的消融与逐段核对。
- `sweep.py`：参数扫描。
- `verify.py`：核对「视图 = 记录」逐字节一致。
- `counterfactual.py`：真实模型的反事实回放。
- 测试在 `evals/tests/test_context_view.py`，不读事件库、不调模型。
