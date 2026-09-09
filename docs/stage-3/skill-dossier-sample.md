# 技能档案样例

日期：2026-09-09  
状态：3.0 准备包，未实施  
上位依据：

- [第三阶段计划](../stage-3-plan.md) 第 3 节技能行、第 5 节 3.0 / 3.5
- [组织与持续运行研究](../research/organization-runtime-evolution.md) 第 4 节（4.1 技能是有证据的工作过程、4.2 技能比较）、第 11 节准备包
- [总体路线图](../program-roadmap.md) 第 4 节技能封装
- [实验协议](../research/experiment-protocol.md) 第 8 节「技能封装」
- [原生项目演化设计](../research/native-project-evolution-design.md) 第 9 节（技能比较可挂在同一 CLI 任务族上）

**这是研发者手写的技能档案。系统自动提炼技能属于第四阶段。** 一次成功的 run 不能把本档案变成默认技能（研究 4.1）。封装后的正常路径与展开路径使用**同一过程版本**；展开是显示并操控这些步骤，不是失败后换成无限自由 Agent。

## 0. 选择哪一项、为什么

候选与取舍：

| 候选 | 现有证据 | 外部副作用 | 结论 |
| --- | --- | --- | --- |
| 工程交付前的主机检查与证据收集 | 交付接纳强制工程回执；脚本与测试多次走过写文件 → `run_check` → `submit_delivery` | 检查在工作区**副本**上执行（`Workspace.check_copy`），不改交付树；无发布 | **采用** |
| 质检独立复核 | `collect_evidence` / `run_check` + `submit_review`；release 绑定质检回执 | 同样无发布；但是独立评价权，过早封装容易把「意见」和「放行」混在技能里 | 本文件不写档案；可作下一份手写档案 |

采用理由：

1. 过程稳定、步骤短、副作用小于发布类技能（研究 4.2：发布技能要另证查询/取消/恢复，不能从本技能类推）。
2. 合同已经硬编码该顺序：`DEFAULT_PROMPTS["engineering"]` 要求实际写文件并用 `run_check`；`validation.py::_accept_delivery` 要求当前 activation / 合同 / 计划 / 快照上的工程回执。
3. 第三阶段计划 3.5：首项选已有稳定证据、副作用少的流程。

名称澄清：建议表述里的 `write → run_check → collect_evidence → 提交 delivery_spec` 与**现状工具权限不一致**。`harness/tools.py::TOOL_DEFS` 中 `collect_evidence` 的部门只有 `quality`；工程交付路径是 `write_file`（及必要时 `delete_file` / `move_file`）→ `run_check` → `submit_delivery`。本档案按现状写。若 3.5 实施时要让工程调用 `collect_evidence`，那是改权限，不属于本样例已有证据。

档案版本：`eng-host-check-before-delivery@0.1`（手写，未注册、未执行）。

## 1. 现状（技能相关，2026-09-09 核对）

| 事实 | 位置 |
| --- | --- |
| 无技能对象、无注册、无适用性判断 | 第三阶段计划第 2 节「没有」表；代码中无 skill 符号（本轮按「当前没有技能」记录） |
| 工程工具 | `tools_for("engineering")`：`read_file`、`list_files`、`write_file`、`delete_file`、`move_file`、`run_check`、`submit_plan`、`submit_delivery`、协作与指导提交 |
| 检查执行 | `ToolRuntime._run_check` → `_execute_check`；`Workspace.bind_check` / `record_check` |
| 交付合同 | `evaluate_proposal` → `_accept_delivery` |
| 工具准入 | `Orchestrator._begin_tool` |
| 用量 | `ObservabilityQuery.model_usage`；记账 `Orchestrator._record_usage`（`TOOL_CALLED` + `name=provider_usage`） |

## 2. 研究 4.1 字段

### 2.1 适用条件

同时成立才允许选用本技能（宿主判断，不由模型自称）：

1. 当前部门是 `engineering`，阶段是 `ENGINEERING` 或 `REWORK_ENGINEERING`。
2. 已有接纳的 `engineering_plan`，且 `plan.effective_contract_hash` 等于当前有效合同（`_accept_delivery` 与 `_begin_tool` 的同一约束）。
3. 计划 `scope` 覆盖本次要写的路径。
4. 要提交的 `delivery_spec.check_names` 非空，且每一项都能映射到一条可在副本上执行的 argv（现有检查是预绑定主机检查，不是任意 shell）。
5. 工作区是本 run 的 `Workspace`，不是未核验的外部目录。
6. 没有未结的、禁止写文件的协作请求（`collaboration.py::tool_error`：仅 `revise_delivery` 动作允许写）。

### 2.2 不适用情况

出现任一条则拒绝本次技能使用，返回原因与可复用材料（研究 4.1 路径「前置条件不成立」）：

1. 部门是产品或质检，或阶段不在工程交付。
2. 没有当前合同绑定的计划；或计划过期。
3. 目标路径超出 `scope`。
4. 需要通用 shell、网络取回、发布、MCP（3.2 之前不存在；存在后若无外部动作契约，仍不适用本技能）。
5. 要「证明」的检查会改被测树且无法隔离：`_execute_check` 若 `tree_changed`，回执写明不能把通过绑到原快照。
6. 技能版本已撤销（见 3.5）；或依赖的检查定义已不在项目设置中。

### 2.3 输入 / 输出

输入：

| 项 | 含义 |
| --- | --- |
| `run_id` / 事项 id | 根任务身份 |
| `effective_contract_hash`、`engineering_plan_hash` | 绑定版本 |
| 拟写入文件列表 | 相对路径 + 内容或补丁意图 |
| `check_names` + 各检查 argv | 与交付单将引用的名字一致 |
| 技能版本 | 必须是 `eng-host-check-before-delivery@0.1` |

输出：

| 项 | 含义 |
| --- | --- |
| 工作区公开树 digest | `Workspace.digest` / 交付 `code_tree_digest` |
| 每项检查的 `CheckReceipt` | `name`、`exit_code`、`snapshot_hash`、`activation_id`、合同/计划哈希、`tree_changed`、`summary` |
| 接纳或拒绝的 `delivery_spec` | 成功时 `DELIVERY_ACCEPTED`；失败时 `PROPOSAL_REJECTED` 字段错误 |
| 技能证据记录 | 见第 4 节；当前不存在，属新增 |

### 2.4 固定过程（步骤表）

版本 `@0.1` 的步骤。正常路径与展开路径都指这一张表。

| 步骤 | 动作 | 执行者 | 必要检查（步骤出口） | 现有记录 | 展开时可否重做 |
| --- | --- | --- | --- | --- | --- |
| S1 | 核对应计划、合同、scope、阶段 | 宿主 | 哈希一致；否则拒绝技能 | 投影字段；无技能事件 | 否（前置） |
| S2 | `write_file` / `delete_file` / `move_file` 落到计划范围 | 工程模型提出，`_begin_tool` 准入，`Workspace` 执行 | 工具 `ok`；路径在 scope | `TOOL_STARTED`、`TOOL_CALLED` | 仅当工作区已变且前序回执失效时重做写入 |
| S3 | 对每个 `check_name` 调用 `run_check` | 同上；`ToolRuntime._execute_check` | 回执存在；`tree_changed` 必须进入已知限制，不能当「静默通过」 | `TOOL_CALLED`（`run_check`）+ `record_check` | 检查失败可从 S3 展开，不重置 S2 中仍有效的文件身份 |
| S4 | `submit_delivery`（`delivery_spec`） | 工程提出，`_accept_delivery` | 文件存在；每项检查有绑定当前 snapshot / 合同 / 计划 / `last_activations["engineering"]` 的工程回执 | `PROPOSAL_SUBMITTED`、`DELIVERY_ACCEPTED` 或 `PROPOSAL_REJECTED` | 拒绝时留在 S4，不把技能标成普遍失败 |

S0（技能外、常先发生）：`submit_plan`。本技能**不包含**改计划；计划调整走现有计划修订，不适用本技能或先退出。

质检的 `collect_evidence` 不是本技能步骤。

### 2.5 必要检查

1. 每条回执 `department=="engineering"`（质检回执不能用来过 S4）。
2. `activation_id` 等于当前工程激活（`_accept_delivery` 读 `projection.last_activations.get("engineering")`）。
3. `effective_contract_hash`、`engineering_plan_hash`、`product_spec_hash` 与投影一致。
4. `snapshot_hash` 与提交时 `WorkspaceSnapshot.digest` 一致（提交前不得再写文件导致回执过期）。
5. `exit_code` 是否必须全 0：由合同与检查名约定。`_accept_delivery` **不**要求 exit 0，只要求回执存在；exit 非 0 仍可提交，由质检判断。本技能的「正常使用」定义为：调用方声明的检查都已执行；「步骤检查失败」定义为：某次 `run_check` 未形成回执，或 `tree_changed` 且技能调用方要求绑定原快照。
6. 检查超时：`_execute_check` 将 `exit_code=124` 并写摘要。这是已完成步骤的回执，不是「外部结果未知」。

### 2.6 所需权限

- 部门：`engineering`。
- 工具：`write_file`、`delete_file`、`move_file`、`run_check`、`submit_delivery`；只读辅助 `read_file`、`list_files`。
- 不准：`collect_evidence`、`submit_review`、任意发布、未授权 shell。
- 计划范围与协作写限制仍由 `_begin_tool` / `tool_error` 收紧，技能不能放宽。

### 2.7 版本

| 字段 | 值 |
| --- | --- |
| id | `eng-host-check-before-delivery` |
| version | `0.1` |
| 过程表 | 本文 2.4 |
| 兼容声明 | 无。改步骤即新版本；旧 run 不热替换（研究 8.3 精神，技能尚未实施） |

### 2.8 来源经历（证据形式，不是一次 run 的推广）

本档案依据的是**可重复的测试与合同形状**，不是 `.yudao/` 里某次真实模型 run（本任务不读那些目录）。

| 经历类型 | 指向 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| 合同测试 | `harness/tests/test_workspace_delivery.py`（如 `test_first_run_archives_and_restores_every_public_byte_from_a_new_data_directory`） | 脚本化路径能走到交付封存；`files` 与公开树规则 | 真实模型会遵守步骤顺序 |
| 交付接纳逻辑 | `harness/validation.py::_accept_delivery` | 无绑定回执不能接纳 | 检查内容对应用户目标为真 |
| 检查实现 | `harness/tools.py::ToolRuntime._execute_check`；`harness/tests/test_tools.py`（待用该文件作回归时引用具体用例名） | 主机执行、超时、树变更标记 | 预绑定检查覆盖所有工程错误 |
| Prompt | `DEFAULT_PROMPTS["engineering"]` | 对模型的公开要求包含写文件与 `run_check` | Prompt 不是安全控制，也不构成技能已执行 |
| Smoke | `harness/smoke.py::HAPPY_TASK` | 任务文本要求工程写文件并让主机跑检查 | 未宣称每次真实 Provider 都成功 |

3.5 封装前还应用 Stage 2 的 2.3 稳定过程证据替换「仅测试形状」。2.3 未完成前，本档案不得注册为可执行技能。

### 2.9 资源边界

| 量纲 | `@0.1` 样例上限 | 现有可观测 |
| --- | --- | --- |
| 本技能内模型步骤 | 计入所在激活的 `model_steps`；耗尽 → `RUN_PAUSED` / `model_steps_exhausted` | 有 |
| 检查次数 | 每个 `check_name` 正常路径 1 次；展开后每名最多再 2 次 | `TOOL_CALLED` 可数 |
| 单次检查墙钟 | `CHECK_TIMEOUT_SEC = 30` | 回执摘要 |
| 检查输出 | `CHECK_OUTPUT_LIMIT = 4000` | 回执 `summary` |
| 技能级预算预留 | 无 | 待 3.4 / 3.5；未单独预留时占用父任务额度，展开不重置父账（研究 OR-04） |

### 2.10 等待与异常出口

| 情况 | 出口 | 禁止 |
| --- | --- | --- |
| S1 失败 | 拒绝技能；返回当前计划/合同哈希与 scope | 不进入写文件 |
| S3 回执形成但 exit ≠ 0 | 视为已完成步骤 + 已知限制；可展开修正写入后重跑该检查 | 不把整个技能当未执行 |
| S3 超时（124） | 同上，有回执 | 不视为未知 |
| 工具已 `TOOL_STARTED` 进程中断 | 转动作核实：查是否有 `TOOL_CALLED` / 回执行；副本内检查默认无外部发布副作用 | 不整段重跑技能（研究 4.1「外部结果未知」） |
| S4 拒绝 | 保留文件与回执；按字段错误补检查或改交付单 | 不改质检材料 |
| 版本撤销 | 停新分派；在途按研究第 8 节分类 | 不把历史 `DELIVERY_ACCEPTED` 改写成未发生 |

## 3. 五条路径的具体例子

场景背景与[组织比较样例](organization-comparison-samples.md)相同：第二次变更，给 echo 增加文件输入。`check_names` = `echo_literal`、`echo_file`、`echo_empty_file`、`echo_missing`。

### 3.1 正常使用

适用条件成立：工程阶段、计划范围 `src/`、无未结只读协作。宿主选中 `@0.1`。S2 写入 `src/echo.py`。S3 四次 `run_check` 均有回执，`tree_changed=false`。S4 接纳。技能证据：选中原因=适用条件清单；版本=`0.1`；已完成 S1–S4；未展开。

### 3.2 前置条件不成立

工程尚未 `submit_plan`，模型直接请求本技能。S1 失败。返回：`engineering_plan` 缺失；可复用材料=当前有效合同哈希与工作区文件列表（`list_files` 结果）。不写文件。对应 `_begin_tool` 在无计划时拒绝写入的同一约束。

### 3.3 步骤检查失败

S3 中 `echo_file` 得到 exit 1，回执完整。展开从 S3 起：显示失败 argv 与 `summary`；执行者改 `src/echo.py`（S2 局部重做）后只重跑 `echo_file` 及因树变化而失效的检查。S1 的计划绑定与未改文件的身份仍有效。预算不因展开清零。

### 3.4 外部结果未知

`run_check` 已 `TOOL_STARTED`，工作进程在 `subprocess.run` 返回前被杀。副本目录可能已跑完或未跑。出口：建立核实项——是否存在对应 `TOOL_CALLED` 与 `receipts.jsonl` 新行。有回执则复用；无回执且无法证明未执行则保持未知，**禁止**再发同一动作直到核实策略允许（检查类无幂等键，重复可能只是再跑副本，但仍须记录为新尝试）。不能从 S1 整段重跑导致重复写入。

### 3.5 依赖或版本被撤销

`@0.1` 被研发者撤销（例如发现某检查 argv 会在副本外写盘）。活跃事项里已选中该版本的技能：停止新分派；S2 未开始的取消；S3 在途按 3.4 核实；已 `DELIVERY_ACCEPTED` 的交付不改写历史，由外层 QA/事项决定是否作废。依赖本技能的经验候选标记待复核。对应研究 4.1 表格「按第 8 节处理在途与接续」。

## 4. 可观察证据清单（4.1）

每条对应现有字段，或写明需新增。实施前新增名称只作文档标识。

| 证据问题 | 现有字段 / 工件 | 需新增 |
| --- | --- | --- |
| 为什么选中 | 无。阶段与计划可从投影读取，但没有「选中技能」记录 | `skill_selected`：技能 id/版本、适用条件逐条引用（合同哈希、阶段、scope） |
| 实际版本 | 无 | 同上，加上执行中的 version；禁止只写名字不写版本 |
| 已完成步骤 | 可间接看 `TOOL_CALLED` 顺序与 `DELIVERY_ACCEPTED` | `skill_step`：S1–S4 状态、对应 `event_id` / 回执 `name` |
| 展开原因 | 无 | `skill_expanded`：失败步骤、回执 `exit_code`/`summary`、是否保留前序 digest |
| 复用哪些前序成果 | 工作区文件与 `snapshot_hash`；计划哈希 | 明确列出复用的 `write_file` event_id 与未重跑的 `check_name` |
| 新增花费 | 展开后新的 `provider_usage`、`TOOL_CALLED`、`model_usage` 差额 | 按技能执行 id 过滤的用量；与父账同一套 reported/unknown 规则 |
| 最终仍有哪些限制 | `delivery_spec.known_risks`；回执 `tree_changed`；QA 缺陷 | 技能结果上的 `remaining_limits`：未跑检查、未知核实、exit ≠ 0 的项 |

技能入口的一次 `DELIVERY_ACCEPTED` 只证明该次执行，不能写入「技能普遍有效」。

## 5. 技能比较方案（研究 4.2）

任务族：贯穿 CLI（echo → 文件输入 → 去重）及同结构的「改一处行为 + 主机检查 + 交付」事项。

比较组：

1. **展开过程**：不调用技能，模型按 Prompt 自行 `write_file` / `run_check` / `submit_delivery`（当前默认）。
2. **封装技能**：宿主适用则走 `@0.1` 固定步骤；失败按第 3 节展开，过程版本仍是 `@0.1`。

固定：同一公开要求、同一检查名、同一工具授权、同一根预算。质量先决：交付合同与外层 QA 不低于事先约定；检查与副作用语义一致（仍是副本内检查，无发布）。

| | 计入收益 | 计入成本 |
| --- | --- | --- |
| 正常路径 | 少重复的「必须 run_check」上下文；少一次模型自行拼交付字段的往返；人工少翻步骤 | 技能选择与证据写入、适用性判断本身的模型/规则开销 |
| 异常路径（必须计入，否则高估收益） | — | 3.2 拒绝后的人工改计划；3.3 展开多出的检查；3.4 核实等待；3.5 撤销与接续；适用性误判（不该用却用 / 该用却拒）；档案维护与回归测试 |

实验协议第 8 节「技能封装」：

- 最小通过：外层合同仍可核验（`_accept_delivery` + QA）；失败可展开到表 2.4；同预算下质量与成本可并排。
- 不足以通过：只是把 Prompt 拼成一段 `SKILL.md` 而无步骤证据。

相关 OR-04：中途失败并展开时，已验证前序可复用，未知副作用先核实，展开不重置预算。

比较执行时机：Stage 2 的 2.3 给出稳定过程证据之后，在 3.5 实施中跑配对样本。2.1 基线提供质量与成本列。本文件不产生「封装更好」的结论。

## 6. 与第四阶段的边界

- 研发者可以增删手写档案、改版本号、决定是否注册。
- 系统可以根据重复失败**提议**「把某过程写成技能」（第四阶段候选），但不能自行采用、不能改本档案的通过标准。
- 一次真实 run 成功 ≠ 登记 `@0.2` 为默认。

## 7. 待决点

1. 3.5 是否保持 `collect_evidence` 仅质检；若放开给工程，本档案步骤与权限表要整版替换，不留兼容。
2. `_accept_delivery` 不强制 exit 0：技能「正常」是「回执齐全」还是「声明的检查全 0」，需在注册前写进合同。
3. 预绑定检查之外的 argv 谁登记：等 3.2 受控 shell 与主机检查扩展点。
4. 技能证据事件的最终名字与是否独立 `EventType`（避免再复用 `TOOL_CALLED`）。
5. 2.3 稳定过程的具体样本列表未定时，来源经历仍停留在测试与代码形状。
6. 检查类超时后重复执行的策略：副本无外部扣费，但仍要防止把「未知」当「未执行」。
