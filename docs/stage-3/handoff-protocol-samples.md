# 交接协议样例

日期：2026-09-09。状态：3.0 准备包，未实施。

上位依据：

- [组织与持续运行研究](../research/organization-runtime-evolution.md) 第 5 节（交接以接收为准；重复/乱序/迟到）、第 11 节（交接协议样例）
- [第三阶段计划](../stage-3-plan.md) 第 5 节 3.0 / 3.6
- [总体路线图](../program-roadmap.md) 第 4 节（部门间协议：交接承诺、澄清、变更影响、责任转移、等待、失败和取消）
- [项目工作台合同](../archive/project-workbench-contract.md)（B0：事项创建与采纳结算的事件顺序与幂等）

研究 §5.1：交接至少有提出和接收两段；**只有接收决定生效后才改变责任归属**。本文用当前事件核对哪些交接其实是「提出即生效」（宿主接纳发送方提案后立刻改 `phase` / `active_department`），标为 3.6 要改的点。

贯穿任务（固定领域，各节复用）：实现本地 Python CLI，路径 `src/lines.py`（早期事项可用 `src/echo.py`，与 `harness/smoke.py::HAPPY_TASK` 同族）。三轮事项：

1. echo：打印第一个参数，退出 0。
2. 文件输入：`python src/lines.py --file PATH` 按行打印文件内容。
3. 去重：只保留首次出现的行，其后重复行丢弃。

样例用表格与编号步骤。不写实现代码，不设计 DSL。

---

## 1. 现有交接在事件里的样子

责任转移以投影为准：`harness/projection.py::apply_event`。提交入口：`Orchestrator._apply_proposal` → `evaluate_proposal`（`harness/validation.py`）→ `SubmissionWriter.commit`（`harness/submissions.py`）→ 可能再 `append` `transition`（`Orchestrator._commit_accepted`）。

### 1.1 产品 → 工程（`spec_accepted` / `contract_accepted` → `transition`）

| 段 | 事件 | 谁写 | 投影效果 |
| --- | --- | --- | --- |
| 提出 | 产品激活中 `submit_product_spec` → `tool_called`；随后 `proposal_submitted` | 产品模型 + `_apply_proposal` | 尚不改 phase |
| 宿主接纳 | `spec_accepted`（可先有 `spec_superseded`）；若合同变化则同批 `contract_accepted` | `SubmissionWriter.commit` 经 `append_batch` | 有效要求变为新产品规格与合同 |
| 责任转移 | `transition` `PRODUCT_SPEC→ENGINEERING` 或 `REWORK_PRODUCT` 路径上的同类路由 | `_commit_accepted` **另一次** `store.append` | `phase=ENGINEERING`，`active_department=engineering` |

`_accept_product_spec`（`validation.py`）：非协作、非产品指导时，`transitions = [(phase, "ENGINEERING")]`。工程部门没有「接收规格」提案。

**3.6 标记：提出即生效。** 宿主接纳发送方提案的同时把责任切到工程；没有接收方事件。

`product_decision_accepted` 同类：无 pending request 时直接 `transition` 到 ENGINEERING。

### 1.2 工程 → 质检（`plan_accepted` / `delivery_accepted` → `transition`）

| 段 | 事件 | 说明 |
| --- | --- | --- |
| 计划提出与接纳 | `plan_accepted` | `_accept_plan` **不带** `transitions`。责任仍在工程。计划不是对 QA 的交接。 |
| 交付提出 | `submit_delivery` → `proposal_submitted` | |
| 宿主接纳 | `delivery_accepted`（`store_tree` + 工作区核对） | |
| 责任转移 | `ENGINEERING→DELIVERY` 再 `DELIVERY→QUALITY` 两条 `transition` | `_accept_delivery`：无 pending request 时 `[(from_phase, "DELIVERY"), ("DELIVERY", "QUALITY")]` |

质检没有「接收交付」提案；`qa_review` 假定已有 `delivery_spec`。

**3.6 标记：交付交接提出即生效。** 计划接纳不是跨部门交接。

### 1.3 质检返工（`qa_submitted` verdict `rework_*` → `transition`）

| 段 | 事件 | 投影 |
| --- | --- | --- |
| 提出 | `submit_review` | |
| 接纳 | `qa_submitted` | `rework_count+1`，交付 `invalidation_reason` 为 `qa_rework_*`（`_supersede_active_deliveries`） |
| 转移 | `rework_product`：`QUALITY→REWORK_PRODUCT` 再 `REWORK_PRODUCT→PRODUCT_SPEC`；`rework_engineering`：`QUALITY→REWORK_ENGINEERING` 再 `REWORK_ENGINEERING→ENGINEERING` | `_accept_review` |
| 放行 | `qa_submitted` verdict `release` → `QUALITY→DONE` → `run_done` | 事项结束；项目 `settle` 尚未实现 |

被返工方没有「接收返工单」事件。

**3.6 标记：提出即生效。**

### 1.4 专家协作（`collaboration_requested` / `responded` / `closed`）

| 段 | 事件 | 责任 |
| --- | --- | --- |
| 提出 | `collaboration_requested`（`id` 在 commit 时 `new_id("request")`） | `pending_request` 打开；`active_department` **立刻** 设为 `recipient`（`apply_event`）。phase **不变**。 |
| 接收/回答 | `collaboration_responded`（`submit_response`） | `pending_request=None`；`phase=return_phase`；`active_department=department_for_phase(phase)` |
| 非自愿关闭 | `collaboration_closed` | `_close_request`：新用户输入、请求过期、取消/暂停/失败。`return_work_valid` 常为 false |

接收方可以 `declined` / `needs_work` / `answered` 或 `completed`（`collaboration.py` 按 `consultation` vs `action` 分允许 status）。**没有**单独的「我接受处理该请求」事件：被指定为 recipient 的瞬间就已经是 `active_department`。

**3.6 标记：路由提出即生效；内容等待 `responded`。** 比规格/交付更接近研究 5.1，但仍缺「接收方承认承担」与「拒绝承担且责任留在发送方」的拆分——`declined` 会关请求并按 `resume_phase` 回去，不是「从未离开发送方」。

### 1.5 部门指导（`department_guidance_received` / `applied` / `responded`）

| 段 | 事件 | 谁 | 责任 |
| --- | --- | --- | --- |
| 提出 | `department_guidance_received`（`id=new_id("guidance")`，`status=received`） | 用户 `Orchestrator.add_guidance` → `InteractionWriter.receive_guidance` | 不改 phase |
| 采用进上下文 | `department_guidance_applied` | `_begin_request` 在 step 首次请求前，若 manifest 含 `guidance_ids` | `status=in_input`；可能 `guidance_only` 激活非当前 phase 部门（`_prepare_activation`） |
| 回答 | `department_guidance_responded` | 该部门 `submit_guidance_response` | 指导关闭；可能 `_resume_yielded_work` 再写 `transition` 回到让出的工作 |

用户提出指导即进入列表；部门不能拒绝「接收这条指导」，只能后来 `declined`。

**3.6 标记：入队提出即生效；让出主线工作是宿主调度，不是接收协议。**

### 1.6 连续输入（`user_input_received` / `product_input_assigned`）

| 段 | 事件 | 责任 |
| --- | --- | --- |
| 提出 | `user_input_received` | `input_version+1`，`task` 拼接文本；**phase 不变** |
| 分配给产品 | `product_input_assigned`（`through_version`） | `_assign_new_inputs`：关掉过时协作，`phase=PRODUCT_SPEC`，`product_work_input_version` 追上 |

分配发生在下次 `_prepare_activation` 或 `_activation_stopped` 路径上的 `_close_obsolete_request` → `_assign_new_inputs`，不是用户 POST 的同一把锁里（`add_input` 只 `receive`）。因此存在「输入已入账、产品尚未被指定处理新版本」的窗口（恢复文档 I16）。

**相对接近研究 5.1**：提出与「产品必须处理该版本」分开。仍不是产品部门的接收决定，而是宿主指定。

### 1.7 一览：哪些是 3.6 要改的「提出即生效」

| 交接 | 提出事件 | 本应有的接收 | 今天何时改责任 | 3.6 |
| --- | --- | --- | --- | --- |
| 产品规格 → 工程 | `proposal_submitted` / `spec_accepted` | 工程接收或拒绝规格 | `transition` 紧接宿主接纳 | 要改 |
| 产品决定 → 工程 | `product_decision_accepted` | 同上 | 同上 | 要改 |
| 工程计划 | `plan_accepted` | 无跨部门 | 不改部门 | 不是跨部门交接 |
| 交付 → 质检 | `delivery_accepted` | 质检接收交付包 | 双 `transition` 紧接接纳 | 要改 |
| QA 返工 | `qa_submitted` | 产品/工程接收返工范围 | 双 `transition` | 要改 |
| QA 放行 | `qa_submitted` release | 根任务/项目接收运行责任 | `run_done`；项目 settle 未实现 | 放行即结束 run；项目层接收见 B0 |
| 协作请求 | `collaboration_requested` | 接收方承认/拒绝承担 | 立刻改 `active_department` | 要改路由；保留 responded |
| 指导 | `department_guidance_received` | 部门承认处理 | 入队即存在；调度可打断主线 | 入队策略待决 |
| 用户输入 | `user_input_received` | 产品开始处理该版本 | `product_input_assigned` | 可保留两段，把 assigned 当成宿主接收代理 |

---

## 2. 研究 5.1 六种协作动作：完整故事

共同初始：项目已有（或将有）贯穿 CLI。输入版本从 1 起。允许动作以 `allowed_proposal_kinds`（`collaboration.py`）为准。

异常列固定五类：超时、拒绝、重复投递、乱序、迟到。今天没有交接超时事件；超时行写 3.6 预期，并注明现状。

### 2.1 提交交付（工程 → 质检）

事项 2 结束：`src/lines.py` 已支持 `--file`，工程要提交给质检。

**主路径**

| 步 | 责任人 | 输入版本 | 允许动作 | 写入事件 |
| --- | --- | --- | --- | --- |
| 0 | 工程 | 1 | `engineering_plan`、`delivery_spec`、`collaboration_request` | 已有 `plan_accepted`（当次合同） |
| 1 | 工程 | 1 | 写文件、`run_check` | `tool_started` / `tool_called`（write、check） |
| 2 | 工程 | 1 | `submit_delivery` | `tool_called` submit；`proposal_submitted` |
| 3 | 宿主 | 1 | 校验树与检查收据 | `delivery_accepted` |
| 4 | 宿主 | 1 | 改 phase | `transition` ENGINEERING→DELIVERY；DELIVERY→QUALITY |
| 5 | 质检 | 1 | `qa_review`、`collect_evidence`、`collaboration_request` | （3.6 前已是责任人） |

3.6 目标插在步 3 与步 4 之间：质检写接收（范围：这些文件、该 `code_tree_digest`、该合同哈希）或拒绝（缺检查、树对不上）。只有接收事件提交后才出现步 4。

**异常**

| 类 | 故事 | 预期 |
| --- | --- | --- |
| 超时 | `delivery_accepted` 后质检未激活（I13） | 现状：责任已在质检，发送方工程不再是 `active_department`。3.6：超时未接收则工程仍负责跟进，可查询同次交接（研究 5.1 表） |
| 拒绝 | 质检拒绝：缺去重验收的检查名 | 现状：不能拒接收，只能后面 `rework_engineering`。3.6：拒绝事件，责任留工程，交付不进入 QUALITY |
| 重复投递 | 同一激活工具列表里两次 `submit_delivery` | 现状：第一次 submit 后 `_skip_calls` 其余工具（`engine.py`） |
| 乱序 | 先到 `qa_submitted` 再补 `delivery_accepted` | 现状：无交付则 `_accept_review` 失败。按 seq 投影，不会用后来的交付解释先前的 QA |
| 迟到 | 工程旧 Worker 在 QUALITY 阶段交上一个旧 digest 的交付 | `_apply_proposal` 核 `request_basis` / 合同 / 计划；工作区已变则校验失败。3.1 再加 generation |

### 2.2 请求澄清（工程 → 产品）

事项 3：去重「首次出现」是按整行还是按 strip 后的行？工程在 ENGINEERING 发咨询。

**主路径**

| 步 | 责任人 | 输入版本 | 允许动作 | 写入事件 |
| --- | --- | --- | --- | --- |
| 0 | 工程 | 1 | 计划、交付、协作 | phase=ENGINEERING |
| 1 | 工程 | 1 | `submit_request` `request_type=consultation`，recipient=product | `collaboration_requested`（`id=request_…`） |
| 2 | 产品（调度） | 1 | 仅 `collaboration_response`（及指导响应） | `active_department=product`，phase 仍为 ENGINEERING |
| 3 | 产品 | 1 | `submit_response` status=`answered` | `collaboration_responded` |
| 4 | 工程 | 1 | 恢复工程允许集 | `return_phase` 多为 ENGINEERING；`return_work_valid` 依 `resume_phase` |

未回答前工程不得交付（不是当前 `active_department`）。研究：未解决前只做不依赖该答案的工作——现状更硬：发送方完全让出激活。

**异常**

| 类 | 故事 | 预期 |
| --- | --- | --- |
| 超时 | 产品不响应，撞 `max_cycles` | 现状：`_pause(max_cycles)`，`collaboration_closed` status=`stopped`。3.6：超时发送方仍「负责跟进」，可查同一 `request_id` |
| 拒绝 | 产品 `declined`：去重定义已在验收条款 | 请求关闭，工程拿 `text` 继续；责任回 `return_phase` |
| 重复投递 | 工程再 `submit_request` 而前一条仍 open | `request_errors`：`finish the pending request before starting another request` → `proposal_rejected` |
| 乱序 | `responded` 先于 `requested` | 投影只按 seq；孤立 responded 对不上 `pending_request`（`apply_event` 按 `request_id` 清 pending）。写入路径上 responded 必须针对当前 pending，否则校验失败 |
| 迟到 | 产品回答时用户已 `user_input_received` 新版本 | `_assign_new_inputs` 可 `collaboration_closed` superseded；迟到 `responded` 因 `request_id` 不匹配或 basis 变而拒绝 |

### 2.3 要求返工（质检 → 工程）

事项 3 交付后：质检发现重复行仍输出。

**主路径**

| 步 | 责任人 | 输入版本 | 允许动作 | 写入事件 |
| --- | --- | --- | --- | --- |
| 0 | 质检 | 1 | `qa_review`、`collect_evidence` | 已有 `delivery_accepted` |
| 1 | 质检 | 1 | 当次激活跑检查 | `tool_called` collect_evidence |
| 2 | 质检 | 1 | `submit_review` verdict=`rework_engineering`，defects 定位「第二次 `a\\n` 仍打印」 | `qa_submitted` |
| 3 | 宿主 | 1 | 作废交付、改 phase | 两条 `transition`；可能 `lesson_candidate_recorded` |
| 4 | 工程 | 1 | 计划（须 `reason`）、再交付 | 不得沿用已 superseded 的交付 |

3.6：步 2 与步 3 之间工程接收「可核验变化」或拒绝（口径变成新要求）。口径变化应单独标记，不把新要求记成原工程错误（研究 5.1）。

**异常**

| 类 | 故事 | 预期 |
| --- | --- | --- |
| 超时 | 返工 transition 后工程不激活 | 同 2.1 超时；现状责任已在工程 |
| 拒绝 | 工程认为是需求变更（应 strip） | 现状：工程只能 `collaboration_request` `revise_requirements`，不能拒收 QA 单。3.6：拒收返工 vs 转范围变更要分开 |
| 重复投递 | 两次 `submit_review` | 第一次提交后跳过后续工具；第二次激活若交付已作废，release/rework 校验会变 |
| 乱序 | 返工事件早于 `delivery_accepted` | 接纳失败，phase 仍 QUALITY 或更早 |
| 迟到 | QA 在工程已根据新用户输入改规格后，对旧 `delivery_spec_hash` 提交 rework | 审查绑定当前 delivery / 合同；旧哈希失败。旧 Worker 还要过 `_apply_proposal` 版本核 |

### 2.4 提出范围变更（用户 / 产品）

事项 1 已采纳 echo。事项 2 用户要求文件输入；事项进行中用户又追加「同时支持 stdin」。

**主路径（run 内追加）**

| 步 | 责任人 | 输入版本 | 允许动作 | 写入事件 |
| --- | --- | --- | --- | --- |
| 0 | 工程 | 1 | 实现 `--file` | phase=ENGINEERING |
| 1 | 用户 | 1→2 | POST inputs | `user_input_received`（phase 仍 ENGINEERING） |
| 2 | 宿主 | 2 | 下次准备激活 | 可能 `collaboration_closed`；`product_input_assigned` `through_version=2`；phase=PRODUCT_SPEC |
| 3 | 产品 | 2 | 必须先纳入新输入才能 `product_spec`（`input_version == product_work_input_version`） | 修订规格须 `change_record` 与完整 `decision_changes` |
| 4 | 宿主 | 2 | 新合同 | `spec_accepted`、`contract_accepted`、`transition`→ENGINEERING |
| 5 | 工程 | 2 | 新计划 `reason`、新交付 | 旧交付因 `product_spec_changed` / `effective_contract_changed` 作废 |

项目层另一条路径（B0，未实现）：用户开**新事项**而不是 run 内输入；基线为当前 `deliverable_adopted`。

**异常**

| 类 | 故事 | 预期 |
| --- | --- | --- |
| 超时 | assigned 后产品不改规格 | `max_cycles` 暂停；新输入已在 intend 工件 |
| 拒绝 | 产品想忽略 stdin 要求 | 现状：不能「拒收用户输入」；只能把范围写进 `non_goals` 并在规格中说明。3.6：是否允许产品拒绝未授权变更，待决 |
| 重复投递 | 同一正文 POST 两次 | 两次 `user_input_received`，version 3 与 4；无按内容去重 |
| 乱序 | `product_input_assigned` 的 `through_version` 小于最新 `input_version` | `_assign_new_inputs` 一次追上 `projection.input_version`；按 seq 重放仍单调 |
| 迟到 | 工程在 assigned 之后仍提交旧合同上的交付 | `_begin_tool` / `_apply_proposal` 因合同哈希或 `input_version` 变化停止或拒绝 |

### 2.5 等待外部条件

今天没有 `wait_opened` 一类事实。最接近：协作 pending、SSE 断开、Provider 超时、`max_cycles` 暂停。

**主路径（3.1/3.6 要用事件表达的故事）**

场景：事项 3 的去重金样例文件尚未放到工作区，产品声明等待用户提供 `fixtures/dup.txt`。

| 步 | 责任人 | 输入版本 | 允许动作 | 写入事件（草案） |
| --- | --- | --- | --- | --- |
| 0 | 产品 | 1 | 规格未完成 | phase=PRODUCT_SPEC |
| 1 | 产品 | 1 | 提出等待 | `wait_opened`：`wait_id`、对象=用户文件、继续条件=路径存在且 hash、期限、责任人=产品 |
| 2 | （无线程） | 1 | 禁止假装文件已到 | 释放执行槽（3.4）；lease `may_dispatch=false` 或仅允许唤醒检查 |
| 3 | 用户 | 1 | 提供文件或输入 | `wait_satisfied` 或 `user_input_received` |
| 4 | 产品 | 1 | 条件成立才继续规格 | 重复唤醒只推进一次（研究 5.1） |

**异常**

| 类 | 故事 | 预期 |
| --- | --- | --- |
| 超时 | 期限过 | `wait_expired`；产品仍负责跟进，不得把等待当成功 |
| 拒绝 | 用户不提供夹具 | 产品缩小验收或停止；写明未纳入范围 |
| 重复投递 | 两次「文件已到」唤醒 | 同一 `wait_id` 只 `satisfied` 一次 |
| 乱序 | `satisfied` 早于 `opened` | 拒绝写入或仅作历史 |
| 迟到 | 旧版本等待的唤醒在规格已修订后到达 | 唤醒带着 `wait_id`+要求哈希；不匹配则不推进（OR-06） |

现状对照：把「等用户」做成不暂停的循环会烧 `max_cycles`。不要用 `collaboration_request` 假装外部等待——协作的对方是部门，不是用户文件。

### 2.6 取消或停止使用

场景：事项 2 进行中，用户取消。

**主路径**

| 步 | 责任人 | 输入版本 | 允许动作 | 写入事件 |
| --- | --- | --- | --- | --- |
| 0 | 工程 | 1 | 写文件中 | `_active` 有激活 |
| 1 | 用户 | 1 | `POST cancel` 或输入 `/stop` `/cancel` | `cancel`：`_abort.set`、`adapter.abort`、可能 `collaboration_closed`、`run_failed` `stop_reason=cancelled` |
| 2 | 宿主 | 1 | 终态 | `sessions.close_run`；Web Worker 随后退出 |
| 3 | 项目层（B0） | — | 不结算 | 取消的 run 不 `deliverable_adopted` |

研究要求回执区分：已停止分派、仍在运行、外部未知。现状把这些压成一条 `run_failed`。

**异常**

| 类 | 故事 | 预期 |
| --- | --- | --- |
| 超时 | abort 后 `run_check` 子进程仍在 | 恢复文档 I17 / 矩阵第 12 项；未知检查要核实 |
| 拒绝 | 模型还想 `submit_delivery` | `_apply_proposal` 见终态直接 return；或 `execution_basis` 拒绝 |
| 重复投递 | 两次 cancel | 第二次：已是 `TERMINAL_PHASES`，`cancel` 原样返回投影，不再写事件 |
| 乱序 | `run_failed cancelled` 与迟到 `delivery_accepted` | 接纳路径先看终态；`append` 仍可能发生若旧进程绕过检查——3.1 generation 要挡 |
| 迟到 | 取消后旧 Worker `tool_called` 写成功 | 用量/工具事件是否入账见恢复文档待决；不得 `transition` 到 QUALITY |

---

## 3. 重复、乱序、迟到（研究 5.2）

### 3.1 稳定身份从哪来

| 身份 | 生成 | 用途 | 跨投递稳定？ |
| --- | --- | --- | --- |
| `event_id` | `new_id("evt")` 在 `append_batch` | 事件主键 | 每次写入新值 |
| `run_id` | `new_id("run")` 或项目预生成 | 事件流 | 是 |
| 规格/计划/交付/QA/决定 `payload.id` | commit 时 `new_id("spec"|"plan"|"del"|"qa"|"decision")` | 领域对象 | 内容哈希另有 `content_hash`；id 每次接纳新建 |
| `content_hash` | 规范哈希 | 内容身份 | 同内容应相同；产品决定重复内容会被拒 |
| `request_id`（协作） | `new_id("request")` | `pending_request.id`；工具 payload 也带激活时的 `request_id` | 一次协作稳定；客户端不能指定 |
| `guidance_id` | `new_id("guidance")` | 指导全生命周期 | 是（单条指导） |
| `activation_id` | `DepartmentSession.activate` → `new_id("act")` | 一次部门激活 | 进程内稳定；重启后新激活新 id |
| `step_id` | `run_department` 循环 1..32 | 激活内模型步 | 仅该激活 |
| `logical_call_id` | `{activation_id}:root-{root_step_id}:{purpose}` | D17 重试共用 | 是（相对该激活） |
| `attempt_id` | `{logical_call_id}:attempt-{n}` | 单次模型尝试 | 是 |
| `call_id` / 工具 `id` | 模型输出 | `tool_started` / `tool_called` | 提供方给的；未当业务幂等键 |
| `seq` | 每 run 单调 | SSE `Last-Event-ID`、因果顺序 | 是；研究要求用有效事实顺序而非本机时钟 |

没有：交接业务 id（「这一次产品→工程的规格交接」）、执行 `generation`、外部动作 `action_id`。

### 3.2 哪些动作已有幂等性

| 动作 | 有？ | 机制 |
| --- | --- | --- |
| `EventStore.append_batch` | 整批原子 | 同一连接事务；失败不消耗 seq（`test_event_store_batch.py`） |
| 产品决定同 `content_hash` | 拒绝第二次 | `_accept_product_decision` |
| 第二条协作在 pending 未关时 | 拒绝 | `request_errors` |
| 指导已 responded 再答 | 拒绝 | `_accept_guidance_response` |
| 同激活内第二份 submit 工具 | 不执行 | `_skip_calls` |
| 工具观察重复 `step_id:call_id` | 忽略 | `_record_observation` 的 `activation.tool_ids`（**内存**，重启无效） |
| Web 二次 cancel | 无新事件 | 终态短路 |
| B0 `settle` | 合同规定幂等 | **代码未落地**；按 `run_id` 已有 adopted/held 则不再写 |
| B0 Prompt 同文本保存 | 不写事件 | 合同 §9 |
| `spec_accepted` / `delivery_accepted` 重复提交同内容 | **否** | 新 `id`、新 revision |
| SSE 重连 | 只读去重靠客户端持有 last seq | 不重发执行 |
| `run_check` | 否 | 每次新进程 |

研究：重复投递返回该次已有结果；内容不一致应报冲突而不是覆盖。协作 `request_id` 无法由发送方重放「同一 id」。3.6 交接应允许客户端（或宿主）指定 `handoff_id`，重复提出返回已有接收状态。

### 3.3 「接纳决定与新增待交付责任不能只写一半」

研究 5.2：本地持久层应保证这两件事不出现只写一半。

当前拆分：

| 一起提交的（`append_batch`） | 随后单独 `append` 的 |
| --- | --- |
| `spec_superseded`? + `spec_accepted` + `contract_accepted` | `transition` → 工程 |
| `plan_accepted` | （无部门转移） |
| `delivery_accepted` | `transition` → DELIVERY → QUALITY（两条） |
| `qa_submitted` | `transition` 两条或 `transition`+`run_done`；另可能 `lesson_candidate_recorded` |
| `collaboration_requested` 单条 | 无 transition；责任已在该事件的 `apply_event` 里切走 |
| `run_created` | 紧接着 `transition` CREATED→PRODUCT_SPEC（phase 在 created 上已是 PRODUCT_SPEC） |

因此：**规格/交付/QA 的「接纳」与「对方开始待交付」今天可以只完成前半。** 这是 3.6（及恢复 I11）的核心缺口。

3.6 方向（仍不写代码）：要么把 `handoff_offered` 与 `handoff_accepted` 放进**一次** `append_batch`，要么在只有 offered 时投影不得把 `active_department` 换成接收方。不要靠「崩溃很少」假设。

跨进程投递（研究后半句）：当前三部门同进程同库，用同事务即可，不必上分布式事务。Web SSE 不是交接通道。

乱序：只按 `seq` 应用 `apply_event`，不用 `created_at` 排序。迟到旧要求：例如已 `product_input_assigned` 到 v2 后到达的 v1 交付，应只留历史、不覆盖 v2 成果——今天靠合同哈希与 `processed_input_version`，没有「旧交接 id 显式作废」事件。

---

## 4. 待决点

1. **3.6 是否对规格、交付、QA 返工都强制接收事件**，还是先做交付与返工、规格仍宿主直切（规格几乎总是「工程必须接着干」）？
2. **协作 `declined` 是否改为「从未转移 active_department」**，还是保持「已转移、回答后再回来」？
3. **交接超时**：用 `max_cycles`、墙钟、还是显式 `wait_opened`？谁在超时后仍是跟进责任人？
4. **`handoff_id` 由谁分配**：发送方工具参数，还是宿主在 `proposal_submitted` 时分配并回给模型？
5. **用户输入能否被产品拒绝**（未授权范围变更），还是只能写进规格边界？
6. **`append_batch` 扩大到包含 transition** 是否算 3.1（恢复原子性）还是 3.6（协议语义）？两者都依赖它。
7. **项目 `settle` 与 QA `release`**：run `DONE` 是否仍不算「项目接收成果」，必须 `deliverable_adopted`？B0 已如此写；3.6 是否把项目结算当成第七种接收？
8. **指导打断主线**（`guidance_only`）算不算一次交接？若算，让出/收回是否也要接收语义？
