# LOOP — 长任务自动闭环协议

> 本文件定义"无人值守、自动把任务做到闭环"时怎么循环、何时停。
> 配套：目标看 `NORTH_STAR.md`，交接看 `NEXT.md`，记录看 `docs/journal/`。
> 触发：用户说"进入长任务模式 / 自动推进 / 闭环把它做完"或用 `/loop` 时，按本协议运行。

---

## 0. 一句话

**朝 `NORTH_STAR.md` 的 done 定义循环推进，只在硬边界停下问人，其余一律自动往下做。**

---

## 1. 循环体（每一轮）

```text
loop:
  1. 定位      读 NEXT.md 的 "Next Action"，确定当前要推进的 Task（按 tasks-detailed 顺序）
  2. 计划      用 todowrite 把该 Task 拆成可验证小步，每步写明 verify 方式
  3. 实现      写最小可用代码（遵守 AGENTS.md 编码规则）；优先派 subagent 做探索/读取
  4. 验证      跑该 Task 的"验收门槛"对应命令（见 §4）；测不过→修代码，不改测试
  5. 记账      journal 追加结果（PASS/FAIL + 命令 + 产物路径）；决策写 decision.md
  6. 提交      小块验证通过即 commit + push（见 §5）
  7. 判定      达成本 Task 的 done？
       是 → 更新 NEXT.md 指向下一个 Task，回到 1
       否 → 回到 3 继续
  终止：NS-1 三项必过全绿（见 NORTH_STAR）→ 闭环达成，停。
        或命中 §3 硬边界 → 停下等人。
```

---

## 2. 终止条件（达成即停，这是成功）

NS-1 达成，即以下三条全绿（命令见 §4）：

1. 第 1 层 fake-runner e2e 全绿
2. 第 2 层黑盒全自动验收门跑通一次（`outcome=succeeded` + Playwright AC1–AC5 全过）
3. `pnpm test` 全绿 + `pnpm build` 通过

达成后：写一条 journal 收尾 + 更新 NEXT.md 标注"NS-1 达成，等人决定是否进入 NS-2"，然后停。
**不要自动滑进 NS-2 自举**——那是新阶段，需要人显式开启。

---

## 3. 硬边界——只在这三种情况停下问人

其余一切（写代码、跑测试、改文档、装依赖、修 bug、重构自己刚写的代码）全自动，不要停下来请示。

```text
[HALT-1] 需求真歧义且无法从已有文档推断
  —— 设计稿/tasks/验收门都没给出答案，且不同解释会导致明显不同的产物。
     先尝试自查这三份文档；仍无解才停。不要为"风格偏好"级别的小选择停。

[HALT-2] 不可逆 / 高爆炸半径操作
  —— 删库/删多文件、git 重写历史(force push/reset --hard/clean -f)、改生产、
     改鉴权与访问控制、动 .env/密钥、rm -rf。
     这类一律停下说明风险再等确认。本地可逆的文件编辑不算。

[HALT-3] 同一问题连续失败 2 次
  —— 同一个错误改了两次还在（哪怕错误信息变了但根因没解决）：
     停止增量打补丁，先做根因分析，写进 decision.md，再换一条根本不同的路线。
     若新路线会偏离用户原意（换语言/换架构/砍需求），停下确认。
```

停下来时：在 journal 和 NEXT.md 的 "open BLOCKs" 写清"卡在哪、试过什么、需要什么决定"，然后停。不要猜着往下做。

---

## 4. 验证命令（本项目真实命令）

```bash
pnpm test                                   # Vitest 单元/集成全量
VITE_FAKE_RUNNER=1 pnpm test:e2e            # 第 1 层 fake runner（确定性，开发期保护网）
ACCEPTANCE=1 pnpm test:e2e                  # 第 2 层黑盒验收门（需装 codex/claude）
pnpm build                                  # tsc 类型检查 + vite 构建
pnpm api                                    # 起后端（tsx src/server/index.ts）
```

铁律（来自 AGENTS.md 规则 9/12）：
- 测试必须能在业务逻辑出错时失败；只验"返回了点东西"的测试等于没写。
- 跳过的测试不算通过；静默跳过的记录不算迁移完成。失败就如实说失败，附输出。

---

## 5. Git（自动 commit + push）

```text
- 工作分支：禁止直接提交 main。首轮自动切到 work/v01a（不存在则建），后续都提交到它。
- 提交粒度：每个验证通过的小块 commit 一次，conventional commits（feat:/fix:/docs:/chore:）。
- Verified-By：有具体验证产物时带 trailer，例：Verified-By: pnpm test (42 passed)。
- 推送：每次 commit 后 push 到 origin 对应工作分支（已配 SSH: github.com:bender2333/yudao）。
  首次用 git push -u origin work/v01a 建立跟踪。
- 不自动开 PR、不自动并入 main——那一步等人。
- 不用交互式 git（-i）；不加 --no-verify（保留 hooks）；不动 git config。
```

---

## 6. Context 与 Subagent（长任务的命脉）

```text
- context 会被自动压缩；压缩后靠 NEXT.md + journal + 最近 commit 重新定位，不靠记忆。
- 凡是"扇出"型工作（读多文件、搜多处、跑多组测试、调研某模块）→ 派 subagent，
  主上下文只留结论，不留原始文件内容。探索用只读 subagent。
- 每个 subagent 派发与它的结论都记一行 journal。
- 不要为了硬撑着多做一点而疯狂压缩 context——到点了就干净收尾，让下一轮从 NEXT.md 续上。
```

---

## 7. 每轮自检（贴在心里）

- 这一步的产物，能追溯到 NORTH_STAR 的某条 done 吗？不能就别做。
- 我在改测试让它过，还是在改系统让它对？只能是后者。
- 我是不是在第 2 次失败后还在打补丁？是→停，做根因。
- 我现在能一句话说清"做了什么、验证了什么、还差什么"吗？不能→停下重述（规则 10）。
