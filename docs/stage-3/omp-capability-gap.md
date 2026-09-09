# OMP 能力差距清单（按源码逐项核对）

日期：2026-09-09  
状态：3.0 准备包，未实施  
OMP 底本：`fdfeef1f78`（`C:\project\codes\oh-my-pi`，`git log --oneline -1`：`fdfeef1f78 test(tui): isolated terminal color environment`）  
旧审查底本：`e3106be`（`docs/research/omp-stage2-system-review.md`）。本机没有该提交；本文不以旧审查行号为准，全部按 `fdfeef1f78` 重核。  
Yudao 基线：当前 HEAD `735e120`（分支 `harness_1`）。  
上位依据：[第三阶段计划](../stage-3-plan.md) 第 3 节对照表、第 5 节 3.0；[S4-A 采用映射](../s4a-omp-adoption-evidence-2026-09-08.md) 未采用归档。

差距类型只取：`采用` / `Yudao 已有等价` / `不采用` / `待决`。  
`不采用` 沿用 S4-A 与计划第 3 / 7 节：OAuth 运行时、自动发现、适配器内重试、key 轮换、`previous_response_id`、远端压缩回退、Snapcompact、OTEL 作为领域事实、并行工具批次/steering/IRC 的原样照搬、computer-use、`xd://` 设备目录、宽松参数校验。

---

## 0. 底本差异（相对 `e3106be`）

旧审查写于 2026-09-06，OMP 固定在 `e3106be`，本机无该对象，无法逐文件 diff。`fdfeef1f78` 上能直接看到、且旧文未覆盖或已明显加厚的部分：

- 技能发现拆成多 provider（`discovery/builtin.ts`、`claude.ts`、`agents.ts`、`github.ts`、`agent-plugins.ts`），Agent Plugin 的 frontmatter 闭集校验（`discovery/agent-plugin-format.ts`）。
- 压缩方法顺序含 `remote` / `snapcompact` / `handoff` / `shake` / `soft`（`session/compaction-methods.ts`）。
- 中断后续行：`session/turn-recovery.ts` 用 `Agent.continue()` 重放未完成工具批次；子 Agent 有 `task/persisted-revive.ts`。
- 思考等级独立类型：`packages/agent/src/thinking.ts` 的 `ThinkingLevel`，映射到 catalog 的 `Effort` 与各协议 wire 字段。
- 扩展 hook 事件表比旧审查列得更全（见第 7 节）。
- 包集合含 `metaharness`、`mnemopi`、`collab-web`、`wire`（第 12 节）。旧审查未把这些当作 Stage 2 借鉴项。

`packages/` 在本底本下可见：`agent`、`ai`、`catalog`、`coding-agent`、`collab-web`、`metaharness`、`mnemopi`、`natives`、`snapcompact`、`stats`、`tui`、`wire`，以及 `browser-relay`、`omptype`、`typescript-edit-benchmark`、`utils`。

---

## 1. 工具

| OMP 机制 | 源码位置（文件:行或函数名） | 它实际做什么（以源码为据） | Yudao 现状（文件::函数，或「无」） | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 文件读 `read` | `coding-agent/src/tools/read.ts:656` `ReadTool`；`name = "read"` `:657` | 读本地路径、内部 URI、URL；目录走 `buildDirectoryTree` 列出；文本有行数/字节截断 | `harness/tools.py::ToolRuntime._read_file` → `workspace.read_file`；整文件、无行区间 | 采用 | 3.2 | Stage 3 要区间读/编辑；整文件读已有 |
| 文件写 `write` | `coding-agent/src/tools/write.ts:515` `WriteTool`；`name = "write"` `:516` | 整文件写入；可走归档、`xd://` 设备、plan-mode 沙箱 | `harness/tools.py::ToolRuntime._write_file` → `workspace.write_file`；工程部门 + 计划范围 | Yudao 已有等价 | 3.2 | 整文件写已有；设备目录不采用 |
| 区间编辑 `edit` | `coding-agent/src/edit/index.ts:298` `EditTool`；`name = "edit"` `:299` | 按匹配片段替换文件内容，不是整文件覆盖 | 无 | 采用 | 3.2 | 计划第 3 节「区间编辑」 |
| 删除 / 移动 | 未找到独立 builtin 名；写/编辑覆盖改名场景 | builtin 列表无 `delete`/`move`（`tools/builtin-names.ts:1-31`） | `harness/tools.py::_delete_file` / `_move_file`；`orchestrator._begin_tool` 要求计划范围与 reason | Yudao 已有等价 | — | OMP 侧未找到对等独立工具 |
| `bash` 执行 | `coding-agent/src/tools/bash.ts:554` `BashTool`；`exec/bash-executor.ts:454` `executeBash` | 在给定 `cwd` 跑 shell；可交互 PTY、自动后台、direnv | 无通用 shell。`harness/tools.py::_execute_check` 只跑预绑定检查 argv | 采用 | 3.2 | 受控 shell，不是任意命令 |
| bash 超时 | `tools/tool-timeouts.ts:10-18` `TOOL_TIMEOUTS.bash`；`:33` `clampTimeout` | 默认 300s，最小 1s，最大 3600s，可再被全局 `maxTimeout` 封顶 | `harness/tools.py::CHECK_TIMEOUT_SEC = 30`，仅检查子进程 | 采用 | 3.2 | 检查超时不能当通用 shell 超时 |
| bash 输出截断 | `tools/bash.ts` 使用 `session/streaming-output.ts` 的 `DEFAULT_MAX_BYTES`、`enforceInlineByteCap`、`streamTailUpdates` | 流式尾部缓冲，超限后只保留封顶字节/预览行 | `harness/tools.py::CHECK_OUTPUT_LIMIT = 4000`，`_summarize_output` | 采用 | 3.2 | 检查输出封顶可作口径参考 |
| bash 工作目录 | `exec/bash-executor.ts:230` `resolveShellCwd`；`tools/path-utils.ts` `resolveToCwd` | 调用方传入 `cwd`；`cd` 可改持久 shell 的 PWD | `harness/tools.py::_execute_check` 固定 `cwd=check_copy` 副本根 | 采用 | 3.2 | Stage 3 约束为工作区内 |
| `grep` | `tools/grep.ts:917` `GrepTool`；`natives/native/index.d.ts:1638` `grep` | 调原生 ripgrep；路径、上下文、匹配上限、归档内搜 | 无 | 采用 | 3.2 | |
| `glob` / 旧名 `find` | `tools/glob.ts:116` `GlobTool`；`name = "glob"` `:117`；schema 名 `findSchema` `:43`；别名 `builtin-names.ts:41` `find → glob` | 按 glob/路径列文件，默认/硬上限 200，超时 5s | `harness/tools.py::_list_files` 只按前缀列工作区文件 | 采用 | 3.2 | `list_files` 不是 glob |
| 目录列出（无独立 `ls`） | `tools/read.ts:651-655` 注释 + `ReadTool` 对目录走 `buildDirectoryTree` | 对目录调用 `read` 得到带 mtime 的树，不是单独 `ls` 工具 | `harness/workspace.py::Workspace.list_files` | Yudao 已有等价 | 3.2 | 独立 `ls` 工具：未找到 |
| Web 取回 | `tools/fetch.ts:1649` `fetchReadUrl`；`:1722` `executeReadUrl`；由 `ReadTool` 对 URL 调用 | HTTP 取页，HTML→markdown，有超时（`TOOL_TIMEOUTS.fetch` 默认 20s）与输出上限 | 无 | 采用 | 3.2 | 按项目授权 |
| Web 搜索 | `web/search/index.ts:318` `WebSearchTool`；`name = "web_search"` `:319` | 按配置的搜索 provider 链查询并回退 | 无 | 待决 | 3.2 | 计划只写「网络取回」；是否包含搜索见文末 |
| MCP 客户端 | `mcp/manager.ts:193` `MCPManager`；`mcp/tool-bridge.ts:536` `MCPTool`；`:439` `createMCPToolName`；传输 `mcp/transports/{stdio,sse,http}.ts` | 连 stdio/SSE/HTTP MCP，工具名 `mcp__<server>_<tool>`，作为 `CustomTool` 进循环 | 无 | 采用 | 3.2 | 外部工具须先成为已声明工具 |
| 工具 `concurrency` | `agent/src/types.ts:808`；`tools/bash.ts:612` 按参数返回 `shared`/`exclusive` | 批次调度前决定共享或互斥 | 无。`harness/engine.py::run_department` `:133-157` 对 `function_call` 逐条串行 | 采用 | 3.2 / 3.4 | Stage 3：只读可并发；不照搬任意批次并行 |
| 工具 `interruptible` | `agent/src/types.ts:822`；循环消费 `agent-loop.ts:2430-2436` | 声明可被 steering/IRC 硬中断；未声明则只收合作式 `steeringSignal` | 无 | 不采用 | — | S4-A：steering/IRC 原样不搬 |
| `beforeToolCall` | `agent/src/types.ts:493`；调度 `agent-loop.ts:2274-2336` | 校验后、入队前可 `block` 或改写 args，改写写回调用块 | `harness/orchestrator.py::_begin_tool`：权限、合同/计划、路径范围；不能改写 args | 采用 | 3.7 | 准入钩子只能收紧；改写权限不采用 |
| `afterToolCall` | `agent/src/types.ts:528` | 执行后可覆盖结果字段 | 无。`engine.py::run_department` 直接 `record_tool` | 待决 | 3.7 | 见文末：是否允许改写结果 |
| 宽松参数校验 | `agent/src/types.ts:810` `lenientArgValidation`；`agent-loop.ts:2318` | schema 失败仍把清理后的原始参数交给 `execute` | `engine.py::run_department` `:143-149`：非 object 则失败、不执行 | 不采用 | — | S4-A / 计划第 3 节 |
| 工具结果归一化 | `agent/src/agent-loop.ts:447` `coerceToolResult` | 要求 `content` 数组；非法块改成错误文本，避免坏结构进会话 | `engine.py::run_department` `:158-162` 把 `ToolResult` 收成 `function_call_output` JSON | Yudao 已有等价 | 3.2 | MCP 接入时要按第三方结果再收一层 |
| computer-use | `tools/computer.ts:84` `ComputerTool`；`builtin-names.ts:16` | 桌面截屏与指针操作 | 无 | 不采用 | — | 计划第 3 / 7 节 |
| `xd://` 设备目录 | `internal-urls/xd-protocol.ts:4` `XD_URL_PREFIX`；`:33` `XdProtocolHandler` | 把虚拟设备当 URL 挂到 read/write | 无 | 不采用 | — | S4-A / 计划第 3 节 |

---

## 2. 技能

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `SKILL.md` 发现路径 | `extensibility/skills.ts:135` `loadSkills`；`discovery/helpers.ts:444` `scanSkillsFromDir`；`discovery/builtin.ts:282`：祖先 `.omp/skills/`、`~/.omp/agent/skills/`、`managed-skills`；另有 Claude / Agents / GitHub / plugin 目录 | 扫 `<dir>/<name>/SKILL.md`；可选 `includeSelf` 扫目录自身的 `SKILL.md` | 无 | 采用 | 3.5 | Yudao 技能档案字段与 OMP frontmatter 不同，见样例 `skill-dossier-sample.md` |
| Frontmatter 字段（通用扫描） | `discovery/helpers.ts:465-479`：`enabled`、`description`、`name`；`skills.ts:113` `hide` / `disableModelInvocation` | 无 description 且 `requireDescription` 则跳过；`enabled===false` 跳过 | 无 | 采用 | 3.5 | 通用扫描是开放字段 + 若干约定键 |
| Agent Plugin frontmatter 闭集 | `discovery/agent-plugin-format.ts:90-97` `SKILL_FIELDS`；`:124` `validateAgentSkillFrontmatter` | 只允许 `name`、`description`、`license`、`allowed-tools`、`metadata`、`compatibility` | 无 | 采用 | 3.5 | 仅 plugin 路径闭集；其他 provider 更松 |
| 加载时机 | `skills.ts:59` `setActiveSkills`：「每个顶层会话一次」；`loadSkills` 在会话构造/重载时经 capability API | 进程内快照供 `skill://` 解析 | 无 | 采用 | 3.5 | |
| 与 Prompt 的关系 | `prompts/skills/autoload.md`；`prompts/skills/user-invocation.md` | 自动加载把 body 塞进系统侧；用户 `/skill:` 用「必须遵循」模板包一层 | 无。部门 Prompt 是项目配置，不是技能 | 采用 | 3.5 | Prompt 不是安全控制 |
| 斜杠命令 | `extensibility/slash-commands.ts:69` `loadSlashCommands`；来源 `extension` / `prompt` / `skill`（`:10`） | 从 capability 与内嵌模板装 `/` 命令，frontmatter `description` + 占位符替换 | 无 | 待决 | 3.5 / 3.7 | 技能档案是否暴露为斜杠，见文末 |
| Prompt 模板 | `config/prompt-templates.ts:17` `PromptTemplate`；`:4-6` 用户/项目 prompts 目录 | markdown 模板，frontmatter + `substituteArgs` | 无独立模板层 | 采用 | 3.5 | 技能展开路径可用同一模板版本 |
| 自动提炼 / `manage_skill` | `tools/manage-skill.ts:39` `ManageSkillTool`；`autolearn/managed-skills` | 模型可写 managed skill；优先级低于手写 | 无。计划第 7 节：自己提炼属第四阶段 | 不采用 | — | 与 3.5「研发者封装」一致 |

---

## 3. 会话与恢复

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 会话文件格式与位置 | `session/session-entries.ts:13` `CURRENT_SESSION_VERSION = 3`；`:35` `SessionHeader`（`type: "session"`）；`session-loader.ts:71` `parseSessionContent` 解析 JSONL；`session-paths.ts:185` `computeDefaultSessionDir`（按 cwd 编码目录，根在 sessions 目录） | 每会话一个 JSONL：首条 header，其后 `parentId` 链条目 | `harness/event_store.py::EventStore`：SQLite `events` / `project_events`，按 `run_id, seq` | Yudao 已有等价 | 3.1 | 事实源已是事件库，不搬 JSONL |
| `--resume` | `cli/flag-tables.ts:246`；`main.ts:1739` 无值出选择器；`utils/resume-command.ts:14` `resumeCommand` | 按 session id 打开已有 JSONL，重建对话与模型 | 无执行续行。`LoopSystem.replay` 只重放投影；`collaboration.py::resume_phase` 是协作请求回到哪一阶段，不是杀进程后续跑 | 采用 | 3.1 | |
| `--continue` | `session-paths.ts:200-217` 终端 breadcrumb；`main.ts:928` `-c` / `--continue` | 找本终端上次会话文件再打开 | 无 | 采用 | 3.1 | 语义应对「从最后一致边界续行」，不是「同一段聊天」 |
| 会话树 / 分支 | `session-manager.ts:2722` `createBranchedSession`：新文件只保留根到 `leafId`；`agent-session.ts:9329` 树导航 | 条目 `parentId` 成树；分支写新 JSONL，`parentSession` 指回源文件 | 无会话树。事件有 `parent_event_id`，不是用户可切的对话分支 | 待决 | 3.1 | 控制恢复不依赖对话树；是否要产品化分支见文末 |
| 压缩触发 | `agent/src/compaction/compaction.ts:337` `shouldCompact`；会话侧 `session-maintenance.ts:1631` 等处调用 | 用量（与本地历史估计取大）超过窗口阈值则自动压 | `harness/compaction.py::plan_compaction`：输入将吃进输出预留时规划一次摘要 | Yudao 已有等价 | — | 思考模型输出预算缺口属 3.3，不是缺触发器 |
| 摘要保留 | `compaction.ts:854+` `generateSummary`（旧审查已述）；`prepareCompaction` `:1315` | 按切点摘要；可走远端保留 | `compaction.py::finish_compaction`：只要助手文本；失败不进有效历史 | Yudao 已有等价 | — | |
| 远端压缩 / 方法回退 | `session/compaction-methods.ts:11-49` 默认序 `remote → snapcompact → handoff → shake → soft` | 一种失败可换下一种 | 无。压缩固定部门冻结模型 | 不采用 | — | S4-A 远端回退、Snapcompact |
| Snapcompact | `packages/snapcompact`（package.json：把历史打成 bitmap 给视觉模型） | 无 LLM 摘要的视觉压缩 | 无 | 不采用 | — | |
| 中断后续行（工具重放） | `session/turn-recovery.ts:118-129`：剥掉失败工具尾，`Agent.continue()`（`agent.ts:1216`）按原调用再执行；部分成功批次不重放 | 会话重载 + 对未完成批次再执行，不是只读回消息 | 无。进程死后须新执行；`orchestrator.cancel` 中止当前适配器 | 采用 | 3.1 | OMP 是再执行；Yudao 要动作核实契约，不能假定重放安全 |
| 子 Agent 冷恢复 | `task/persisted-revive.ts:45-51` | 按 sessionFile 重开子 Agent，与 `--resume` 同类 | 无 | 采用 | 3.1 / 3.4 | 并行后才有子执行者所有权 |

---

## 4. 并行与调度

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 子 Agent（`task`） | `task/index.ts:500` `TaskTool`；`name = "task"` `:501` | 再开一层 agent 跑指定任务，可隔离目录、自带会话文件 | 无。每进程一活动 run（`orchestrator._activate_once`） | 采用 | 3.4 / 3.6 | 有组织语义的是部门循环，不是照搬 task |
| 并行工具批次 | `agent-loop.ts:2367` `executeToolCalls`：先 `prepareToolCallDispatch`，再按 `concurrency` 调度整批 | 同一助手消息里多工具可并行（共享/互斥） | `engine.py::run_department` 逐条 `begin_tool` + `execute` | 不采用 | — | 原样不搬；只读并发是 3.2 子集 |
| steering 队列 | `agent/src/types.ts:131-278` `interruptMode` / `hasSteeringMessages`；`agent-loop.ts:2398-2414` | 运行中注入用户/系统消息；可立刻打断 interruptible 工具 | `orchestrator.add_guidance` / `runtime.add_guidance`：部门指导，下一激活可见 | Yudao 已有等价 | — | 已有有限 steering；不搬队列中断 |
| IRC / `hub` | `tools/hub`；`session/irc-bridge.ts`；`agent-loop.ts` `hasIrcInterrupts` | 子 Agent 间消息与中断 | 无 | 不采用 | — | S4-A |
| 取消传播 | `task/index.ts` 多处 `aborted` / `runSignal.aborted`（如 `:1136`）；RPC `abort`（`modes/rpc/rpc-types.ts:36`） | 父取消后子任务标 aborted，未启动的标 cancelled before start | `orchestrator.cancel`：置 abort、`adapter.abort`、run 失败；无子槽位 | 采用 | 3.4 | 计划：父取消后子状态真实可见 |

---

## 5. 部门内部循环与协议

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 无组织语义的子循环 | 同上 `TaskTool` | 子 Agent 不区分产品/工程/质检 | `harness/engine.py::run_department` + 三部门交接；`collaboration.py` 请求/结果所有权 | Yudao 已有等价 | 3.6 | OMP 无部门协议 |
| 协作请求 / 指导 | 无对等「部门合同」类型 | — | `tools.py::SUBMIT_KINDS`；`collaboration.py::request_basis` / `resume_phase` / `guidance_resume_phase` | Yudao 已有等价 | 3.6 | Stage 3 要接收语义与四种有限组织 |
| 四种有限组织 | 未找到 | OMP 不预置组织型 | 无执行能力（仅研究与 3.0 样例） | 采用 | 3.6 | 研发者预选，模型不自选 |

---

## 6. Provider 与模型

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 目录结构 | `catalog/src/types.ts:1053` `Model`；`:9-24` `KnownApi`；`catalog/src/model-manager.ts` 捆绑/缓存/models.dev | Provider + 模型 + 协议 + 窗口 + 费用 + thinking 配置 | `harness/provider_catalog.py::ProviderCatalog` / `ResolvedProviderTarget`：providers、models、三部门 bindings | Yudao 已有等价 | 3.3 | 缺 thinking 字段 |
| 协议种类 | `catalog/src/types.ts:9-23`：`openai-completions`、`openai-responses`、`anthropic-messages`、`google-generative-ai` 等 14 个 KnownApi | 各协议有独立 stream 实现（`packages/ai/src/providers/`） | `ResolvedProviderTarget.create_adapter`：仅 `responses` 与 `fake` | 采用 | 3.3 | 第二协议适配器 |
| OAuth / 凭据运行时 | `ai/src/registry/oauth/index.ts:35` `registerOAuthProvider`；`:67` `refreshOAuthToken`；各 `login*` | 登录、刷新、按 provider 存凭据 | `provider_catalog.py::resolve_snapshot` 经宿主 `CredentialSource`；无 OAuth | 不采用 | — | S4-A |
| 宿主 API key | `ai` 的 `getEnvApiKey`（fetch 等处引用） | 环境变量/存储解析 | `runtime.py::environment_credentials`；`provider_catalog.py::_resolve_credential` | Yudao 已有等价 | — | |
| 会话内换模型 | `modes/rpc/rpc-types.ts:52` `set_model` / `cycle_model` | 同一会话改 provider/model | run 创建时冻结快照；无 run 内换模 | 不采用 | 3.3 | 计划：事项级换模 = 新 run 绑定 |
| 思考等级 / 推理预算 | `agent/src/thinking.ts:8-17` `ThinkingLevel`（`off`/`inherit`/`minimal`…`max`）；`catalog/src/effort.ts:2` `Effort`；`catalog/src/types.ts:27-32` `ThinkingControlMode`（`effort`/`budget`/`google-level`/Anthropic 变体）；wire：`ai/src/providers/openai-shared.ts` `reasoning_effort`；`ai/src/stream.ts:2273` Gemini `thinkingLevel` | 用户等级映射到协议字段；有的按 token budget，有的按离散 level | 无绑定级思考设置。`compaction.py::plan_compaction` `:200-205` 已注明思考 token 计入 `max_output_tokens` | 采用 | 3.3 | Stage 2 截断的直接缺口 |
| 适配器内重试 | `ai/src/utils/openai-http.ts` `fetchWithRetry`；`providers/openai-responses.ts` replay-safe 再试 | 传输层与未提交输出可重发 | `adapters/responses.py:134,339` `max_retries=0`；`engine.py` D17 有界尝试 | 不采用 | — | S4-A |
| key 轮换 | `ai/src/auth-storage.ts:6666` `rotateSessionCredential`；`auth-retry.ts` | 401/403/额度错误换兄弟凭据 | 无 | 不采用 | — | S4-A |
| `previous_response_id` | `ai/src/providers/openai-responses.ts:120,204,329` | 用上一次 response id 做增量输入 | 无。每次请求自带完整 input | 不采用 | — | S4-A |
| 自动发现 | `catalog/src/model-manager.ts:15` `ModelRefreshStrategy`；`:20` `ModelsDevFallback` | 在线拉 models.dev / 缓存补目录 | `ProviderCatalog.load` 读本地 JSON | 不采用 | — | S4-A |

---

## 7. 扩展点

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| Extension API | `extensibility/extensions/types.ts:1-8`：生命周期、注册工具/命令/快捷键/CLI、UI | TS 模块订阅事件并注册能力 | 无 | 采用 | 3.7 | 只做准入钩子、观察者、主机检查/MCP 登记 |
| Hook 类型清单 | `extensibility/hooks/types.ts:481-510` `HookAPI.on` | `session_start` / `session_before_switch` / `session_switch` / `session_before_branch` / `session_branch` / `session_before_compact` / `session.compacting` / `session_compact` / `session_shutdown` / `session_before_tree` / `session_tree` / `context` / `before_agent_start` / `agent_start` / `agent_end` / `turn_start` / `turn_end` / `auto_compaction_start` / `auto_compaction_end` / `auto_retry_start` / `auto_retry_end` / `ttsr_triggered` / `todo_reminder` / `tool_call` / `tool_result` | 无 | 采用 | 3.7 | 首批只需工具前后（收紧）与只观察事件 |
| 自定义工具 | `extensibility/custom-tools/` | 从路径加载 `CustomTool` | 无。工具表写死 `TOOL_DEFS` | 采用 | 3.2 / 3.7 | 经 `begin_tool` 唯一入口 |
| 自定义命令 | `extensibility/custom-commands/`；`slash-commands.ts` | 文件/扩展注册 `/` 与 CLI | CLI 仅 `demo`/`serve`/`replay`/`smoke`（`harness/__main__.py::main`） | 采用 | 3.7 | 完整 CLI，不是 OMP 斜杠生态 |
| 扩展权限 | `tools/approval.ts` + 扩展包装 `extensions/wrapper.ts:198` | 扩展工具仍走 approval mode；yolo 可绕过提示 | 无扩展。部门权限在 `has_tool` / `_begin_tool` | 采用 | 3.7 | 钩子不能授权限 |

---

## 8. 接口与嵌入

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| TUI | `packages/tui`（差分渲染库）；`coding-agent/src/modes/interactive-mode.ts` | 终端交互主界面 | 无。主界面是 Web | 待决 | 3.7 | 计划第 9 节用户项 3 |
| RPC / NDJSON | `modes/rpc/rpc-types.ts:3-5`：stdin JSON 行命令，stdout JSON 行事件；`:28` `RpcCommand`（prompt/steer/abort/compact/set_model/…） | 无界面宿主用行协议驱会话 | 无 NDJSON。Web 是 HTTP + SSE | 采用 | 3.7 | |
| print / JSON 模式 | `modes/print-mode.ts:1-7`；`PrintModeOptions.mode` `"text"` \| `"json"` `:21` | `-p` 只打最终文本；`--mode json` 打事件流（去掉二次快照） | `harness/__main__.py`：`replay` 打投影 JSON；无事项驱动的无界面循环 | 采用 | 3.7 | CI 无界面跑事项 |
| SDK | `coding-agent/src/sdk.ts` 导出会话/Agent 装配（文件头即核心 import） | TS 嵌入同一 runtime | `harness/runtime.py::LoopSystem`：`create_run` / `run_until_stop` / `cancel` / `project` | Yudao 已有等价 | 3.7 | 雏形已有；缺恢复/并行/CLI 表面 |
| Web 工作台 | 非 OMP 主界面（OMP 主路径是 TUI） | — | `harness/web/server.py::serve`；`/api/health`、`/api/runs` | Yudao 已有等价 | — | Web 仍是主界面 |

---

## 9. 权限与沙箱

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 权限模式 | `tools/approval.ts:14` `ApprovalMode`：`always-ask` / `write` / `yolo`；`:37-41` 模式对应最大 tier `read`/`write`/`exec` | 用户 `tools.approval.<tool>` 可 allow/deny/prompt | `tools.py::TOOL_DEFS` 部门 × access；`_begin_tool` 计划范围 | 采用 | 3.2 / 权限 | 项目设置授权 shell/网络/发布 |
| 逐次批准 | `approval.ts` `ResolvedApproval`；工具 `approval` 字段（如 `WriteTool` `:517`） | 超出模式上限则 prompt | 无用户批准通道；超权限直接 `ToolAdmission.error` | 采用 | 3.2 | 批准一次不作永久授权 |
| `yolo` 默认 | `session-tools.ts:751-763`；schema 默认可为 yolo | 显式 yolo 才跳过门 | 无 | 不采用 | — | 与「用户批准过一次当永久」同类，不搬默认放开 |
| OS 级 shell 沙箱 | 在 `coding-agent/src/exec` 未找到 landlock/seccomp/bwrap/seatbelt | 执行层是子进程 + cwd/env；plan-mode 有 `local://` 产物沙箱（`plan-mode-guard.ts`） | 检查在 `workspace.check_copy` 副本上跑 | 待决 | 3.2 | 计划第 9 节用户项 2：子进程限制 vs OS/容器 |
| 部门 / 路径准入 | 无三部门模型 | — | `orchestrator._begin_tool`；`collaboration.py::tool_error` | Yudao 已有等价 | — | 新工具仍只进此口 |

---

## 10. 运维

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 交付物运行责任 / 告警进变更 | 未找到对应领域模块 | `metaharness` 是仓库基准测试管理器（见第 12 节），不是生产运维 | 无 | 采用 | 3.8 | OMP 无此能力域；Yudao 按研究 §7 自建 |

---

## 11. 观测

| OMP 机制 | 源码位置 | 它实际做什么 | Yudao 现状 | 差距类型 | Stage 3 归属包 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| Stats 扫描 JSONL | `stats/src/parser.ts:42` `classifyAgentType`；`:154+` 解析 usage（旧审查：缺字段补 0） | 从会话文件派生消息/工具/费用 | `observability.py::ObservabilityQuery` 只读事件与工件 | Yudao 已有等价 | — | 查询只派生 |
| Stats SQLite 与成本仪表 | `stats/src/aggregator.ts:474` `getCostDashboardStats`；`getCostTimeSeries` | 独立库做跨会话成本时间序列 | `observability.py::usage_summary` / `_usage_totals`：`reported` 才进小计，缺费用不填 0，混币种 `cost` 为 null | Yudao 已有等价 | — | 不另立 Stats 库 |
| OTEL spans | `agent/src/telemetry.ts:1-20`；`types.ts:533` 默认关闭 | 可选 `invoke_agent` / `chat` / `execute_tool` | 无 OTEL。尝试级事件在 EventStore | 不采用 | — | OTEL 不作领域事实 |
| 尝试级用量与费用 | Stats 从 assistant `usage` 汇总；缺则 0（parser） | 展示用，不是运行权威 | `orchestrator._record_observation` 写 usage；`Usage.reported` / `cost_reported` | Yudao 已有等价 | 3.7 观测加项 | Stage 3 再加等待、恢复、槽位、技能、动作核实 |

---

## 12. 额外包（是否落入第 3 节某域）

**metaharness**（`packages/metaharness/README.md`）：同一套 experiment → run → trace、SQLite、REST/SSE，用来跑 Harbor / TypeScript edit / SnapCompact 等仓库内基准。凭据不进容器。与第 3 节无直接对应；不是 3.8 运维。差距：`不采用`。

**mnemopi**（`packages/mnemopi/package.json`：Local SQLite memory engine；`src/index.ts` 导出 `remember` / `recall` / `query` 与 MCP 入口）：给 Agent 用的本地记忆/嵌入/三元组，不是会话恢复，也不是技能档案。与 3.5「来源经历」最多相邻。差距：`不采用`（第三阶段不引入记忆引擎）。

**collab-web**（`packages/collab-web/package.json`）：浏览器访客客户端 + 本地 relay，跟 omp 实时协作会话。与 Web 工作台不是同一产品。差距：`不采用`。

**wire**（`packages/wire/src/index.ts`）：协作直播协议的共享 JSON 形状（文本/图/thinking/工具等），给浏览器与测试用，避免依赖 coding-agent。与 3.7 NDJSON 只是「行协议」同类想法，类型集不能当 Yudao 事件词义。差距：`不采用`。

---

## 13. 建议改判

主代理默认不改 S4-A。下列仅供对照，不视为决定。

1. **只读工具并发（不是「并行工具批次原样」）**  
   S4-A 拒绝的是任意批次并行 + steering 硬打断。计划第 3 节已写「只读工具可并发」。`concurrency: shared` 在只读 grep/glob/read 上与 3.2 / 3.4 一致，不必打开 exclusive 写并行。代价：调度与取消测试变多，但比整批照搬小。

2. **思考等级（本来就在「采用」）**  
   不改判 S4-A。S4-A 拒绝的是适配器内 reasoning fallback，不是宿主绑定上的 `ThinkingLevel`。3.3 应做绑定级设置，并让输出上限与推理预算分开记账。代价：目录与 UI 要增字段；不做则思考模型会继续撞 `max_output_tokens`。

3. **不建议改判的项（维持不采用）**  
   OAuth 运行时、自动发现、适配器内重试、key 轮换、`previous_response_id`、远端压缩回退、Snapcompact、OTEL 作事实、steering/IRC 原样、computer-use、`xd://`、宽松校验。理由与 S4-A / 计划第 7 节相同：另立事实源或把控制权交给适配器。

---

## 14. 待决与不确定

1. **TUI**（计划第 9 节项 3）：CLI + Web 是否足够。OMP 主界面是 TUI；Yudao 已定 Web 为主。  
2. **受控 shell 隔离强度**（计划第 9 节项 2）：OMP `exec` 未见 OS 沙箱实现；只有子进程 cwd/超时/输出封顶与 plan-mode 文件沙箱。Yudao 检查已用工作区副本。3.2 要比的是「子进程限制够不够」。  
3. **`afterToolCall` 改写结果**：3.7 观察者「只观察不推进」。若钩子能改工具结果，等于第二事实源。待决：只订阅，还是允许覆盖。  
4. **`beforeToolCall` 改写 args**：OMP 会写回历史。Yudao 准入今日只拒绝。待决：钩子能否改参，还是只能 block。建议默认只能收紧。  
5. **斜杠命令**：3.5 是技能档案 + 宿主适用性；OMP 还有 `/skill:`。待决：要不要斜杠，还是只在部门循环里由宿主选用。  
6. **会话树 / 分支**：控制恢复不需要用户可切的对话树。待决：是否做成产品能力。  
7. **Web 搜索 vs 仅 URL 取回**：计划写「网络取回」；OMP 搜索与取回是两个工具。待决：3.2 是否包含 `web_search`。  
8. **第二协议选哪一种**：OMP `KnownApi` 有 14 种。3.3 要真实第二套服务，协议未定。  
9. **3.8 真实交付物**（计划第 9 节项 1）：与 OMP 无关，但运维域没有 OMP 对照物。  
10. **独立 `ls` / `find` 工具名**：OMP 无 `ls`；`find` 是 `glob` 别名。不必为对齐名字再做第三套列举工具。

### 未找到（不猜测）

- 独立 builtin 工具名 `ls`、`find`（`find` 仅为 `glob` 别名）、`delete`、`move`、`fetch`（取回函数在 `fetch.ts`，工具入口是 `read`）。  
- `coding-agent/src/exec` 下的 landlock / seccomp / bwrap / seatbelt 实现。  
- OMP 源码中的「运维职责 / 告警进入变更流程」模块。  
- 与 Yudao 三部门合同对等的组织协议类型。

---

## 15. 各域行数与分类合计

| 能力域 | 行数 |
| --- | ---: |
| 工具 | 22 |
| 技能 | 8 |
| 会话与恢复 | 10 |
| 并行与调度 | 5 |
| 部门内部循环与协议 | 3 |
| Provider 与模型 | 10 |
| 扩展点 | 5 |
| 接口与嵌入 | 5 |
| 权限与沙箱 | 5 |
| 运维 | 1 |
| 观测 | 4 |
| **表内合计** | **78** |
| 第 12 节额外包（4 段，各 1 条判定） | 4 |

| 差距类型 | 表内 11 域 | 含额外包 |
| --- | ---: | ---: |
| 采用 | 37 | 37 |
| Yudao 已有等价 | 18 | 18 |
| 不采用 | 17 | 21 |
| 待决 | 6 | 6 |

表内 11 域 78 条 = 37 + 18 + 17 + 6。额外包 4 条均 `不采用`。分域（采用/已有/不采用/待决）：工具 12/4/4/2；技能 6/0/1/1；会话 4/3/2/1；并行 2/1/2/0；部门 1/2/0/0；Provider 2/2/6/0；扩展 5/0/0/0；接口 2/2/0/1；权限 2/1/1/1；运维 1/0/0/0；观测 0/3/1/0。
