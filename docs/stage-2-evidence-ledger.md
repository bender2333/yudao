# Stage2 工作包证据账

日期：2026-09-08，2026-09-09 补记 HEAD，2026-09-10 记 S2-0，2026-09-11 记候选冻结 `4c5cde4`，2026-09-14 记 A1 完成条件、B3 外壳与 A4 比较器，2026-09-15 记 harness 基线实施计划收口。  
原始冻结起点：`239c3b1b4eb71020555ccff62764abcf4e6f8e9d`。  
当前被测应用：`041eaa1`（Context/Trace 收口）。按用户指定的 `docs/stage-2-implementation-plan.md`，2.1–2.6.5 已关闭。学习轨道原 2.2–2.4 仍后置。

文档提交不改变被测应用身份；本文件更新只解释当前提交与历史记录。  
本表区分五类证据，不能互相替代：主线代码、候选代码、局部测试、真实运行、最终验收。

阶段状态：**CLOSED**（实施计划 2.1–2.6.5）。2.6.6 全量回归数字另记，不以未完成的 pytest 冒充通过。当前执行入口：[实施计划](stage-2-implementation-plan.md)。

## 1. 基线与工作树

| 项 | 事实 |
| --- | --- |
| 原始起点 | `239c3b1` `stagecommit` |
| 当前 HEAD | B3 合入后以新提交为准；此前被测应用身份是 `4c5cde4` |
| 本轮主线增量 | A1–A3 `6a89056`…`03c25d4`/`b2c25ca`；B0 `f95d3fd`/`735e120`；S2-0/B1 `76e4c74`；A3 timeout `4c5cde4`；A4 比较器 `d872da1`；B3 外壳已合入 |
| 分支 | `harness_1` 领先 `origin/harness_1` 的文档提交以推送时点为准；应用身份 `4c5cde4` |
| 工作树 | 未跟踪 `.serena/project.yml`，不提交 |
| 隔离候选远端 | `origin/codex/stage2-workspace` @ `0e1616d`，不整支合入 |
| S2-0 回归 | `python -m pytest -q harness/tests -p no:cacheprovider --junitxml=.tmp/s2-0-full.xml`：923 通过、0 失败、1 跳过，1152.90 秒。定向项目测试 38 通过。未调真实模型 |
| `4c5cde4` 局部测试 | timeout 连续 10 次通过；该函数五参数化 5 通过；Node UI 35 通过（含 64KB Raw）。A1 反例与 `test_smoke_guidance_audit.py` 在同源应用上通过 |

## 2. 候选提交拓扑

`origin/codex/stage2-workspace` 相对 HEAD 仍可见、但不是 HEAD 祖先的提交：

| SHA | 主题 | 与 HEAD 的关系 |
| --- | --- | --- |
| `ad08784` | 原型工作台骨架 | HEAD 的 `harness/web` 已是后续版本，多出约 350 行，不是未合入孤本 |
| `5729856` | 终态证据与草稿 | 行为已进入主线 UI 测试与终态草稿路径 |
| `5c6ffb1` | 模型尝试查询 | HEAD 的 `observability.py` / 测试已是后续版本 |
| `0473b01` | 连接复用与观测合并 | HEAD 对应后续 `d4adff8` 及之后提交 |
| `0e1616d` | 结构化 Context parts | HEAD 对应后续 `a8f9015` 及之后提交 |

HEAD 在这些候选之后继续有：`e3b9830` Context 查看、`db71d5e` 测试、`fe78667` 部门指导、`b4aa6ce`/`7bf3c70` 观测导出。

**P1 结论：不整支合并 `origin/codex/stage2-workspace`。** 主线已是同一工作的后续版本；整支合并会回退。若后续发现隔离分支独有且主线缺失的文件，只樱桃摘取那些文件，不合并整支。

## 3. 工作包证据表

图例：`主线` = 已在 `239c3b1`；`候选` = 仅隔离分支或过时 SHA；`局部测试` = Fake/本地 HTTP/SSE/Node；`真实运行` = `provider.md` 指定模型的实际调用；`最终验收` = 冻结源码上的完整 Web/小窗/QA/封存/来源审计。

| 工作包 | 主线代码 | 候选代码 | 局部测试 | 真实运行 | 最终验收 | 阶段状态 |
| --- | --- | --- | --- | --- | --- | --- |
| Provider 连接/目录/部门绑定 | 有：`fced43e`、`2930ba1`、`0da5740` | 不作为主线缺口 | 本地多 Provider、连接复用、过载分类已通过 | 有成功探针和复用；长流程仍有过载/断流失败 | 未关闭 | PARTIAL |
| 第一阶段真实验收 | 运行时已具备持续输入、压缩、QA、封存 | — | 确定性回归存在 | back Provider 的 A1 已到 QA/release；luna 失败记录保留 | S2-1 已关闭 | CLOSED |
| OMP 系统审查 | 审查文档已有 | — | 采用项已部分落到 W1/W3 | 不单独算运行验收 | 采用项尚未按固定清单逐项独立验证 | PARTIAL |
| W1 采集查询 | 已在主线 | 隔离 SHA 过时 | `test_observability.py` 等已覆盖 O1/O2/O4/O5 | 真实记录可打开过载原文 | 未与完整 UI 联调 | 主线局部完成 |
| W2 工作台骨架 | 已在主线 | 隔离 SHA 过时 | Node UI 含 U1/U2/U6；真实 320px 矩阵未做 | 旧 UI 曾误建任务 | W7 浏览器矩阵未关闭 | 主线局部完成 |
| W3 Context/详情 | 已在主线 `20c7e42` | 隔离 SHA 过时 | Raw CSS 选择器已测 | 64KB/320px 真机仍待 W7 | 详情行为已修，真机未验 | PARTIAL |
| W4 列表/用量 | 已在主线 `20c7e42` | — | O3 取消筛选、O6 总计费用/不可合计已测 | 未作为真实验收关闭项 | 查询与 UI 口径已对齐，联调未关 | 主线局部完成 |
| W5 总览/全局输入 | 骨架已有 | — | 终态草稿/新建入口已测（U6） | 连续输入真实验收未通过 | 待 P3 | PARTIAL |
| W6 部门指导 | `fcb06ab` | 旧 auto-processed 已不在主线 | G1 解释/动作合同、空结果与旧写入反例、G2/G3 调度准入与 QA 竞态已测；浏览器待验 | 无真实指导闭环 | 真实验收未做 | 主线局部完成 |
| W7 联调 | B3 矩阵替代旧 run 壳联调 | — | Node 23；浏览器 `.yudao/s2-2-b3-20260914/` 五档×浅/深 | 无真实模型 | 外壳矩阵关闭；64KB 以 Node 为准 | 主线局部完成 |
| Prompt 比较 | 协议与比较器；结论保留原版 | — | Fake 4 通过 | 8 场 `agnes-3.0-flash`：`.yudao/s2-3-a4-20260914/`。候选任务 2 `max_cycles`。不改默认 Prompt | 真比较关闭 | 主线局部完成 |
| 2.1–2.4 / 2.E | B1+B3+B4；2.1 L1–L3 已提交；2.2–2.4 后置 | — | analysis L1 13 / L2 5 / L3 2 | B4 三事项真实放行 `.yudao/s2-4-b4-20260914/` | 2.E 三次变更关闭；学习轨道移出 Stage 2 | 主线局部完成 |
| B1 项目事项内核（S2-0） | 有：`76e4c74` | — | 项目 38 通过；完整 Python 923/1 跳过 | 无 | B3/B4 已做 | 主线局部完成 |
| B3 第三版外壳（S2-2） | `POST /api/runs` 删除；项目壳 + 第一版部门内部 | — | Node 23；pytest 57 | fake 浏览器矩阵 | B4 已在此外壳上三次真实变更 | CLOSED |
| A1 主验收到 QA（S2-1） | 压缩规则已在 `03c25d4`/`4c5cde4` | — | 未声明工具反例通过；8000 附录 | luna `run_d004266f212a4c2c` 窗口 32000 `FAILED / provider_error`，保留。用户改 back：`run_770ea827673545a5` 窗口 32000 DONE/release，`agnes-3.0-flash`，压缩 2 次后继续 QA。512K 对照 `run_8741e726d9dd4ba6` DONE/release | 本冻结关闭 | 主线局部完成 |



## 4. O/U/G 状态

### 4.1 历史审计（2026-09-07，对象 `239c3b1`）

下表保留原时点结论，不能当作 `fcb06ab` 的当前状态。

| ID | 状态 | 证据口径 |
| --- | --- | --- |
| O1 | CLOSED | 查询区分 prepared/requesting/partial/completed/failed/cancelled；部分输出不进工具与有效历史 |
| O2 | CLOSED | `observed_at` + 按来源分组，不拼造 Provider 时间 |
| O3 | PARTIAL | API 保留 `cancelled`；UI 标签/筛选/路由无取消 |
| O4 | CLOSED | 失败/取消消息只在观测详情 |
| O5 | CLOSED | `reported=False` 不进上报小计 |
| O6 | PARTIAL | 分组有费用；总计条无费用；不可合计与未上报未区分 |
| U1 | OPEN | `popstate` 不清理 `runPayload`，跨任务后退可串数据 |
| U2 | OPEN | SSE 不刷新部门缓存；详情关闭 SSE 后不再更新 |
| U3 | PARTIAL | 部门页已用短目标；观测范围/面包屑仍用全文任务 |
| U4 | OPEN | Request/Response/Raw 的 `.dw-json` 无视口内滚动 |
| U5 | PARTIAL | 查询已有 requested/actual；列表/详情折叠成单一身份 |
| U6 | CLOSED | 终态保留草稿，只有显式新建创建 run |
| G1 | PARTIAL | 已删除按激活事件自动 processed；`completed` 仍可仅凭自然语言 |
| G2 | PARTIAL | 非活动部门可被 `guidance_only` 安排；被让出工作依据未单独保存 |
| G3 | PARTIAL | 取消、在途指导、QA 待处理有片段；缺竞态矩阵测试 |

### 4.2 历史被测提交 `cdcdce5`（2026-09-08）

| ID | 状态 | 证据口径 |
| --- | --- | --- |
| O1-O6 | 代码及局部回归通过、浏览器待验 | `20c7e42` 已补取消筛选、费用总计、Raw 滚动、请求/返回身份 |
| U1-U6 | 代码及局部回归通过、浏览器待验 | `20c7e42` 已补 popstate、SSE 刷新、短目标、终态草稿 |
| G1 | 代码及局部回归通过、浏览器/真实指导待验 | `fcb06ab`：`explained` 与 `completed` 分开；空结果和指导前旧写入不能标动作完成；宿主只绑定本指导被采用后的结果 |
| G2 | 代码及局部回归通过 | `0b076f6`/`d52d7d6` 被让出工作恢复与只读准入 |
| G3 | 代码及局部回归通过 | 取消优先、QA 放行前待处理指导、拒收回应不消耗指导 |

S1 局部验证：相关 Python 233 通过、0 失败、374.48 秒；Node 34 通过。未调用真实模型。F1/F2 正式回归已纳入 `test_department_guidance.py`。

S2：HTTP 400 根因是 `submit_product_spec.change_record` 的 anyOf schema。诊断结论 [s2-http400-2026-09-08.md](s2-http400-2026-09-08.md)。新 happy smoke `run_7c4ea172110841cc` DONE/release。旧失败 `run_506da3ee67304de7` 保留。

S3：联合验收 [s3-acceptance-2026-09-08.md](s3-acceptance-2026-09-08.md) 为 PARTIAL。浏览器主 run `run_cb69cec4c1f74100` DONE/release；连续输入与部门指导已取得。小窗压缩 `run_2268b511fece4392` 触发摘要后因 Gemini 返回 function_call 被宿主拒绝，未到 QA。本机 `test_responses.py::...[timeout]` 仍有既有超时 flake。

### 4.3 候选冻结 `4c5cde4`（2026-09-11）

| ID | 状态 | 证据口径 |
| --- | --- | --- |
| O1-O6 / U1-U6 / G1-G3 | 代码及局部回归沿用 `cdcdce5` 之后主线 | 本冻结未改这些实现 |
| A3 timeout | 局部关闭 | `test_responses.py` timeout 连续 10 次、五参数化 5 通过；不改生产超时 |
| A1 真实小窗 | 未关闭 | 三场 `model_steps_exhausted`，见 `.yudao/s2-1-a1-20260911/`。不提高 `MAX_MODEL_STEPS` |
| A2 真实组合 | 本冻结关闭（API 路径） | `run_ffa5247370e8469a` DONE/release，审计 verified。不是浏览器点击 |
| A3 浏览器 64KB / 矩阵 | 关闭 | `.yudao/s2-1-a3-20260911/`：10 档 PASS；64KB 在 `.dw-json` 内滚动，320 宽无横向溢出 |


## 5. 真实运行保留入口

失败与部分成功均保留，不改写：

- `.tmp/stage2-real-acceptance/`
- `.tmp/stage2-real-acceptance-browser2/`
- `.tmp/stage2-real-acceptance-compaction/`
- `.tmp/stage2-observed-real-acceptance/`
- `.yudao/p4-smoke-20260907a/`：`run_506da3ee67304de7` 首次 happy 请求 HTTP 400，无交付/QA；诊断正文当时只有 status_code
- `.yudao/p4-smoke-20260908-s2/`：`run_7c4ea172110841cc` 修正 schema 后 DONE/release
- `.yudao/s2-1-a1-20260910/`：`run_f721f94809f443d7` 窗口 8000，参考 12180 字节，31 次压缩后 `model_steps_exhausted`，无 QA；冻结当时为 `76e4c74`
- `.yudao/s2-1-a1-20260911/`：`run_55c1957632854891` / `run_b432e4604d3149d1` / `run_16d31b59894c4387`，窗口 8000，均未到 QA
- `.yudao/s2-1-a2-20260911/`：`run_ffa5247370e8469a` 窗口 32000，DONE/release
- `.yudao/s2-1-a3-20260911/`：fake/demo 浏览器矩阵与 64KB 注入
- `.yudao/s2-1-a1-20260914/`：luna 主验收 `run_d004266f212a4c2c` 窗口 32000，`provider_error`；对照 `run_84fb12435fa9454c` 窗口 1M，DONE/release
- `.yudao/s2-2-b3-20260914/`：B3 fake 浏览器矩阵，`POST /api/runs` 404，五档×浅/深




指定配置仍是 `provider.md` 的服务与模型；能力值为试验限制，不是服务商标称上限。

## 6. 记录规则

- 主线完成 ≠ 阶段完成。
- 候选 SHA 不得写入“主线已完成”。
- 历史测试数字不与当前 HEAD 混加。
- 每个后续工作包提交后更新本表的对应行，并附命令、通过/失败/跳过、报告路径。
