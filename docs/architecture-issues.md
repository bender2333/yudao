# 架构执行问题记录 (Architecture Execution Issues)

本文档记录智能体在执行计划与工单实现过程中遇到的架构设计问题、规范冲突、未覆盖边界及阻塞事项。

## 记录规则
1. 严禁在代码中私自编写违背架构原则的临时兼容层或绕过逻辑。
2. 发现架构冲突、设计缺漏或规范矛盾时，必须在此如实登记。
3. 登记条目必须包含工单上下文、具体问题描述、受阻范围与处置建议。
4. 认为总图（`docs/architecture.html`）本身有错的，问题描述开头写「总图」与节号，由总架构师处理；设计说明与代码和总图不符的，改设计说明与代码，不在这里登记。

## 记录格式规范
`模型 ID / 时间（到分钟） / 工单编号或任务 / 遇到的架构问题与冲突 / 影响与建议处置方案`

---

已处理的条目归档在 [docs/archive/architecture-issues-2026-09-10.md](archive/architecture-issues-2026-09-10.md)（2026-09-26 至 2026-10-11）、[docs/archive/architecture-issues-2026-10-19.md](archive/architecture-issues-2026-10-19.md)（2026-10-01 至 2026-10-17）与 [docs/archive/architecture-issues-2026-10-25.md](archive/architecture-issues-2026-10-25.md)（2026-10-21 至 2026-10-25）。

solo-deepseek-v4.1-flash / 2026-10-26 01:29 / 工单 #952 / 画面 2 的两条验收标准互相矛盾。验收标准 2 要求 `translate/tables.ts` 的每个服务端值都翻成画面合同（`client/src/renderer/src/pixel/contract.ts`）取值表里的值；验收标准 3 与「What to build」第 2 条要求 `floorModelOf`、`buildingModelOf` 改用对应表并且画面行为不变、现有楼层与楼的单元测试照常通过、`building/model.ts` 里那份 `IN_ROOM`/`ACTIVE`/`sceneStatus` 删掉。可是这两个函数的另一头是当前的画面场景，它们还认旧词：`pixel/world/floor.ts` 第 18、20 行的 `IN_ROOM`/`ACTIVE` 认 `running`/`asking`/`waiting_provider`/`waiting_decision`/`stopped_for_upgrade`，`pixel/floor/render.ts` 第 28 至 36 行的 `STATUS_TEXT`/`STATUS_CHIP` 与 `pixel/building/status-text.ts` 的 `BUILDING_STATUS` 同旧词，`pixel/building/render.ts` 第 22 行的 `BLINK` 认 `running`；换成合同的词（`in_progress` → `working`，灯 `running` → `working`）以后，楼层里进行中的事项不再进房间、不亮灯（#900 的行为回退），首页每层的灯与文字从「运行中」变成「空闲」，`client/tests/unit/pixel-building.test.ts` 第 13 行的 `sceneStatus` 导入与第 163 行的 `floor.status === "running"` 会红，而该测试文件不在本工单的「只改」里。另外服务端的 `held`（成果已挂起）与 `released_unsettled`（已放行）在画面合同的 `ITEM_STATES`/`FLOOR_SIGNS` 里没有对应的值，对应表只能自己选一个（本轮暂按 `held` → `paused`、`released_unsettled` → `done`），首页的「成果已挂起」会跟着变。场景文件属于画面 3（#953）与画面 5（#955），扩到那里会与它们重叠 / 本轮先做完不依赖这个决定的部分（页面拿到快照的位置、五张对应表与它们的测试、说话的文字、翻译覆盖核对、事件种类夹具与服务端测试），`floorModelOf`/`buildingModelOf` 的接线与 `building/model.ts` 那份对应表的删除留到架构师决定以后。可选做法：① 本单只做对应表与测试，接线随画面 3、5 一起做（它们本来就重写这两个文件与场景）；② 把场景文件并进本单「只改」，本单把楼层与楼的取值一并换成合同的话；③ 改验收标准 2：本单的对应表先输出当前画面的词，画面 3、5 换场景时再改成合同的词。`held`、`released_unsettled` 在合同里补什么值也请一并定
处理：2026-10-26 总架构师定做法 ①：#952 只建对应表、不接线，接线随画面 3（#953）与画面 5（#955）做；服务端的 `held` 翻成 `paused`、`released_unsettled` 翻成 `done`（`docs/decision.md` 2026-10-26「画面翻译层先建表、后接线」）。#952、#953、#955 已关闭（2026-10-27 补记）
