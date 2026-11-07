# Yudao 本体：第一步（研究分支）

这是 Yudao 自己的本体第一步的试验代码，只在分支 `research/ontology-step1` 上，不进 main。方案在分支 `research/yudao-ontology` 的 `docs/research/yudao-ontology-v2.md`（第 4、5、9 节）。分支 `research/ontology-step1-r2` 是对齐 11-07 夜的 main（`37e9d68`）以后重跑的一版。结果见 [reports/step1-report.md](reports/step1-report.md)。

只读仓库里的文档（总图、设计说明、`CONTEXT.md`、name-map），不改任何文档和代码。

## 文件

| 文件 | 是什么 |
| --- | --- |
| `onto/core.ttl` | 类与属性（词汇），没有个体 |
| `onto/shapes.ttl` | SHACL 形状，由 `run.py` 生成，留着给人看 |
| `batches/batch0-axioms.ttl` | 第 0 批：意图的必有公理与约束公理，每条带依据 |
| `batches/batch1-*.ttl` | 第 1 批：总图的参照抽取、承诺范围、试验假定 |
| `batches/batch2-*.ttl` | 第 2 批：设计说明的参照抽取、承诺范围、假定（半开环）；`batch2-contested.ttl` 是三份抽取对不上、没放进模型的断言，不加载 |
| `extractions/` | 两份独立抽取（A 与 B，两个不同的模型、互相看不到）和参照的子集 |
| `run.py` | 按批加载、HermiT 推理与分类、推空位、SHACL、空位追踪 |
| `mutate.py` | 检验模型本身：在内存里的副本上埋错，看能否查出 |
| `compare.py` | 检验模型本身：几份抽取按标签对齐，只列对不上的 |
| `openloop.py`、`rules/` | 开环标记的检查：几处判开环的文字写成公理，枚举探针，找判定相反的组合；`python3 openloop.py 5159317 eb8429e` |
| `defs.py` | 第 3 批：把 `runtime.py` 登记的三份形态的定义文件转写成 `batches/batch3-definitions.ttl`（`python3 defs.py eb8429e`） |
| `crosscheck.py` | 第 3 批：设计与定义文件分成两张图逐条对照，写 `reports/crosscheck.json` |
| `codecheck.py` | 第 4 批：从提交里读代码事实（分层、name-map、来源、对照缺行），写 `batches/batch4-code.ttl` 和 `reports/codecheck.json`；`python3 codecheck.py eb8429e` |
| `quotecheck.py` | 跟版本走：模型里每一句原句，到给定的提交里逐句核对还在不在，写 `reports/quotecheck.json`；`python3 quotecheck.py 5159317 eb8429e 37e9d68` |
| `names.py` | 正名表：`CONTEXT.md` 词条与 _Avoid_、name-map 第一列 |
| `reports/` | `results.json`、`mutations.json`、两批的抽取对照、报告 |

## 跑

要 Java（HermiT）和 `python3 -m pip install rdflib pyshacl owlready2`。

```
python3 defs.py 37e9d68  # 转写第 3 批
python3 run.py           # 第 0 至 3 批，深度 3，写 reports/results.json
python3 crosscheck.py    # 设计对定义文件
python3 codecheck.py         # 第 4 批，代码（默认 37e9d68）
python3 openloop.py          # 开环检查
python3 quotecheck.py 37e9d68  # 原句还在不在
python3 mutate.py        # 埋错，写 reports/mutations.json
python3 compare.py batches/batch1-overview.ttl extractions/batch1-model-a.ttl extractions/batch1-model-b.ttl
```
