# 内核读取运行状态投影的清点（2026-10-24）

清点对象：main `5eae5803` 之后、#557 合并以后的代码。范围是内核清单里的八个裁决模块：`write_path.py`、`adjudication.py`、`validation.py`、`bounds.py`、`contracts.py`、`collaboration.py`、`tools.py`、`path_rules.py`。方法：逐处找出读取 `RunProjection` 字段的位置，说明这一处检查做什么、字段由哪些事件折叠，再分成四类。由架构师会话的子 agent 只读完成，架构师抽查了其中几条关键的说法（`validation.py` 不读提案合同；投影从写文件的工具推出交付失效；`allowed_proposal_kinds` 在裁决中计算调度）。

用途：[骨架与应用设计说明](../design/skeleton-and-application.md)第 5.5 节「裁决的分工」与第 12 节 S1a 至 S1d、S2a 的范围。M0 的 #558 至 #561 会改变 D 类，S1a 放出之前在当时的 main 上重做一遍。

## 1. 四类

| 类 | 含义 | 条数 | 去向（第 5.5 节） |
| --- | --- | --- | --- |
| A | 版本、状态、上限，最小投影接得住 | 25（其中 12 条要补第 4 节列的几样） | 内核，读最小投影 |
| B | 要读成果在当前版本的内容 | 9 | 最小投影记下工件引用；按内容的结构检查归路由的收紧检查 |
| C | 通用的关系规则，可以写成合同 | 11 | 内核，按提案合同里的通用条件核对（S1c） |
| D | 成果驱动特有：询问、分支会话、指导、用户输入的版本、探索轮 | 14 | 路由的收紧检查与路由（S1d、S2a） |

按模块：

| 模块 | A | B | C | D |
| --- | --- | --- | --- | --- |
| `write_path.py` | 1 | – | – | – |
| `bounds.py` | 3 | – | – | – |
| `contracts.py` | 2 | 2 | – | – |
| `adjudication.py` | 4 | – | – | 4 |
| `validation.py` | 8 | 3 | 6 | 4 |
| `collaboration.py` | 7 | 4 | 5 | 6 |

`tools.py` 与 `path_rules.py` 不读投影。导入 `RunProjection` 的是 `adjudication.py`、`bounds.py`、`contracts.py`、`collaboration.py`（从 `models.py`）与 `validation.py`（从 `projection.py`）；`write_path.py` 不导入，经无类型的 `self.projection` 读两个字段。

## 2. 要补进最小投影的几样（A 类里的 12 条）

- **契约**（4 条）：`contract_accepted` 由主机签发，不在原来的六种成果里。工作依据、检查回执的绑定都用它。
- **事项种类**（2 条）：决定部门拿哪一份工具清单、能交哪些种类。
- **项目与事项的编号**（1 条）：写入口给每条 run 事件附上。
- **上限的数值**（2 条）：`max_cycles`、`run_time_limit_sec` 记在事项上，原来的六项只有参数版本。
- **当前交付**（3 条）：它除了被新的接纳事件取代，还会被别的事件清掉，见第 4 节第 1 条。

## 3. C 类：写死在代码里的关系规则

| 规则 | 位置 |
| --- | --- |
| 拒绝与已接纳过的产品决定内容相同的决定（要历史） | `validation.py` `_accept_product_decision` |
| 质检结论依据的交付要基于当前 PRD 与契约 | `validation.py` `_accept_review` |
| 基线核验要有当前 PRD 的结构说明 | `validation.py` `_accept_baseline_review` |
| 列出的检查要有这个部门这一轮的 `run_check` 主机回执 | `validation.py` 四个 `_accept_*` |
| 建档提案的工作区树要等于建档时的快照 | `validation.py` `_unchanged_tree_errors` |
| 放行要求回执用当前的质检测试材料运行 | `validation.py` `_accept_review` |
| 工程有新工作：最新交付依据的 PRD 不是当前 PRD | `collaboration.py` `_latest_engineering_basis` |
| 建档时质检等结构说明对应当前 PRD | `collaboration.py` `_has_new_structure` |
| 最新交付有没有质检结论（要结论的历史） | `collaboration.py` `_has_new_delivery`、`_has_new_defect_record` |
| 基线核验是否覆盖当前 PRD | `collaboration.py` `has_new_baseline_review` |
| 已接纳的交付要基于当前契约才算数 | `collaboration.py` `_current_guidance_result` |

`validation.py` 不读 `proposal_contracts.json`，只有 `context.py` 读它；所有「引用的版本要是当前版本」都写在各个 `_accept_*` 函数里。

## 4. 最难搬出内核的八处

1. **当前交付的失效**（`projection.py` 第 470 行附近、第 817 至 822 行）：非质检部门写文件的工具调用、PRD 与契约的接纳、返工结论都会清掉当前交付。只按接纳事件折叠「每种成果的当前版本」复现不了它。设计的处理：成果失效写成事件（S1b）。
2. **契约**：由 PRD 的内容（`decision_changes` 与有效决定的集合）推出（`contracts.py`、`projection.py` 第 825 至 832 行）；工作依据与每一处回执绑定都用它。
3. **工作依据与提交前的依据核对**（`adjudication.py` 第 203 至 208 行）：它是内核的停止规则，输入却是应用状态（用户输入的版本、指导的版本、任务文本的摘要）。任务文本的摘要与输入版本重复，都在收到用户输入时改变；`started` 参数没有用到。
4. **`allowed_proposal_kinds`**（`collaboration.py` 第 274 至 292 行）：它把关工具错误、工具许可、可用工具与提案校验，同时把成果驱动的调度整个算一遍（会话、询问栈、评审结论、指导与输入版本）。提案的把关和调度缠在一起。
5. **询问分支的工具限制**（`adjudication.py` 第 88 至 132 行、`validation.py` 第 117 行）：按询问栈与会话身份收紧许可，回问深度来自组织定义。设计把询问栈与分支会话归应用。
6. **回执来自这一轮**：规则是通用的，但 `last_activations` 只从主线会话折叠，这是询问分支的规则；最小投影原来只有激活次数，没有这一轮的编号。
7. **质检放行的关卡**（`validation.py` 第 511 至 513、550、558 行）：探索轮的判断读一轮开始时折叠的依据；放行还要求每条指导都有回应、要求当前的质检测试材料，而测试材料不在六种成果里。
8. **指导的「已完成」认领**（`collaboration.py` 第 349 至 542 行）：除了投影，还重新扫原始事件，并重新核对主机工具输出的摘要。整块都是指导特有的。

## 5. 其他事实

- `write_path.py` 不按投影核对运行状态与执行权；执行权的编号在 `event_store.py` 核对（约第 239 行，`StaleExecutionRight`），写入口里没有拒绝结束以后写入的检查。
- 已用时间不在投影里，`bounds.py` 由调用方传入；`RunProjection` 没有模型步数的计数。
- 取代 PRD 以后，`product_spec` 不为空、标为 `superseded`；只有 `contract_payload` 查这个状态，各个 `_accept_*` 只判断是否为空。

清点没有核对这八个文件以外的调用方，只做了检索；混合情形（例如回执来自这一轮、有效决定的保留）的分类是判断。
