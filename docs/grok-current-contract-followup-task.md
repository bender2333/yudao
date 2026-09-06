# Grok 当前合同小批：字段保真返修

继续本会话的实现，但只修复本文件列出的一个已复现问题，然后测试并返回结果。

## 必须遵守的协作边界

- 禁止任何 git 写操作：不能 add、stage、commit、push、reset、restore、checkout、revert、amend、clean，也不能直接修改 `.git`。主任务 Codex 统一处理 git。此前 commit 带入了其他任务暂存文件，本轮不能再次提交。
- 只改本批 `harness/context.py`、`harness/models.py`、`harness/projection.py` 和相关 `harness/tests/test_context.py` / `test_replay.py`。
- 不改 OMP adapter、smoke、tools、workspace、Web、CLI、views、取消、usage、lesson 或其他文档。
- 不调用真实 provider。现有回执合同和 `last_activations` 必须保留。

## 已通过的独立反例

- 同一 spec 下连续两个 Ask 的选项能同时传给工程、QA。
- 新 spec 生效后，旧决定不会继续进入当前合同。
- 旧交付以 `superseded`、`repair_basis` 和具体失效原因供工程修复使用。
- 再次交付后 revision 为 `[1, 2]`，父 hash 正确，仅一个 active 交付。
- 以上场景 replay 与当前投影一致。

## 尚未通过的反例

当前 `ProductDecision` 仅保留 Ask 的 question/options/recommendation/decide_fields，省略 background 与 impact，仍可能丢失决定的实际语义。

复现顺序：

1. 产品创建 spec。
2. 工程提交 Ask：question 为“采用背景中描述的方案吗？”，background 为“Actual required output token is BACKGROUND_CANARY”，options 为 `["A: use the described approach", "B: defer"]`，recommendation 为 A。
3. 产品返回 `accept`，rationale 为 `Use option A.`，不创建新 spec。
4. 激活工程，再交付并激活 QA。

独立结果：工程和 QA prompt 均不包含 `BACKGROUND_CANARY`，因此新会话只知道“采用背景中的方案”却拿不到背景。

要求：保留当前有效 Ask/React 结构化工件中表达决定含义所需的公开字段，至少补齐 background 和 impact；不能依赖模型把这些字段重复抄入 rationale，也不需要注入 transcript。新 spec 取代时沿用已有失效逻辑。

验收：新增上述 background canary，以及 impact 中包含有效决策依据的情况；工程与 QA 能读到当前有效决定的完整依据。运行 context、replay、路由测试，报告命令及结果后立即结束，不进行 git 操作。
