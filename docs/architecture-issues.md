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
