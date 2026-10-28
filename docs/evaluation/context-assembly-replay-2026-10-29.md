规则版本 `sha256:6d66cca8e0935b187fb1b2580dcdcda1b4ee60fe3948894bb7f225790f3b369b`；回放 646 步。

- 用量：8331638 → 6930883 token，省 1400755（16.8%）。
- 召回：0.9548 → 0.9448（按需要的记号计）。
- 浪费：50.0% → 40.1%。
- 召回下降的步：18 步。

**按部门**

| 分组 | 步数 | 现状 token | 新视图 token | 省 | 召回 现状 | 召回 新视图 |
| --- | --- | --- | --- | --- | --- | --- |
| engineering | 311 | 4051482 | 3424994 | 15.5% | 0.9734 | 0.966 |
| product | 97 | 457403 | 421504 | 7.8% | 0.983 | 0.983 |
| quality | 238 | 3822753 | 3084385 | 19.3% | 0.9662 | 0.9648 |

**按步序**

| 分组 | 步数 | 现状 token | 新视图 token | 省 | 召回 现状 | 召回 新视图 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 105 | 1049534 | 828250 | 21.1% | 0.9953 | 0.9953 |
| 16+ | 63 | 1787171 | 1257195 | 29.6% | 0.969 | 0.9337 |
| 2-3 | 163 | 1622820 | 1352549 | 16.7% | 0.9802 | 0.9802 |
| 4-7 | 190 | 2051049 | 1844656 | 10.1% | 0.9702 | 0.9689 |
| 8-15 | 125 | 1821064 | 1648233 | 9.5% | 0.9468 | 0.9455 |

**逐条规则的贡献**（打开这一条相对关掉它省下的用量；召回一列为正表示这一条会丢召回）

| 规则 | 打开后省下的用量 | 这一条省下的 token | 这一条丢掉的召回 |
| --- | --- | --- | --- |
| input_single_copy | 13.3% | 295030 | +0.0006 |
| superseded_read_collapse | 15.4% | 119944 | -0.0025 |
| tool_result_age_budget | 9.3% | 624063 | -0.0071 |
| error_result_keep | 16.9% | -6432 | +0.0002 |
| pinned_reference_gate | 13.7% | 259715 | -0.0000 |
| round_fold_granularity | 16.8% | 0 | -0.0000 |

**R5 逐段核对**（这一段换成摘要能省多少、会不会丢掉只在这一段里的记号）

| 段 | 步数 | 省下的 token | 丢掉的记号 | 丢记号的步 |
| --- | --- | --- | --- | --- |
| current_delivery_spec | 172 | 191334 | 0 | 0 |
| prior_delivery | 29 | 29990 | 0 | 0 |
| existing_overview | 132 | 18480 | 0 | 0 |
| causal_chain | 646 | 16329 | 0 | 0 |
| binding_refs | 646 | 15588 | 0 | 0 |
| prior_structure | 6 | 8430 | 0 | 0 |
| prior_initial_prd | 5 | 4605 | 0 | 0 |
| current_product_decisions | 23 | 2047 | 0 | 0 |

**召回下降的步（逐个）**

| run | 部门 | 步 | 现状召回 | 新视图召回 | 缺的记号 |
| --- | --- | --- | --- | --- | --- |
| run_487814ceab394396 | engineering | 11 | 1.0 | 0.9474 | usr/bin/env |
| run_487814ceab394396 | engineering | 20 | 1.0 | 0.9167 | serialization |
| run_d50eaf60623e42d6 | engineering | 7 | 0.5714 | 0.381 | ). Prints a usage line on stderr. -, error: bad.txt: 'utf-8' codec can't decode byte 0xff in position 2: invalid start byte, error: missing.txt: [Errno 2] No such file or directory: 'missing.txt' 1, line, no traceback., lines: 2 words: 2 chars: 4 file: sample.txt 0, sh python textstats.py missing.txt; echo $?, sh python textstats.py sample.txt; echo $?, sh python textstats.py; echo $?, usage: python textstats.py [--json] <file> 2, — file error  Path missing or unreadable, or the bytes are not valid UTF-8. stdout stays empty, stderr is exactly one line |
| run_22dfbdc3050c4b8a | engineering | 21 | 1.0 | 0.7143 | ArgumentParser, parse_known_args |
| run_062b44be06ff46bc | engineering | 5 | 0.8333 | 0.7778 | Standard library only. Exit codes: 0 success, 1 file error, 2 wrong arguments.","new_text":"## Usage, sh $ printf 'l1\ l2\ l3\ ' > /tmp/t.txt $ python head.py /tmp/t.txt 文件: /tmp/t.txt l1 l2 l3, sh python head.py <file> python head.py -n 20 <file>, the content line count is 10. |
| run_11cbb348bbb54e93 | engineering | 29 | 0.875 | 0.75 | Comprehensive, sp.dist_to[dest] |
| run_11cbb348bbb54e93 | engineering | 35 | 1.0 | 0.6667 | dev/null |
| run_11cbb348bbb54e93 | engineering | 43 | 0.8333 | 0.6212 | --line_preference, <meters> meters (<km> km), Connectivity, PathfindingConfig().preferred_lines == [], _SOURCE_SIDE_PATH, __post_init__, _best_key, _node_state, best_key, construction |
| run_11cbb348bbb54e93 | engineering | 44 | 1.0 | 0.875 | src/data_loader.py |
| run_11cbb348bbb54e93 | engineering | 47 | 0.9362 | 0.7872 | Comprehensive, _check_data, args.c, documentation, duplicate/self, instructions, next_state, optimisation, pref_pen, validate_data |
| run_11cbb348bbb54e93 | engineering | 48 | 0.9545 | 0.9091 | --format json, heapq.h |
| run_11cbb348bbb54e93 | engineering | 49 | 0.9 | 0.8 | __init__, tests/__init__.py |
| run_11cbb348bbb54e93 | engineering | 50 | 0.913 | 0.8696 | --format json, authoritative, continuation, inconsistent, src/models.py, src/pathfinding.py |
| run_11cbb348bbb54e93 | quality | 11 | 0.8409 | 0.7273 | --line_preference, --max_transfers, Alternatively, Contradiction, Implementation, contradicting, contradiction, contradictory, for one transfer and, independently |
| run_11cbb348bbb54e93 | quality | 19 | 0.8302 | 0.6981 | Alternatively, Contradiction, Requirements, Rework_product, __post_init__, authoritative, contradiction, contradictory, fare/time, functionality |
| run_11cbb348bbb54e93 | quality | 20 | 0.6571 | 0.6 | Professional, Rework_product, authoritative, automatically, contradiction, contradictions, contradictory, fare/time, functionally, instructions |
| run_11cbb348bbb54e93 | quality | 22 | 0.8276 | 0.7931 | Alternatively, authoritative, contradiction, contradictory, inconsistency, verification |
| run_7be8a0074290452c | engineering | 16 | 0.9545 | 0.4545 | __file__, a.txt, capture_output, emoji.txt, empty.txt, exist_ok, nonl.txt, nonl2.txt, nope.txt, sub/a |
