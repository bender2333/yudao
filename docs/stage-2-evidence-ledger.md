# Stage2 工作包证据账

日期：2026-09-07。  
冻结起点：`239c3b1b4eb71020555ccff62764abcf4e6f8e9d`（`harness_1`，`origin/harness_1`）。  
本表区分五类证据，不能互相替代：主线代码、候选代码、局部测试、真实运行、最终验收。

阶段状态：**PARTIAL**。局部代码、局部测试或一次真实成功请求都不能关闭阶段。

## 1. 基线与工作树

| 项 | 事实 |
| --- | --- |
| HEAD | `239c3b1` `stagecommit` |
| 分支 | `harness_1` = `origin/harness_1` |
| 工作树（P0 记录时） | 已修改 `jour.md`（既有 A/B/C/D 设计笔记，不代为提交）；未跟踪 `.serena/project.yml`（不提交）；未跟踪后纳入本账的 `docs/grok-stage2-completion-plan.md` |
| 隔离候选远端 | `origin/codex/stage2-workspace` @ `0e1616d` |

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
| W2 工作台骨架 | 已在主线 | 隔离 SHA 过时 | Node UI 部分覆盖；U1/U2/U4 无测试 | 旧 UI 曾误建任务；新工作台未做完整浏览器矩阵 | 未关闭 | 主线局部完成 |
| W3 Context/详情 | 已在主线 | 隔离 SHA 过时 | Context parts 测试存在 | 64KB Request 在 320px 曾形成超高页面 | U4 未修，不能称详情完成 | PARTIAL |
| W4 列表/用量 | 已在主线 | — | 分组费用有 UI 测试；总计条缺费用 | 未作为真实验收关闭项 | O3 UI 筛选、O6 总计未闭合 | PARTIAL |
| W5 总览/全局输入 | 骨架已有 | — | 终态草稿/新建入口已测（U6） | 连续输入真实验收未通过 | 待 P3 | PARTIAL |
| W6 部门指导 | `fe78667` 已在主线 | 旧 `4c684b4` 的 auto-processed 已不在主线 | 接收/注入/非活动部门只读激活已测 | 无真实指导闭环 | G1/G2/G3 仍 PARTIAL | PARTIAL |
| W7 联调 | 未开始 | — | 无 1440/1024/390/360/320 对照报告 | 无 | 未开始 | 未开始 |
| Prompt 比较 | 仅有比较方案 | — | 无固定任务比较 | 真实验收仍用原 Prompt | 未开始 | 未开始 |
| 2.1–2.4 / 2.E | 未开始 | 研究资料已导入 | — | — | 依赖 P0–P6 | 未开始 |

## 4. 当前 HEAD 的 O/U/G 缺口（P2）

只读审计日期 2026-09-07，对象为 `239c3b1`。

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

## 5. 真实运行保留入口

失败与部分成功均保留，不改写：

- `.tmp/stage2-real-acceptance/`
- `.tmp/stage2-real-acceptance-browser2/`
- `.tmp/stage2-real-acceptance-compaction/`
- `.tmp/stage2-observed-real-acceptance/`

指定配置仍是 `provider.md` 的服务与模型；能力值为试验限制，不是服务商标称上限。

## 6. 记录规则

- 主线完成 ≠ 阶段完成。
- 候选 SHA 不得写入“主线已完成”。
- 历史测试数字不与当前 HEAD 混加。
- 每个后续工作包提交后更新本表的对应行，并附命令、通过/失败/跳过、报告路径。
