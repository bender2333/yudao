# 文档一致性全量扫描（2026-10-29）

状态：一次性扫描记录，2026-10-29。依据：总图 [architecture.html](architecture.html)、[总体路线图](program-roadmap.md)、[CONTEXT.md](../CONTEXT.md)、[基础规则](foundation-rules.md)、[共同规则](agents/shared-rules.md)。范围：仓库内 `md` 与 `html` 共 662 份（排除 `.claude/worktrees`、`docs/archive`、`.venv`、`node_modules`、`.tmp`）。处理完以后归档到 `docs/archive/`。

## 1. 怎么扫的

- 先把正本读成一份核对清单（总图六节、方程、三环、外环九个状态词、内环六步、十三道缝与已定未定、路线图五阶段与十条道、六条基础规则），再从清单出 20 条硬检查点。
- 两轮并发审查：第一轮 18 组覆盖设计说明与总图对照表，第二轮 9 组覆盖需求记录、根目录规则、角色规则、ADR、调研、试用、原型与评测。每份文件读全文，引用逐条用 `Test-Path` 与行号核对。
- 另做四组机器核对：全仓链接可解析性、状态词的改名与增减、旧阶段编号的分布、术语表避免说法的出现位置。
- 回收：设计说明与总图对照表 81 条（表 A），需求记录与规则 203 条（表 B），技能复核 20 条，机器核对 21 条（第 3 节）。去重合并以后约 300 条。

## 2. 结论

**一条根因占去约六成。** 路线图从按 Stage 编号改成五阶段制以后，设计说明与需求记录里的路线位置没有跟着改。表现分两种。一种仍是旧编号：Stage 3、Stage 4、Stage 5、Stage 6，里程碑 M0 到 M5，工作包 3.1、3.2B、3.2C、3.2D、3.4A、3.7、3.8、3.9。另一种更麻烦：编号按旧表写，落在与现行路线图相反的位置。

| 这件事 | 现行路线图 | 多份文件写的 |
| --- | --- | --- |
| 常驻自转、运维部门、看门狗 | 阶段三 | Stage 4 |
| 判定点、语义系统、外包角色、部门内多角色、任务池 | 阶段四 | Stage 5 |
| 受治理的演化（第二层自举） | 阶段五 | Stage 6（现行路线图里没有 Stage 6） |
| 单 agent 对照 | 阶段二 | Stage 3 |
| 可靠恢复 | 阶段二 | 第三阶段、Stage 3 |

涉及约 35 份文件，重灾区是 `app-and-interface.md`（37 处）、`requirements/README.md`（14 处）、`semantic-system.md`、`operations-department.md`、`web-game-frontend.md`、`model-management.md`、`evaluation/baseline-omp-stage3.md`（15 处）。

**第二大类是把已归档的文档当现行依据。** 36 处指向 `docs/archive/`，其中 12 处引用的节号在现行路线图里根本不存在（第 5.1、5.4、6、6.1、7、8.3 节），另有 4 处指向已不存在的 `docs/stage-3/` 路径。读者按链接落到归档区，会以为那是当前依据。

**结构性错误只有三处，但都在总图的转述上，风险最高。**

1. `design/context-assembly.md:3` 把装配缝两侧写成「执行实现 ↔ 装配实现」，总图第四节是「执行 ↔ 装配实现」。
2. `design/architecture/overall-architecture.md` 第 1.3 节的缝表有 14 行：漏了「投影」这道缝，把内核内部的「裁决」与「最小投影」当成缝列进去，观察者、判定点与外包派发挤在一行，看门狗标成 `Stage 4`（正本是阶段三）；与同一份文件第 19 行「裁决与最小投影不是缝」自相矛盾。
3. 同一份文件第 455 行引「总体路线图第 8.3 节」，现行路线图只有 1 到 5 节。

**术语有 25 处用了术语表点名的避免说法**：交接与持有交接（应为「一轮工作」「关注的成果」）、激活与部门激活与跨激活（应为「一轮工作」）、模型目录（应为「模型能力表」）、额度（应为「套餐状态」）、震荡（应为「振荡」）、第一环第二环第三环（应为内圆中圆外圆）、控制层（应为「控制核心」）、事件存储库（应为「事件日志」）。其中「待恢复」被当成外环状态词使用（6 处），与总图的九个状态词冲突，等用户回答时正本是「等用户」。

**台账两处。** `architecture-issues.md` 63 行里有 16 条带「处理：」的条目没有归档，只剩 #1156、#1215 两条未处理；`docs/adr/` 只剩 7 份，新加的试用 ADR 与 2026-10-28 删掉的 `0039-departments-work-from-watched-outputs.md` 撞号，`decision.md:312` 仍指向已删的那一份。

**规则文件之间有 5 处冲突，会直接改变执行者的行为。** `triage-labels.md` 一处说只有派发者加 `needs-triage`、另一处说执行者自己也加；`acceptance-evidence.md` 把合并前的「集成通过」记在派发者名下，`autopilot-runtime.md` 说本机集成层开 4 个进程，而 `AGENTS.md` 规定本地只用单进程；`triage-labels.md` 把「设计说明有改动」当成交回理由，`AGENTS.md` 明说不是；`.claude/skills/trial/SKILL.md` 第 10 节按工单关闭状态算缺陷命中率，与 2026-10-29 的 ADR-0039「命中率按裁决的成立与不成立算」相反。

**从头到尾没有发现问题的有三份**：`docs/design/architecture/name-map.md`（166 行，严格按十三道缝组织，行内写明「不一致」「代码里还没有」）、`docs/design/visualization.md`、`docs/requirements/department-guidance.md` 的正文。

### 最该先改的七件事

1. 设计说明与需求记录里的路线位置换成阶段一至阶段五（约 35 份文件、110 条）。这一项做完，六成条目消失。
2. 把指向 `docs/archive/` 的「现行依据」改成现行文档，确实需要留作出处的补一句「已归档」。
3. 修三处结构性转述：装配缝两侧、缝表 14 行、看门狗的阶段。
4. 术语一次性按 `CONTEXT.md` 换掉 25 处。
5. 修规则文件之间的 5 处冲突，`foundation-rules.md` 与总图本身除外（只由你改）。
6. 台账：`architecture-issues.md` 归档 16 条；试用 ADR 改号并修 `decision.md:312`。
7. 状态行补齐：9 份需求记录没有状态行，另约 12 份缺「依据」「路线位置」「总图位置」，`foundation-rules.md` 第 3 行是累积式「更新：」段落（该文件只由你改）。

### 处理归属

2026-10-29 与你确认：本报告只留清单，暂不动任何文件。其中两处由你改，因为 `CONTEXT.md` 正由你编辑（新增「agent 试用」一节）：

- `CONTEXT.md:154` 看门狗写「Stage 4 建设」，正本是阶段三。
- `CONTEXT.md:382` 循环实例状态写「震荡」，同文件第 300 行与正本都用「振荡」。

`foundation-rules.md` 与总图 `architecture.html` 的改动只由你批准，报告里涉及这两份的条目只列不改。其余条目按第 1 到第 7 件的顺序处理，等你说了再动。

## 3. 我自己的机器核对结论（21 条）

### 失效链接

全仓逐个解析 markdown 链接并用 `Test-Path` 核对，命中 159 处，去掉噪音后是三类。

1. `decision.md` 第 6、30、82、132、138、160、192、247、256、312、607、720、725 行指向 13 个已被删除的 ADR（0004、0023、0025、0026、0032、0033、0035、0036、0037、0039-departments-work-from-watched-outputs、0042、0043 等）。删除发生在提交 `d585db6f 2026-10-28 删除 36 篇过时的 ADR；各处引用改指设计说明与总图`，那批引用没改完。36 篇 ADR 是直接删除，`docs/archive/` 下没有副本。
2. `decision.md` 第 985、996、1296 行指向 `docs/current-baseline.md`，该文件已归档为 `docs/archive/current-baseline-2026-10-29.md`（提交 `ed8bfcd8 当前验收基线归档，活动文档里去掉对它的引用`，同样没改干净）。
3. 大量 `agents_jour/*.md` 第 3 行用根目录相对写法（`docs/...`，正确写法是 `../../docs/...`），另有引用 `docs/user-session-log.md`（已归档）。

### ADR 编号

`docs/adr/` 现存 0018、0019、0021、0024、0034、0038 六份已提交，加一份未跟踪的 `0039-agent-trial-observation-reproduction-and-judgment.md`。新这份与已删的 0039 撞号，且已删的 0040 也是试用主题，建议新 ADR 取 0044。

### 结构转述

`overall-architecture.md` 的 1.3 缝表与 455 行节号问题见第 2 节；`context-assembly.md:3` 缝两侧写反见第 2 节。

### 与代码不一致

`README.md:356` 写「各实际尝试计入每次部门激活的 32 次模型调用上限」，同文件 366 行写「部门激活次数上限（`max_cycles`）和单次激活模型步数上限……默认值已大幅放宽（均为 999999）」。核对代码：`harness/bounds.py` 只有 `max_cycles` 与 `run_time_limit_sec` 两条边界，没有 32 次模型调用的上限，`test_api.py:166` 也断言默认 `max_cycles == 999999`。356 行这句是旧约束的残留。

### 术语与台账

`shared-rules.md:8` 把控制核心叫「控制层」，术语表 13 处用「控制核心」、0 处用「控制层」；`shared-rules.md:9` 写「事件存储库」，术语表 10 处用「事件日志」。`architecture-issues.md` 63 行里 16 条已处理未归档。`ticket-spec.md:44` 与 `foundation-rules.md:23` 都引 `AGENTS.md` 的「内核路径的测试覆盖」小节，`AGENTS.md` 里没有这个小节名（实际内容在「共同要求」第 3 条「核心的内核模块，需要确保单元测试覆盖率」）。`foundation-rules.md:21` 引已归档的 `archive/requirements/stage-requirements-overview.md` 第 5.3 节。

### 违禁词

`CLAUDE.md:22` 用「与总架构师对齐走向」，`.claude/skills/module-sync/SKILL.md` 标题用「模块对齐」，两处都在共同规则第 73 条禁用的范围里（落地、钉死、对齐）。

### 复核后确认的两条假阳性

1. `flow/SKILL.md` 引用的 `/triage`、`/wayfinder`、`/grill-with-docs` 在用户级 `~/.claude/skills/` 里确实存在，引用有效。
2. `delivery-archive.md:14` 的 `DONE` 是代码里 run 的结束状态（`README.md:366`「只有独立质检 release 才能进入 DONE」），不是外环九个流转状态词，不构成状态词改名。

## 4. 明细

表 A、表 B 来自两轮并发审查的原始条目，按组排列，每条给位置、类别、矛盾点与改法。类别按共同规则分四档：冲突（两处说法不能同时为真，照任一处做会做出不同结果）、不一致（与正本用字或阶段不同）、失效引用（按链接或节号找不到）、含糊（一处可以读成两种做法）。

## 表 A　设计说明与总图对照表（第一轮，组 01–10，共 81 条）

### 01 总体架构、模块图与缝的对照表

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/architecture/overall-architecture.md:21 | 冲突 | 正本总图第四节明确定义了 13 道缝（系统内 10 道：写入口、路由、装配、执行、模型、动作、投影、接口、画面、定义；系统外 3 道：评价、观察者、看门狗）。但本表列出 14 行，遗漏了系统内 10 道缝之一的「投影」（两侧：一份事实 → 读的人），却把总图明确属于内核内部而非缝的「裁决」与「最小投影」作为缝列入；同时将「观察者、判定点、外包派发」合并为一行，且把唯一未定的看门狗缝（表内称健康协议）标为 Stage 4。这既与正本总图硬冲突，又与同文件第 19 行（明确说明裁决和最小投影不是缝、总图十道缝包含投影）自我矛盾。 | 重构缝清单表格为严格对齐总图第四节的 13 道缝（10 道内部缝 + 3 道外部缝）：补齐「投影」（两侧：一份事实 → 读的人），将「裁决」与「最小投影」移出缝表归入内核内部机制说明，拆分「观察者」，并将看门狗（健康协议）明确标注为唯一「未定」外部缝。 |
| docs/design/architecture/overall-architecture.md:455 | 失效引用 | 链接指向的现行正本《总体路线图》（docs/program-roadmap.md）全文仅有 5 个小节（1. 怎么推进，2. 五个阶段，3. 十条内容道，4. 三个空间，5. 五条判据与总图的阶段对照），根本不存在「第 8.3 节」。「第 8.3 节」（近期顺序与完成边界）属于已归档的旧版路线图 docs/archive/program-roadmap-2026-10-25.md。此处引用了现行文件中不存在的失效小节。 | 改为引用现行《总体路线图》（docs/program-roadmap.md）实际存在的对应章节，或显式说明指向归档文档 docs/archive/program-roadmap-2026-10-25.md 第 8.3 节。 |
| docs/design/architecture/overall-architecture.md:210 | 不一致 | 现行正本《总体路线图》第 2 节将系统规划为五个阶段（阶段一至阶段五），第二层自举与受治理演化归入阶段四第二层和阶段五，路线图中已废除「Stage 6」。本文件（第 36、210、225、385、463 行）多处仍沿用 Stage 6，未与现行路线图五个阶段对齐，且未提供映射说明。 | 将文中的 Stage 6 对齐现行路线图更正为「阶段四（第二层）」或「阶段五：受治理的演化」，或在文档开头增加旧版 Stage 编号与现行路线图五个阶段的对应关系说明。 |
| docs/design/architecture/overall-architecture.md:213 | 冲突 | 现行正本《总体路线图》第 2 节明确将「运维部门」和「看门狗」排在「阶段三：常驻自转、运维部门、看门狗兜底」（阶段结束标志为看门狗缝从未定到已定、运维已建）；而现行路线图的阶段四是「拆开部署、细粒度协作、产品的城」。本文件（第 37、213、357、461 行）将运维部门与看门狗标注为旧版规划的「Stage 4」，与现行正本路线图的阶段规划发生直接冲突。 | 将运维部门与看门狗所属阶段更正为现行路线图的「阶段三」，避免与现行阶段四（拆开部署）产生排期混淆。 |
| docs/design/README.md:47 | 失效引用 | docs/archive/stage-3-plan.md 已于 2026-10-25 归档并被路线图取代（CLAUDE.md 明确说明 docs/archive/stage-3-plan.md 已被路线图取代）。docs/design/README.md 在第 47 行依然将其作为「计划：」项下的现行依据引用，违反了归档文档不得被当作现行依据引用的规则。 | 将计划依据替换为现行正本《总体路线图》（docs/program-roadmap.md）或对应阶段工单；如仅用于追溯历史，需显式注明为历史归档。 |
| docs/design/README.md:6 | 冲突 | 正本《总体路线图》第 2 节将看门狗排在「阶段三：常驻自转、运维部门、看门狗兜底」；README.md 第 6 行沿用旧归档路线图称看门狗为「Stage 4」，与现行路线图冲突。 | 将（Stage 4，只写设计）更正为（阶段三，只写设计）或注明对应现行路线图阶段三。 |
| docs/design/README.md:104 | 失效引用 | 同第 47 行，将已归档且被路线图取代的 docs/archive/stage-3-plan.md 作为现行「计划：」依据引用，违反正本规则。 | 更新为现行路线图或工单，或注明已归档。 |

### 02 可信内核与骨架

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/skeleton-and-application.md:266 | 冲突 | 路线图正本将看门狗建设设在阶段三，且本文件第 3 行已写明在阶段三，但第 10 节标题与正文仍写为 Stage 4（旧编号），会导致看门狗建设被错误推迟到阶段四。 | 将第 266 行标题、第 268 行与第 330 行的「Stage 4」统一改为「阶段三」。 |
| docs/design/trusted-kernel.md:33 | 冲突 | 正本路线图规定看门狗在阶段三建设，此处引用写为 Stage 4，与正本阶段规划矛盾。 | 将「Stage 4」改为「阶段三」。 |
| docs/design/trusted-kernel.md:167 | 冲突 | 路线图正本在阶段三引入运维部门并开始统计故障修复，此处写 Stage 4 起由运维发现故障，推迟了运维部门的生效阶段。 | 将「Stage 4 起」改为「阶段三起」。 |
| docs/design/trusted-kernel.md:161 | 不一致 | 路线图正本仅规划五个阶段，结构性定义演化在阶段五，Stage 6 属于作废旧编号且不存在于正本。 | 将「Stage 6」改为「阶段五」。 |
| docs/design/trusted-kernel.md:3 | 不一致 | 状态行未按现行五个阶段做映射，仍使用已归档路线图的 Stage 3 及 M3 命名，使执行者无法确定当前工作在五个阶段中的位置。 | 对照路线图五个阶段改写路线位置，指明对应阶段一（换骨架）与阶段三（内核守卫、发布检查）。 |
| docs/design/skeleton-and-application.md:44 | 不一致 | 正本路线图将判定点安排在阶段四建立，此处写为 Stage 5（旧规划编号），会导致判定点建设被推迟至阶段五。 | 将「Stage 5」改为「阶段四」。 |
| docs/design/skeleton-and-application.md:262 | 不一致 | 正本路线图将外包角色（ACP）安排在阶段四，此处写为 Stage 5，导致执行者误判实施阶段。 | 将「Stage 5」改为「阶段四」。 |
| docs/design/trusted-kernel.md:41 | 冲突 | 第 3 行已声明 B2 已完成且 bounds.py 已分出，但第 41 行仍称「现在与调度写在同一个类中，B2 把它分到单独的内核模块」，且第 3 节 paths 清单漏掉 bounds.py，文件内前后自相矛盾。 | 修改第 41 行确认 B2 已完成并分出 bounds.py，并在第 3 节内核清单 paths 中补入 harness/bounds.py。 |
| docs/design/trusted-kernel.md:24 | 冲突 | trusted-kernel 认为协作规则属于内核（第 24、57 行），但骨架设计说明已明确 collaboration.py 实际是路由实现、将在 S2a 移出内核，两份文档对 collaboration.py 的归属定性矛盾。 | 更新 trusted-kernel.md 第 2 节表格与第 3 节清单说明，注明 collaboration.py 为成果驱动路由、将在 S2a 移出内核。 |

### 03 循环、收敛与独立验证

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/loops-and-convergence.md:3 | 失效引用 | 状态行将已归档的 docs/archive/native-harness/loop-system-principles.md 列在「依据：」中作为现行依据。归档文件是被取代或历史记录，不作为正本依据。 | 从「依据：」中移除对已归档文档 loop-system-principles.md 的引用，或改写为对应现行设计说明/ADR。 |
| docs/design/loops-and-convergence.md:3 | 冲突 | 路线位置使用已废弃的旧 Stage 3/4/5 与工作包/里程碑（3.1、B2、M2）划分；且将「子循环与部门内循环的边界」归入 Stage 5，与现行路线图（已重划为阶段一至阶段五，且部门内多角色与子循环已移入阶段四）直接冲突。 | 将 Stage 3/4/5 与 3.1/B2/M2 对应映射到阶段一至阶段五（例如将部门内多角色与子循环对齐到阶段四）。 |
| docs/design/loops-and-convergence.md:21 | 冲突 | 表格将部门内循环标为 Stage 5，现行路线图中部门内多角色已调整至阶段四，此处不仅使用旧阶段编号，且与现行正本路线图归属阶段冲突。 | 将「部门内循环（Stage 5）」改为「部门内循环（阶段四）」。 |
| docs/design/loops-and-convergence.md:106 | 冲突 | 正文判定说明使用旧 Stage 体系（Stage 3/4/5），并将部门内角色（D26）写在 Stage 5，与现行路线图中 D26 属于阶段四直接冲突。 | 将 Stage 3 改为阶段一/阶段二，将 Stage 5，[D26] 改为阶段四（[D26](../requirements/department-roles.md)），将 Stage 4，[D27] 改为阶段四（[D27](../requirements/operations-departmen… |
| docs/design/loops-and-convergence.md:166 | 不一致 | 验收条目使用旧 Stage 体系代号 Stage 4，未注明对应现行路线图的阶段四。 | 将「Stage 4 起全部通过」改为「阶段四起全部通过」。 |
| docs/design/department-loop.md:9 | 不一致 | 正文中直接出现旧 Stage 3 计划的工作包编号 3.4A，未注明对应现行路线图阶段四。 | 将「不同项目之间的并行（3.4A）」改为「不同项目之间的并行（阶段四，原 3.4A）」。 |
| docs/design/department-loop.md:139 | 不一致 | 正文出现旧里程碑代号 M4 且未注明对应新阶段；同时与 independent-verification.md 状态行声称「先判断后看解释已随阶段一实施（#554）」在阶段与实施进度表述上不一致。 | 去除旧里程碑编号 M4，标明对应现行阶段（如阶段二），并与 independent-verification.md 统一实施状态。 |
| docs/design/independent-verification.md:3 | 冲突 | 文档状态行自身矛盾（前写「未实施」，后写「已随阶段一实施（#554）」）。且代码与关联设计证实 #554 仅实现了质检下结论前隐藏解释部分，第 4 节规定的独立判断事件（independent_judgement）及先判断后看解释流程未实施。状态行存在事实冲突。 | 修正状态行描述：说明交付说明事实与解释字段的解耦已随阶段一实施（#554），而第 4 节独立判断事件（independent_judgement）与先判断后看解释完整流程未实施。 |
| docs/design/independent-verification.md:121 | 不一致 | 正文第 6 节仍将已关闭且在新路线图中无落点的旧任务「3.9 对照实验」作为执行依据，与本文件第 3 行状态行明确指出的「原在 3.9（#100，已关闭），新路线图里还没有落点」不一致。 | 更新正文 3.9 对照实验的表述，去除已关闭且在新路线图中无落点的旧代号 3.9。 |
| docs/design/independent-verification.md:193 | 不一致 | 验收条件中将已关闭且在新路线图中无落点的旧工作包代号「3.9 的对照报告」作为验收项，与状态行自述不一致。 | 将「3.9 的对照报告」改为对应实验说明（如 D32 共享组对照报告），去除作废的旧编号 3.9。 |

### 04 装配与语义

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/semantic-system.md:3 | 不一致 | 路线图正本将语义系统明确归入「阶段四：拆开部署、细粒度协作、产品的城」（第 34 行），阶段五为「受治理的演化（第二层自举）」。此处沿用旧规划名称 Stage 5，与正本路线图不一致。 | 状态行路线位置改为「阶段四（拆开部署、细粒度协作、产品的城）『装配与语义』道」 |
| docs/design/semantic-system.md:14 | 不一致 | 正本路线图仅规划五个阶段（阶段一至阶段五），系统演化与第二层自举在正本中属于「阶段五：受治理的演化（第二层自举）」（第 36 行、第 87 行），全篇不存在「Stage 6」。此处及第 181 行、第 357 行出现的「Stage 6」为旧版规划残留，与正本路线图不一致。 | 将「Stage 6」统一修改为「阶段五（受治理的演化）」 |
| docs/design/semantic-system.md:314 | 不一致 | 正本路线图中判定点与观察者、语义系统均属于阶段四（第 34 行），判定点准入属于阶段五（第 36 行），现行路线图无 Stage 5 接入 JEV 的陈述。此处及第 638 行（链接指向总体路线图）沿用旧版规划中的 Stage 5，与正本路线图不一致。 | 按现行路线图更新 JEV 接入与判定点的阶段归属（阶段四「判定点与观察者」/阶段五「判定点准入」），修正第 638 行对总体路线图的失效引用描述 |
| docs/design/semantic-system.md:587 | 含糊 | 「3.2D」为已归档旧 Stage 3 计划编号。现行路线图已重排为阶段一至阶段五及 M0~M4 里程碑，此处未按检查点第 4 条对照现行路线图阶段与里程碑，代号孤立含糊。 | 将「在 3.2D 实施」改为对照现行路线图具体里程碑（如阶段三 M4 浏览器与 computer use 部分） |
| docs/design/semantic-system.md:42 | 不一致 | CONTEXT.md:739 规定轨迹五层为「事项、一轮工作、计划条目、角色任务与任务内部的尝试」；该文档第 3 行状态声明也承认「轨迹的『交接』一层改称『一轮工作』」，但正文第 42 行与第 248 行仍使用旧词「交接」，与术语表正本不一致且文件内部矛盾。 | 将第 42 行及第 248 行表格等处的「交接」层统一更新为术语表规定的「一轮工作」 |
| docs/design/context-assembly.md:3 | 不一致 | 总图正本 docs/architecture.html:364 第四节明确将「装配」缝定义为「执行 ↔ 装配实现」（左侧为内核槽位「执行」，右侧为应用层「装配实现」），此处写为「执行实现 ↔ 装配实现」，与总图正本不一致。 | 将「执行实现 ↔ 装配实现」修正为「执行 ↔ 装配实现」 |
| docs/design/context-assembly.md:330 | 失效引用 | 总图正本 docs/architecture.html 仅六节大纲，无「第 1.3 节」，实际指向 docs/design/architecture/overall-architecture.md 第 1.3 节；且 overall-architecture.md:26 已改写为包含减法规则链接的已实施状态，原句「减法视图 #912」已不存在，引用目标与内容均已失效。 | 将「总图第 1.3 节」更正为「总体架构设计说明（docs/design/architecture/overall-architecture.md）第 1.3 节」，并同步更新该表当前最新实施描述 |

### 05 模型管理与规则参数

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/model-management.md:259 | 不一致 | 路线图的五个阶段命名为「阶段一」至「阶段五」，不存在「Stage 4」；按 CONTEXT.md 阶段对照表，旧 Stage 4 对应现行路线图「阶段三：常驻自转、运维部门、看门狗兜底」；且 CONTEXT.md 明确规定「Avoid: 新文档里写 Stage 几」。此处直接写「（路线图 Stage 4）」与路线图正本阶段命名及术语规范不一致。 | 将「（路线图 Stage 4）」修改为「（路线图阶段三）」。 |
| docs/design/model-management.md:3 | 不一致 | 状态行存在三处不一致：1) 出现未注明与路线图阶段对照的旧阶段名「（Stage 3）」；2) 缺少 shared-rules.md 3.2 节要求的「路线位置：...」要素；3) 总图第一节的方框正本名称为「模型与工具」，此处误写作「模型」。 | 状态行补齐路线位置（如「路线位置：路线图阶段一（旧 Stage 3 M1/D24 工作包）」），总图方框修正为「模型与工具」，消除裸写旧阶段名「（Stage 3）」。 |
| docs/design/model-management.md:257 | 冲突 | 总图第三节严格定义外环事项的九个状态（等待工作、一轮工作中、核验中、接纳、询问中、等用户、排空中、返工、停止），外环中不存在「待恢复」状态。等待用户修复配置并回答决定请求时，外环分支状态是「等用户」。「待恢复」是决定请求的种类或 run 层的暂停原因，表述为「事项进入待恢复」（同文件 Line 22、186、201、290 亦有同类表述）与总图外环九状态冲突。 | 将「事项进入待恢复」改为「事项进入等用户状态（发出待恢复决定请求）」或表述为「run 暂停，流程编排发出待恢复决定请求」。 |
| docs/design/model-management.md:148 | 失效引用 | 文档内部第 5.6 节标题为「5.6 部门的建议能力」，主题为建议能力的保存与页面提醒；而按输入方式过滤工具并在请求时提供工具的内容实际位于 Line 272（第 5.6 节末尾）或第 6 节。Line 148、Line 305 及 Line 479 均引用「第 5.6 节」指代工具提供规则，导致文件内部小节命名与节号引用错位。 | 理顺 5.6 节「部门的建议能力」与第 6 节「请求时按模型输入方式提供工具」的划分，将工具过滤单独成节，并修正 Line 148、305、479 及状态行中的节号引用。 |
| docs/design/model-management.md:369 | 失效引用 | 调研文档已被归档至 docs/archive/research/，且已形成正式的设计说明 context-assembly.md。CLAUDE.md 明确要求归档文件除非用户指定不读取，硬检查点 5 禁止将已归档的旧文档当作现行依据。此处将归档调研与现行设计并列作为「压缩的依据」，属于将归档文档作为现行依据的失效引用。 | 删除对归档调研文件的引用，仅保留活文档「[上下文装配设计说明](context-assembly.md)」。 |
| docs/design/model-management.md:529 | 不一致 | CONTEXT.md 明确规定术语为「套餐状态（服务端报告的订阅权限与使用窗口）」，并标明「Avoid: 额度, 配额」。此处使用了明确被禁止的 Avoid 词「额度耗尽」。 | 将「额度耗尽」改为符合 CONTEXT.md 的规范表述，如「使用窗口受限」或「套餐状态耗尽」。 |
| docs/design/model-management.md:13 | 不一致 | CONTEXT.md 明确规定来自 models.dev 的快照数据称为「模型能力表」，并标明「Avoid: 能力目录, 模型目录, 模型清单」。该表第三列注明「数据来自 models.dev」，第二列却使用了 Avoid 词「模型目录」。 | 将表格第二列的概念名称从「模型目录」更正为「模型能力表」。 |
| docs/design/rules-and-parameters.md:86 | 不一致 | 硬检查点 4 规定旧工作包代号必须写明与路线图五个阶段的对照关系。「3.9」是旧 Stage 3 计划中的工作包代号，现属于路线图阶段二的对照实验。此处直接引用「3.9」未注明路线图阶段对照。 | 补充路线图阶段对照，修改为「（路线图阶段二对照实验完成，原 3.9 工作包，见...）」。 |
| docs/design/rules-and-parameters.md:150 | 失效引用 | 出处引用了 limits.json。在代码实现（工单 #343）及现行规范中，运行限制参数已全部合并进入 rules.json，代码库中已不存在 limits.json 文件，此处属于指向已不存在旧文件的失效引用。 | 将出处更新为 rules.json（或说明原出处为 D09 / 已合并的 limits.json）。 |
| docs/design/rules-and-parameters.md:155 | 失效引用 | 引用的 independent-verification.md 第 4 节主题为「先判断后看解释」，而 verification.recheck_ratio 参数及其在阶段四的调节规则位于第 5 节「验证密度」（第 80 行起），引用节号错误。 | 将「第 4 节」更正为「第 5 节」。 |
| docs/design/rules-and-parameters.md:180 | 不一致 | 在 app-and-interface.md 第 285-293 行中，规则与参数领域的命令仅定义了 parameter.set 与 experiment.start，候选版本的采用和撤回统一走定义缝的 definition.adopt 与 definition.withdraw，并未定义 experiment.plan、experiment.adopt、experiment.abandon；此外 parameter.set 包含项目级事件 project_parameter_set，本表亦遗漏。两份设计说明对命令和事件体系的定义不一致。 | 将第 9 节表格中的命令和事件与 app-and-interface.md 对齐，候选采用统一使用 definition.adopt / definition.withdraw，补充 project_parameter_set 事件。 |

### 06 执行环境、网络与本地工具

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/execution-environment.md:3 | 冲突 | 引用已归档的 Stage 3 计划作为现行依据；现行路线图已将远程执行代理与远程机器拆开部署排入阶段四，此处仍标为 Stage 3 计划 3.2C，执行阶段冲突。 | 将路线位置更新为现行路线图阶段四（道 05 动作与工具、道 10 部署与环境）。 |
| docs/design/execution-environment.md:14 | 冲突 | 此处要求 3.2B 依赖合同所在的 #128（属于阶段四），而 network-and-mcp.md 第 16 节与第 18 节已明确重排「去掉对阶段四 #128 的依赖」并在阶段二先行单机落地，两份设计文档关于工单阻塞关系的说明直接冲突。 | 修正执行环境设计说明，删除 3.2B 工单依赖 #128 的陈旧表述。 |
| docs/design/execution-environment.md:288 | 失效引用 | 引用的「总体路线图第 5.1 节」属于已归档的旧版路线图（docs/archive/program-roadmap-2026-10-25.md），现行路线图 docs/program-roadmap.md 无 5.1 节及该规则内容。 | 将依据改为现行有效需求文档 docs/requirements/execution-limits.md（D09）。 |
| docs/design/execution-environment.md:465 | 失效引用 | docs/stage-3/ 目录已于 2026-10-25 整体归档至 docs/archive/stage-3/，活文档树中已不存在 docs/stage-3/ 路径。 | 更新验收报告存放路径为现行有效路径。 |
| docs/design/network-and-mcp.md:3 | 不一致 | 状态行缺少正本核对清单硬检查点 6 与架构师规则明确要求的「路线位置」与「总图位置」，脱离总图与路线图锚定。 | 在状态行末尾补充「路线位置：路线图阶段二「质检自己核验网页」（薄片 ③，父工单 #122）；总图位置：第四节「动作」的缝；第一节「模型与工具」方框。」。 |
| docs/design/network-and-mcp.md:107 | 不一致 | 文内第 16 节已明确重排全部属于「阶段二薄片 ③」，第 5.1 节（及第 14 节 line 274）仍沿用旧 Stage 3 称谓，文档内部阶段归属不一致。 | 将「Stage 3」更新为现行路线图对应的「阶段二」。 |
| docs/design/network-and-mcp.md:232 | 不一致 | 沿用已归档旧计划的里程碑代号 M3，未与路线图五个阶段建立对照，且与第 16 节的阶段二薄片 ③ 归属矛盾。 | 将「M3 试用」改为「阶段二薄片 ③ 试用」。 |
| docs/design/local-tools.md:35 | 不一致 | 使用了已归档旧计划的里程碑代号「M2」，现行路线图未建立该代号与五个阶段的映射对照。 | 将「M2 起」改写为路线图对应阶段或薄片名称（阶段二）。 |

### 07 浏览器与接入项目

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/browser-and-computer-use.md:3 | 冲突 | 现行路线图 docs/program-roadmap.md 已重写为五个阶段（一个阶段为一个 GitHub 里程碑），「质检自己核验网页」（动作加网络与浏览器）属于阶段二；之前按 Stage 写的路线图和计划已归档。本文档状态行仍写属于 Stage 3 与里程碑 M4，将已归档的 Stage 3 计划作为现行路线位置，且未对照现行五个阶段。 | 改写状态行，将路线位置更新为路线图阶段二「质检自己核验网页」，注明原属 Stage 3 的 3.2D（父工单 #123），删除属于里程碑 M4 的表述。 |
| docs/design/browser-and-computer-use.md:310 | 失效引用 | 正文引用已归档且被取代的旧路线图 docs/archive/program-roadmap-2026-10-25.md 第 5.1 节。现行有效路线图为 docs/program-roadmap.md。 | 将引用更新为现行有效路线图 docs/program-roadmap.md。 |
| docs/design/browser-and-computer-use.md:390 | 不一致 | 总图第三节定义的外环状态词仅九个（等待工作、一轮工作中、核验中、接纳、询问中、等用户、排空中、返工、停止），无「待恢复」状态；决定请求停在写入口等待用户回答时，外环状态应当为「等用户」。 | 将「run 显示待恢复」修改为符合总图九个外环状态词的「等用户」状态。 |
| docs/design/browser-and-computer-use.md:638 | 失效引用 | docs/stage-3/ 目录在仓库中不存在，该目录已被归档迁移为 docs/archive/stage-3/。 | 将路径更新为归档路径 docs/archive/stage-3/ 或现行验收报告存放目录。 |
| docs/design/existing-project-onboarding.md:379 | 失效引用 | docs/stage-3/ 目录在仓库中不存在，该目录已被归档迁移为 docs/archive/stage-3/。 | 将路径更新为归档路径 docs/archive/stage-3/ 或现行验收报告存放目录。 |

### 08 应用层与接口层

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/app-and-interface.md:518 | 冲突 | 正本总图与清单硬检查点 19 均规定用字为「振荡」且不可写成「震荡」，本文误写为「震荡」，产生用字冲突。 | 将「震荡」改为「振荡」 |
| docs/design/app-and-interface.md:3 | 失效引用 | docs/archive 下文件已被取代，状态行将其列为当前设计的现行「界面要求」依据，违反硬检查点 5。 | 将归档调研中的有效界面要求吸收至现行设计说明，移除状态行中指向 ../archive/ 的引用 |
| docs/design/app-and-interface.md:393 | 失效引用 | 当前定稿原型已是 v13，正文仍将已归档的历史原型 v9 及 v8 设计说明作为回放机制的生效依据，违反硬检查点 5。 | 将依据更新为当前定稿的 v13 原型或画面与播放设计说明（visualization.md），删除指向归档原型的链接 |
| docs/design/app-and-interface.md:432 | 失效引用 | 首页与机器页路径将已归档的旧原型 v9 与 v8 作为生效依据，违反硬检查点 5 且与状态行声明冲突。 | 删除指向归档原型 v8/v9 的链接，按状态行声明以本文和现行原型规范为准 |
| docs/design/app-and-interface.md:285 | 冲突 | 现行路线图只有五个阶段，自举第二层属于阶段五；本文出现已被归档废弃的 Stage 6（另见 290-292、346、445、544、614 行），与路线图直接冲突。 | 将 Stage 6 统一修正为路线图现行的「阶段五」（第二层自举） |
| docs/design/app-and-interface.md:316 | 冲突 | 路线图正本将运维部门、故障修复与看门狗归入阶段三；本文将运维标为旧编号 Stage 4（另见 436、445、543、855 行），与现行路线图阶段划分冲突。 | 将运维及相关故障修复/看门狗等阶段归属修正为现行路线图的「阶段三」 |
| docs/design/app-and-interface.md:322 | 冲突 | 路线图正本将部门内多角色、语义系统归入阶段四；本文使用旧编号将其标为 Stage 5（另见 245、309、519 行），与现行路线图阶段划分冲突。 | 将语义记录、多角色设置等所属阶段修正为现行路线图的「阶段四」 |

### 09 画面、发布与起始文件夹

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/web-interface-and-release.md:3 | 失效引用 | 引用已归档的旧规划文档作为现行路线位置，执行者无法从现行路线图索引该设计。 | 将路线位置改指现行 docs/program-roadmap.md 阶段一，注明原属旧 Stage 3 界面工作线。 |
| docs/design/web-interface-and-release.md:15 | 冲突 | 正本路线图将看门狗与常驻服务安排在阶段三，此处写随 Stage 4 进行会导致看门狗延后规划。 | 将看门狗与常驻服务规划改为对齐路线图「阶段三：常驻自转、运维部门、看门狗兜底」。 |
| docs/design/web-interface-and-release.md:156 | 不一致 | 沿用旧 Stage 3 的 M1-M4 命名，未说明与路线图现行五个阶段的关系。 | 改写版本号规划，对齐现行路线图五个阶段，移除旧 Stage 3 的 M1-M4 命名。 |
| docs/design/web-interface-and-release.md:189 | 失效引用 | docs/stage-3/ 目录已归档删除，读者按举例路径找不到或误建文件。 | 删除不存在的 docs/stage-3/ 举例，改为指涉阶段文档通用规范。 |
| docs/design/project-initial-files.md:3 | 不一致 | 状态行未以标准状态行格式组织，开头夹带「更新：」并将「依据：」分段另起。 | 将第 3 行与第 5 行合并为单行标准状态行，去除「更新：2026-10-06。」前缀。 |
| docs/design/project-initial-files.md:3 | 不一致 | 沿用已归档 Stage 3 与 M2 命名，未对齐现行路线图阶段二。 | 将路线位置改为「路线图阶段二「真实项目接着做」；原属 Stage 3 的 3.8（父工单 #124）」。 |

### 10 测试分层、评测与恢复契约

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/design/test-pyramid.md:3 | 不一致 | 状态行缺少「依据：...」与「路线位置：...」，未满足活动设计说明开头要素规范。测试分层在路线图中属于贯穿全阶段的基础设施。 | 在状态行补充「依据：[D38](../requirements/system-intent.md)、[共同规则](../agents/shared-rules.md)」与「路线位置：全阶段基础设施（贯穿阶段一至阶段五）」。 |
| docs/design/test-pyramid.md:293 | 冲突 | 总图正本明确只有外环变更「只由你批准」（中环由质检放行，内环由工程自测）。此处模糊写为「环是需你批准」，既偏离总图正本授权边界，又存在语句脱落。 | 将「环是需你批准」改为「外环变更只由你批准」。 |
| docs/design/test-pyramid.md:301 | 不一致 | 第 13 节通篇把总图第二节同心圆称为「第一环、第二环、第三环」（包括第 309-311 行表格与 315-316 行 R1/R2），直接违反了 CONTEXT.md 明确禁用的「Avoid: 第一环、第二环、第三环」，且由外向内编号容易与外环/中环/内环混淆。 | 将第 13 节各处的「第一环、第二环、第三环」改回总图第二节正本用词「内圆、中圆、外圆」。 |
| docs/design/test-pyramid.md:317 | 不一致 | 使用了已被 CONTEXT.md 列为 Avoid 的禁用旧概念「模型目录」，正本术语为「模型能力表」。 | 将「模型目录」替换为正本术语「模型能力表」。 |
| docs/design/evaluation-scenarios.md:3 | 失效引用 | 路线位置将已归档被取代的 docs/archive/stage-3-plan.md 作为现行依据，且使用已被路线图废除的旧阶段编号「Stage 3」和旧里程碑「M2」「M4」。现行正本路线图中评测工作线属于阶段二（薄片②与薄片④）。 | 删除对 stage-3-plan.md 的依据引用，路线位置改写为对照现行路线图：「阶段二（可靠恢复、接入真实项目、独立评价）的薄片②（场景 2、3 评测与单 agent 对照）与薄片④（场景 1 界面核验）」。 |
| docs/design/evaluation-scenarios.md:156 | 不一致 | 使用了被废除的阶段编号 Stage 4，且未对照现行路线图。现行路线图判据二明确规定留出场景在阶段三结束时首次运行。 | 将「第一次运行在 Stage 4 结束时」改为「第一次运行在阶段三结束时」。 |
| docs/design/evaluation-scenarios.md:200 | 不一致 | 使用了已被路线图取代的旧任务包编号「Stage 3 的 3.2D」，未对照现行路线图阶段二薄片③。 | 改为「浏览器工具由阶段二薄片③（[D34](../requirements/browser-and-computer-use.md)）提供」。 |
| docs/design/evaluation-scenarios.md:206 | 不一致 | 实施顺序整节基于已废弃的旧 Stage 3 里程碑（M2、M4）和旧任务包编号（3.2D、B4、3.8），未对照现行路线图阶段二的四个薄片。 | 将第 10 节实施顺序改写为按现行路线图阶段二薄片对应：第 1-4 项归入薄片②，3.8 接入已有项目对应薄片①，3.2D 对应薄片③，场景 1 运行对应薄片④。 |
| docs/design/recovery-contract-and-fault-matrix.md:3 | 失效引用 | 将已归档被取代的 docs/archive/stage-3-plan.md 作为现行路线范围和顺序的依据。现行路线图中可靠恢复属于阶段二薄片①与阶段三。 | 删除对 stage-3-plan.md 的依据引用，路线位置改为：「阶段二（可靠恢复、接入真实项目、独立评价）薄片①（单机可靠恢复）与阶段三（常驻自转、运维部门、看门狗兜底）」。 |
| docs/design/recovery-contract-and-fault-matrix.md:51 | 冲突 | 使用了明确禁用的概念「持有交接」。总图第三节与术语规范规定，部门围绕成果循环，没有部门「持有」事项或交接；工作区写入是一轮工作中由当前执行的工程角色发起，不存在「持有交接」。 | 将「run 的工作区只有持有交接的工程写入，这个对比可靠」改为「run 的工作区在一轮工作中只有工程写入，这个对比可靠」。 |
| docs/design/recovery-contract-and-fault-matrix.md:104 | 不一致 | 验收归属出现「Stage 6 完整撤销」。正本路线图只有阶段一至阶段五，根本没有 Stage 6。且整张故障矩阵通篇使用旧 Stage 3 任务包号作为验收归属，未与路线图对照。 | 将「Stage 6 完整撤销」改为「阶段五 完整撤回」，并将整张矩阵的验收归属（3.1, 3.2B, 3.2C, 3.4A, Stage 4, Stage 5）对照映射至现行路线图五个阶段。 |

## 表 B　需求记录、根目录规则、角色规则、ADR、调研、原型与评测（第二轮，共 203 条）

### g11 需求记录：README、系统意图、自举、三部门、指导与角色

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/requirements/README.md:31 | 不一致 | 用已废弃的 Stage 3 与里程碑 M1 当现行路线位置，未对照到阶段一至五；同类还见本文件第 33、35–38 行。 | 改写成路线图的阶段名（如「阶段一」），旧编号只作括注。 |
| docs/requirements/README.md:42 | 不一致 | 整行以 Stage 3、M2/M4、工作包 3.9 与「Stage 4 结束时」为路线位置，未对照五阶段；同类还见第 43–47 行的 3.8、3.2B、3.2D。 | 按路线图的阶段与薄片名重写该行的路线位置，旧编号只作括注。 |
| docs/requirements/README.md:48 | 不一致 | 现行路线图没有「迭代底座」工作包，也没有 Stage 名，D38 的实现位置对不上任何阶段或道。 | 按阶段一至阶段五与十条道重写这句。 |
| docs/requirements/README.md:39 | 不一致 | 同一件事这里写旧工作包 3.2C/里程碑 M3，self-hosting.md 写阶段四，两处对不上。 | 统一写「阶段四（拆开部署）」。 |
| docs/requirements/README.md:30 | 冲突 | 同一项指导的送达与处理，索引说已实施、需求记录说未实施。 | 核对 #476 的实际交付范围，两处写成同一种状态。 |
| docs/requirements/system-intent.md:136 | 不一致 | 用旧的 Stage 4 指阶段三，现行路线图与总图都不用 Stage 编号。 | 改写为「阶段三的完成依据」。 |
| docs/requirements/system-intent.md:138 | 不一致 | Stage 6 是旧名，对应现行路线图的阶段五，验收列没有给出阶段名。 | 改写为「阶段五的四条完成条件」。 |
| docs/requirements/system-intent.md:263 | 不一致 | 结尾的实现位置用旧阶段名与已不存在的工作包名，指不到路线图的任何阶段或道。 | 改写为五个阶段的名称与对应的道。 |
| docs/requirements/system-intent.md:206 | 不一致 | 正本用「振荡」，此处与第 225 行都写「震荡」（第 103 行属任务书原文引用，不改）。 | 两处改为「振荡」。 |
| docs/requirements/system-intent.md:3 | 不一致 | 状态行只有状态、确认时间与设计链接，缺「依据」一项，路线位置只以一句指代。 | 补「依据：总图第几节／路线图第几节」并把路线位置写成具体阶段。 |
| docs/requirements/self-hosting.md:3 | 不一致 | 状态行是「最近一次改动…；…」的累积段落，缺「依据」，来源又写成已归档的旧路线图。 | 压成「状态 + 依据 + 路线位置 + 设计」的短行，改动历史移到正文或 CHANGELOG。 |
| docs/requirements/self-hosting.md:3 | 不一致 | 阶段三的内容里没有这项工具，路线图把它列在道 08 未排阶段的未知落点。 | 改为「未排阶段，见路线图道 08 的未知落点」。 |
| docs/requirements/self-hosting.md:34 | 不一致 | 五项前置条件用已废弃的工作包编号表示，读者无法在现行路线图里定位。 | 改成路线图里的阶段与薄片名（如「阶段二『真实项目接着做』」）。 |
| docs/requirements/self-hosting.md:36 | 失效引用 | 把已归档的旧路线图第 5.1 节当依据；同样写法在第 74 行还有一处。 | 改引现行路线图对应的一节，或删除并注明该项未排阶段。 |
| docs/requirements/self-hosting.md:57 | 失效引用 | 现行路线图只有五节，没有第 5.4 节；这句话的内容实际在第 3 节道 10。 | 改为「见路线图第 3 节道 10」。 |
| docs/requirements/self-hosting.md:61 | 不一致 | 用旧工作包 3.8 与旧阶段名 Stage 6 指代对照物，现行正本里没有这两个名字。 | 改写为「阶段二『真实项目接着做』的基线检查回执、阶段五的检查定义」。 |
| docs/requirements/self-hosting.md:52 | 失效引用 | 把已归档的「系统架构原理」当现行依据，正文也没有写它是归档。 | 改引 docs/foundation-rules.md 基础规则 3 的对应行或总图第四节的缝。 |
| docs/requirements/self-hosting.md:72 | 不一致 | 用已删除工作包号 3.4B 描述待办，未写它对应路线图的哪个阶段。 | 写成「阶段四：同一项目多个写入者与采纳前对合并结果的验证」。 |
| docs/requirements/three-department-loop.md:16 | 不一致 | 正文用了术语表标为禁用的「交接」（第 5 行是用户原话，不属于此处）。 | 改为「交出与回复主要使用明确消息与 spec」。 |
| docs/requirements/department-guidance.md:31 | 不一致 | 用禁用的「激活」描述部门开始一轮工作。 | 改为「在返工的一轮工作中处理」。 |
| docs/requirements/department-history.md:13 | 不一致 | 一句里用了两个禁用词（第 27 行「跨部门激活保留」同）。 | 改为「部门交出任务后重新参与时继续保留，不能因开始新一轮工作就清空」。 |
| docs/requirements/department-prompts.md:26 | 不一致 | 用禁用的「激活」表示部门的一次工作。 | 改为「一次工作固定版本，下次目标部门开始一轮工作时采用更新」。 |
| docs/requirements/department-roles.md:47 | 不一致 | 用禁用词「持有交接」「激活」改写外环规则，与总图的状态词对不上（第 48 行同）。 | 改用正本状态词，例如「一个部门处于一轮工作中，其他部门只做准备工作」。 |
| docs/requirements/department-roles.md:54 | 不一致 | 画面一节用禁用词「交接」。 | 改为「部门之间的交出经过管道」。 |
| docs/requirements/department-roles.md:71 | 不一致 | 链接指向现行路线图，却用旧名 Stage 5 写路线位置。 | 改为「阶段四：部门内多角色与外包角色」。 |
| docs/requirements/department-roles.md:3 | 不一致 | 状态行用旧阶段名，且缺「依据」一项（路线位置在第 71 行另写）。 | 状态行写「依据 + 路线位置：阶段四」并去掉 Stage 5。 |
| docs/requirements/department-roles.md:30 | 不一致 | 旧阶段名横跨两个阶段，读者无法看出哪条属阶段四、哪条属阶段五（第 38、39 行同）。 | 分别写成「阶段四」与「阶段五」。 |
| docs/requirements/department-guidance.md:1 | 不一致 | 文件开头没有状态行（无依据、无路线位置），只有正文第 31 行的一句「状态：」；department-history.md、department-prompts.md、three-department-loop.md、intend-original.md 同样没有。 | 在标题下补一行「确认时间／状态／依据／路线位置／设计」。 |
| docs/foundation-rules.md:3 | 不一致 | 状态行是四段「更新：…；…」的累积段落，没有依据与路线位置。 | 仅报告：该文件只由用户修改，是否改为单行状态由用户决定。 |

### g12 需求记录：语义、元观察、运维、三空间、web 游戏、对照实验、外包

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/requirements/semantic-system.md:3 | 不一致 | 状态行只有确认时间与状态，缺「路线位置」与「总图位置」；路线位置只写在文末第 180 行，且写的是已被取代的 Stage 5。 | 在状态行补「路线位置：阶段四（语义系统、判定点与观察者）」与「总图位置：第三节装配、第四节装配缝」，与第 180 行一致。 |
| docs/requirements/semantic-system.md:67 | 不一致 | 沿用旧 Stage 编号，现行路线图只有阶段一至阶段五，JEV 协议接入属阶段四的判定点工作。 | 改写为「JEV 的协议接入排在阶段四的判定点工作，随语义系统与观察者一起接入」。 |
| docs/requirements/semantic-system.md:142 | 冲突 | 现行路线图把语义系统排进阶段四薄片，文件仍写成 Stage 5，且 Stage 5 这个阶段名在路线图里已不存在。 | 改为「语义系统排在阶段四（语义系统、判定点与观察者薄片）」，并注明原 Stage 编号已由阶段四取代。 |
| docs/requirements/semantic-system.md:163 | 不一致 | 规则变更流程属阶段五，文件用旧 Stage 6 指代，未与阶段一至五对照。 | 改为「按阶段五（受治理的演化）的规则变更流程处理」。 |
| docs/requirements/semantic-system.md:180 | 冲突 | 路线位置写 Stage 5，与路线图把语义系统放在阶段四相反，阶段名也是旧的。 | 改为「路线位置：阶段四，语义系统、判定点与观察者薄片」。 |
| docs/requirements/semantic-system.md:78 | 不一致 | 用的是术语表列为避免说法的「交接」，同一说法还在第 98、99、149、157 行。 | 按术语表改为「关注的成果」或「一轮工作」等对应说法（L98、L99、L149、L157 一并改）。 |
| docs/requirements/semantic-system.md:45 | 失效引用 | 把归档文档当作现行做法的依据，读者按链接会到归档区找当前依据。 | 把这条参照改写为对现有设计说明（如语义系统设计说明第 15 节）的引用，或标注「已归档，仅作历史参考」。 |
| docs/requirements/semantic-system.md:103 | 失效引用 | 调研已归档（说明它已写进设计），文件仍把它当现行调研入口；同类还有第 111、132、165 行指向 archive/research。 | 改为指向已写成的设计说明小节，并注明原调研已归档（L111、L132、L165 一并处理）。 |
| docs/requirements/meta-observer.md:3 | 冲突 | 元观察在总图上是观察者加判定点，路线图把它排在阶段四，文件把设计与路线位置都写成 Stage 6。 | 状态行改为「路线位置：阶段四（判定点与观察者）」，并补总图位置；第 23 行同步改。 |
| docs/requirements/meta-observer.md:30 | 不一致 | 两处都用旧 Stage 编号，未与阶段一至五对照；协议接入与元观察使用都在阶段四。 | 改为「协议接入与元观察都在阶段四，随判定点薄片一起做」。 |
| docs/requirements/meta-observer.md:49 | 不一致 | 部门内多角色已排在阶段四，此处仍写 Stage 5；第 41、45 行的「Stage 6 设计时确定」同样是旧阶段说法。 | 改为「阶段四引入的部门内部角色」，并统一把 Stage 6 改成阶段四/阶段五的具体阶段名。 |
| docs/requirements/meta-observer.md:58 | 不一致 | 前置依赖用旧工作包号 3.7 指代只读观察接口，没有与阶段一至五对照，读者查不到这张工作包。 | 改为「前置依赖：阶段四的观察者缝（只读订阅与写入口提案）」。 |
| docs/requirements/operations-department.md:3 | 冲突 | 路线图把运维部门与看门狗一起排在阶段三（薄片「只写声明加运维部门」），文件把设计与路线位置都写成 Stage 4。 | 状态行改为「路线位置：阶段三（常驻自转、运维部门）」，第 46、48 行的 Stage 4 一并改。 |
| docs/requirements/operations-department.md:34 | 冲突 | 部门内多角色按路线图属阶段四，文件写 Stage 5。 | 改为「部门内多角色在阶段四对四个部门一起引入」。 |
| docs/requirements/operations-department.md:47 | 冲突 | 语义系统按路线图属阶段四，此处写 Stage 5，与三空间记录「城与指向式输入（阶段四，与语义系统同期）」也相左。 | 改为「语义系统在阶段四」，完成依据挂到阶段三的判据上。 |
| docs/requirements/operations-department.md:48 | 不一致 | 用旧工作包号 3.8 与已不存在的 Stage 3 当现状说明，没有与阶段一至五对照。 | 改为「原路由线的运维工作并入阶段三的运维部门薄片」。 |
| docs/requirements/operations-department.md:42 | 不一致 | 以旧工作包号 3.2B 当规则出处，现行文档里没有这张工作包，读者无法定位。 | 改为写明现行出处（外部内容随请求放入的规则在语义系统设计说明或装配缝一节）。 |
| docs/requirements/operations-department.md:66 | 不一致 | 前置依赖用旧工作包号 3.1、3.2C，没有与阶段一至五对照，无法在现行文档中查证。 | 改为按阶段写：动作缝的结果未知处理与执行缝的执行代理，均已在前序阶段建好。 |
| docs/requirements/operations-department.md:61 | 不一致 | 同时用了术语表禁止的两个说法，术语表的正说法是「关注的成果」与「一轮工作」。 | 改为「谁可以向谁询问、打回」，下一个开始一轮工作的部门由关注的成果决定。 |
| docs/requirements/operations-department.md:62 | 失效引用 | 把归档的 Stage 3 运行责任样例当现行设计依据，而未实施的设计要从归档文档取规则，读者按链接落在归档区。 | 把这些沿用条目写成本记录或设计说明里的正文，链接标注「已归档，仅作历史参考」。 |
| docs/requirements/operations-department.md:46 | 不一致 | 运维相关规则挂在旧 Stage 4 上，与路线图的阶段三不一致，且阶段名已不存在。 | 改为「阶段三的通知与决定请求只在 Yudao 的界面中显示」。 |
| docs/requirements/game-world-three-spaces.md:21 | 冲突 | 路线图第 4 节把步 4 整步放在阶段四，文件写成「阶段三至四」，把一步拆到两个阶段。 | 改为「步 4 规则成为物件与物理（阶段四）」。 |
| docs/requirements/game-world-three-spaces.md:3 | 不一致 | 状态行说「六步」，正文与路线图都列了步 0 到步 6 共七步，同一份文件前后不一致。 | 把「六步」改为「七步（步 0 至步 6）」，或统一编号后两处对齐。 |
| docs/requirements/game-world-three-spaces.md:37 | 冲突 | 本文件把运维部门放在阶段三，运维记录自己写 Stage 4，两份文件对同一阶段说法不同。 | 以路线图为准统一为阶段三，并把运维记录的状态行改过来。 |
| docs/requirements/comparison-experiment.md:3 | 冲突 | 单 agent 对照按路线图是阶段二薄片「比单个 agent 好多少」，文件把整条评测工作线挂在已不存在的 Stage 3，并引用 M2、M4 与 3.2D。 | 状态行改为「路线位置：阶段二薄片②（比单个 agent 好多少）」，M2、M4 换为阶段名；第 65、75 行同步改。 |
| docs/requirements/comparison-experiment.md:64 | 冲突 | 路线图把留出场景放在阶段三结束的判据里，文件把第一次运行排到 Stage 4 结束，晚了一个阶段。 | 改为「第一次运行在阶段三结束时」，与判据二对齐。 |
| docs/requirements/comparison-experiment.md:66 | 不一致 | 用旧工作包号 3.2D 当代理依赖，现状说明里查不到这张工作包；第 75 行的前置依赖同样写 3.2D。 | 改为「依赖阶段二薄片③的浏览器核验工具」。 |
| docs/requirements/comparison-experiment.md:67 | 冲突 | 两项工作都排在阶段四，文件写 Stage 5，阶段归属错。 | 改为「决定阶段四中语义系统与部门内多角色等工作的先后」。 |
| docs/requirements/comparison-experiment.md:67 | 不一致 | 以旧工作包号 3.9 指代隔离组运行，没有与阶段一至五或现行工单对照，读者无法定位。 | 写清 3.9 现在对应哪份设计或哪张工单（或改为按阶段二对照记录描述）。 |
| docs/requirements/web-game-frontend.md:3 | 冲突 | 现行路线图没有「Stage 3 界面工作线」这一位置，界面在阶段一（画面缝）与阶段二（界面为已建）交付；第 80 行重复同一说法。 | 改为「路线位置：阶段一画面缝与阶段二界面已建」，第 80 行同步改。 |
| docs/requirements/web-game-frontend.md:48 | 不一致 | 整句用旧 Stage 3/4/5 与旧工作包号 3.1、3.2C、3.8 作现行依据，未与阶段一至五对照。 | 按阶段重写：界面随阶段二、运维随阶段三、部门内多角色与语义系统随阶段四验收。 |
| docs/requirements/web-game-frontend.md:24 | 不一致 | 已确认条目用旧 Stage 3 至 Stage 6 划分界面范围，未与阶段一至五对照，Stage 编号在现行路线图中已不存在。 | 改为按阶段一至阶段五写界面的范围，元观察与演化入口挂在阶段四、阶段五。 |
| docs/requirements/web-game-frontend.md:31 | 不一致 | 用旧里程碑编号 M1 指代试用，现行路线图只有阶段一至五的里程碑，读者无法对应。 | 改为「阶段一薄片试用以后」或写明当时里程碑对应现在的哪个阶段。 |
| docs/requirements/web-game-frontend.md:30 | 不一致 | 把版本区间与「随 Stage 4 的长时间运行」挂在旧阶段编号上，其中长时间运行按路线图属阶段三。 | 改为按阶段写版本区间与「随阶段三的常驻运行」。 |
| docs/requirements/expert-ask-react.md:18 | 不一致 | 术语表把「交接」「持有交接」列为避免说法，正说法是关注成果与该部门是否在等工作人员。 | 改为「同一事项同一时刻只有一个部门在开始一轮工作」。 |
| docs/requirements/expert-ask-react.md:32 | 失效引用 | 指向的验收记录文件已不存在，读者按路径找不到 C 批记录的出处。 | 改为指向现行的验收证据位置（如验收证据规则中的记录处或对应 PR），或删掉该句。 |
| docs/requirements/expert-ask-react.md:1 | 不一致 | 文件开头没有状态行（确认时间、状态、依据、路线位置、总图位置），实现状态在第 30 行也没有路线位置。 | 补一行状态行：确认时间、状态、依据、路线位置（阶段二询问分支）、总图位置（第三节询问中）。 |
| docs/requirements/outsourced-agent-roles.md:3 | 不一致 | 路线图已把外包角色排在阶段四，文件仍写「路线位置：待定」，第 43 行还把它列为待确认，与实际排期不符。 | 改为「路线位置：阶段四（部门内多角色与外包角色）」，并删去第 43 行的「路线位置」待确认项。 |
| docs/requirements/in-flight-input.md:21 | 不一致 | 用术语表列为避免说法的「激活」，正说法是「一轮工作」。 | 改为「一轮工作及已经发出的请求保留当时的输入版本」。 |
| docs/requirements/in-flight-input.md:1 | 不一致 | 文件开头没有状态行，缺确认时间、状态、依据、路线位置与总图位置，第 33 行的实现状态也没有路线位置。 | 补一行状态行，写明依据（D06 相关设计说明）、路线位置（阶段一至二已实现）与总图位置（第三节输入边界）。 |

### g13 需求记录：其余 22 份

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/requirements/browser-and-computer-use.md:3 | 失效引用 | 路线图已改为五阶段与十条道，文中指向的 Stage 3 与 3.2B、3.2D、3.9 在现行路线图里都不存在。 | 改写成「阶段二，道 05『动作与工具』中网络取回与 MCP 之后的『浏览器与截图』一项」。 |
| docs/requirements/browser-and-computer-use.md:37 | 不一致 | 以旧工作包号与旧 Stage 名作现行依据，没有与阶段一至阶段五对照。 | 改为「阶段二 道 05 的浏览器与截图一项内验收」。 |
| docs/requirements/browser-and-computer-use.md:61 | 不一致 | 旧 Stage 4 按对照表是现行阶段三，文件未写对照，读者会以为安排在阶段四。 | 直接写现行阶段名，或补「（旧 Stage 4＝阶段三）」。 |
| docs/requirements/context-compaction.md:1 | 不一致 | 标题后直接是引用块，没有状态行，缺状态、依据与路线位置。 | 标题下补一行状态行，写明状态、依据与路线位置。 |
| docs/requirements/context-compaction.md:32 | 不一致 | 「跨激活」是一轮工作条的禁用词。 | 改为「跨轮工作的恢复」。 |
| docs/requirements/delivery-archive.md:5 | 不一致 | 批次 E 是旧批次编号，文件没写它与阶段的对照，现在无法判断归属。 | 改写为所属阶段与该阶段的事项。 |
| docs/requirements/delivery-archive.md:14 | 不一致 | 正本九个状态词里没有 DONE，这是状态词改名或增设。 | 改为「不能接纳 QA 或进入接纳」，不引入 DONE。 |
| docs/requirements/delivery-archive.md:19 | 不一致 | 用批次字母与「第二阶段」作现行依据，没有与阶段一至阶段五对照。 | 统一写阶段名，删去批次字母。 |
| docs/requirements/department-providers.md:3 | 不一致 | 状态行只有「保留首版需求」，缺依据、路线位置与总图位置。 | 补依据、路线位置与总图位置（如第四节「模型」这道缝）。 |
| docs/requirements/department-providers.md:13 | 不一致 | 「第二阶段」是旧阶段名，现行叫阶段二并与 M 编号脱钩，文件没写对照。 | 写成「阶段二的 Provider 基础工作」。 |
| docs/requirements/department-providers.md:41 | 不一致 | 「模型目录」是禁用词，又与语义系统里「目录」这个术语撞名。 | 改为「Provider 与模型能力表」。 |
| docs/requirements/department-providers.md:43 | 不一致 | 「交接」是禁用词，部门之间说的是传递主机接纳的结构化结果。 | 改为「部门之间传递的结果」。 |
| docs/requirements/department-providers.md:47 | 不一致 | 「部门激活」是禁用词，指的是部门的一轮工作。 | 改为「每次部门的一轮工作」。 |
| docs/requirements/domain-completion.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/domain-completion.md:13 | 不一致 | 批次 F 是旧批次编号，没有与阶段对照，读者查不到 F 指什么。 | 改成对应阶段与工单编号。 |
| docs/requirements/effective-contract-changes.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/effective-contract-changes.md:17 | 不一致 | 同一句里用禁用词「激活」，又用旧批次字母 C、D、F 当验收依据。 | 改「一轮工作开始时绑定」；验收写阶段与工单编号。 |
| docs/requirements/engineering-plan.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/execution-limits.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/execution-limits.md:22 | 失效引用 | 把已归档的旧路线图当现行依据，并引用归档件的小节号。 | 改指现行路线图阶段三「长时间运行」一行，删掉 5.1 节。 |
| docs/requirements/execution-limits.md:28 | 不一致 | 「部门激活」是禁用词；「震荡」与路线图的用字「振荡」不同。 | 改「部门一轮工作的次数上限」「振荡」。 |
| docs/requirements/execution-limits.md:34 | 不一致 | 「模型目录」是禁用词。 | 改为「模型能力表」。 |
| docs/requirements/execution-limits.md:48 | 不一致 | 旧 Stage 4 当现行依据，没写与阶段三的对照，排的阶段与路线图不同。 | 改为「阶段三」。 |
| docs/requirements/existing-project-onboarding.md:3 | 失效引用 | 指向现行路线图里不存在的 Stage 与工作包号。 | 改为「阶段二，道 02『接入真实项目』一项」。 |
| docs/requirements/existing-project-onboarding.md:43 | 不一致 | 依赖用旧工作包号 3.1 表示，没有写现行阶段位置。 | 改为「阶段二的可靠恢复（#119）」。 |
| docs/requirements/git-change-management.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/git-change-management.md:9 | 不一致 | 「第二阶段」是旧阶段名，没有与现行阶段对照。 | 写明落在哪个阶段（如阶段四的拆开部署）。 |
| docs/requirements/git-change-management.md:27 | 不一致 | 「第一阶段」是旧阶段名，现行写「阶段一」并与 M 编号脱钩。 | 改为「阶段一」。 |
| docs/requirements/model-management.md:3 | 冲突 | 开头说已实施，末尾的实现状态写未实施，同一份文件前后相反。 | 核实 #83 的实际完成范围后统一，并写明 M1 对应的现行阶段。 |
| docs/requirements/model-management.md:25 | 不一致 | 这里的「目录」指模型能力表，与语义系统里「目录」这个术语撞名。 | 改为「在模型能力表中声明支持的档位」。 |
| docs/requirements/model-management.md:26 | 不一致 | 「待恢复」是禁用词，现行说法是「等待模型服务」。 | 改为「事项进入等待模型服务」。 |
| docs/requirements/network-and-mcp.md:3 | 失效引用 | Stage 3、3.2B、M3、3.2D 在现行路线图里都不存在。 | 改为「阶段二，道 05『网络取回与 MCP』一项」。 |
| docs/requirements/network-and-mcp.md:20 | 不一致 | M3 是旧里程碑编号，没有与阶段对照。 | 改为「阶段二的试用与验收」。 |
| docs/requirements/network-and-mcp.md:36 | 不一致 | 依赖与推迟都用旧工作包号与 M5，没写现行阶段位置。 | 改写成阶段二（网络与 MCP）与阶段四（更多服务）的对照。 |
| docs/requirements/product-prd.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/product-prd.md:22 | 不一致 | 批次 F 是旧批次编号，没有与阶段对照。 | 写阶段与工单编号。 |
| docs/requirements/project-initial-files.md:3 | 失效引用 | Stage 3、3.8、M2 在现行路线图里都不存在。 | 改为「阶段二，道 02『接入已有项目』一节的补充」。 |
| docs/requirements/provider-layer.md:3 | 失效引用 | 把已归档的 Stage 2.7 计划与报告当现行阶段依据。 | 改成现行阶段的说法，归档证据留作历史并标明已归档。 |
| docs/requirements/provider-layer.md:29 | 不一致 | 「交接」是禁用词。 | 改为「部门之间的传递」。 |
| docs/requirements/provider-layer.md:40 | 不一致 | 「额度」是禁用词。 | 改为「套餐用量不足」。 |
| docs/requirements/provider-layer.md:65 | 不一致 | 用 Stage 3 与 2.7 两个旧编号说明先后，没有与阶段对照。 | 改成「从阶段三前移到阶段一」这类阶段说法。 |
| docs/requirements/provider-retries.md:12 | 失效引用 | 把已归档的旧路线图当现行依据，并引用归档件的小节号。 | 指向现行路线图阶段三，删掉 5.1 节。 |
| docs/requirements/provider-retries.md:18 | 不一致 | 「部门激活」是禁用词。 | 改为「每个部门一轮工作的模型步数上限」。 |
| docs/requirements/provider-retries.md:30 | 不一致 | 旧 Stage 4 当现行依据，没写与阶段三的对照。 | 改为「阶段三」。 |
| docs/requirements/remote-execution.md:3 | 失效引用 | Stage 3 与 3.2C 在现行路线图里不存在。 | 改为「阶段二，道 05『远程执行代理』一项」。 |
| docs/requirements/remote-execution.md:25 | 不一致 | 旧工作包号 3.1 当现行依据，未写阶段对照。 | 改为「按阶段二的可靠恢复规则」。 |
| docs/requirements/remote-execution.md:75 | 不一致 | 依赖用旧工作包号表示，没有写现行阶段位置。 | 改为「阶段二的可靠恢复」。 |
| docs/requirements/request-observability.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/request-observability.md:20 | 不一致 | 「部门激活」是禁用词。 | 改为「部门的一轮工作」。 |
| docs/requirements/request-observability.md:44 | 失效引用 | 阶段关系指向已归档的实施计划，把归档件当现行依据。 | 改指现行路线图的阶段与事项，归档件只作历史。 |
| docs/requirements/skeleton-and-application.md:3 | 失效引用 | 路线位置引用归档路线图与归档的 Stage 3 计划，并继续用 M0、M2 编号。 | 改为现行路线图里的阶段一事项，删掉归档引用与 M 编号。 |
| docs/requirements/skeleton-and-application.md:44 | 不一致 | 现行路线图没有 M5 与 3.2D，这句话没法核对。 | 改成阶段二道 05 的网络与 MCP 一条、阶段四的服务扩展。 |
| docs/requirements/skeleton-and-application.md:54 | 不一致 | M0.5 是旧里程碑编号，没有与阶段对照（同文件 33 行同）。 | 写明这批工单属于哪个阶段的哪个事项。 |
| docs/requirements/startup-provider-reload.md:5 | 失效引用 | 纳入依据是已归档的 Stage 2.7 计划。 | 改为现行阶段与工单编号。 |
| docs/requirements/startup-provider-reload.md:59 | 不一致 | 旧 Stage 名与旧工作包号当现行依据，没有与阶段对照。 | 改为「阶段二的可靠恢复」。 |
| docs/requirements/startup-provider-reload.md:76 | 不一致 | 「待恢复」是禁用词。 | 改为「进入等待模型服务」。 |
| docs/requirements/startup-provider-reload.md:142 | 不一致 | 同一句里用 Stage 2.7 与 3.1 两个旧编号，没有现行阶段对照。 | 写成现行阶段与工单编号。 |
| docs/requirements/web-continuous-input.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/web-continuous-input.md:24 | 失效引用 | 用归档验收记录当现行依据，并用旧批次字母 D 指验收范围。 | 写明是哪一阶段的哪次验收与工单编号。 |
| docs/requirements/workspace-refactoring.md:1 | 不一致 | 没有状态行，缺状态、依据与路线位置。 | 标题下补状态行。 |
| docs/requirements/workspace-refactoring.md:17 | 不一致 | 用批次 E、F 作验收依据，没有与阶段对照。 | 改成阶段与工单编号。 |

### g14 根目录四份：CONTEXT、README、CLAUDE、AGENTS

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| CONTEXT.md:382 | 不一致 | 同一个概念在正本与术语表另一条都写「振荡」，此处写「震荡」，执行者按定义文件写收敛状态取值时会抄成两个不同的词。 | 把「震荡」改为「振荡」。 |
| CONTEXT.md:154 | 不一致 | 看门狗的落点用旧 Stage 编号写，读者拿它当现行依据时对不上路线图的阶段三，也违反本文件自己定的禁用写法。 | 改为「阶段三建设（看门狗的缝从未定到已定）」。 |
| CONTEXT.md:10 | 冲突 | 执行权挂在 run 上还是挂在事项上会做出不同的实现：前者随 run 结束释放且允许多个 run 并存，后者一个事项只有一份执行权。 | 改为「持有每个事项的执行权」。 |
| CONTEXT.md:189 | 含糊 | 发布时机这里写「试用里程碑」，薄片一条写薄片做完发版本、试用工单一条写薄片一张，执行者不知道按哪个粒度发版。 | 改为「每个薄片交给用户试用之前发布一次」。 |
| README.md:356 | 冲突 | 同一份 README 一处说单次上限是 32 次模型调用、一处说默认已放宽到 999999，使用者按 32 次估算用量或调参都会算错。 | 改为「计入单次激活的模型步数上限（默认 999999，可由调用方设小）」或删去 32 这个数。 |
| README.md:325 | 不一致 | 「激活」是术语表明列的禁用词，被用成运行状态的名称；同一份文件 356、358、362、366 行沿用，读者会以为系统里有一个叫「激活」的状态。 | 统一改为「下一次一轮工作生效」「当前一轮工作不受影响」，其余几处的「激活」同样改为「一轮工作」。 |
| README.md:205 | 冲突 | 一处说全量集成层由架构师手动按批运行、一处说由 CI 每次合并后自动运行，照着任一处做会得出「谁负责跑全量集成层」的不同结论。 | 改为「集成层只跑本次改动或新增的文件，全量集成层由 CI 在每次合并以后运行」。 |
| README.md:19 | 含糊 | 正文把对应关系指向「旧阶段名」，而那一条只映射 Stage 3 的里程碑与 Stage 4、5、6，没有说 Stage 1、Stage 2 是哪个阶段，读者对不上。 | 改写为「之前的几轮建设（…）」并在「旧阶段名」一条补上 Stage 1、Stage 2 的归属。 |
| README.md:217 | 不一致 | 两份文件给的两项固定检查的依赖安装命令不同（`npm ci` 与 `npm install`），README 那条还漏了 `client` 那一份依赖。 | 两份统一成同一组命令，并写明 `harness/tests/openapi` 与 `client` 都要安装依赖。 |

### g15 角色规则与基础规则

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/agents/shared-rules.md:8 | 不一致 | 术语表与总图把这个部件叫「控制核心」，这里改叫「控制层」，同一部件两个名字。 | 把「控制层」改为「控制核心」。 |
| docs/agents/shared-rules.md:8 | 不一致 | 「交接」是术语表避免的词，这里用它表示宣布完成。 | 改为「自作主张宣布完成」。 |
| docs/agents/shared-rules.md:9 | 不一致 | 术语表规定的词是「事件日志」，这里另造「事件存储库」。 | 改为「事件日志（Event Store）」。 |
| docs/agents/ticket-spec.md:44 | 失效引用 | AGENTS.md 没有叫「内核路径的测试覆盖」的小节，引用指向不存在的小节名。 | 改为引用 AGENTS.md:11「核心的内核模块，需要确保单元测试覆盖率」。 |
| docs/agents/ticket-spec.md:44 | 不一致 | 把「只由你批准」这一环说成到第二层自举时才立，与总图把写入口、裁决算作已经立住的结构不符。 | 改为说明这一环已随阶段一的写入口立缝守住，第二层自举时纳入自改流程。 |
| docs/foundation-rules.md:3 | 不一致 | 开头是累积式的更新段落，也没有「依据」「路线位置」「总图位置」。 | 收成一行状态（最近一次改动与依据）；本文件只由用户改，此处仅报告。 |
| docs/foundation-rules.md:21 | 失效引用 | 出处仍指向已归档、被取代的文档，把它当现行依据。 | 改指向总图或设计说明里同一规则的位置。 |
| docs/foundation-rules.md:23 | 失效引用 | AGENTS.md 没有这一小节名，出处指向不存在的段落。 | 改为「AGENTS.md 共同要求『核心的内核模块，需要确保单元测试覆盖率』」。 |
| docs/agents/autopilot-runtime.md:56 | 失效引用 | 引用的测试文件不存在，「入口与生成逐字节相同」的核对没有实现。 | 改为实际存在的核对文件，或先补这个测试再引用。 |
| docs/agents/autopilot-runtime.md:110 | 冲突 | 这份文件让本机集成层开 4 个进程，AGENTS.md 规定本地测试只用单进程，按哪处做结果不同。 | 删掉 `-n 4`，或写明这条命令属于哪一种例外。 |
| docs/agents/triage-labels.md:32 | 冲突 | 一处说只有派发者加这个标签，另一处说执行者自己也会加。 | 改为「由执行者在发出 `ARCHITECT:` 评论后加上，其余由派发者加上」。 |
| docs/agents/triage-labels.md:42 | 冲突 | 这里把设计说明有改动当成转给架构师的理由，AGENTS.md 与派发者规则说它不是交回理由。 | 从 `needs-architect` 的理由清单里删掉这一项。 |
| docs/agents/acceptance-evidence.md:12 | 冲突 | 合并前的「集成通过」被记在派发者名下，另两份把它交给执行者，派发者规则里没有这一步。 | 改为「执行者（合并之前，`touches-core` 工单）、架构师（试用之前）」。 |
| docs/agents/acceptance-evidence.md:41 | 不一致 | 用旧的 Stage 3 · M 编号指已关闭的里程碑，没换成阶段一、阶段二的说法。 | 按 CONTEXT.md:106-107 的对照换成阶段名，或删掉这句。 |

### g16 ADR、架构问题登记与决策记录

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/adr/0024-git-in-process-with-pygit2.md:3 | 不一致 | 该 ADR 第 1 行是标题，第 3 行直接进正文，全文没有状态行，缺状态、最近改动、依据、路线位置，读者无法判断它与哪一阶段、哪份依据对齐 | 在第 3 行前补一行状态行：状态：有效；最近一次改动：<日期与内容>；依据：<需求或 D 编号>；路线位置：<阶段几>。 |
| docs/adr/0024-git-in-process-with-pygit2.md:3 | 不一致 | 「激活」是术语表里明令避免的旧词，现行说法是「一轮工作」，同一份 ADR 第 3、17 行两处沿用旧词，与术语表不一致 | 两处改为「一轮工作」（「一次一轮工作收尾」「等待一次一轮工作收尾或完整循环」）。 |
| docs/adr/0019-project-stream-across-versions.md:11 | 冲突 | ADR 说用「已采纳成果」重启，术语表说用「项目的起点」，而没有采纳成果的项目起点是起始文件夹快照或空树，按哪一处做重启后的工作区不同 | 改为「用项目的起点重新开始」，与 CONTEXT.md 的排空条目一致。 |
| docs/architecture-issues.md:19 | 不一致 | 本文件自定已处理条目要移到 archive，CLAUDE.md 也写只留未处理条目，但文件里 16 条已带「处理：」行的条目（第 19、22、25、28、30、33、35、38、41、44、47、50、53、56、63 行等）都还留着，只剩 #1156、#1215 未处理 | 把带「处理：」行的条目移到 docs/archive/architecture-issues-<新日期>.md，本文件只留未处理的 #1156、#1215。 |
| docs/architecture-issues.md:32 | 不一致 | 登记正文用术语表避免的旧词「激活」描述一轮工作的步数重置，读者会把它误解成一个独立的概念 | 改为「每次一轮工作从零数」。 |
| docs/decision.md:1296 | 失效引用 | 链接指向的 docs/current-baseline.md 已不存在（Test-Path 为假），而这条落点是活链接，按它找依据会找不到文件 | 改为指向 docs/archive/current-baseline-2026-10-29.md，或删去这一项并写明基线已取消。 |
| docs/decision.md:1266 | 失效引用 | 相对路径多退了一层，链接打不开，按链接找不到技能说明文件 | 改为 ../.claude/skills/architect-loop/SKILL.md。 |

### g17 调研与试用

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/research/architecture-diagnosis-2026-10-19.md:7 | 失效引用 | 被引行号已不含五条判据，判据的正本在第 5 节。 | 改为「路线图第 5 节的五条判据」。 |
| docs/research/architecture-diagnosis-2026-10-19.md:124 | 失效引用 | 现行路线图没有第 6.1 节，该节号只存在于已归档的 archive/program-roadmap-2026-10-25.md。 | 改指第 2 节阶段表（第二层自举）或注明按归档版第 6.1 节。 |
| docs/research/architecture-diagnosis-2026-10-19.md:125 | 失效引用 | 现行路线图没有第 7 节。 | 改指第 5 节判据一「真实负载」或第 2 节对应阶段。 |
| docs/research/architecture-diagnosis-2026-10-19.md:189 | 失效引用 | 被引的 system-intent.md:129 现是「下列需求按任务书」标题、N-G1 已不再写「不劣于 OpenCode」；CLAUDE.md:46 是分布式锁例子，「高于」的句子在第 67 行。 | 更新为 system-intent.md 第 135 行与 CLAUDE.md 第 67 行，并按 N-G1 现行写法重述现象。 |
| docs/research/architecture-diagnosis-2026-10-19.md:144 | 不一致 | 用旧里程碑 M2、M4 当作现行依据，全文没有与阶段一至五对照。 | 改成对应阶段名，或在开头状态行给出 M 编号与阶段一至五的对照。 |
| docs/research/architecture-diagnosis-2026-10-19.md:3 | 不一致 | 状态句说提议未获确认，正文末尾记了用户当天已确认全部提议，两处说法相反。 | 状态句改为「第 9 节的提议已于 2026-10-20 由用户确认」。 |
| docs/research/architecture-diagnosis-2026-10-19.md:72 | 不一致 | 「激活」是术语表禁用的词，此处与同段「start-2 激活 7 次」等写法沿用了旧词。 | 改为「start-1 三个部门各一轮工作（产品 → 工程 → 质检）」。 |
| docs/research/game-world-as-projection.md:277 | 失效引用 | 第 5.3 节只在归档的 program-roadmap-2026-10-25.md 里存在。 | 改指第 2 节阶段五（第二层自举）或注明按归档版第 5.3 节。 |
| docs/research/game-world-as-projection.md:3 | 不一致 | 开头状态行只有日期与状态，缺「依据」与「总图位置」两项。 | 补「依据：D41 …」「总图位置：第六节拆开部署／第四节画面缝」。 |
| docs/research/README.md:9 | 不一致 | 索引的用途列用旧阶段名当现行位置，没有与阶段一至五对照。 | 改为「阶段一结束之前…」或写成「原 Stage 3 末（阶段一末）」。 |
| docs/research/complexity-and-mutation-testing.md:3 | 不一致 | 以旧阶段名 Stage 3 标示文件的现行有效期限，未与阶段一至五对照。 | 改为「阶段一结束之前」，或补一句与五个阶段的对照。 |
| docs/research/jev-decision-model.md:3 | 不一致 | 按术语表 Stage 5 是阶段四，而路线图把运维部门放在阶段三；同文第 80、81 行又写 Stage 4，指向前后不一。 | 改成「阶段三：运维部门；阶段四以后：元观察」并加旧阶段名对照。 |
| docs/research/experiment-protocol.md:5 | 失效引用 | 开头「依据」指向已归档文档；第 24、113、149 行同样指向 archive。 | 改引在用的需求与设计说明（如 system-intent.md、rules-and-parameters.md），归档件只在追溯时提。 |
| docs/research/experiment-protocol.md:61 | 不一致 | 用旧工作包编号 2.1 当作现行依赖点，没有与阶段一至五对照。 | 改为「阶段一的可信基线（薄片 S1a 至 S1d）之后」。 |
| docs/research/experiment-protocol.md:129 | 不一致 | 恢复引擎放在「## 8. 第三阶段选型与组织实验」，而路线图把可靠恢复放在阶段二。 | 把恢复引擎一行移到第二阶段一节，或注明它是阶段二遗留的收尾。 |
| docs/research/organization-runtime-evolution.md:5 | 失效引用 | 上位依据指向已归档的 stage-3-plan.md，「第四阶段计划」也没有出处。 | 改引 program-roadmap.md 第 2 节与相关设计说明，删掉无出处的「第四阶段计划」。 |
| docs/research/organization-runtime-evolution.md:104 | 不一致 | 全文用禁用的「额度」（另见第 110、114、115、117、347 行），与术语表用字不同。 | 统一改为「可用量／预留」等术语表允许的词。 |
| docs/research/organization-runtime-evolution.md:145 | 不一致 | 小节名与正文（第 151、155、164、349、401 行）用禁用的「交接」。 | 改为「部门间协议与责任接收」并同步正文用词。 |
| docs/research/organization-runtime-evolution.md:402 | 不一致 | 用旧工作包编号 3.0、3.1 充当接入时机（另见第 392、404 行），没有与阶段一至五对照。 | 改写为阶段二／阶段三的对应薄片名。 |
| docs/research/kernel-projection-reads-2026-10-24.md:5 | 不一致 | 用旧里程碑 M0 当现行依赖，且本文件没有给出与阶段一至五的对照。 | 改为「阶段一的工单 #558 至 #561」。 |
| docs/research/kernel-projection-reads-2026-10-24.md:11 | 不一致 | 12 条要补的清单在第 2 节，本节号指向的第 4 节讲的是另一件事。 | 改为「要补第 2 节列的几样」。 |
| docs/trial/skill-revision-plan.md:3 | 不一致 | 状态行仍写「实施方案待最终核对」，与任务集里记录的当天确认相反；状态行也没有「总图位置」。 | 状态改为「2026-10-29 用户已确认」，并补「总图位置」一项。 |
| docs/trial/skill-revision-plan.md:22 | 含糊 | 所指的 README 无法确定是哪一份，试用目录下没有 README.md。 | 写明具体文件，例如 .claude/skills/trial/SKILL.md 或仓库根 README.md。 |
| docs/trial/skill-revision-plan.md:63 | 不一致 | 这里「凭据交接」指读取凭据，用禁用词会让读者误以为有责任移交。 | 改为「凭据读取」。 |

### g18 原型变更记录与当前定稿

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/prototypes/CHANGELOG.md:20 | 失效引用 | 现行路线图没有第 6 节，这一节号来自已归档的旧路线图，按它查不到任何依据。 | 改为「远程执行属于阶段四（路线图第 2 节阶段四、第 3 节道 05）」之类的现行位置。 |
| docs/prototypes/CHANGELOG.md:18 | 不一致 | M0.5 是归档路线图的里程碑名，现行只有阶段一至阶段五，读者无法判断这条待办挂在哪个阶段的契约上。 | 写成「等阶段一（旧 M0.5）的装配契约……」或直接写阶段一薄片名。 |
| docs/prototypes/CHANGELOG.md:20 | 不一致 | 用旧工作包编号 3.2C 当现行依据，没有与阶段对照，看不出这段分界落在阶段三还是阶段四。 | 改成「与阶段三机房的设备画面、阶段四远程执行（旧 3.2C）的分界在哪」。 |
| docs/prototypes/CHANGELOG.md:28 | 不一致 | 新写的说明直接以 Stage 几当现行档位名，未注明它是旧名、对应阶段四。 | 写成「档位切到『Stage 5』（旧名，即阶段四）」。 |
| docs/prototypes/CHANGELOG.md:54 | 不一致 | 三个状态名与正本用字不同（工作中／回答询问／等待用户），属状态词改名。 | 按正本写「一轮工作中、询问中、等用户」，并注明这是 v12 当时界面的旧标签。 |
| docs/prototypes/CHANGELOG.md:88 | 不一致 | 「激活」是术语表禁用词，此处指的就是一轮工作。 | 改为「部门房间写这次一轮工作的已用量与上限」。 |
| docs/prototypes/v13/design.md:3 | 不一致 | 状态行缺「依据」「路线位置」「总图位置」，依据另起在第 7 行，读者看状态行判不出它细化总图哪一节。 | 状态行补「依据：…；路线位置：…；总图位置：第四节「画面」的缝、第一节「界面」方框」。 |
| docs/prototypes/v13/design.md:125 | 不一致 | 场景表的档位列直接用「Stage 5」，未与阶段四对照，读表的人不知这批场景对应哪个阶段。 | 档位列写「Stage 5（旧名，即阶段四）」，或改列名注明档位字样取自界面、括号给阶段。 |
| docs/prototypes/v13/design.md:148 | 不一致 | 把旧工作包编号（3.1／3.2C／3.4A）当现行档位依据，未与阶段对照。 | 括号注明各档对应阶段（如 3.2C 属阶段四远程执行），或改用阶段名。 |

### g19 评测记录

| 位置 | 类别 | 矛盾点 | 改法 |
| --- | --- | --- | --- |
| docs/evaluation/predictions-2026-10-20.md:3 | 不一致 | 全文用旧里程碑 M0／M2 作检验时机，没有与阶段一至阶段五对照。 | 把 M0／M2 换成对应的阶段名并注明原里程碑编号。 |
| docs/evaluation/baseline-omp-stage3.md:5 | 不一致 | 用已归档的 Stage 3 里程碑与 3.1／3.2B／3.8／M1-M4 等旧编号作现行基线口径，全文没有一处对照阶段一至五。 | 补一句 Stage 3 对应哪个阶段、哪条判据，并说明 3.x／M1-M4 编号只作历史标识。 |
| docs/evaluation/test-subtraction-2026-10-26.md:104 | 失效引用 | 引用路线图里不存在的阶段三第 3 项内容来当删除理由。 | 改为只说该能力来自工单 #348（迭代底座 B7），不称其为路线图阶段三第 3 项。 |
| docs/evaluation/test-subtraction-2026-10-26.md:277 | 失效引用 | 把守的判据写成路线图阶段二第 4 项，现行阶段二④与「离开期间的报告」无关。 | 改引真实出处（评测说明或判据编号），不挂阶段二④。 |
| docs/evaluation/test-subtraction-2026-10-26.md:694 | 不一致 | 采纳写回与三树合并被挂到阶段二第 2 项，实际对应第 4 项「改一处、看得见、能撤回」。 | 改引阶段二④。 |
| docs/evaluation/test-subtraction-2026-10-26.md:3 | 不一致 | 状态行有口径与总图位置，缺「依据」「路线位置」两项。 | 补「依据：测试分层设计说明第 13 节」与「路线位置：阶段对应的判据」。 |
| docs/evaluation/scenario-3-yudao.md:198 | 冲突 | 同一接口能力两处相反：一侧说没有放文件的命令，另一侧说用 initial_directory 带入了该文件（#324 的写法）。 | 按 #324 的写法改写本段起点说明：接口有起始文件夹参数。 |
| docs/evaluation/scenario-3-qwen38flash-2026-10-20/opencode.md:39 | 不一致 | 同一模型、同一代理下未上报的费用记成 0，与本组另一侧及本组口径相反。 | 费用改为未知，并记有效样本数为 0、未知样本数 3。 |
| docs/evaluation/scenario-3-yudao.md:196 | 不一致 | 节号从七跳到九，缺第八节，正文第 203 行说明未提供版本比较段即第八节被删而编号未改。 | 本节改为第八节（或补回第八节版本比较）。 |
| docs/evaluation/scenario-3-qwen38flash-2026-10-20/README.md:5 | 失效引用 | 起点说明在第九节，第七节是不计入结果的运行。 | 改为引第九节。 |


