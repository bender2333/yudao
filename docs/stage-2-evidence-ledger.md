# Stage2 工作包证据账

日期：2026-09-08，2026-09-09 补记 HEAD，2026-09-10 记 S2-0。  
原始冻结起点：`239c3b1b4eb71020555ccff62764abcf4e6f8e9d`。  
当前被测应用提交：`76e4c74` `feat(B1): 项目事项内核与 S2-0 收口`。此前 S3 被测应用仍是 `cdcdce5`；A1–A3 代码在 `03c25d4`，但真实小窗到 QA 未关闭，S2-1 尚未冻结。  
文档提交不改变被测应用身份；本文件更新只解释当前提交与历史记录。  
本表区分五类证据，不能互相替代：主线代码、候选代码、局部测试、真实运行、最终验收。

阶段状态：**PARTIAL**。局部代码、局部测试或一次真实成功请求都不能关闭阶段。当前执行入口：[剩余工作计划](stage-2-completion-plan-2026-09-10.md)。

## 1. 基线与工作树

| 项 | 事实 |
| --- | --- |
| 原始起点 | `239c3b1` `stagecommit` |
| 当前 HEAD | `76e4c74` `feat(B1): 项目事项内核与 S2-0 收口` |
| 本轮主线增量 | A1–A3 `6a89056`…`03c25d4`；B0 `f95d3fd`/`735e120`；S2-0/B1 `76e4c74` |
| 分支 | `harness_1` 领先 `origin/harness_1` 13 个提交 |
| 工作树 | 未跟踪 `.serena/project.yml`，不提交 |
| 隔离候选远端 | `origin/codex/stage2-workspace` @ `0e1616d`，不整支合入 |
| S2-0 回归 | `python -m pytest -q harness/tests -p no:cacheprovider --junitxml=.tmp/s2-0-full.xml`：923 通过、0 失败、1 跳过，1152.90 秒。定向项目测试 38 通过。未调真实模型 |

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
| 第一阶段真实验收 | 运行时已具备持续输入、压缩、QA、封存 | — | 确定性回归存在 | 基础交付曾 release；连续输入/小窗缺最终 QA | 未关闭 | PARTIAL |
| OMP 系统审查 | 审查文档已有 | — | 采用项已部分落到 W1/W3 | 不单独算运行验收 | 采用项尚未按固定清单逐项独立验证 | PARTIAL |
| W1 采集查询 | 已在主线 | 隔离 SHA 过时 | `test_observability.py` 等已覆盖 O1/O2/O4/O5 | 真实记录可打开过载原文 | 未与完整 UI 联调 | 主线局部完成 |
| W2 工作台骨架 | 已在主线 | 隔离 SHA 过时 | Node UI 含 U1/U2/U6；真实 320px 矩阵未做 | 旧 UI 曾误建任务 | W7 浏览器矩阵未关闭 | 主线局部完成 |
| W3 Context/详情 | 已在主线 `20c7e42` | 隔离 SHA 过时 | Raw CSS 选择器已测 | 64KB/320px 真机仍待 W7 | 详情行为已修，真机未验 | PARTIAL |
| W4 列表/用量 | 已在主线 `20c7e42` | — | O3 取消筛选、O6 总计费用/不可合计已测 | 未作为真实验收关闭项 | 查询与 UI 口径已对齐，联调未关 | 主线局部完成 |
| W5 总览/全局输入 | 骨架已有 | — | 终态草稿/新建入口已测（U6） | 连续输入真实验收未通过 | 待 P3 | PARTIAL |
| W6 部门指导 | `fcb06ab` | 旧 auto-processed 已不在主线 | G1 解释/动作合同、空结果与旧写入反例、G2/G3 调度准入与 QA 竞态已测；浏览器待验 | 无真实指导闭环 | 真实验收未做 | 主线局部完成 |
| W7 联调 | 未开始 | — | 无 1440/1024/390/360/320 对照报告 | 无 | 未开始 | 未开始 |
| Prompt 比较 | 仅有比较方案 | — | 无固定任务比较 | 真实验收仍用原 Prompt | 未开始 | 未开始 |
| 2.1–2.4 / 2.E | B1 覆盖 2.E 的 E0–E2 内核；E3=B4、学习轨道未开始 | 研究资料已导入 | B1 局部测试见 S2-0 | 无 | 依赖 S2-1 冻结与 B3/B4 | 主线局部完成 / 学习未开始 |
| B1 项目事项内核（S2-0） | 有：`76e4c74` | — | 项目 38 通过；完整 Python 923/1 跳过 | 无 | 未做 B3 外壳与 B4 三次变更 | 主线局部完成 |
| A1 小窗到 QA（S2-1） | 压缩规则已在 `03c25d4`/`76e4c74` | — | 未声明工具反例通过 | `run_f721f94809f443d7` 31 次压缩后 `model_steps_exhausted`，无 QA；审计 verified | 未关闭 | PARTIAL |
| A2 组合审计（S2-1） | `6c7750c`/`b3c35f0` | — | `test_smoke_guidance_audit.py` 冻结上 verified | 无新的真实组合 run | 真实组合待 B4 | 主线局部完成 |
| A3 timeout/64KB（S2-1） | 应用无长度分支；测试收口待本提交 | — | timeout 10/10；五参数化 5 通过；Node 64KB 通过 | 无 | 浏览器 64KB 仍是脚本注入 | 主线局部完成 |



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

### 4.2 当前被测提交 `cdcdce5`（2026-09-08）

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

## 5. 真实运行保留入口

失败与部分成功均保留，不改写：

- `.tmp/stage2-real-acceptance/`
- `.tmp/stage2-real-acceptance-browser2/`
- `.tmp/stage2-real-acceptance-compaction/`
- `.tmp/stage2-observed-real-acceptance/`
- `.yudao/p4-smoke-20260907a/`：`run_506da3ee67304de7` 首次 happy 请求 HTTP 400，无交付/QA；诊断正文当时只有 status_code
- `.yudao/p4-smoke-20260908-s2/`：`run_7c4ea172110841cc` 修正 schema 后 DONE/release

指定配置仍是 `provider.md` 的服务与模型；能力值为试验限制，不是服务商标称上限。

## 6. 记录规则

- 主线完成 ≠ 阶段完成。
- 候选 SHA 不得写入“主线已完成”。
- 历史测试数字不与当前 HEAD 混加。
- 每个后续工作包提交后更新本表的对应行，并附命令、通过/失败/跳过、报告路径。
