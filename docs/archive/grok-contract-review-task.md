# Grok 合同与上下文返修任务

## 分工与范围

你负责实现，Codex 负责审查和独立验收。与 `docs/grok-runtime-review-task.md` 同轮处理，避免覆盖 Web 专属文件中的并行修改。以下问题均使用 fake adapter 和真实主机检查进程在临时目录复现，不依赖 provider，也不依赖已报告的检查原目录恢复问题。

只处理三部门循环中的合同、上下文、校验问题，以及用户已确认的可审计 lesson 候选最小记录。不展开长期记忆、规则自动更新、动态部门或新的架构层。

## 1. Ask 回答后的有效决策丢失

位置：`harness/context.py:200`、`:222`、`:331`，`harness/projection.py:144`。

复现：产品生成 spec；工程提出问题，选项为 `ASK_CHOICE_CANARY_A` 和 `ASK_CHOICE_CANARY_B`，建议 A；产品返回 `accept`，rationale 为 `Use option A.`，不更新 spec；随后进入新的工程激活，再进入 QA。

实际结果：工程上下文有 `Use option A.`，没有原问题和任何选项正文；QA 上下文没有原问题、选项或 reaction 正文。因果链只留 ID/hash，部门没有读取 Ask 历史的工具，因此新会话无法恢复“选项 A”是什么。多个未改 spec 的 ask/reaction 还会只保留最后一个 reaction。

要求：明确当前有效产品合同包含哪些已回答的产品决策。让新的工程与 QA 激活均能取得完成当前工作所需的有效 Ask/React 内容，包括被接受的实际方案，并且能处理连续两次 ask。不要靠完整 transcript 或要求模型凭空推断补齐；也不要每次把完整历史直接追加到 prompt。随新 spec 失效的旧决定必须可辨识或从当前合同中移除。

验收：用两次不同 canary 选项、仅返回“接受 A”的 reaction、不创建新 spec，验证后续工程和 QA 可以得到两个有效决定的语义；再验证新 spec 替换后不会无条件注入过时决定。

## 2. 新产品合同能够复用旧 QA 检查直接放行

位置：`harness/validation.py:319`、`:347`，`harness/workspace.py` 的 `latest_check` 和检查回执合同。

确定性复现脚本顺序：

1. `product_spec(acceptance=['old behavior'])`。
2. `delivery_turn()`。
3. QA 实际执行 `smoke`，退出 0，但发现合同问题，提交 `rework_product` 和一个 major 缺陷。
4. `product_spec(acceptance=['new behavior'])`，产生产品 spec r2。
5. 工程再次提交相同代码的 delivery，并执行工程检查。
6. QA 仅提交 `review('release', 'I am done without any new check')`，不运行任何新的 QA 检查。

实际结果：`DONE`，spec revision 为 2；最后一次 QA 的工具只有 `provider_usage` 和 `submit_review`，release 却附带 1 条旧 QA 回执。原因是回执只按 role/name/code digest 检索，然后在 review 中重新绑定当前产品 spec；代码未变不能证明新验收标准已经检查。

要求：检查证据保留其实际被检查的产品合同及所属 QA 激活/交付依据。产品合同或所审交付变化后，不得把旧回执重新绑定为新 QA 的亲自检查。与 runtime-review 的可丢弃副本修复统一设计，避免两套回执逻辑。

验收：上述序列的最终 release 必须被拒绝，QA 收到具体字段错误；当当前 QA 对当前合同/交付真正运行检查后，才允许有效 release。补充同代码、不同 spec 的回归场景。

## 3. 无效 QA payload 会抛异常，不能返回结构化拒绝

位置：`harness/validation.py:138`、`:150`、`:315`、`:340`，`harness/orchestrator.py` 的提案处理边界。

复现：准备合法产品 spec、交付物和当前 QA `smoke` 回执，再分别提交：

```json
{"kind":"qa_review","verdict":"release","rationale":"OK","checks":[123],"defects":[]}
```

```json
{"kind":"qa_review","verdict":"release","rationale":"OK","checks":["smoke"],"defects":null}
```

实际结果：第一个抛 `AttributeError: 'int' object has no attribute 'get'`，第二个抛 `TypeError: 'NoneType' object is not iterable`。run 留在 `QUALITY`，没有 `proposal_rejected` 事件，最后一个事件是 `tool_called`。

要求：控制层对不合法提案做完整且一致的类型验证，所有不合法输入都返回字段级错误并留在当前部门；不依赖 OMP 上游 schema 作为唯一保护。检查列表中数字、null、不合法对象和缺陷 null 等输入须明确拒绝或在 schema 层一致规范化。避免在 schema 层局部规范化却在接受阶段继续使用原始坏值。

验收：上述两个输入不抛异常，不进入 DONE；有可观察的 `proposal_rejected` 和下一次激活反馈；修正后可以继续正常完成。

## 4. 失效交付物仍作为当前工件注入

位置：`harness/projection.py:115`、`:151`，`harness/context.py:179`。

复现：产品 r1、交付摘要 `OLD_DELIVERY_CANARY`、QA `rework_product`、产品 r2，再激活工程。

实际结果：工程同时得到 r2 的新 spec 和名为 `current_delivery_spec` 的 r1 旧交付；旧交付正文没有 status。第二次交付提交后，两个 `delivery_specs` 的 status 都是 `active`。

要求：产品版本改变、QA 返工以及新交付替代旧交付时，清楚区分当前有效交付与供修复参考的历史交付。历史内容需要时可作为带失效原因的局部修复依据，不能以无状态的当前交付身份注入。避免旧的 reaction 或 validation feedback 永远无条件成为当前指令。

验收：产品改版后，旧交付不再被声称为当前有效交付；新交付成功后只有一个有效交付。默认上下文内出现的旧工件具有明确历史/失效标记，保留的内容有当前修复用途。

## 5. 补齐可审计 lesson 候选最小记录

用户已确认首版记录可审计 lesson/经验候选，不自动改变规则或模型。当前 `harness/models.py` 的事件和工件种类、状态投影和运行停止路径尚无对应记录。架构师已决定按以下边界完成，实施计划 Phase 5 将同步修正。

要求：候选记录带来源 run、相关事件/spec/检查证据引用，以及待验证建议；记录能够在事件导出中审计，并在 replay 后保留。只记录候选，不自动注入后续部门、不改变规则/模型，不另起 LLM 蒸馏调用。采用当前事实足以支持的最小生成/提交方式，不为每个成功 run 虚构可学习经验。不要实现 active lessons、Scorer 或长期经验库。

验收：构造具有明确返工或失败原因的场景，能从候选追溯到实际来源事件和工件；导出/replay 保留同一候选；后续部门上下文不自动包含候选，部门规则和模型配置未被候选修改。

## 交付回报

- 列出上述五项各自的修复和回归测试结果。
- 说明有效产品决策、交付有效性及检查证据绑定的边界，保持实现与现有分层一致。
- 不用 fake 成功宣称真实 provider 验收通过；真实 happy path 与 Ask/React 仍需随后单独验证。
