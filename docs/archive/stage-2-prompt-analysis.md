# Stage 2 Prompt 分析（2.5.1）

日期：2026-09-15。计划条目：`docs/stage-2-implementation-plan.md` §2.5.1。  
方法：只读已有真实 transcript / 事件库 / 比较报告，**不调用模型**，不改 `harness/department_prompts.py`，不改任何 Prompt 默认。  
凭据、Authorization、完整部门 Prompt 正文不进入本文件。

## 建议：保留默认 Prompt

与 [A4 结论](stage-2-a4-report.md) 一致：**保留原版**。本样本不能支持改默认，也不能证明「平均往返减少 20%」可测量。没有一条既有证据、又不与 A4 冲突的具体改写。

## 样本

三包共 **13 个 run**（满足「10+ 真实任务」的计数；任务族并不独立同质）。Provider 均为 `p4-back` / `agnes-3.0-flash` / Responses。A4、B4 任务窗 32000、`max_cycles=8`；A1 主场 32000、对照 512000，`max_cycles=16`。未用 FakeAdapter。

| 包 | 目录 | 用途 | Prompt |
| --- | --- | --- | --- |
| A4 | `.yudao/s2-3-a4-20260914/` | 4 任务 × 基线/候选 | 基线 `DEFAULT_PROMPTS` v0；候选只给工程追加三段（项目配置 v1） |
| B4 | `.yudao/s2-4-b4-20260914/` | 同一项目三次变更 | 默认部门 Prompt；工程仅追加无行为含义标记 `B4-PROMPT-MARK v1` |
| A1 back | `.yudao/s2-1-a1-back-20260914/` | 32k 主场 + 512k 对照 | 默认 |

A4 身份：`proj_366696b9b6ce4101`（baseline）、`proj_6aa810700af440fd`（candidate）。B4 主项目 `proj_22c675f3fce8469e`。

## 计数口径

从各包 `events.sqlite` 统计，不采用比较器里 `request_count=0` 的展示缺陷。

- **循环 / 往返**：`department_activated` 次数 = `cycle_count`（内核每激活一次部门 +1）。快乐路径下限是 4：产品 1 + 工程计划 1 + 工程交付 1 + 质检 1。
- **协作请求**：事件类型 `collaboration_requested` / `collaboration_responded` / `collaboration_closed`。A1 报告里的 `collaboration_requests` 数组作交叉核对。
- **返工**：`qa_submitted.verdict ∈ {rework_product, rework_engineering}`。提案被主机拒收（`proposal_rejected`）单独记，不计入 QA 返工。
- **压缩**：`compaction_recorded`；对照 `model_requested.purpose=compaction`。
- **停止原因**：终端事件 `run_done` / `run_paused` / `run_failed` 的 `stop_reason`。
- **工作请求**：`model_requested.purpose=work`（含部门内多步工具回合，不是部门间往返）。
- **用量**：`model_attempt_finished.usage.total_tokens` 合计（含失败尝试与压缩）。

## 逐 run

### A4（8）

协议：`docs/stage-2-a4-protocol.md`。比较器：`.yudao/s2-3-a4-20260914/a4-compare.md`。正式结论：`docs/stage-2-a4-report.md`。

| 任务 | 组 | run_id | work_item_id | 循环 | 工作请求 | 协作 | QA 返工 | 压缩 | 停止 | 结算 | token |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |
| 1 逐行文本 | 基线 | `run_99231365e3d3427e` | `wi_50013c3aeecb4e64` | 4 | 13 | 0 | 0 | 0 | released | adopted | 103270 |
| 1 逐行文本 | 候选 | `run_ac9b53bd7c164d7c` | `wi_fa63bf61b8624e4c` | 4 | 12 | 0 | 0 | 0 | released | adopted | 128023 |
| 2 CSV | 候选 | `run_bbacdca62d374995` | `wi_852bc692daf84904` | 8 | 51 | 0 | 2 | 12 | **max_cycles** | 未结算 | 1097343 |
| 2 CSV | 基线 | `run_074ac038a24b4985` | `wi_80331a77598648c6` | 5 | 18 | 0 | 0 | 0 | released | adopted | 236536 |
| 3 澄清 | 基线 | `run_94b65c7bd856494d` | `wi_0d894c5ad03c4da0` | 4 | 10 | 0 | 0 | 0 | released | adopted | 119532 |
| 3 澄清 | 候选 | `run_2d3ca293affb4f18` | `wi_889e0457b03b447b` | 5 | 15 | 0 | 0 | 1 | released | adopted | 211509 |
| 4 空行回归 | 候选 | `run_8e89c2deb60f407d` | `wi_0f3e627e1582442b` | 4 | 13 | 0 | 0 | 0 | released | adopted | 133263 |
| 4 空行回归 | 基线 | `run_e0ead7799ecf4333` | `wi_346244792646471e` | 4 | 12 | 0 | 0 | 0 | released | adopted | 120998 |

候选任务 2 在第 8 次激活后 `RUN_PAUSED` / `max_cycles`（`run_bbacdca62d374995` 保留）。其余 7 场 `DONE` / `released`。两侧都没有计划接纳前写文件。基线合计约 58 万 token，候选约 157 万（其中任务 2 约 110 万）。

候选任务 2 路径：`QUALITY → REWORK_ENGINEERING` 两次，工程第 8 循环耗尽。两次 QA 缺陷同一条：`tests/fixed_input.csv` CRLF（48 字节）对合同 LF（45 字节）。另有一次工程 `delivery_spec` 被拒：`check_names` 缺少绑定当前快照的 `csv_fixed_input` 回执。流中断 `provider_error` 后内核重试成功，不记为 Prompt 问题。

### B4（3）

报告：`.yudao/s2-4-b4-20260914/report.md`。三事项均 `DONE` / `released` / `deliverable_adopted`。

| 事项 | run_id | work_item_id | 循环 | 工作请求 | 协作 | QA 返工 | 压缩 | 停止 | token |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |
| 1 stdin 逐行 | `run_4817d4cc746e4d33` | `wi_c28637c695e84fef` | 4 | 17 | 0 | 0 | 0 | released | 195494 |
| 2 文件输入 | `run_df2686239efb4276` | `wi_bd28e28c82dc49bd` | 5 | 17 | 0 | 0 | 0 | released | 204061 |
| 3 只保留首次 | `run_cce0ff393dae4c6b` | `wi_af1271bf1b9547ee` | 5 | 13 | 0 | 0 | 0 | released | 159830 |

事项 2、3 各多 1 次产品激活：第一次 `product_spec` 被主机拒收，第二次通过。拒收字段分别是 `change_record.rationale` 必须非空、`decision_changes` 必须对每条仍有效决定显式 retain/integrate/retire。这是后续事项的合同模式校验，不是向用户追问。事项 3 有 1 次 `model_attempt_failed` + 重试后放行。

### A1 back（2）

| 场景 | run_id | 循环 | 工作请求 | 协作 | QA 返工 | 压缩 | 停止 | token | 窗 |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| a1-main-32k | `run_770ea827673545a5` | 9 | 20 | 0 | 0 | 2 | released | 319770 | 32000 |
| a1-contrast-512k | `run_8741e726d9dd4ba6` | 4 | 9 | 0 | 0 | 0 | released | 75080 | 512000 |

32k 主场 9 循环来自 **两次用户追加输入**（设计内的方向调整，不是产品自发澄清）：

1. `engineering_usage`：无参数时打印一行 usage、退出 0。
2. `quality_flags`：未知 flag 非零退出，并保持 hello / 空 argv 行为。

对应 3 次 `spec_accepted`、2 次 `spec_superseded`。质检第一次 `qa_review` 因 `checks` 未全部 exit 0 被拒，第二次 `release`（缺陷列表空）。压缩 2 次（工程、质检各 1），与小窗设定一致，不是无效部门往返。512k 对照无追加输入、无压缩，4 循环快乐路径。

`collaboration_audit`：`pre_spec_consultation=false`，`requirements_action=false`，`directions=[]`。

## 合计

| 指标 | A4 基线 4 | A4 候选 4 | B4 3 | A1 2 | 13 run 合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 循环 | 4+5+4+4 = 17 | 4+8+5+4 = 21 | 4+5+5 = 14 | 9+4 = 13 | 65 |
| 协作请求 | 0 | 0 | 0 | 0 | **0** |
| QA 返工 | 0 | 2（同一候选 run） | 0 | 0 | 2 |
| 压缩 | 0 | 13（12+1） | 0 | 2 | 15 |
| released | 4 | 3 | 3 | 2 | 12 |
| max_cycles | 0 | 1 | 0 | 0 | 1 |
| 提案拒收（非 QA 返工） | 1（质检 checks） | 1（工程回执） | 2（产品后续事项模式） | 1（质检 checks） | 5 |

部门工具里没有 `ask_expert` / 显式协作工具；13 场也没有发出 `collaboration_request`。产品在首份合同前的工作请求：多数 1 次（直接 `submit_product_spec`），部分 3–4 次（`list_files` / `read_file` 看空工作区后提交）。没有对用户的澄清回合。

## 无效往返标注

计划要求标注三类。本样本的证据如下。

### 产品过度澄清（应直接形成 PRD）

**未观察到。** 13 场协作请求为 0。任务 3（协议要求「提问或自行取舍并写进合同」）两侧都自行取舍、写出单一合同，没有提问：

- 基线 `run_94b65c7bd856494d`：废止「按字母排序」，合同为 CSV 按输入行序透传。
- 候选 `run_2d3ca293affb4f18`：同样排除排序，写成 stdin 原样输出。公开检查按最终合同执行并通过。

A1 32k 的额外产品循环是用户从总览追加输入触发的合同升级，属于 2.1 Web 场景，不是 Prompt 让产品停下来问人。

B4 事项 2/3 多出来的产品激活是 **schema 拒收后当场改正**（rationale / decision_changes），一回合内完成，没有把问题抛回用户。样本只有两次后续事项，不足以改产品默认，也与 A4（A4 未改产品 Prompt）不构成对照。

### 工程不必要的专家请求（应自主完成）

**未观察到。** 协作事件 0。工程工具停留在读写、检查、提交计划和交付。A4 候选任务 2 的膨胀是 **同一 CRLF 夹具缺陷上的返工 + 压缩**，不是专家请求；且发生在候选工程 Prompt 上，A4 已因此不采用。

### 质检模糊返工（应明确验收标准）

**未观察到模糊返工。** 唯一两次 `rework_engineering`（`run_bbacdca62d374995` seq 669、3489）都写了可验证缺陷：夹具换行 CRLF vs LF、字节数 48 vs 45，并区分「脚本行为正确 / 夹具不符合合同」。这是具体缺陷，不是「不够好」。

其余质检一次提交即 `release`，缺陷列表为空，rationale 引用宿主检查回执。三次 `qa_review` 被主机拒收（A4 基线任务 2、A1 32k、以及候选任务 2 的交付回执问题）都是 **检查未 exit 0 / 缺绑定回执**，模型改正后放行，没有变成模糊返工 verdict。

### 其它膨胀（不归入上述三类）

- 候选任务 2：8 循环打满、12 次工程/质检压缩、约 110 万 token。这是 A4 否定候选的主证据，不是改默认的理由。
- `provider_error`（流在终端响应前结束）出现在 `run_99231365e3d3427e`、`run_bbacdca62d374995`、`run_cce0ff393dae4c6b`；内核重试后继续。属网关/流，不属 Prompt。
- 压缩集中在 A4 候选长跑和 A1 32k 小窗，是窗口压力，不是部门间无效往返。

## 20% 往返减少是否可测

**不可测；本样本不能为 Prompt 编辑提供依据。**

1. **快乐路径已贴地板。** 默认 Prompt 且无用户追加的 released run：A4 基线 4/5/4/4，B4 4/5/5，A1 512k 4。中位数 **4**，即最低部门激活数。20% × 4 = 0.8 次激活，在整数循环上无法观测，除非把「往返」改定义为部门内 `work` 请求——那一列方差来自 `provider_usage`、读文件和宿主拒收，不是协作或返工。
2. **要减的那三类事件基数是 0 或 1。** 协作 0；模糊返工 0；产品问人 0。20% of 0 无意义。仅有的 2 次 QA 返工来自 **候选** 的同一夹具错误，改默认工程 Prompt 不能从这里外推。
3. **样本不同质。** 13 run 混了对照实验、项目演进、窗口对照和两次设计内用户改向。不能合成「平均往返」再承诺降 20%。A4 已证明：同一任务上候选更贵（token 157 万 vs 58 万）且任务 2 失败，质量未更好。
4. **成功 run 之间的 4 vs 5 循环** 来自一次产品/质检提案拒收或一次额外工程计划，不是稳定浪费模式。n 太小，改 Prompt 会与 A4「没有改善、不缩小范围再加跑」冲突。

计划 2.5 验收里的「平均往返减少 20%+」在当前证据下 **不应作为 Stage 2 门槛**；应记为不可测量，保持默认。

## 与 A4 的关系

A4 已结论：不把候选写入系统默认，不把工程三段追加提升为以后项目默认。候选项目上的 v1 只是该次比较配置。B4 按该结论使用默认正文。本分析复查 A4 八场，并补上 B4 三场与 A1 两场，**没有发现推翻「保留原版」的新模式**。

因此 2.5.2–2.5.4（改三部门 Prompt）和 2.5.5（新旧对照回归）在本样本上 **没有启动条件**。若以后要动默认，需要新的未见任务、预先登记的往返口径，以及不会把 A4 已否定的工程三段再混进默认。

## 不改什么

- `harness/department_prompts.py` 与 `DEFAULT_PROMPTS`：不改。
- 不把 A4 候选三段、B4 标记、或「补全 rationale / decision_changes」写进默认。
- 不调用模型，不重跑任务，不提交 git。
