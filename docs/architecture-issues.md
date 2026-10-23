# 架构执行问题记录 (Architecture Execution Issues)

本文档记录智能体在执行计划与工单实现过程中遇到的架构设计问题、规范冲突、未覆盖边界及阻塞事项。

## 记录规则
1. 严禁在代码中私自编写违背架构原则的临时兼容层或绕过逻辑。
2. 发现架构冲突、设计缺漏或规范矛盾时，必须在此如实登记。
3. 登记条目必须包含工单上下文、具体问题描述、受阻范围与处置建议。

## 记录格式规范
`模型 ID / 时间（到分钟） / 工单编号或任务 / 遇到的架构问题与冲突 / 影响与建议处置方案`

---

已处理的条目归档在 [docs/archive/architecture-issues-2026-09-10.md](archive/architecture-issues-2026-09-10.md)（2026-09-26 至 2026-10-11）与 [docs/archive/architecture-issues-2026-10-19.md](archive/architecture-issues-2026-10-19.md)（2026-10-01 至 2026-10-17）。
9router/ag/gemini-3.8-flash-high / 2026-10-21 03:35 / 工单 #633 / harness/tests/test_department_providers.py 与 harness/tests/test_smoke_guidance_audit.py 借用协作请求改用询问后，因 harness/smoke.py:891 assembly.department_history(before, event.department) 缺少 session_id=event.session_id 参数，导致分支内部的输入未能重建进历史，_model_input_audit 报错 input history differs from this department's recorded outputs。工单只改清单限制在 11 个测试文件，无法修改 harness/smoke.py。 / 建议将 harness/smoke.py 加入「只改」清单（行 891 补齐 session_id=event.session_id），或由架构师处理后继续。
处理：属实，是 #624 遗漏的实现，不改设计；#633 的「只改」加入 harness/smoke.py，修正第 891 行（claude-架构师 2026-10-21）

solo-minimax-M3.1-Flash / 2026-10-23 00:38 / 工单 #753 / 测试分层设计说明第 2.2 节按层给测试定时限（集成层 300 秒），集成层又用 `-n 4` 运行（第 4.2 节）。Windows 上 pytest-timeout 没有 SIGALRM，用线程方式，超时结束的是整个进程，也就是结束了一个 worker：xdist 报「node down」与「worker crashed」，堆栈跟着丢掉，看到的是崩溃而不是一条失败。发布构建那条用例的耗时正好在 300 秒上下（CI 上两次实测都在 297 秒附近被杀），因此偶发崩溃 / 已在第 2.2 节写明：工作量超过本层上限的文件单独定时限（根 conftest.py 的 FILE_TIMEOUTS），并由测试自己写子进程时限，超时先由它接手，worker 不消失
处理：已在 docs/design/test-pyramid.md 第 2.2 节写明，由 #753 实现（solo-minimax-M3.1-Flash 2026-10-23）

solo-minimax-M3.1-Flash / 2026-10-23 00:38 / 工单 #753 / 工单 #704（合并为 #760）给发布脚本加了一步「把这一份页面文件对应的接口版本写进 harness/release_assets/api-version.json」，同一张工单里发布脚本的核对仍然要求 wheel 内的 harness/release_assets/ 与页面构建输出逐个相同，接口版本记录因此被当成页面构建输出以外的文件，发布脚本每一次都失败（自 7473c01e 起 main 的集成层每次推送都红，7 个 ERROR 加一次 worker 崩溃）。设计说明第 6.1 节的一次发布内容表与第 6.3 节第 4 步都没有写这个文件，#704 也没有改这两处 / 已在第 5.1、6.1、6.3 节写明它是什么、它不参与页面文件的比对；发布脚本与核对它的两处测试按同一条规则改：接口版本记录单独核对读不读得出版本，别的一律拒绝
处理：已在 docs/design/web-interface-and-release.md 第 5.1、6.1、6.3 节写明，由 #753 实现（solo-minimax-M3.1-Flash 2026-10-23）

solo-minimax-M3.1-Flash / 2026-10-23 09:40 / 工单 #747 / 恢复观察状态按结束的方式分开以后（完成、暂停、取消、停止四种），原型 v9 与 v10 的恢复页与它的示例数据仍用旧的状态取值：`docs/prototypes/v10/js/ui/views/recovery.js` 与 v9 的同名文件里的 `STATES`／`STATE_LABEL`／`STATE_KIND` 写着运行中、中断、待核实、待恢复、已终止（`terminated` 画成 `cancelled`），示例数据里 `runs[...].recovery.state` 写的也是 `terminated`；客户端与服务端已经用新的七种状态（工单 #747），原型是界面对照与录制的基准（ADR-0021），于是原型的这一页与客户端不一致。改它要动两版的恢复页脚本、两版的合同处理器与六份示例数据，共十四个文件，超过运行配置第 7 节「只改」清单手写文件 15 个的上限（本工单还要改服务端、客户端与设计说明） / 已在本工单里把设计说明（`docs/prototypes/v8/design.md` 第 7.2 节与第 14 节、`docs/prototypes/v8/BUILD.md`）与客户端、服务端改到新口径；原型脚本与示例数据单独一张工单改，改的时候示例数据里 `terminated` 按真实情形分开写（完成的写 `completed`，取消的写 `cancelled`），并删掉早已不存在的「待核实」

solo-minimax-M3.1-Flash / 2026-10-23 13:39 / 工单 #709 / 写回命令只把「项目找不到」「项目已归档」「没有可写回的对象」三种情况变成中文的拒绝（工单 #661 已经为第三种做过处理），写回目标不可用的三种情况没有接住：`harness/writeback.py` 在远端仓库路径不存在时抛 `FileNotFoundError`、那个路径不是 git 仓库时抛 `pygit2.GitError`、目标分支不存在时抛 `ValueError`，`harness/app/project_and_work_item_commands.py` 的 `_execute_writeback` 只接住前两种项目状态，这三种一路冒到接口层变成 500 内部错误，页面上什么也没发生。采纳以后自动发起的写回（`harness/projects.py` 的 `_trigger_writeback_if_enabled`）走的是同一条路，目标不可用时异常还会从结算里冒出来，让这一次采纳所在的运行任务报错 / 已在 `harness/writeback.py` 增加 `WritebackTargetUnavailable`（带着是哪一种与目标是什么），命令层按 `not_allowed` 给出中文说明；自动发起的那一次接住它，不因此让采纳失败（页面上这一次采纳仍是「还没有写回」，用户改好设置以后按「写回成果」重新发起，那时给出同样的中文说明）；`harness/tests/test_issue_709.py` 覆盖目标分支不存在、目标仓库不存在与自动写回三种
处理：已在 #709 实现（solo-minimax-M3.1-Flash 2026-10-23）

solo-minimax-M3.1-Flash / 2026-10-23 13:39 / 工单 #709 / 源目录登记的保存是整份替换：`harness/projects.py` 的 `configure_source_directory` 把没有给出的字段一律写成缺省值，而客户端的源目录表单只提交名称、路径与基准版本，用户在页面上改一次路径就把写回设置（是否打开、远端、目标分支）与写回检查的命令清空了。写回检查的命令只有服务端能填，界面上没有入口 / 表单补上写回的三项设置，保存时把写回检查的命令与凭据引用按原来的值写回；写回检查的命令的界面入口另开工单
处理：已在 #709 实现（solo-minimax-M3.1-Flash 2026-10-23）；写回检查命令的界面入口另开工单

solo-minimax-M3.1-Flash / 2026-10-23 13:39 / 工单 #709 / 写回的结果没有查询可以读：`project.overview`、`project.flow` 与 `project.settings` 都不返回写回记录，项目投影里的写回记录只进了控制核心，界面拿不到。因此页面上既看不出成果有没有回到仓库，刷新以后连刚才的结果也留不住 / 新增查询 `project.writeback`（写回记录：状态、停止原因、推送的分支、目标分支、合并请求、冲突的文件、发生的时间），项目设置页与概览页都按它显示；接口快照与客户端类型按合同重新生成
处理：已在 #709 实现（solo-minimax-M3.1-Flash 2026-10-23）

solo-minimax-M3.1-Flash / 2026-10-23 13:39 / 工单 #709 / 接入已有项目设计说明第 5 节写「写回的结果写成事件，列在事项详情里」，界面上没有事项详情这个位置（事项的内容在部门工作间里），写回的结果因此没有落点 / 写回的结果改为列在项目设置页的「成果写回」一节里，概览页的「当前成果」给出这一次采纳有没有写回；设计说明按此改写，与代码一致
处理：已在 #709 改写 docs/design/existing-project-onboarding.md 第 5 节（solo-minimax-M3.1-Flash 2026-10-23）

solo-minimax-M3.1-Flash / 2026-10-23 22:40 / 工单 #557 / 同时运行以后，质检的「预测性探索」这一轮不保证发生：质检关注「PRD 被接纳」，PRD 被接纳以后质检开始一轮工作，这一轮开始时还没有交付就是预测性探索（提交的结论被拒绝），有交付就是核验。工程与质检同时起跑，工程的一轮（写入、检查、提交交付）比质检的一轮（起草测试用例）长，工程完全可能先交付；质检准备这一轮的时刻因此落在交付到达以后，这一轮就成了核验，预测性探索没有发生，设计说明第 3.1 节写的「质检在看到交付之前按 PRD 写出测试用例，判断来自要求、不受实现的影响」这个好处拿不到。写事务的版本冲突与重排也会改变两个部门的先后 / 设计说明第 3.1 节已经写明「PRD 被接纳以后、交付到达之前，质检的一轮工作是预测性探索」，但没有写「PRD 被接纳以后这一轮一定是预测性探索」。两个可选做法由架构师定：(1) 质检在 PRD 被接纳以后的那一轮固定是预测性探索（这一轮开始时即使已经有交付也不核验，交付到达以后另起一轮核验）；(2) 保持现在这样，在设计说明里写明预测性探索有可能被跳过，并说明跳过的场合。#557 里先把现在的行为定下来：用例按当前有没有交付决定做什么（`harness/tests/helpers.py` 的 `quality_turns`），与同时运行无关的用例逐个部门驱动（`activate_once`），结果不再取决于会话的先后
处理：待架构师决定（solo-minimax-M3.1-Flash 2026-10-23 22:40）

solo-minimax-M3.1-Flash / 2026-10-23 21:40 / 工单 #557 / 同时运行的会话里，一个会话修订了 PRD，另一个会话的询问分支依据过时：分支还没开始工作就被拒绝，这次询问记成「没能回答」。设计说明第 5 节要求的是「PRD 有了新版本时，正在工作的部门与在询问链上等待的部门在各自的下一步收到一条通知，写明新版本与改动，然后接着工作」，第 11 节的对照表也写着「合同、计划、请求、输入或指导一变化，激活就结束」要改成「送达通知，部门接着工作」。这条规则由工单 #558（#520 的子工单）实现，#558 被 #557 阻塞，因此 #557 里只能是现在这样：依据在分支工作期间变了的分支被拒绝 / 已在 #557 里把现在的行为定下来：分支的依据变了就写明是哪一种变化（PRD 被另一个会话修订、新的用户输入、新的指导）作为「没能回答」的原因，提问方拿到的原因说明白发生了什么（设计说明第 4.5 节）；`harness/tests/test_concurrent_departments.py` 的 `test_an_ask_branch_whose_basis_changed_cannot_answer_and_the_asker_continues` 断言这个真实行为（PRD 修订以后进行中的分支没能回答、原因写明是 PRD 被修订、提问方接着工作）。PRD 新版本作为通知送达进行中的会话、检查工作区按会话保留由 #558 实现
