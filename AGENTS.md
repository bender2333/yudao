# native-harness 分支指令

当前分支 `exp/native-harness` 用 Python harness 做受控实验，研究：

> 单 Agent（S）与需求/开发/质检工单闭环（T）各自跑到完成时，T 是否更容易交付正确的复杂软件任务，以及质量收益是否值得额外成本。

T 获胜不是完成条件。得到“支持 / 不支持 / 证据不足”中的任一可复查结论，都比为了证明假设而调结果更重要。

## 控制文件

- `NEXT.md`：当前 focus、活动实验协议、下一步和 BLOCK。
- `LOOP.md`：长任务自动循环、硬边界和 git 规则。
- `docs/native-harness/`：实现规格、冻结实验协议、题库和结果。
- `docs/journal/YYYY-MM-DD.md`：只记录测试、实验、决策和重要发现。
- `NORTH_STAR.md`：Mission 平台主线背景，只读；不是本实验分支的验收门。

## Session

开始写入前：

1. 先跑 `git status --short --branch`，识别并保留已有改动。
2. 读 `NEXT.md` 及其中列出的活动实验协议。
3. 多步任务写一个带验证方式的短计划。
4. 不为“Session start”单独制造文件改动；有测试、实验、决策或重要发现时再写 journal。

收尾时：

1. 跑与改动匹配的最小测试；代码共享边界变化时跑 harness 全量测试。
2. 更新 journal 和 `NEXT.md`。
3. 只暂存明确路径，commit 并 push 当前分支。
4. 保留未参与本任务的用户改动。

## 研究纪律

1. **先冻结，后跑数**：协议、题目、oracle、预算和评分先 commit；看到评测结果后不得改门槛再重算同一批。
2. **一次只回答一个问题**：明确比较的是“完整 multi 方案”还是“等预算下的角色分工”。两种估计不得混写。
3. **成对比较**：同题、同模型、同 provider、同预算规则、同运行环境；记录全部 run，不筛失败样本。
4. **循环外评分**：agent 不接触 oracle；评分在 run 完成后独立执行。
5. **隔离未验证就不宣称隐藏**：只要 `bash` 仍能越 workspace，就不得把 oracle 不可见当成已满足。
6. **成本必须来自确定性计数**：calls、tokens、墙钟和失败原因由代码记录，不让 LLM 推断。
7. **复杂任务才回答复杂系统问题**：单文件 CLI 只能做校准题，不能支撑“多部门更优”的结论。
8. **允许证伪**：质量无提升、成本失控或结果方差过大，都必须原样报告。

## 编码规则

- 先读导出、调用方和现有测试，再改共享函数。
- 修根因，不在每个调用方贴补丁。
- 写最小实现，不加投机抽象或新依赖；优先标准库。
- 信任边界必须校验；会丢数据、泄密或假成功的错误处理不能省。
- 确定性逻辑不用 LLM：路由、状态、预算、重试、计数和门禁由普通代码完成。
- 测试编码业务意图：非平凡分支至少留一个能在回归时失败的检查。
- 大声失败：skip、缺 summary、oracle 未运行、部分批次失败都不算 PASS。
- 文档和注释用中文；代码标识符与 API 字段保持英文。

## Workspace 与密钥

- 禁止 `git add .`、`git clean`、`reset --hard` 和未经确认的批量删除。
- `provider.md`、`runs/`、原始日志和缓存不提交；研究报告只引用脱敏结果。
- 事件中不得出现 provider key。发现泄密立即停止 live run，先修隔离和脱敏。
- 不把 hidden oracle 放进 agent workspace，也不把 oracle 路径写入 prompt、事件或 summary。

## Subagent

- 多文件搜索、批量验证、结果汇总和只读审查优先派 subagent。
- 实现和连续编辑同一批文件留在主线。
- 只把会影响实验/实现判断的结论写 journal，不记录机械性派发噪声。

## Git

- 始终留在 `exp/native-harness`；禁止自动切到 `work/v01a` 或 `main`。
- 验证通过的小块使用 conventional commit，并 push 到 `origin/exp/native-harness`。
- 有测试证据时添加 `Verified-By:` trailer。
- 不自动开 PR、不合并、不 force push、不跳过 hooks、不改 git config。

## 真实命令

```bash
python -m pytest harness/tests -q
python -m harness.run_solo "<task>" --task-id <id> --run-dir runs/<id> --seed-dir <seed> --checks-file <checks.json>
python -m harness.run_team "<task>" --task-id <id> --run-dir runs/<id> --seed-dir <seed> --checks-file <checks.json>
```

live smoke 或批量实验会消耗外部模型额度，只能在活动协议已冻结且 `NEXT.md` 明确授权该批次时运行。

