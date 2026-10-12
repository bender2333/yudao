# 网络取回与 MCP 的参照实现、官方 SDK 与搜索服务：事实调研

- 调研日期：2026-10-01。
- 用途：3.2B 网络与 MCP 专题讨论的材料（[D36](../requirements/network-and-mcp.md)、[设计说明](../design/network-and-mcp.md)）。
- 来源写法：网页写链接；源代码写仓库、提交号、文件与行号。OpenCode 的提交为 `0027387`，文件在 `packages/opencode/src/` 的 `mcp/`、`tool/` 下；OMP 的提交为 `fdfeef1f78`，文件在 `packages/coding-agent/src/` 的 `mcp/`、`tools/`、`web/scrapers/` 下；其余文件写明目录。Codex 的提交为 `8ea2428c38`，文件在 `codex-rs/` 下。
- 本文只记录事实，不包含建议。

## 1. OpenCode（0027387）

### 1.1 MCP 客户端

| 项 | 事实 | 位置 |
| --- | --- | --- |
| 配置 | `opencode.json` 的 `mcp` 项，全局与项目合并；`local` 是 stdio，`remote` 先尝试 StreamableHTTP，再尝试 SSE；整份配置支持 `{env:X}` 与 `{file:路径}` 替换，其余明文；子进程继承全部环境变量；支持 OAuth，令牌保存在 `mcp-auth.json`（权限 0600） | `mcp/index.ts:269,352`，`config/variable.ts:34`，`mcp/auth.ts:37,80` |
| 生命周期 | 首次读取 MCP 状态时并发连接全部已启用的服务器，连接超时 30 秒；没有自动重连，断开后标记为失败，只有 HTTP 会话过期时由 SDK 补丁重新初始化；退出时只有非 Windows 对后代进程发送 SIGTERM，Windows 不结束进程树 | `mcp/index.ts:38,418,443,492`，仓库根 `patches/*sdk@1.29.0.patch:35` |
| 工具提供 | 名称 `服务器_工具`（非法字符替换为 `_`）；参数结构补 `type: object` 与 `additionalProperties: false`；`list_changed` 触发重新拉取；按服务器用 `enabled: false` 关闭；按工具或智能体用 `permission` 通配符 `deny` 隐藏 | `mcp/catalog.ts:43,117`，`permission/index.ts:204` |
| 权限 | 每次调用经过 `ctx.ask`，权限名是工具名，匹配串 `*`，不按参数；默认规则 `"*": "allow"`，默认不询问；配置为 `ask` 后可选 once、always、reject，always 只保存在内存，随项目实例结束失效 | `session/tools.ts:408`，`agent/agent.ts:120`，`permission/index.ts:146` |
| 结果 | image 作为附件，resource 取文本，二进制只支持 PDF 与常见图片且不超过 10 MB，音频忽略；文本超过 2000 行或 50 KB 截断，全文保留 7 天；`isError` 转为抛出异常；带取消信号；超时使用配置值，缺省为 SDK 的 60 秒，收到进度会续期 | `session/tools.ts:426`，`tool/truncate.ts:12`，`mcp/catalog.ts:53,68` |
| 工具注解 | 没有找到使用 | |

### 1.2 网络取回与搜索

| 项 | 事实 | 位置 |
| --- | --- | --- |
| 参数与限制 | 参数 `url`、`format`（text、markdown、html）、`timeout`（秒，不超过 120）；只发 GET；响应上限 5 MB（先检查 `content-length`，下载后再检查）；默认 30 秒，只覆盖到响应头；重定向沿用 fetch 的默认跟随，没有跨主机处理 | `tool/webfetch.ts:9-22,76-104` |
| 地址拦截 | 没有找到对回环地址、内网地址与链路本地地址的拦截 | |
| 转换与截断 | Markdown 用 Turndown，文本用 htmlparser2；依据 `content-type` 是否含 `text/html`，图片作为附件；截断为 2000 行或 50 KB，标记 `...N lines truncated...`，附全文文件路径 | `tool/webfetch.ts:106-192`，`tool/truncate.ts:124-139` |
| 权限 | `ctx.ask` 的匹配串是完整地址，always 为 `*`，默认 allow，不按域名；请求头固定，没有 Cookie | `tool/webfetch.ts:39,69` |
| 取回工具的注册 | `webfetch` 在工具注册表中默认启用；`websearch` 只在特定提供方或开关下启用（`webSearchEnabled(providerID, {exa, parallel})`） | `tool/registry.ts:108-109,218-220,292-295` |
| 搜索 | 设置 `OPENCODE_ENABLE_EXA=1` 或 `OPENCODE_ENABLE_PARALLEL=1` 启用，默认按会话在两者之间各取一半；端点 `mcp.exa.ai/mcp`（工具 `web_search_exa`）与 `search.parallel.ai/mcp`（工具 `web_search`）；请求为单次 `tools/call` POST，不做 initialize 握手 | `tool/mcp-websearch.ts`，`tool/websearch.ts` |

## 2. OMP（fdfeef1f78）

### 2.1 MCP 客户端

| 项 | 事实 | 位置 |
| --- | --- | --- |
| 配置 | 项目 `.omp/mcp.json`，用户 `~/.omp/agent/mcp.json`，并导入其他工具的配置；stdio、http、sse；`${VAR}` 展开，`env` 与 `headers` 的值可以写 `!命令`（10 秒）或环境变量名；子进程继承全部环境变量；支持 OAuth（PKCE、动态注册），凭据保存在 `agent.db` | `discovery/builtin.ts:207`，`config/resolve-config-value.ts:21`，`mcp/transports/stdio.ts:579`，`mcp/oauth-flow.ts:465` |
| 生命周期 | 会话启动时并行连接，只等待 250 毫秒，较慢的服务器先使用缓存的工具定义；超时 30 秒；断线自动重连（间隔 500 至 4000 毫秒），30 秒内超过 5 次则暂停；调用遇到连接错误时重连并重试一次；退出时先关闭标准输入，再 SIGTERM、SIGKILL，Windows 只结束直接子进程 | `mcp/manager.ts:79,105,603`，`mcp/timeout.ts:3`，`mcp/tool-bridge.ts:43`，`mcp/transports/stdio.ts:461-537` |
| 工具提供 | 名称 `mcp__服务器_工具`（小写，非 a-z 替换为 `_`，超过 64 个字符追加哈希）；`list_changed` 后整体替换该服务器的工具；默认 discoverable，按需检索，不进入每次请求；按服务器用 `enabled`、`disabledServers`；子智能体可以整体关闭 | `mcp/tool-bridge.ts:406,569`，`mcp/manager.ts:793`，`extensibility/custom-tools/wrapper.ts:29`，`task/executor.ts:3279` |
| 权限 | 全部为 write 级；默认模式 yolo 全部自动放行，always-ask 模式每次询问；策略按精确的工具名，没有通配符，不按参数；提示只有 Approve 与 Deny，仅此一次，不保存 | `mcp/tool-bridge.ts:545`，`tools/approval.ts:128`，`extensibility/extensions/wrapper.ts:333` |
| 结果 | text 合并，image 透传，resource 只取文本；`isError` 添加 Error 前缀，异常转为含 `retryable` 的结构化文本；超过 50 KB 保存为 artifact；超时 30 秒，不随进度延长；取消只在本地中止，没有找到 `notifications/cancelled` | `mcp/tool-bridge.ts:207`，`mcp/errors.ts:270`，`tools/output-meta.ts:653` |
| 工具注解 | 只有类型定义，没有使用 | `mcp/types.ts:219` |

### 2.2 网络取回

| 项 | 事实 | 位置 |
| --- | --- | --- |
| 工具 | `read` 工具读取网址；GET；超时 30 秒（上限 45，模型不能设置）；响应体上限 50 MB，流式截断并加注；`redirect: follow`，没有特殊处理 | `tools/fetch.ts:170,1657`，`tools/tool-timeouts.ts:16`，`web/scrapers/types.ts:32,162` |
| 地址拦截 | 没有找到 | |
| 转换与截断 | Rust 库 html-to-markdown-rs（去除导航与表单），不足时依次尝试 trafilatura、lynx、Parallel、Firecrawl、Jina；依据 MIME 与扩展名判断类型；超过 500000 个字符标记 truncated，交给模型 300 行或 50 KB，全文保存为 artifact | `tools/fetch.ts:248,595,1722`，`web/scrapers/types.ts:58` |
| 权限 | read 级，所有模式自动放行，只有 `fetch.enabled` 总开关；不按域名；请求头固定，没有 Cookie | `tools/read.ts:658`，`config/settings-schema.ts:4401` |
| 搜索 | 与取回是两个工具：`web_search` 按配置的搜索提供方链查询并回退 | `web/search/index.ts:318` |

## 3. Claude Code（官方文档，读取于 2026-10-01）

文档地址：`https://code.claude.com/docs/en/` 的 mcp、permissions、tools-reference、data-usage、security 各页；另见 `github.com/anthropics/claude-code` 的 `CHANGELOG.md`（2.1.246）。

- MCP 配置范围：本地（默认，保存在 `~/.claude.json` 的项目路径下，仅本人）、项目（根目录 `.mcp.json`，可提交）、用户（`~/.claude.json`，全部项目）；同名时本地、项目、用户依次优先，整条替换。项目 `.mcp.json` 的服务器在交互会话中逐个批准，结果写入 `.claude/settings.local.json`；未信任的工作区忽略仓库自带的批准；`claude -p`、SDK、云会话不询问，直接加载。
- 变量展开：`command`、`args`、`env`、`url`、`headers` 支持 `${VAR}` 与 `${VAR:-默认值}`；缺失且无默认值时保留原文并警告；远程服务器 `url` 与 `headers` 中的 `ANTHROPIC_API_KEY`、`NPM_TOKEN` 等凭据变量一律读取为空。
- MCP 工具权限规则：粒度为 `mcp__服务器`、`mcp__服务器__工具`、`mcp__服务器__*`；allow 的通配只能出现在字面 `mcp__服务器__` 之后，deny 与 ask 可以写 `mcp__*`；settings 中带括号（参数匹配）的 `mcp__` 规则被跳过；deny、ask、allow 依次判断，任一范围的 deny 都生效。更新日志显示 MCP 工具的提示含「不再询问」并写入 allow 规则；工具的 `_meta` 标记 `anthropic/requiresUserInteraction` 时每次必须询问。
- WebFetch：权限 `WebFetch(domain:example.com)` 按主机名匹配，`*.example.com` 含任意深度的子域、不含根域；内置文档域名免询问；「不再询问」按仓库与域名保存。跨主机重定向不跟随，返回原地址与目标地址，由模型再调用一次，重新走域名授权。拒绝 `localhost` 与不含点号的主机名，私网 IP 没有找到说明；请求前把主机名发给 `api.anthropic.com` 做黑名单检查。HTML 转 Markdown，超长截断，再由小模型按提示抽取，主模型通常只收到抽取结果；缓存 15 分钟，下载总期限 5 分钟。

## 4. Codex CLI（openai/codex，提交 8ea2428c38）

- MCP 配置（`codex-rs/config/src/mcp_types.rs:222-305,365-435`，官方文档的 extend/mcp 页）：stdio 有 `command`、`args`、`cwd`、`env`（静态值）、`env_vars`（只写变量名；子进程默认只继承 PATH、HOME 等少量变量，`rmcp-client/src/utils.rs:16-58`）；HTTP 有 `url`、`bearer_token_env_var`、`http_headers`、`env_http_headers`。没有找到 `${VAR}` 展开；明文 `bearer_token` 被校验拒绝。
- 工具与时限：`enabled_tools`、`disabled_tools`（之后再扣除）、`enabled`、`required`；`startup_timeout_sec`、`tool_timeout_sec`：文档默认 10 秒与 60 秒，源码 `codex-mcp/src/rmcp_client.rs:106-107` 为 30 秒与 300 秒，两者不一致。OAuth 令牌保存在系统钥匙串，缺失则保存到 `CODEX_HOME/.credentials.json`。
- 批准（`core/src/mcp_tool_call.rs`）：服务器级 `default_tools_approval_mode`、工具级 `tools.<工具>.approval_mode`：auto（默认，按 MCP 注解：destructive 必须询问，read-only 免询问，无注解则询问，`:2472-2503`）、prompt、writes、approve；选项「本次」「本会话」（内存，键为服务器加工具）「不再询问」（写入 `mcp_servers.<服务器>.tools.<工具>.approval_mode = "approve"`，保存到声明该服务器的项目或用户 `config.toml`，`:2293-2427`），后两项只在 auto 模式提供。`approval_policy = never` 且沙箱未全开时，需要批准的调用被拒绝。项目 `.codex/config.toml` 只在信任项目时加载。
- 网络（`core/src/tools/network_approval.rs`，`rmcp-client/src/http_client_redirect.rs`）：命令默认无网络，`sandbox_workspace_write.network_access = true` 开启；再启用 `features.network_proxy` 可设域名 allow 与 deny（deny 优先，`*.x` 只含子域，`**.x` 含根域），默认拦截回环、链路本地、私网地址，解析到私网的主机名同样拦截；未列出的主机触发批准（本次、本会话或持久规则，键为主机加协议加端口）。没有找到独立的网页取回工具；网页经托管的 `web_search` 获得：cached（默认，预索引，不访问实时页面）、indexed、live、disabled，`tools.web_search` 可设 `allowed_domains`；网络代理不覆盖 `web_search` 与 MCP 连接。MCP 的 HTTP 请求只允许同源重定向，最多 10 次。

## 5. 官方 MCP Python SDK

调研时取回的 SDK 源码、参考服务器与实测脚本放在仓库的 `.tmp/mcp-research/`（已被忽略，用后删除）。

- 版本：PyPI `mcp` 2.2.0，Python >=3.10；1.x 维护线 1.30.0。协议规范最新为 2026-07-28（上一版 2025-11-25）。客户端相关的新增：取消握手与会话（新增 `server/discover`）；`subscriptions/listen` 取代 GET 流；删除 ping；服务端改用 `InputRequiredResult` 多轮往返；Tasks 移入扩展（SDK 没有实现）。
- 传输：`stdio_client(StdioServerParameters, errlog)`；`streamable_http_client(url, http_client=httpx2.AsyncClient)`；`sse_client` 已被规范弃用。
- 会话（`client.py`、`session.py`）：默认先探测 `server/discover`，失败回退 `initialize`。`call_tool(name, arguments, read_timeout_seconds, progress_callback(progress, total, message))`，超时默认不限，进度不重置超时（实测）。超时或任务取消时 2.x 发送 `notifications/cancelled`（`jsonrpc_dispatcher.py:413`），1.30.0 不发（issue #2507）。工具失败返回 `is_error=True` 的 `CallToolResult`；协议错误抛出 `MCPError`，超时错误码 -32001。`list_changed` 只交给 `message_handler` 并清除 `tools/list` 缓存；2026 版的连接须先 `client.listen(tools_list_changed=True)` 才会收到。
- stdio 与 Windows（`stdio.py:40`、`win32/utilities.py`）：支持 `cwd`、`env`；Windows 子进程只继承 12 个变量，`env` 叠加其上。`shutil.which` 补全扩展名，不用 shell：`npx` 变为 `npx.CMD`、`uvx` 变为 `uvx.EXE`，不需要 `cmd /c`（实测）。结束：关闭标准输入，等待 2 秒，用作业对象强制结束进程树（实测有效）。标准错误直连 `errlog`（默认 `sys.stderr`），必须是带 `fileno()` 的真实文件（实测）。已知问题：issue #3335 白名单缺少 `COMSPEC`、`WINDIR` 等，`env` 里的 `Path` 与 `PATH` 并存使覆盖失效（未修复）；issue #2233 pywin32 硬依赖。
- roots、sampling、elicitation（`session.py:614`）：注册回调即声明能力，都不传则能力为空；服务端仍发来请求时被 -32600 拒绝，`call_tool` 抛出 `MCPError`。roots 与 sampling 已被规范弃用。
- 工具注解（规范 tools 页）：默认 `readOnlyHint` false、`destructiveHint` true、`idempotentHint` false、`openWorldHint` true；规范要求客户端把注解视为不可信，除非来自受信任的服务器；SDK 不读取注解。
- OAuth（`oauth2.py:129`）：只用于 HTTP，`OAuthClientProvider`（httpx2 的 Auth）挂在 `httpx2.AsyncClient(auth=)` 上，401 以后自动发现、注册、PKCE、刷新；没有内置的令牌存储，需要自己实现 `TokenStorage` 协议。
- 参考服务器（`modelcontextprotocol/servers` 仓库）：TypeScript 的 `npx -y @modelcontextprotocol/server-filesystem <目录…>`、`@modelcontextprotocol/server-memory`；Python 的 `uvx mcp-server-fetch`、`mcp-server-git`、`mcp-server-time`。fetch 服务器不限制回环与内网地址（实测读到 127.0.0.1），遵守 robots.txt，只检查模型发起的调用；filesystem 服务器没有声明 roots 时使用命令行给出的目录。

## 6. 搜索类 MCP 服务器（截至 2026-10-01）

说明：地址均为 https；HTTP 指 streamable HTTP；GreatFire 是大陆封锁监测站（`en.greatfire.org/domain/<域名>`，记录截至 2026-09）；没有找到任何一家要求境外手机号的说明。

| 服务 | 连接 | 认证与额度 | 大陆可达性 | 工具 |
| --- | --- | --- | --- | --- |
| Exa 官方 MCP（exa-labs/exa-mcp-server） | HTTP `mcp.exa.ai/mcp`；stdio `npx -y exa-mcp-server`，环境变量 `EXA_API_KEY` | 不填 Key 限每秒 3 次、每天 150 次（`exa.ai/docs/changelog`，2026-02）；有 Key 用 `x-api-key` 请求头或 `?exaApiKey=`，每月免费 10 美元，不需要支付方式 | GreatFire：`mcp.exa.ai`、`api.exa.ai` 未被封锁 | `web_search_exa`、`web_fetch_exa`，返回标题、链接与高亮片段或全文 |
| Tavily（tavily-ai/tavily-mcp） | HTTP `mcp.tavily.com/mcp/`；stdio `npx -y tavily-mcp@latest`，环境变量 `TAVILY_API_KEY` | `Authorization: Bearer Key` 或 `?tavilyApiKey=`；每月免费 1000 积分，不需要信用卡；加请求头 `X-Tavily-Access-Mode: keyless` 可以不用 Key 使用搜索与提取，限速数值没有找到 | GreatFire：`tavily.com` 未被封锁，api、mcp 子域未知 | `tavily-search`、`tavily-extract`（另有 map、crawl），返回标题、链接、摘要 |
| Brave Search（brave/brave-search-mcp-server） | 没有找到托管端点；stdio `npx -y @brave/brave-search-mcp-server`，环境变量 `BRAVE_API_KEY` | 官方定价页 `brave.com/search/api`：5 美元每千次，每月抵扣 5 美元，订阅必须绑定信用卡，大陆发卡行能否使用没有找到 | GreatFire：`brave.com` 61 个已测地址中 60 个被封锁，包含 `search.brave.com`；`api.search.brave.com` 未知 | `brave_web_search` 等，返回链接与摘要 |
| 智谱联网搜索 MCP（`docs.bigmodel.cn/cn/coding-plan/mcp/search-mcp-server`） | HTTP `open.bigmodel.cn/api/mcp/web_search_prime/mcp` | `Authorization: Bearer Key`，Key 来自 GLM Coding Plan 付费套餐，没有找到免费额度；套餐使用须知写明「仅限在指定工具与产品环境中使用，用于非支持工具将被限制权益」，Yudao 是否算指定工具没有找到说明；按量路径 `open.bigmodel.cn/api/mcp-broker/proxy/web-search/mcp?Authorization=Key`（价格表 0.01 至 0.05 元每次） | 端点在国内 | `webSearchPrime`，返回标题、链接、摘要、网站名；网关的 SSE 行写作 `event:message`（冒号后没有空格），符合规范，较老或自写的解析器会初始化超时（eca issue #586） |
| 阿里云百炼联网搜索 MCP（`help.aliyun.com/zh/model-studio/mcp-introduction`） | HTTP `dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp` | `Authorization: Bearer 百炼 Key`，需要先在百炼 MCP 广场开通；免费 2000 次（没有写明按月还是总量），超出 29 元每千次，限流 15 QPS | 端点在国内 | `bailian_web_search`（query、count），返回标题、链接、摘要、域名 |
| 百度 AI 搜索 MCP（`cloud.baidu.com/doc/qianfan/s/Omh4su4s0`） | HTTP `qianfan.baidubce.com/v2/ai_search/mcp` | `Authorization: Bearer 千帆 Key`；每日免费 100 次，超出按量后付费；纯检索的「百度搜索」每月免费 1500 次，其 MCP 地址 `qianfan.baidubce.com/v2/tools/web-search/mcp` 只见于第三方博客 | 端点在国内 | 返回大模型总结与引用，工具名没有找到 |
| DuckDuckGo（社区，nickclyde/duckduckgo-mcp-server） | stdio `uvx duckduckgo-mcp-server`，不需要 Key | 靠抓取网页实现，遇到机器人拦截（HTTP 202、403）时改用 curl_cffi 重试 | GreatFire：`duckduckgo.com` 61 个地址全部被封锁（包含 `html.duckduckgo.com`） | `search`、`fetch_content`，返回标题、链接、摘要 |
| SearXNG（社区，ihor-sokoliuk/mcp-searxng） | stdio `npx -y mcp-searxng`，环境变量 `SEARXNG_URL` | 不需要 Key，需要自备已开启 JSON 输出的实例；自建时可以启用 baidu、sogou、bing 引擎（SearXNG 文档，默认关闭） | 公共实例的大陆可达性未知 | `searxng_web_search`、`web_url_read` |
| open-websearch（社区，Aas-ee/open-webSearch） | stdio `npx open-websearch@latest`，环境变量 `MODE=stdio` | 不需要 Key，抓取 Bing、百度、搜狗页面；README 提示频繁搜索会被临时拦截 | 未知 | `search`、`fetchWebContent`，返回标题、链接、描述 |

OpenCode 的搜索工具使用的端点：`mcp.exa.ai/mcp` 与 `search.parallel.ai/mcp`（Parallel 的匿名限速数值没有找到，大陆可达性未知）。

## 7. 控制主机的网络环境

- 调研时在这台电脑上探测：所有域名都解析到 198.18.0.0/16（虚拟网卡代理使用的虚拟地址段），`google.com`、`duckduckgo.com` 也能连通；上面的大陆可达性结论只来自 GreatFire 记录与域名归属，本机实测不代表纯大陆直连。
- 进程环境中没有 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`。
- Python 的 `ipaddress` 把 198.18.0.0/15 归为私有地址（不属于全球可达地址）。
