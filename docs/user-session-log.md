# 用户使用记录

本文件记录以用户身份实际使用 Yudao 时遇到的问题。记录先于修复：问题先登记，再由架构师分诊、拆工单。

记录格式：`编号 / 日期 / 场景 / 现象 / 复现步骤 / 初判 / 状态`。

## 2026-10-21 用户使用（真实模型，9router/ds）

环境：main `a49165a4`，从源码运行 `uv run python -m harness api --no-browser`，数据目录 `%LOCALAPPDATA%\Yudao`，真实模型 9router 的 `ds`（deepseek-v4.1-flash，Chat Completions），三部门绑定同一模型。页面版本 0.1.1。

走过的路径：从想法新建项目 → 填长期目标 → 进入项目概览 → 以新事项开始 → 观察三部门循环 → 第二个事项 → 发指导 → 停服务再启动。

工单 #629 的走查记录（含各段用时、质检结论与一致性）写在它的评论里。

| 编号 | 现象 | 复现步骤 | 初判 | 状态 |
| --- | --- | --- | --- | --- |
| U01 | 概览页「记录原文」与「新的要求」两个输入框共用同一份内容。在「新的要求」里写的文字，同步出现在「记录原文」框里；反过来也一样。 | 项目概览页 → 在「新的要求」输入文字 → 看「记录原文」框；再在「记录原文」输入文字 → 看「新的要求」框 | `client/src/renderer/src/views/project/overview.tsx` 第 187 行与第 201 行都绑定 `recordText`/`setRecordText`，两个输入框共用一份状态。后果：想「先记原文再写要求」做不到；提交「记录原文」会把「新的要求」一起清空（`setRecordText("")`），反之亦然；「记录原文」的按钮也会因为「新的要求」有内容而亮起来 | 工单 [#652](https://github.com/bender2333/yudao/issues/652) |
| U02 | 首页顶部在页面刚打开时显示「连接中断：刚刚断开，正在重新连接」，随后自己变成「已连接」。 | 打开服务地址，等 1 秒 | 顶栏只有「已连接」与「连接中断」两档，没有「连接中」。`client/src/renderer/src/contract/client-app.ts` 第 108 行把初始状态设为 `streamConnected: false`、`disconnectedAt: null`，事件流连上以后才改成 true；`shell/topbar.tsx` 第 77 行按 `disconnectedAt === null` 渲染成「刚刚断开」，于是首次连接的几秒里说的是「中断」而不是「连接中」。措辞与事实不符，用户会以为服务有问题 | 工单 [#653](https://github.com/bender2333/yudao/issues/653) |

核对过但不成立（2026-10-21）：曾怀疑首页把同一个项目显示成两种名字。查 `projects.list` 与 `project.overview` 的原始数据，项目名只有「Demo 项目」一处，侧栏、楼层与表格一致，不是问题。

核对过但不成立（2026-10-21）：曾怀疑概览页「已放行（0）」说明事项没有放行。看 `project.overview` 的原始数据，该事项 `stop_reason=released`、`phase=DONE`、`status=adopted`；看板的「已放行」列对应 `released_unsettled`（已放行但未采纳），放行并采纳的事项归到「已采纳」列，`board.ts` 第 21 至 43 行的分列逻辑正确。标签容易误读，但不是错误。

## 走查中确认正常、值得记下的行为

- 三部门循环走完一轮并到达放行：产品 → 工程 → 质检 →（问题反馈 + 返工）→ 产品 → 工程 → 质检 → 放行采纳，共 8 分 25 秒，45 次模型调用全部成功。
- 质检发现了真实缺陷且定位准确：有效合同里的验收条目把 `'  hello\t世界  '` 的字符数写成 14，按合同自己另一条要求应当是 12。质检在自己的独立检查里按 12 验证，拒绝放行并退回产品；产品提交 `ProductSpec r2` 修正这一条，质检复核后放行。缺陷在合同里而不在代码里，工程不需要改代码。
- 指导可以送达正在工作的部门：产品正在工作时发出的指导进入 `department.workspace`，状态 `received`，在下一个安全激活进入模型输入。
- 重启后会话接着工作：工程部门正在工作（第 2 轮）时停掉服务、25 秒后重启，事件流里第 1105 位 `model_request_serialized`（15:09:50）之后是第 1106 位 `run_resumed`（15:10:42），随后重新激活部门并继续请求模型。事项保持 `in_progress`，轮次推进到第 6 轮，没有停在等用户的状态。

## 过渡期的现象（不另开工单）

产品当时无法当场修订合同。工程部门发现合同自相矛盾后用旧协作请求通道（`request_type: consultation`）问产品，产品两次提交 `product_spec` 与 `product_decision` 都被拒（`product cannot issue product_spec / product_decision in the current work`）。原因：

- `harness/collaboration.py` 第 47 至 48 行：产品能提交 `product_spec`，只在协作请求是 `request_type == "action"` 且 `action == "revise_requirements"` 时；咨询类请求不授予修订合同的权限。
- `harness/validation.py` 第 118 至 124 行：阶段闸门先于上面这条判断。
- 新询问机制没有这个限制：`harness/validation.py` 第 119 至 122 行，`active_ask` 的收件方是 product 时允许提交 `product_spec`；`harness/tests/test_ask_branch.py` 的 `test_ask_answer_with_spec_revision_continuous_work` 覆盖了它。
- 本次运行 `run.asks` 返回 0 条询问：模型在 `ask`（新）与 `submit_request`/`submit_response`（旧）两套通道之间选了旧的那套。

这是 #636（删除协作请求的工具、提案、规则与提交校验）合上以后的过渡状态，模型只剩一条通道时不会选错。新机制本身可用且有测试覆盖。等 #636 至 #639 合并后再走一次，确认产品能在询问回答里当场修订合同。

## 待补充

后续继续使用中遇到的问题按上表格式追加。
