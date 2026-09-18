# 第二阶段执行进度

> 2026-09-19 状态口径：本文是 Stage 2 Harness 基线的历史验收记录。阶段名称与新工作依赖以 [总体路线图](program-roadmap.md) 为准，当前版本验证范围见 [当前验收基线](current-baseline.md)。下文 CLOSED 只对应当时冻结版本与合同；历史进度表中的 OPEN/PARTIAL 不自动成为当前欠项。

更新日期：2026-09-15。用户指定以 [harness 基线实施计划](stage-2-implementation-plan.md) 为 Stage 2 完成合同。应用冻结 `041eaa1`。阶段状态：**CLOSED** ✅。

Stage 2 验收已完成，所有 6 个子阶段（2.1-2.6）均已通过验收：
- 十场真实验收：9 次 DONE、1 次计划取消；场景以 echo 变体为主，不外推复杂任务成功率
- Context/Trace View 可追溯失败
- Provider 配置界面可用（21s 完成配置）
- 桌面/手机界面流畅
- 核心功能不弱于 OMP（P0 清单为空）
- 回归测试通过（Python 958 passed, JS 29 passed）

同日更早的 H0–H5 收口计划和「学习轨道 2.1–2.4」不再作为本阶段门槛。学习轨道（局部控制、跨任务经验、四组比较）仍后置。

## 实施计划 2.1–2.6 收口

| 包 | 状态 | 证据 |
| --- | --- | --- |
| 2.1 F 真实验收 | CLOSED | 诊断 [stage-1-f-network-diagnostic.md](stage-1-f-network-diagnostic.md)；五场 `.yudao/stage1-final-validation/`，5/5 DONE，Web+小窗独立 replay |
| 2.2 Provider 配置界面 | CLOSED | 原型 `docs/prototypes/provider-config/`；API+页 `77a26df`；2.6 配置页连接测试成功 |
| 2.3 Context/Trace | CLOSED | `041eaa1`：`context-view.js` / `trace-view.js`；取消场次可见 `error_class=cancelled` |
| 2.4 OMP 对标 | CLOSED | [stage-2-omp-feature-comparison.md](stage-2-omp-feature-comparison.md) P0 空 |
| 2.5 Prompt | CLOSED | [stage-2-prompt-analysis.md](stage-2-prompt-analysis.md) 保留默认 |
| 2.6 日常可用性 | CLOSED | [stage-2-real-task-validation.md](stage-2-real-task-validation.md)：041eaa1 上 9/10 DONE；Python 958/1 skip；Node 29 |

2.6 十场与 2.1.3 五场数据目录隔离。luna 历史失败不改写。

## 历史进度表（H0–H5 / 学习轨道，保留）




2026-09-09 起 Web 外壳的视觉基线改为 [第三版原型](prototypes/2026-09-09/README.md)，第一版原型继续作为部门页内部与观测详情的基线；下文"原型约束"一节中"唯一视觉来源是冻结原型"记录的是 2026-09-08 之前的状态。

## 范围与顺序

本阶段先完成一个可正常运行的 Harness：用户从 Web 或 API 发起事项，三部门分别维护上下文，执行工具、交接、QA、交付、停止、重试、压缩、审计和 replay。证据驱动的控制、经验和综合比较后置到后续阶段。

| 顺序 | 交付 | 当前状态 | 下一项完成依据 |
| --- | --- | --- | --- |
| 1 | Provider 连接、统一目录与部门绑定 | back 目录 `.yudao/providers.stage2-a1-back.json`：agnes-3.0-flash / Responses / 声明 512K / 输出 65536。luna 目录与 1M 对照仍保留 | 已核对 back 有效窗口；下一缺口不在目录 |
| 2 | 第一阶段真实验收 | A1 关闭：`run_770ea827673545a5` 窗口 32000 DONE/release，压缩 2 次后继续 QA，审计 verified，echo hello。512K 对照 `run_8741e726d9dd4ba6` DONE/release，`compaction_count=0`。luna `run_d004266f212a4c2c` `provider_error` 保留。A2/A3 已关闭 | S2-1 已关。B3 已合入。下一包 A4 真实比较与 B4 三次变更 |
| 3 | OMP 系统审查 | 固定版本源码审查及独立复核完成，采用项已映射到 W1/W3 与 Prompt 批次 | 已有等价能力、不采用项及新增改进边界可追源；对应应用改进按计划验证 |
| 4 | Context/Trace View | 采集、结构化来源、取消查询已在主线；O3/O6 代码及局部回归已在 `20c7e42`，浏览器待验 | 与 W5/W7 同一冻结提交做浏览器联调 |
| 5 | 按原型完善 Web | B3 第三版外壳：项目列表、概览、流程/看板、D-H、项目 Prompt、项目 SSE、观测返回。独立复验 Node 23 通过；`test_web.py`+`test_projects_web.py` 57 通过。浏览器矩阵 `.yudao/s2-2-b3-20260914/` 五档×浅/深无横向溢出。64KB Raw 以 Node 断言为准，浏览器脚本未注入 64KB | B4 在此外壳上走三次真实变更 |
| 6 | Prompt 优化 | 真实 8 场完成。结论保留原版。候选任务 2 循环耗尽；两侧均无计划前写文件。证据 `.yudao/s2-3-a4-20260914/` | 作为后续证据改进阶段输入，不作为 Stage 2 门槛 |
| 7 | 核心 Harness 真实联调 | PARTIAL：已有真实 API 运行与 Fake 浏览器矩阵，尚缺一条浏览器/Provider/三部门/观测/replay 的同源端到端收口记录 | 在同一冻结上完成真实 Web 或 API 端到端记录，并核对上下文、工具、QA、交付、停止/重试、replay 与输入审计 |
| 2.1 | 可信观察、独立评价与固定基线 | L1–L3 工具已提交，作为后续阶段基础；不作为本阶段完成门槛 | 后续阶段另立合同 |
| 2.2 | 一项有界局部控制 | 后置 | 后续阶段 |
| 2.3 | 跨任务经验与长期记忆 | 后置 | 后续阶段 |
| 2.E | 原生项目演化 | B1+B3+B4：同一项目三次真实事项均采纳，Prompt 版本可追溯 | 2.E 本阶段内核与三次变更关闭 |
| 2.4 | 综合比较与阶段验收 | 后置 | 后续阶段 |

2.1–2.4 属于后续学习与改进阶段；本阶段只保留 2.1 已完成的观测工具，不启动控制、经验或四组比较。

## 原型约束

- 唯一视觉来源是 [冻结原型](prototypes/2026-09-06/README.md)，实际结构取 `department-workspace.html`，不将预览 iframe 包装和 Tweak 调试面板作为产品界面。
- 按总览、产品、工程、质检、观测的独立主视图实施；沿用原型导航、字体、色值、间距、消息区和检查区比例及移动端布局。
- 当前 `8775` 演示服务是上一批 Provider 基础使用的旧控制台，不计为 W2 或 D19 交付。
- W0 先补齐部门指导的处理边界和既有材料、历史、取消等入口约定。W1 与 W2 按各自依赖衔接，W3/W4 使用同一事实查询，不将页面拆成不同运行器。
- Provider 配置、凭据管理、连接测试与绑定选择仍为 W-P 待原型，不自行补出表单，也不将其标为完成。

## 当前验证与依赖

- `b9a965b` 完成 D17 重试规则对齐；`fced43e` 完成 D18 底层与只读身份接入。原生 Python 全文件分组回归为 769 通过、7 项平台跳过，前端 50 通过。最新多 Provider 本地 HTTP/SSE 10 项再次通过。
- 本轮现有服务仍为 `penguinapi.org / gpt-5.6-luna / Responses`。一条小型流式请求约 6.96 秒后连接失败；随后同服务模型列表的多个客户端认证请求返回 200，模型已注册。
- GET 成功只能说明对应请求成功，不能排除间歇网络/TLS 故障，不能在缺少实际传输时序时直接归因于某个端点。下一步使用安全传输时序定位失败阶段，不盲目关闭证书校验或修改全局网络。
- 当前服务模型列表未提供可核实的 `context_window` 与 `max_output_tokens`；第二套真实 Provider 配置也尚未取得。已向用户询问所选服务、模型及宿主配置位置或引用。能力未知时不编造生产目录，不拿本地模拟冒充真实跨 Provider 验收。
- 随后的三条小型 Responses POST 均成功：SDK 流式约 3.795 秒、SDK 非流式约 3.638 秒、HTTPX 流式约 2.157 秒，实际返回模型均为 `gpt-5.6-luna`。安全传输时序均完整经过 TCP、TLS、发送和接收；这证明存在成功路径，不抹去先前失败，也不能据此确定偶发中断的唯一根因。
- 已检查现有服务首页及其实际公开链接，没有取得模型容量说明；标准 `.yudao/providers.json` 也不存在。已准备不含密钥的本机草稿 `.yudao/providers.stage2.pending.json`，`null` 项为真实缺失信息，当前不可用作生产配置。草稿暂按产品/质检使用现有服务、工程使用第二套服务组织，实际绑定以补齐的配置为准。
- 用户随后明确继续使用 `provider.md` 中的模型与专用测试密钥。当前真实验收改为三部门显式绑定这套指定服务，不等待第二套服务；先完成这一配置下的完整真实流程。多连接路由的本地证据保留，不能将单服务真实调用改称真实跨 Provider 验收。
- 服务商标称最大能力仍未知。本次验收采用单独、明确登记的运行限制，并以实际请求核对其可用范围；这些数值不写成服务商标称上限，也不变成缺配置时的运行默认。正在核对已有同模型真实请求证据并准备有效验收目录，前述两服务草稿不直接用于执行。

## 本轮连续流程与连接处理

- 首轮使用 `.tmp/stage2-real-provider-catalog.json`，三部门显式绑定用户指定服务。验收限制为上下文 32000、最大输出 4096，小窗场景为 9000；它们是这批测试约束，非服务商标称容量。
- Web API 连续流程 `run_5bcac82ca5a14bd5` 完成初版合同、计划和交付，随后接收大写输出的新要求。10 次实际请求中有 3 次重试、5 次失败事件；最后产品部门连续三次失败，诊断均为 `connection.start_tls.failed`，没有最终 QA 放行。原始报告保留在 `.tmp/stage2-real-acceptance/20260906T134633Z/web-continuous/report.json`。
- 初版交付的独立封存恢复、固定 CLI 行为、Git、实际输入与重放核验通过。此结果不替代第二版要求的最终交付，也不把 HTTP API 运行称为完整浏览器点击验收。
- 只读网络核对发现当前默认路由经过 Clash 的 Meta Tunnel；`198.18.0.185` 是本机 fake-IP/TUN 路径的一部分，不能据此将 TLS 中断归因远端服务。TLS 1.2 POST 对照仍出现失败，显式代理对照也未改善，未修改系统代理、TLS 版本或证书校验。
- 此时选定的改进只在一次 run 执行范围复用官方 SDK/HTTPX 连接，每次请求和取消状态仍独立。后续本地验证与真实结果见下文，原有 600 秒、三次内核尝试及 SDK 零重试规则保留。
- 主分支保持 Provider 实施与真实验收边界。W1/W2 在 `.tmp/stage2-workspace`、`codex/stage2-workspace` 准备，独立审查后再合入；隔离候选及 mock 截图不计为正式 Web 交付。
- 真实验收脚本的输入版本计数、按有效合同选择交付检查、原始参考文件字节核对正在修正。检查范围须来自各场景预先固定的公开要求，不能额外添加未要求行为，也不能按交付序号猜测有效合同。

### 连接复用的本地验证

- `ResponsesExecutionScope` 使用标准库 `asyncio.Runner`，在一次 `run_until_stop` 内按 Provider、地址、超时及内存认证身份复用官方 SDK client。每个部门激活仍独立持有 adapter；HTTPX hook 按当前请求分派，退出同一事件循环时关闭全部 client。独立 `activate_once` 也有自动释放的执行范围。
- 完成事件与 HTTP 响应体结束是不同边界。完整有效完成事件结束请求等待计时，随后最多用 100 毫秒消费 SDK iterator，以便正常 EOF 后归还连接。尾部不结束则关闭该连接；尾部不会产生第二次模型尝试或执行工具，用户取消仍优先。100 毫秒是应用资源收尾的实现选择，不是服务商规则或 SDK 默认。
- 当前安装版本为 OpenAI Python 2.54.0、HTTPX 0.28.1、HTTPCore 1.0.9。核对了[官方 SDK 流式及资源管理文档](https://developers.openai.com/api/reference/python#streaming-responses)和安装版本源码，未升级依赖。当前 SDK 遇 `[DONE]` 会自行结束迭代并关闭响应；对应对照及时成功，但没有复用连接，这一限制如实保留，不自制协议解析器。
- 主代理独立执行 Responses、目录、部门绑定、重试内核、输入边界及激活六个测试文件：114 项通过，83.00 秒，报告 `.tmp/stage2-connection-scope-tests.xml`。随后发现并修正近截止完成事件被连接收尾误判超时的边界；修正后独立执行 14 项超时、取消、收尾和复用检查，全部通过，6.26 秒，报告 `.tmp/stage2-connection-scope-boundaries.xml`。
- 本地 HTTP/1.1 验证覆盖同一连接跨部门激活、不同 Provider 和同址不同凭据隔离、20 毫秒分段 EOF、坏连接后的新连接、保持流打开和取消。真实服务的复用效果及完整 Web/小窗任务仍需独立报告，未由本地结果推定。

### 2026-09-07 真实运行与独立回归

| 证据 | 结果 | 结论范围 |
| --- | --- | --- |
| `provider-scope-real-20260906-232045.json` | 三次请求均成功，TCP/TLS 建立次数为 1/0/0 | 指定真实服务支持当前 scope 的连接复用；耗时分别约 60.429、11.840、60.389 秒 |
| `provider-scope-real-20260906-232144.json` | 首次成功，后两次 HTTP 429，后两次未重新建立 TCP/TLS | 复用有效，但没有消除服务限流；429 不算成功 |
| `run_971c160eb2494a42` | 浏览器创建后自然运行至 DONE/release，形成初版交付与独立 QA | 基础真实交付成功；追加要求的点击恰遇旧 UI 切入新建模式，另建的 `run_13aa9ef4fc154d5b` 已取消；本场不算连续输入通过 |
| `run_8b6983a76419465e` | 浏览器在同一 run 提交 v2，原文和字节范围、两版合同及计划、Git 和 replay 可核对；无交付 | 测试脚本在首次计划激活结束后等待浏览器输入，已明确登记该协调等待；最终 seq120 为不可重试 `stream_error`，不是 TLS 失败。seq8/13 的 TLS 失败已通过内核重试恢复 |
| `run_3e5f4fadebff4782` | 9 次产品压缩，原始参考字节保持，产品完整读取 3 次；工程尚未读取，无交付或 QA | 最终 seq103 为不可重试 `stream_error`；输入来源、Git 和 replay 通过不替代完整小窗验收 |

上述报告分别位于 `.tmp/stage2-real-acceptance/20260906T154331Z/`、`.tmp/stage2-real-acceptance-browser2/20260906T155334Z/` 和 `.tmp/stage2-real-acceptance-compaction/20260906T160712Z/`。既有失败保留，当前正对一份已保存的失败请求做一次只采集、不执行工具的 SDK 诊断重放，以获得明确的流错误原因。

连接实现提交 `2930ba1` 后，测试确定性修正单独提交 `c85d78b` 并复验通过。隔离分支的 `ad08784`/`5729856` 为 W2，`5c6ffb1` 为 W1，`0473b01` 整合主分支连接复用，`0e1616d` 保存 W3 的结构化 Context parts。

主代理在固定 `5c6ffb1` 的独立验证工作树运行所有 Python 测试文件：779 通过、3 失败、7 平台跳过。3 项失败均为 `test_web.py` 的旧 HTML 或旧 Node 用例名称断言，实际 Node 20 项通过；这些断言正在按新界面保留业务验证后更新。报告为 `.tmp/stage2-w1-full-1.xml` 至 `stage2-w1-full-4.xml`。随后固定 `0e1616d` 独立运行完整 Context 查询和 Responses 两个文件，72 项通过、33.68 秒，报告 `.tmp/stage2-w3-scope-review.xml`。尚未将隔离候选或不完整真实场景标为阶段验收通过。

使用固定 `0e1616d` 的 API 持续输入与小窗两场记录在 `.tmp/stage2-observed-real-acceptance/20260906T162558Z/`。Web `run_70201435045a4129` 的 seq182 和小窗 `run_1368d26f9c0d48c6` 的 seq66 均有实际 SDK 解码事件：`code=server_is_overloaded`，消息为 `Our servers are currently overloaded. Please try again later.`。原分类遗漏此码，错误地直接停止。这两场仍未通过；之前没有原文的其他 `stream_error` 不据此回填原因。

已将该明确临时错误加入分类，并对顶层 SDK error 事件及 nested error 引发的 `APIError` 保持一致。三次内核尝试、既有退避及 SDK 零重试不变，未知错误不按消息猜测。子代理四文件 98 项通过；主代理独立 8 项过载、已知/未知错误和上下文边界检查通过，7.22 秒，报告 `.tmp/stage2-overload-classification.xml`。

同批 Web 的 11 次激活中有 9 次提案拒收：8 次计划合同标识不匹配、1 次不合法协作（含两个字段错误）。独立读取原始工具参数确认前两次把有效合同哈希漏抄了 `ad` 两个字符，后续又重复提交错误标识。该事实不等于选择了旧合同；下一项按 D05/D15 将计划的版本绑定职责与模型提交内容分开，避免让模型机械抄写系统标识，同时保留旧请求不得重新绑定新合同的控制检查。

固定 `0e1616d` 的 Context、smoke、重试审计和压缩回归另有 93 项独立通过，538.94 秒，报告 `.tmp/stage2-w3-context-audit.xml`。已验证的候选提交已推送到 `origin/codex/stage2-workspace`，尚未合入主分支。

## 记录规则

实现由子代理按模块负责，主代理负责架构、任务边界与独立验收。工作包形成可核验结果后分别提交和推送；新发现、首次失败、修正后验证及真实服务结果分别记录。按新定义，下一步以 H0–H5 收口三部门 Harness；2.2–2.4 不再阻塞 Stage 2，另立后续证据改进阶段。

P0 已冻结 `239c3b1`。隔离分支 `origin/codex/stage2-workspace` 不再整支合入：主线已是 W1/W2/W3/W4/W6 的后续版本。P2 只修当前 HEAD 仍开放的 O3/O6、U1-U5、G1-G3；修完后才做 W5/W7 联调与真实验收。隔离候选不计为阶段完成。
