# 用户使用记录

本文件记录以用户身份实际使用 Yudao 时遇到的问题。记录先于修复：问题先登记，再由架构师分诊、拆工单。

记录格式：`编号 / 日期 / 场景 / 现象 / 复现步骤 / 初判 / 状态`。

## 2026-10-21 用户使用（真实模型，9router/ds）

环境：main `a49165a4`，从源码运行 `uv run python -m harness api --no-browser`，数据目录 `%LOCALAPPDATA%\Yudao`，真实模型 9router 的 `ds`（deepseek-v4.1-flash，Chat Completions），三部门绑定同一模型。页面版本 0.1.1。

走过的路径：从想法新建项目 → 填长期目标 → 进入项目概览 → 以新事项开始 → 观察三部门循环 → 第二个事项 → 发指导 → 停服务再启动 → 记录原文 → 第三个事项 → 追加需求 → 取消事项 → 资料页、观测页、部门页 → 模型管理页 → 接入已有项目 → 确认初始 PRD。

工单 #629 的走查记录（含各段用时、质检结论与一致性）写在它的评论里。

本次一共跑了四个事项：两个走到质检放行并采纳，一个由用户主动取消，一个是接入已有项目的建档事项（走完 9 轮，等用户确认初始 PRD 后采纳）。

| 编号 | 现象 | 复现步骤 | 初判 | 状态 |
| --- | --- | --- | --- | --- |
| U01 | 概览页「记录原文」与「新的要求」两个输入框共用同一份内容。在「新的要求」里写的文字，同步出现在「记录原文」框里；反过来也一样。 | 项目概览页 → 在「新的要求」输入文字 → 看「记录原文」框；再在「记录原文」输入文字 → 看「新的要求」框 | `client/src/renderer/src/views/project/overview.tsx` 第 187 行与第 201 行都绑定 `recordText`/`setRecordText`，两个输入框共用一份状态。后果：想「先记原文再写要求」做不到；提交「记录原文」会把「新的要求」一起清空（`setRecordText("")`），反之亦然；「记录原文」的按钮也会因为「新的要求」有内容而亮起来 | 工单 [#652](https://github.com/bender2333/yudao/issues/652) |
| U02 | 首页顶部在页面刚打开时显示「连接中断：刚刚断开，正在重新连接」，随后自己变成「已连接」。 | 打开服务地址，等 1 秒 | 顶栏只有「已连接」与「连接中断」两档，没有「连接中」。`client/src/renderer/src/contract/client-app.ts` 第 108 行把初始状态设为 `streamConnected: false`、`disconnectedAt: null`，事件流连上以后才改成 true；`shell/topbar.tsx` 第 77 行按 `disconnectedAt === null` 渲染成「刚刚断开」，于是首次连接的几秒里说的是「中断」而不是「连接中」。措辞与事实不符，用户会以为服务有问题 | 工单 [#653](https://github.com/bender2333/yudao/issues/653) |
| U03 | 资料页的 PRD 各版都标 `active`，同一页的交付却把旧版标成 `superseded`。两版 PRD 都标「有效」，但第 1 版已经被第 2 版取代。 | 项目资料页 → 看 PRD 一节与交付一节 | `harness/app/project_queries.py` 第 1290 行给合同写死了 status `"active"`（交付用的是 `value.status` 的真值）。写死是因为 `harness/models.py` 第 322 行的 `EffectiveContract` 没有 status 字段，而 `DeliverySpec` 有。投影层其实知道：`harness/projection.py` 第 505 至 508 行在接纳新 spec 时把旧的 active 改成 superseded。界面上第 2 版有绿框（`is-current`）能看出先后，但标签说的与事实不符 | 工单 [#654](https://github.com/bender2333/yudao/issues/654) |
| U04 | 部门工作间「动作与回执」表格的「登记名」一列，每一条都是「没有回执」。三十多条动作没有一条有值。 | 工程或质检部门页面 → 动作与回执表格 | 登记机制已按 ADR-0038 删除（#543 删了登记本身，#544 删了设置页的表单），但表格还留着这一列。`client/src/renderer/src/views/project/department.tsx` 第 305 行的表头有「登记名」，第 313 行显示 `receipt.registered_name`；后端 `harness/app/payloads.py` 第 559 行的注释写着这个字段「只在登记命令获准执行时出现」，`harness/app/project_queries.py` 第 951 行的 `ActionReceipt.registered_name` 现在恒为 None。原型待办里已经写了「动作列表中『登记命令』的显示改为命令原文」，这一条没有工单覆盖 | 工单 [#655](https://github.com/bender2333/yudao/issues/655) |
| U05 | 观测页的用量统计只显示 token 总数，输入 token、输出 token、缓存 token 全是「未上报」。事件里其实有这些数。 | 项目观测页 → 用量统计 | `harness/observability.py` 第 159 至 212 行的 `attempt_usage` 合并两个来源：上游原文（`raw_usage_ref`）与规范化摘要（`usage_summary`）。第 187 行的条件是 `raw is None`，**只有原文整个读不到时才用摘要**。这次原文读到了（Chat Completions 协议的 `prompt_tokens`/`completion_tokens`），于是正确的摘要被跳过；第 170 至 180 行只认 Responses 的 `input_tokens`/`output_tokens`，取到 None；`total_tokens` 两个协议同名，所以有值，`source` 判定为 reported（81）。缓存 token 走 `input_tokens_details`，Chat Completions 在 `prompt_tokens_details`，同样取不到 | 工单 [#656](https://github.com/bender2333/yudao/issues/656) |
| U06 | 用户主动取消的事项，在概览页「当前事项」的状态行写着「已停止 · 执行失败」。取消是用户自己的决定，没有失败。 | 概览页 → 顶栏「范围」选「增加 --count-only 选项（已停止）」→ 看「当前事项」的状态行 | 后端把取消的终态记为 `phase=FAILED` + `stop_reason=cancelled`（`harness/projection.py` 第 705 行设 FAILED；`harness/tests/test_projects.py` 第 173 行钉住这个组合）。客户端 `client/src/renderer/src/views/project/overview.tsx` 第 248 行无条件把 phase 翻成阶段名，`labels.ts` 第 45 行把 FAILED 译成「执行失败」。同一套数据在别处已经分开了：部门页 `department.tsx` 第 154 行对 stopped 写「已停止」（工单 #319）；后端 `_room_status`（`harness/app/project_queries.py` 第 741 行）按 `stop_reason=cancelled` 给出房间的 `cancelled`（「已取消」）。只有概览页这一处没按停止原因区分 | 工单 [#657](https://github.com/bender2333/yudao/issues/657) |
| U08 | 浏览器里新开的标签页打开 Yudao，页面外壳出来以后一直停在初始状态：侧栏「项目 0 · 没有符合的项目」、顶栏「连接中断 · 刚刚断开，正在重新连接」、主区「正在读取数据」。同一浏览器里最早打开的那个标签页正常。 | 浏览器新开一个标签页 → 打开 `http://127.0.0.1:8765/` → 观察十几分钟 | 服务端日志里页面发出的查询都到了也都答了 200，数据在服务端是有的；但页面约每 10 秒又发一轮 `capabilities` + 全部视图查询 + `/api/events?after=0&live=1`，这一轮的形状是客户端 `client-app.ts` 第 185 行的 `resync()`（重读能力清单 → `refreshAll()` 重查所有视图 → 重新订阅事件流），而重新订阅的位置又是 0，等于每次重拉两千多条事件（5.2 MB）。事件流本身是好的：同一个 npm `eventsource` 包、同一个 URL，在 Node 里连 20 秒收到 2015 条事件、3 个检查点、641 个片段，`previous` 链没有断点也没有错误。服务端在请求带 `Last-Event-ID` 且值不是非负整数时会立刻回 `resync` 并关闭连接（`harness/api/app.py` 第 202 至 211 行），用 `curl -H 'Last-Event-ID: undefined'` 能稳定复现。页面版本与服务版本都是 0.1.1，不是版本不符重载；日志里也没有重新加载页面时会有的 `GET /` | 工单 [#659](https://github.com/bender2333/yudao/issues/659) |

核对过但不成立（2026-10-21）：曾怀疑首页把同一个项目显示成两种名字。查 `projects.list` 与 `project.overview` 的原始数据，项目名只有「Demo 项目」一处，侧栏、楼层与表格一致，不是问题。

核对过但不成立（2026-10-21）：曾怀疑概览页「已放行（0）」说明事项没有放行。看 `project.overview` 的原始数据，该事项 `stop_reason=released`、`phase=DONE`、`status=adopted`；看板的「已放行」列对应 `released_unsettled`（已放行但未采纳），放行并采纳的事项归到「已采纳」列，`board.ts` 第 21 至 43 行的分列逻辑正确。标签容易误读，但不是错误。

## 走查中确认正常、值得记下的行为

- 三部门循环走完一轮并到达放行：产品 → 工程 → 质检 →（问题反馈 + 返工）→ 产品 → 工程 → 质检 → 放行采纳，共 8 分 25 秒，45 次模型调用全部成功。
- 第二个事项单独走到放行采纳（第 7 轮），交付说明与有效合同一致；同一批流程里质检仍然独立核验，不是照抄工程的自测结果。
- 质检发现了真实缺陷且定位准确：有效合同里的验收条目把 `'  hello\t世界  '` 的字符数写成 14，按合同自己另一条要求应当是 12。质检在自己的独立检查里按 12 验证，拒绝放行并退回产品；产品提交 `ProductSpec r2` 修正这一条，质检复核后放行。缺陷在合同里而不在代码里，工程不需要改代码。
- 指导可以送达正在工作的部门：产品正在工作时发出的指导进入 `department.workspace`，状态 `received`，在下一个安全激活进入模型输入。
- 重启后会话接着工作：工程部门正在工作（第 2 轮）时停掉服务、25 秒后重启，事件流里第 1105 位 `model_request_serialized`（15:09:50）之后是第 1106 位 `run_resumed`（15:10:42），随后重新激活部门并继续请求模型。事项保持 `in_progress`，轮次推进到第 6 轮，没有停在等用户的状态。
- 运行中追加的要求会另起一版输入，不覆盖原来的：第三个事项运行到第 2 轮时追加「另外，--count-only 与 --json 互斥」，`work_item.inputs` 里两条输入按字节区间并存（第 1 版字节 0–97、第 2 版字节 97–200），各自带事件号与 git 版本。页面上「处理进度」写「已接收第 2 版输入，已由有效需求接纳到第 0 版（还有输入没有接纳）」，没接纳是因为随后就取消了事项。
- 取消事项收得干净：点「取消事项」后事项 `status=stopped`、`stop_reason=cancelled`，三次模型调用里第三次记为 `cancelled`，没有留下半截交付或半截合同；页面给出「如需继续，作为新事项重新开始」的提示，追加需求与取消按钮也都不再出现。
- 记录原文能存成项目材料：提交的原文出现在该事项的 `work_item.materials` 里（`material_5b1bae22811243b4`），带记录时间与事件号，可以被后续事项当作依据引用。
- 接入已有项目这条路径走通了：填项目名称、长期目标、源目录名称与源目录路径 → 建档事项跑 9 轮 → 产品读现有代码产出初始 PRD → 决定请求等用户确认 → 用户确认后事项 `status=adopted`、`stop_reason=baseline_verified`，项目建成。
- 产品读现有代码时用的是真读：初始 PRD 里 11 条要求、5 条边界，每一条都能在快照里的 README 与代码上核对到；验收条目还记下了本机 `python3` 是 Windows 应用别名、调用即退出 49，改用 venv 的 python 这种环境事实。
- 初始 PRD 的边界写得很克制：可 import 的稳定接口、测试套件与 CI 都明确写成「设计中，未实施」，README 里的 sample.txt 明确不作为随附素材承诺；需求只描述快照里已经能观察到的行为。
- 源目录不合法时的拒绝理由是准的：第一次接入时源目录指向了 Yudao 自己的工作区（里面有宿主的私有目录 `.checks`），接口回的是 `source_invalid` 与「宿主私有路径不能进入公开快照：.checks」，指明了是哪一条路径、为什么不能进快照，换一个干净的源目录就通过了。

## 过渡期的现象（不另开工单）

产品当时无法当场修订合同。工程部门发现合同自相矛盾后用旧协作请求通道（`request_type: consultation`）问产品，产品两次提交 `product_spec` 与 `product_decision` 都被拒（`product cannot issue product_spec / product_decision in the current work`）。原因：

- `harness/collaboration.py` 第 47 至 48 行：产品能提交 `product_spec`，只在协作请求是 `request_type == "action"` 且 `action == "revise_requirements"` 时；咨询类请求不授予修订合同的权限。
- `harness/validation.py` 第 118 至 124 行：阶段闸门先于上面这条判断。
- 新询问机制没有这个限制：`harness/validation.py` 第 119 至 122 行，`active_ask` 的收件方是 product 时允许提交 `product_spec`；`harness/tests/test_ask_branch.py` 的 `test_ask_answer_with_spec_revision_continuous_work` 覆盖了它。
- 本次运行 `run.asks` 返回 0 条询问：模型在 `ask`（新）与 `submit_request`/`submit_response`（旧）两套通道之间选了旧的那套。

这是 #636（删除协作请求的工具、提案、规则与提交校验）合上以后的过渡状态，模型只剩一条通道时不会选错。新机制本身可用且有测试覆盖。等 #636 至 #639 合并后再走一次，确认产品能在询问回答里当场修订合同。

## 待补充

后续继续使用中遇到的问题按上表格式追加。
