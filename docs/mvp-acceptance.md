# 三部门循环 MVP 验收记录

## 原生循环重构

2026-09-06 根据用户确认，循环推进与上下文控制改由 Yudao 原生内核负责。OMP 仅保留代码级参考价值，旧 RPC 运行适配器、启动隔离覆盖文件和相关测试已删除。Provider 层只做一次模型请求，宿主工具执行、部门交接、每步上下文组装和停止判定由内核负责。

默认原生数据目录为 `.yudao/native-loop`，真实 smoke 默认使用 `.yudao/native-validation`。早期原生验收保存在 `.yudao/native-final-validation`；当前复验服务位于 [http://127.0.0.1:8771](http://127.0.0.1:8771)，数据目录 `.yudao/stage1-real-web-20260906-145135728`。旧数据目录和服务记录保留为历史证据，不迁移、不提供兼容读取，不作为最新原生架构验收结果。

新的输入验收口径包括：每步完整 developer 输入、原始任务、本部门历史视图、工具 schema 与工件摘要绑定；历史逐项对应同一任务内本部门收到的工作消息、模型输出与宿主工具结果，跨激活延续且不混入其它部门私有历史。自动压缩记录完整来源、连续覆盖范围、摘要原文与近期工具回合，原始事件不删除；压缩请求本身可容纳、可取消并计入同一个模型步骤限制。模型调用尝试与上下文准备分别记录；工程和质检的成功检查对应宿主执行、当前合同与最终代码快照。调用尝试不等于网络请求已送达，只有实际返回结果才作为已观察到的模型执行证据。

### A 批次实现与验证

2026-09-06 完整回归为 Python 187/187、JavaScript 26/26。覆盖原生模型/工具边界、同部门跨激活历史、压缩来源审计、本地 provider 请求捕获、取消与迟到结果、循环/步骤限制、主机检查及 Web。真实模型使用 `responses` adapter、`penguinapi.org / gpt-5.6-luna`，没有改用 fake，也没有自动重试。

| 场景 | 本轮证据 | 结论与限制 |
| --- | --- | --- |
| 原生直达循环 | `run_68698653c64b49a6` 为 `DONE`，7 次请求；实际输入、回执、部门隔离和 replay 通过 | 为 A 较早版本的成功证据，不替代最后一次重测 |
| 修复后的 Ask 接续 | `run_4246f1fae7a14568` 为 `DONE / released`，11 次请求、5 次激活 | 主机回执、实际输入、隔离及 replay 均 verified；同部门再次激活的新工作消息必须保留 |
| 真实压缩来源 | `run_3d97dce6adcf4687` 记录 6 次有效摘要，原始资料保留且来源审计通过，后因摘要超过输出限制停止 | 证明部分真实压缩与来源，不证明压缩后完整交付完成 |
| 浏览器创建与取消 | `run_c7e8ae7f92bf46fe` 在工程工具开始后取消，停止 seq24、最终 seq26，无迟到提交；1440/390 页面及模型输入可查看 | 首次脚本业务断言通过，但 favicon 404 使整体退出失败；修复后只读复测无 HTTP、console 或 page 错误且终态不变 |

真实报告位于 `.yudao/native-final-validation/native-second-attempt-report.json`、`compaction-first-attempt-report.json` 和 `compaction-smoke-report.json`。浏览器完整原始报告保留为 `.tmp/native-browser-acceptance.json`，favicon 修复后的只读报告为 `.tmp/native-readonly-after-favicon.json`，对应桌面和手机截图保留在 `.tmp/`。首次失败报告不覆盖为成功。

对已有真实摘要任务的只读浏览器复验见 `.tmp/native-compaction-browser-run_3d97dce6adcf4687.json`：1440/390 宽均可查看上下文、摘要正文和原始工具来源，无页面溢出、控制台错误或状态写入。此证据只证明来源展示，任务本身仍保留原来的失败结果。

以下最新失败保留全部事件与工件：`run_8f4767c51abb47b4` 到达 QA 后 provider 连接失败；`run_432c2fbefd5b4d14` 在首步连接失败；`run_29f006d4002549de` 读取资料后，摘要请求连接失败。它们均按 `FAILED / provider_error` 保存，不能记为真实验收通过。早期 Ask 失败 `run_9192f5f76d8b40af` 及对应 `ask-first-attempt-report.json` 也保留，后续成功不改写历史。

A 的代码和确定性验证已具备，真实压缩后继续到独立 QA 的完整链路仍需在 F 验收前补齐。本节不宣布第一阶段整体通过。下文旧运行 ID、测试数量、OMP 指纹及费用均属于旧实现历史。

### B PRD 与事前计划

2026-09-06 完整 Python 295 通过、7 项平台或权限跳过，前端 29 项通过。首次完整回归暴露旧候选脚本缺计划及压缩场景混用问题，按当前流程显式补计划、拆分摘要依据变化与不变场景后复验通过，原候选和历史断言保留。

同次产品接纳生成有效合同与 PRD，实际生效补充决定参与合同身份；计划与 PLAN 同源。无计划、范围外路径、无理由调整和旧合同提案被拒绝，旧响应不能绑定新合同。主机材料写入失败形成可重放的 `host_commit_error`，不提前接纳。摘要仅在相同合同和计划下复用，依据改变后从保留原史重建。

fake 浏览器任务 `run_9cf967a74bc4476b` 的 1440/390 视口可查看当前 PRD、计划、历史和精确原文，查询不改变事件序列，无页面错误或溢出。报告为 `.tmp/native-b-browser.json`，截图前缀 `.tmp/native-b-`，临时服务已关闭。该批没有新增真实 provider 成功证据。

### E 完整交付与重构工具

完整 Python 391 通过、7 项平台或权限跳过，前端 30 通过。检查副本、验证和封存使用同次采集的完整公开树字节；交付和 QA 接纳前复核现场，变化不放行，真实检查输出仍保留。删除与移动仅工程有权限，当前计划覆盖实际路径，移动两端均核验且不覆盖目标。硬链接、junction、私有目录、范围外、并发目标和失败回滚反例通过。

真实接纳的 fake 交付包含未声明二进制、隐藏文件与空目录，原工作区删除后仅从持久工件恢复并核对完整树和当时回执通过。Web 只读取已接纳交付的完整封存，拒绝跨 run、篡改、缺失及错误树身份。浏览器 `run_dbc221ffc67c4ab1` 在 1440/390 宽查看清单并实际下载 `[0,255,1,2]` 原始字节，源文件已删除，无写入请求、页面错误或溢出；报告 `.tmp/native-e-browser.json`，截图前缀 `.tmp/native-e-`，临时服务已关闭。

### C 通用专家协作

保留主工作阶段，以单个未结请求临时选择执行部门，复用原生循环，删除单向 Ask/React 专用路径。六个咨询方向及初版 PRD 前咨询均经真实 API 验证；意见、正式产品决定、动作结果与 QA 放行分别接纳。新需求逐项说明对当前有效决定的保留、整合或废止。

25 项核心集成及 59 项纯规则覆盖结果归属、权限、迟到回复、取消、超时和外来依据变化。同激活内 write/delete/move 后以 declined/needs_work 回复的六个反例均安排工程收尾，不能返回旧 QA；评估使用工具完成后的当前投影，接纳仍检查激活时依据。

输入审计 45 项通过并完成独立复验。审计从事件重建当时的合同、计划、请求和允许材料，核对实际固定输入、部门工作消息、完整工具 schema 及摘要适用依据。单独篡改绑定，或在真实新请求工件里加入其他部门私有文本并重新计算摘要，均不能取得 verified。正常 Demo 的 14 次请求全部 verified。

完整 Python 首轮为 495 通过、7 项平台或权限跳过，仅一个旧超时测试仍期待 provider_error；显式更新为 provider_timeout 后，该文件 6 项复验全部通过，保留之前用量、工具、部分消息和重放断言，共覆盖 496 个通过用例。前端 32 项全部通过；没有因测试失败改变业务要求或弱化断言。

浏览器报告 `.tmp/native-c-browser.json` 覆盖 1440/390 宽的等待、完成与取消请求，动作结果链接可打开正式需求，无页面错误、溢出或查询写入。完成任务为 `run_4c8d415d06364d6f`，等待任务为 `run_23dbcedcad3f4b76`，取消任务为 `run_08acf26e2027453f`；主 agent 已目检，临时 8767 服务关闭。首次脚本误用“研发”而页面用“工程”，修正脚本名称后复验通过。

D 持续输入/prompt 的后续完成情况见下节，F 完整真实场景单独验收。

### D 持续输入与 prompt

2026-09-06 最终完整 Python 581 通过、7 项平台或权限跳过，前端 38 通过。首轮 578 通过、3 失败均为旧测试的第二版 ProductSpec 缺少变更说明；逐例补充实际改变、保留、废止及理由后，原文件 17 项及最后完整回归通过，没有修改生产接纳规则或弱化原有断言。

原文按接收顺序直接拼接 UTF-8 字节，逐条工件和范围另存；`intend.md` 原子替换。接收、交给产品和有效需求处理分别记录，普通回复或单条决定不消耗新输入。产品及其咨询不会被已受领输入反复中断。当前工具结束后跳过剩余工具，输入、请求/工具开始、提案和终态共用控制顺序；release 先提交则新输入明确拒收，新输入先接收则旧 release 不能越过。文本 `/stop`、`/cancel` 原样保存后立即取消，按钮取消不生成文本。

prompt 只改当前任务，一次激活固定版本，下次目标部门激活采用最新。摘要同时核对合同、计划、输入和 prompt 版本；依据变化从完整原史重建。17 项新增审计反例覆盖工件正文、逐次版本和激活中更新，重新计算哈希也不能伪造 verified。使用真实 SDK 的本地 HTTP 请求捕获确认 schema 完整保留，未对外部模型成功作额外推断。

确定性浏览器任务 `run_272745e2a0f54951` 在旧 QA 模型期间由手机追加大写要求，三次专家咨询后形成 PRD r2、PLAN r2，最终独立 QA 为 `DONE / released`。工程 prompt r2 已实际采用；两条原文字节范围为 `[0,169)`、`[169,228)`，无新增分隔符。旧 QA 两个工具明确跳过。报告 `.tmp/native-d-browser.json` 与桌面/手机截图已由主 agent 目检，无页面错误或溢出。

独立验收 `.tmp/native-d-independent.json` 仅从两版持久封存恢复到新临时目录，实际执行原样和大写版本，并检查普通参数、以 - 开头、多参数及无参行为。14 次请求输入审计、真实主机检查、原文工件、prompt 采用和 replay 全部通过。文本取消任务 `run_7c21a54c43ef4e5f` 保留精确 `  /stop\n`，按钮取消任务 `run_602346f5645048eb` 仅一条原始输入。临时 8767 服务已关闭。

D 的实现和确定性验收完成；fake 产生的真实文件与主机检查不冒称真实模型完整验收。F 的真实 Web 方向调整和真实压缩后最终放行仍需单独取得成功证据。

### G 任务内 Git 变化管理

每个任务使用主机私有 bare Git 仓库，正式接纳事件引用不可变提交。原文、spec/有效合同/PRD、计划/PLAN、完整交付代码和公开 QA 进入版本历史；spec 与合同在同一数据库事务接纳。准备对象不等于接纳，不以可变分支同步决定生效。原文或需求提交保留上次正式代码，交付 Git 和完整封存使用同次公开树字节；空目录仍由封存清单保存。

独立审查补齐两个反例：活动取消遇到 Git 保存失败仍立即 abort，保存失败也不接纳迟到结果，界面保留原文并说明取消/保存结果；diff 同时核验当前与直接父提交的正式材料，合法 Git 对象中的伪造父内容也不能展示。核心 Git/交互 46 项、最后取消边界 15 项、Web 异常 7 项、前端全部 46 项通过。真实 Git 对象、跨 run、二进制、换行、junction、篡改、filters/hooks 均有定向验证。

完整回归首轮 663 通过、7 项平台或权限跳过、2 失败。失败分别为旧候选测试将 Git 展示字段与原事件整体比较、旧 smoke 成功夹具缺 Git 审计；仅更新两测试后相关文件 37 项通过，来源、导出、replay 与缺证据失败断言保留。最终在 `0533c90` 同一冻结生产及测试源码完成完整回归：683 项 Python 通过、7 项平台或权限跳过，耗时 1122.15 秒；前端 46 项通过。没有剩余失败。

确定性浏览器任务 `run_2abffdec82ab4f42` 在 QA 请求期间追加大写要求，经三次专家咨询、PRD/PLAN r2、工程 prompt r2 实际采用、两版交付及最终独立 QA，得到 9 个正式 Git 提交。初版需求为 `898f7ffbc57f5993a3afe4f3eca098cb6d0e4adb`，新需求为 `033d00d98be851895f4dccfa4a15a22a92735c9b`，最终 QA 为 `ed14dc30ab77febea4f1c67ad90db67d840a6418`。桌面 1440/手机 390 可查看真实 diff，无查询写入、页面错误或溢出，主 agent 已目检。

浏览器首份 `.tmp/native-g-browser.json` 在业务完成与 API 核验后误选合并显示的按钮，截图阶段超时，原报告保留；修正选择器后的 `.tmp/native-g-readonly-browser.json` 对原任务只读复验通过。独立报告 `.tmp/native-g-independent-run_2abffdec82ab4f42-passed.json` 使用 Git CLI 核验对象摘要、父链和原文/PRD/PLAN，并将两版 Git 代码与封存逐字节比较；仅从封存恢复到新目录执行普通、flag、额外和缺失参数行为，输入来源、检查回执、Git 审计及 replay 均通过。首次脚本引用类型错误的失败报告亦保留。

G 的确定性验收通过；真实模型能否在最终基线上完整调整方向、压缩并放行属于 F，不能用这些结果替代。

### F 最终基线真实验收的缺口

G 生产代码已提交推送 `0533c90`。两次最终真实运行使用相同的 G 生产源码，在提交前已冻结；Web 配置由主 agent 从当前 `provider.md` 注入进程环境，小窗配置由验收脚本读取同一文件。配置为 `https://penguinapi.org/v1`、`gpt-5.6-luna`、Responses，SDK 自动重试为 0、单次超时 120 秒。没有改 provider、切 fake 或把失败任务继续运行。

| 场景 | 原始记录 | 实际结果 |
| --- | --- | --- |
| G 前真实 Web | `.tmp/native-f-browser.json`，`run_8a31544b82084a1a` | 首次请求连接失败，未取得完整流程证据 |
| G 前真实小窗 | `.yudao/stage1-compaction-20260906/compaction-smoke-report.json`，`run_68d984647f754790` | 读取完整参考资料后，真实压缩请求连接失败，未产生该次摘要或最终 QA |
| G 最终真实 Web | `.tmp/native-f-browser-run_c9f1b6ca018f41ef.json`，`run_c9f1b6ca018f41ef` | 首次 work 调用约 6.675 秒后连接失败，无模型输出、spec、计划或交付 |
| G 最终真实小窗 | `.yudao/stage1-git-compaction-20260906/compaction-smoke-report.json`，`run_8af405b0b3da4b79` | 窗口 9000；首次调用返回 `list_files` 且工具成功，第二次 work 调用约 5.068 秒后连接失败，未进入压缩、spec、交付或 QA |

`.yudao/stage1-final-provider-audit-20260906.json` 对最后两 run 进行只读核验：原文分别为 493/766 个 UTF-8 字节，事件、工件、intend 文件和 Git 一致；模型输入来源 verified、各自 1 个正式 Git 版本经独立 CLI 核验、replay 一致。旧报告摘要前后相同，审计没有新增 provider 请求。Web 首次失败前事件未记录具体 provider/model 响应身份，报告只依据启动记录说明所配置模型，不冒充观察到了成功执行。

真实 Web 同任务方向调整至独立 QA、真实压缩后继续至独立 QA 仍未通过，当前受 provider 连接失败阻塞。此前连接小请求成功、TLS 握手成功、部分真实 Ask/摘要成功和确定性 G 验收均不替代这两项结果。没有降低完成条件或宣布第一阶段整体通过。

本机新服务在 8768、PID 1464，数据目录 `.yudao/stage1-git-validation`，复验结束后健康检查正常、空闲、无 worker error。重启旧 8766 的命令曾被自动审批拒绝，理由仅为 `blocked by policy`；保留旧服务并使用当时空闲的 8768，没有重试被拒操作或混用旧数据。

### F 按当前 provider.md 再次复验

用户再次要求“请使用provider.md中的模型进行测试，优先使用subagent”。本轮在 `079a632` 代码基线上，由两个子 agent 分别执行真实连接/压缩和 Web 测试，另一个子 agent 独立审计，主 agent 审查及记录结果。当前文件仍为 `https://penguinapi.org/v1`、`gpt-5.6-luna`、`openai-Responses`；密钥只用于认证，不写入报告。生产代码、模型配置及系统网络未修改，SDK 自动重试为 0，失败 run 未被恢复或改写。

| 对象 | 本轮证据 | 结论 |
| --- | --- | --- |
| 实际模型接入 | `.tmp/provider-connectivity-retest-20260906-145604.json`，流式请求约 4.167 秒收到 `response.completed`；压缩及 Web 正式事件记录实际返回模型 `gpt-5.6-luna` | 配置能够调用并收到真实响应，不能据此认为长流程连接稳定 |
| Web 首次 | `run_a471b359753c4ac9`，`.tmp/native-f-browser-run_a471b359753c4ac9.json` | 首次完整请求连接失败 |
| Web 完整方向调整 | `run_e6ccebbdeeae41d8`，`.tmp/native-f-browser-run_e6ccebbdeeae41d8.json` | 11 次激活、16 次模型请求；追加输入 v2 已接纳处理，PRD/PLAN 和交付均形成两版；最后 QA 请求连接失败，未完成 release |
| 真实小窗 | `run_5e5faeeb8d874e39`，`.yudao/stage1-provider-retest-20260906/compaction-smoke-report.json` | 窗口 9000，完整参考资料读取两次、3 次压缩成功，原文和摘要来源保留；第 7 次模型请求为压缩，连接失败，未进入正式产品接纳或最终 QA |
| 失败输入的有界诊断 | Web `.tmp/context-replay-run_e6ccebbdeeae41d8-seq173.json`；小窗 `.yudao/stage1-provider-retest-20260906/failed-request-replay-diagnostic.json` | 从失败请求工件取出实际输入分别单次重放，均收到完整响应；小窗返回模型 `gpt-5.6-luna`、3383 tokens。诊断结果没有写回原任务，不算任务恢复或 QA 通过 |

连接诊断捕获到 `APIConnectionError -> ConnectError -> EndOfStream -> SSLEOFError`。相同配置的普通 JSON、流式和应用 adapter 请求均取得过成功响应；无认证 HTTP 请求也在 TLS 层发生 EOF，且 `trust_env=true/false` 都出现该异常。证据支持连接存在间歇中断，尚不能确定故障位于远端网关还是本机网络路径，也没有证据将其归因于模型名称或压缩请求的确定性格式错误。

网络证据为 `.yudao/stage1-provider-retest-20260906/network-diagnostic.json`：IPv4 TLS 1.3 握手成功；IPv6 探针自身返回 `ValueError`，不把它当成已证实的 IPv6 网络故障。未修改 DNS、代理、证书或 provider 配置。

独立结果审计保存在 `.tmp/native-provider-result-audit-run_e6ccebbdeeae41d8-v3-r2.json` 和 `.tmp/native-provider-result-audit-run_5e5faeeb8d874e39-v3-r2.json`，由主 agent 收尾执行，未新增模型调用。Web 共 15 个完整模型响应、29 个输出项、8 个正式 Git 版本；小窗共 6 个完整响应、11 个输出项、1 个正式 Git 版本。两 run 的原文、真实响应模型、Git 对象与正式材料、上下文来源和 replay 均核验通过，审计前后事件不变。

Web 两版交付的 Git 文件与封存字节一致，最终交付从持久封存恢复后，普通/flag/额外/空格参数大写行为以及缺参 usage/退出 2 均通过；仍缺绑定最终合同与代码树的质量检查及 release。小窗的完整参考文本和 3 次摘要来源通过，未形成交付。审计初版因 Git 索引字段、提交元数据及 Windows 文本换行预期不匹配出现误判，修正脚本后另存 v3 报告，旧报告保留；`intend.md` 始终按原始字节核对。参考资料未预存初始物理字节摘要，仅对已记录完整文本和当前物理文件分别说明，未冒称验证不存在的依据。

当前服务在 8771、PID 19972，真实 Responses、空闲且无 worker error。所有真实调用和浏览器测试会话已结束。最后独立 QA 及压缩后完整交付仍是待补验项目，局部成功不改变原任务的 `FAILED / provider_error`。

### H 模型等待与重试验收

H 功能与设计、验收记录已提交推送 `7c720e1`。

用户新增 D17 后，原生内核新增最多 3 次尝试，默认退避 1 秒、2 秒；有效 Retry-After 最多 60 秒。单次默认等待 600 秒，每个实际尝试计入既有 32 次模型步骤上限，不增加独立逻辑请求总时间预算。Responses adapter 只执行单次请求与错误分类，SDK 自动重试为 0。失败部分输出和用量即时留存，失败步骤从有效历史、摘要和工具执行排除。

本地 SSE 实际延迟 65 秒，默认超时下 67.068 秒成功，仅 1 次请求、0 次重试。报告 `.tmp/native-provider-timeout-boundary-20260906T080150Z.json` 证明超过一分钟仍正常等待，不冒称外部 provider 的慢响应证据。

本轮真实调用继续严格使用当前 `provider.md`：`https://penguinapi.org/v1`、`gpt-5.6-luna`、Responses、单次 600 秒。密钥未写入报告，旧失败 run 未恢复。真实场景使用当时未提交的 H 源码，之后独立审查继续修正上下文重新装配、响应接纳顺序与审计；因此这些运行不能冒称最终提交源码的完整验收。

| 场景 | 证据 | 实际结果 |
| --- | --- | --- |
| 真实小窗 | `.yudao/stage1-retry-compaction-20260906T083307Z/compaction-smoke-report.json`，`run_8743dd750c0d43b1` | 24 次实际请求、19 次成功响应、13 次压缩、4 次自动重试；两次连接中断通过重试恢复，最后压缩请求连续 3 次连接失败。未形成 PRD、交付或 QA |
| 真实 Web 方向调整 | `.tmp/native-f-browser-run_9c12dcee13724a52.json`，`run_9c12dcee13724a52` | 14 次实际请求、3 次失败、2 次重试；追加原文 v2 已处理、PRD 形成两版，只有一版计划与交付。第二版需求后的工程请求连续 3 次连接失败，未形成最终 QA |

真实 Web 终态在桌面 1440 与手机 390 显示第 3/3 次尝试失败，没有残留等待重试。手机正文换行后无横向溢出，未见浏览器页面或控制台错误。只读截图为 `.tmp/native-f-retry-run_9c12dcee13724a52-desktop.png`、`.tmp/native-f-retry-run_9c12dcee13724a52-mobile-after-css.png`，主 agent 已目检。原始脚本因未达 DONE 的失败报告保留。

收尾独立复验 `test_responses.py`、`test_retry_input_boundaries.py`、`test_activation_accounting.py` 共 56 项通过；子 agent 的 engine、activation responses、compaction、context、responses、retry 六文件组合 86 项通过，退出码 0、耗时 187.19 秒。随后主 agent 独立复验新增审计与 Web retry 视图，共 13 项通过。各组有重复用例，不相加成完整回归总数。覆盖错误分类、真实 SDK 本地请求、压缩重试、工具错误反馈、取消和追加输入交错、32 次步骤限制及真实 provider/model 身份保留。本批代码实现与 F 完整真实验收分开记录。

修复输入审计中重试 `max_attempts` 检查的错误缩进，并补真实内核重试事件用例；新增 11 项与原 `test_smoke.py` 的 63 项全部通过。缺失关联、错误次数或失败后残余输出不能取得 verified。已准备但因取消或新输入未发出的请求单独计数，不直接判作缺失调用。两场真实数据只读重审另存 `.tmp/native-provider-result-audit-stage1-retry-compaction-20260906T083307Z-r2.json` 与 `.tmp/native-provider-result-audit-stage1-retry-web-20260906-165258176.json`：原文、实际模型、Git、replay、输入来源及尝试链 verified，小窗 13 次摘要来源亦通过，审计前后事件未改变。Web 只有旧交付，不能将其当作大写新要求的最终交付；小窗没有交付，缺少最终主机检查及 QA，报告整体仍为 `provider_failed / ok=false`。

确定性浏览器报告 `.tmp/native-h-retry-browser.json` 通过：等待期间在手机取消返回 200，任务 `run_1cecfed1276f440f` 停止；手机追加输入返回 201，任务 `run_e925b1b759944815` 处理 v2 后经独立 QA 到 DONE。桌面/手机等待与终态均无页面错误或溢出，DONE/PAUSED 正文不再保留旧等待状态。主 agent 目检代表截图，并独立运行 `node --test harness/tests/test_web_ui.js`，50/50 通过。

最终源码服务在 8774、PID 13076，数据目录 `.yudao/stage1-retry-final-20260906`，当前 provider.md 配置、单次 600 秒；健康检查正常、空闲且无 worker error。重启本轮旧 8773 服务的操作被自动审批拒绝，理由为 `blocked by policy`；原进程和真实证据保留，改用空闲端口和独立目录，未重试被拒操作。

### E 补验：最终放行时的封存完整性

独立反例在临时任务中损坏当前交付的持久 blob，`load_tree` 已能发现摘要不一致，但旧 QA 接纳仍进入 DONE。修复仅在 `SubmissionWriter` 的 release 分支复用现有 `load_tree`，核对当前交付、持久字节和本次受测完整树；在写入 QA_SUBMITTED、转移 QUALITY 到 DONE 及 RUN_DONE 前拒绝异常，不从 workspace/Git/其他任务补缺。

主 agent 独立执行新增封存测试与 `test_delivery_tree_engine.py`、`test_workspace_delivery.py`，首轮 80 项通过；随后新增的同 run 错误引用、交付摘要和接纳前快照变化 3 项独立复验通过。最终 `test_release_archive_integrity.py` 共 10 项通过，子 agent 另复验 3 项正常交付及既有失败路径通过。覆盖 manifest/blob 缺失和损坏、跨 run 引用、合法完成及原目录删除后仅从持久工件恢复。此确定性修复与 H 分开提交，不改写任何真实失败任务。

## 第一阶段完整目标

本阶段应完成 Web 持续输入、intend 原文、有效 PRD、工程事前计划、实施与自检、三部门双向咨询和职责内动作请求、合法需求变化及独立 QA。prompt 可展示和修改，历史压缩、完整交付封存、受控删除/移动及任务内 Git 变化共同验收。实际要求与 A-G 工作包见 [有效设计](stage-1-alignment.md) 和 [已确认清单](confirmed-requirements.md)。

Codex 主 agent 负责架构、独立审查、验收与分批推送，应用实现由 Codex 子 agent 按文件责任推进。跨 run 项目接续、长期记忆、知识图谱、异步恢复、部署维护与新增部门按后续阶段处理。原生内核已实现、局部验证通过与第一阶段整体完成分别记录。

## 旧实现历史证据

旧 OMP 实现的三部门循环 MVP 约定范围曾验收通过。真实执行基线为 `a45c02e`；此后的 `0d5a807` 只修正 smoke 报告中的适配器标签，未改变执行行为。

| 验收对象 | 当前证据 | 结果与边界 |
| --- | --- | --- |
| Provider 接入 | 主、备用接口曾通过 Responses 文本、流式和 function tool 探测；本次最终运行只用 blackrouter / gpt-5.6-terra | 无重试、无自动 fallback、无 fake |
| 真实三部门直达循环 | `run_fff19d8a08cc4485` 为 `DONE / released`；3 次激活、10 条完整模型消息、8 次工具执行 | 独立执行交付符合合同，工程与质检各有独立回执 |
| Ask → React | `run_d3c5228afea1452b` 为 `DONE / released`；5 次激活，产品 accept 后工程实现，质检放行 | 普通参数、含空格参数、以 - 开头参数及多参数行为符合实际产品决定 |
| 停止与预算 | 取消/提交串行化、迟到结果保护、目标 session 中止、实际用量校正与调用中预算暂停通过交错测试 | 浏览器真实取消后终态稳定、worker 释放；无继续执行功能 |
| 检查证据 | 两条成功 run 的 9 条宿主回执均对应唯一工具执行、当前合同和快照；QA 回执还绑定当前交付与激活 | 副本执行及异常清理通过；该机制不提供操作系统沙箱 |
| 上下文隔离 | 8 次实际启动逐份核对来源、manifest、宿主提示摘要，以及 runtime/参数/overlay 指纹 | 本地接入策略验证通过；不声称捕获生产请求正文，详见 `docs/omp-context-isolation.md` |
| Web 控制台 | 真实浏览器创建、SSE 观察、取消、按钮恢复、手机入口和回看板通过；390/1440 无溢出或页面错误 | 服务为 OMP adapter，健康检查可用且空闲 |
| 事件与回放 | 两条成功 run 的 26 条模型消息用量累计正确、64 个工件摘要正确、逐事件与批量 replay 一致 | 用量范围为可观测主对话；不等同于 provider 账户完整账单 |
| 经验候选 | 已接受 QA 返工和非取消失败生成可审计候选；8 项定向测试、来源按钮与导出/replay 通过；不新增 LLM 调用或注入上下文 | 已完成首版范围 |

代码基线 `a45c02e` 的完整 Python 测试为 135/135，显式启用发布版 OMP 的本地 stub 测试，无跳过；前端 JavaScript 为 23/23。报告标签修正后 smoke 定向测试为 26/26。最终真实运行使用新的 `.yudao/mvp-final-validation`，早期成功样例不替代这次验收。

## 旧实现真实证据

- 原始 smoke 报告：`.yudao/mvp-final-validation/smoke-report.md` 与 `.json`，进程退出 0。
- 独立核对：同目录 `independent-acceptance.md` 与 `.json`，进程退出 0；在无 provider key 的新进程执行交付，行为与快照均正确。
- happy 实际用量 26,515 tokens，上报 cost 0.0602196；Ask 为 54,768 tokens，上报 cost 0.1021196。逐激活汇总与预估抵扣一致，不重复计费。
- 真实浏览器任务 `run_96c7edf240c44ebc` 在工程阶段观察到 4 条模型消息及 5 次宿主执行后取消。停止事件 seq26 为 `FAILED / cancelled`，之后只有 `activation_finished`，没有迟到 spec、交付、QA 或状态迁移。
- 浏览器截图：`.tmp/final-real-web-desktop-cancelled.png`、`.tmp/final-real-web-mobile-cancelled.png`、`.tmp/final-real-web-tool-detail.png`；候选查看使用 `.tmp/lesson-desktop.png` 与 `.tmp/lesson-mobile.png`。
- 两条成功 run 没有缺陷，取消 run 也没有生成候选，这是预期行为。候选功能的证据来自确定性返工/失败用例与浏览器 fixture，不把成功 run 冒充候选场景。
- 两条配置密钥未出现在本次成功 run 的事件、工件、报告或工作区。原始运行数据保留本地，不随源码提交。

旧验收时本机控制台位于 `http://127.0.0.1:8765`，使用 OMP 主 provider。该运行不代表当前原生服务；原生启动配置见 README。

## 旧实现失败证据

以下运行保留在 `.yudao/provider-validation`，不得删除后用成功样例替代历史：

- `run_35c3f2c75d4e4292`：产品提交成功，工程激活因 OMP 超时停止。
- `run_16080318a257409a`：产品激活因 OMP 超时停止。
- `run_dcb381c71b10417b`：已发生 Ask；空的 spec 更新对象触发连续合同校验问题，后续未完成。Grok 已修正空更新处理并在新 run 重跑。

旧 smoke 报告中的 `context_isolated=True` 只检查了装配清单，不能证明 OMP 最终发送的系统提示已隔离。现报告拆成 `manifest_boundary`、`omp_launch_policy` 和 `omp_policy_capture`，核对每次实际启动的 runtime、参数、overlay 指纹和上下文绑定；缺少匹配记录时不得称隔离通过。该捕获证据是本地接入策略验证，不表示生产请求正文已被捕获。显式 system prompt 仍含 OMP environment/footer，不能宣称只有部门 manifest 的字节。

## 旧实现放行依据

1. 相关自动化测试通过，包括独立审查给出的反例。
2. 主 provider 完成直达与 Ask → React 场景，核对文件、两个部门的检查回执、spec 引用与事件重放。
3. 浏览器可启动真实任务并观察事件，取消之后不再接受迟到提交，界面恢复可用状态。
4. 预算和循环上限暂停并保留事实；错误和取消明确失败；自然语言完成声明不能绕过质检。
5. 文档如实区分已交付、已验证和后续阶段，运行命令可复现，凭据不进入文档或事件。
