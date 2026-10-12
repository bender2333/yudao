# OpenCode Go 与统一 Provider 层：一手资料核对

日期：2026-09-19。用途：支持 Stage 2.7 / D23 设计。只读取公开文档、公开模型列表与源码；没有登录、购买订阅、读取用户密钥或发送付费推理请求。本报告不构成真实接入验收。

## 1. 可直接用于设计的结论

| 结论 | 一手依据 | 对 Yudao 的影响 |
| --- | --- | --- |
| Go 是订阅套餐，客户端使用 API Key | [Go 官方说明](https://opencode.ai/docs/go/) “How it works”：登录 Zen、订阅 Go、复制 Key，客户端粘贴 Key | 首批不做 OAuth 浏览器登录；接入使用 D22 页面凭据入口 |
| 允许其他编码代理使用 | 同页 “Where can I use it?” 明确包含 other coding agents | Yudao 使用自己的身份，不冒充 OpenCode、OMP 或其他客户端 |
| 需要客户端身份与稳定会话标识 | 同页要求自己的 User-Agent，以及每段会话稳定的 x-opencode-session | 统一请求模块对工作、重试、压缩和测试路径都补齐正确身份；会话标识与尝试标识分开 |
| 同一 Go 服务下模型协议不同 | 同页 “Endpoints” 列出 Responses、Chat Completions、Anthropic Messages | 协议属于模型访问定义，不能只在 Provider 上设置一个协议 |
| 有公开模型发现入口 | [Go models](https://opencode.ai/zen/go/v1/models) | 可以手动刷新候选模型，但不能把列表存在视为有权限或能力已验证 |
| Go 与 Zen 余额存在服务端联动 | Go 文档 “Usage beyond limits”：用户可在控制台开启 Use balance，限额后消耗 Zen 余额 | Yudao 不替用户开启、不自动切到 Zen；同一端点也不意味着每次消费必然属于套餐额度 |
| 套餐额度可变，实际用量可在控制台查看 | Go 文档 “Usage limits”，[Zen 说明](https://opencode.ai/docs/zen/) | 不硬编码“无限”“剩余请求数”或把月费分摊为实际单次成本 |

官方 Go 页面本次显示最后更新为 2026-09-18。页面未来可变化，具体模型和限额不作为长期硬编码合同。

## 2. 协议与模型列表的实际观察

2026-09-19，公开 GET /zen/go/v1/models 返回 HTTP 200，共 37 个条目。抽查 gpt-5.6-luna、glm-5.1、minimax-m2.7，条目只有 id / object / created / owned_by，没有 context_window、输出上限、tool use 或路由协议。

虽然文档称其提供模型和 metadata，本次实际响应不足以直接生成可执行配置。容量和工具能力仍需要可信来源及独立验证；未知必须保持未知。

以下仅为当日官方协议示例，不表示 Yudao 已支持：

| 示例模型 | 官方端点 | 协议族 |
| --- | --- | --- |
| gpt-5.6-luna | https://opencode.ai/zen/go/v1/responses | Responses |
| glm-5.1 | https://opencode.ai/zen/go/v1/chat/completions | Chat Completions |
| minimax-m2.7 | https://opencode.ai/zen/go/v1/messages | Anthropic Messages |

来源：[Go Endpoints](https://opencode.ai/docs/go/#endpoints)。

OpenCode 配置中的 opencode-go/<model-id> 是客户端的选择身份；上游请求模型使用对应 Model ID。Yudao 不应把客户端前缀拼进实际请求模型字段，也不按模型名字猜路由。

尚未验证：所选账户的套餐权限、上述模型当前的实际工具调用/流式/压缩行为、真实最大容量、正式返回的限额错误码。必须在 2.7 实施验收中验证。

## 3. 额度查询：存在源码，稳定性未得到公开合同保证

本次读取 OpenCode 上游 dev 的固定提交 5f9d9187c01708b4e700c9c81c1045ab482bf31d：

- [usage 路由源码](https://github.com/anomalyco/opencode/blob/5f9d9187c01708b4e700c9c81c1045ab482bf31d/packages/console/app/src/routes/zen/go/v1/usage.ts)：Bearer Key；无 Key / 非法 Key 为 401；无订阅为 403；使用 rolling / weekly / monthly 窗口，每窗有 status、percent、resetsAt。
- [models 路由源码](https://github.com/anomalyco/opencode/blob/5f9d9187c01708b4e700c9c81c1045ab482bf31d/packages/console/app/src/routes/zen/go/v1/models.ts)：基于服务端模型目录构造响应。
- usage 路由先经过 proxyInference；源码中的旧窗口形状不保证等同当前线上响应。官方文档本次描述按模型额度，不能用源码中的总体窗口强行冒充逐模型剩余额度。

没有使用任何用户凭据调用 usage。它只作为可选、只读的 Provider 扩展：有经过核验的数据才显示，带来源和采集时间；格式变化或无法获取时显示未知/过期，不阻塞正常推理，不猜计费或账户权限。

首批 Go 接入不依赖这个未公开稳定的接口。订阅入口和官方控制台链接、推理错误分类、真实请求用量是必要项；自动展示套餐剩余额度可后置。

## 4. OMP 借鉴依据

实际本机副本：D:/codes/oh-my-pi。提交 e3106be68f778635da3a17106835ce2e0e6992af，已跟踪文件无差异，只有 .codegraph 未跟踪。以下使用固定提交链接：

| 机制 | 源码证据 | 采用范围 |
| --- | --- | --- |
| 统一模型调用，内部按模型 API 分派 | [stream.ts](https://github.com/can1357/oh-my-pi/blob/e3106be68f778635da3a17106835ce2e0e6992af/packages/ai/src/stream.ts#L874)，stream / streamDispatch 按 model.api 分派 | 采用统一请求/结果接口与协议适配；不照搬重试、并发调度或模型切换策略 |
| 认证方式与调用协议分开 | [auth-storage.ts](https://github.com/can1357/oh-my-pi/blob/e3106be68f778635da3a17106835ce2e0e6992af/packages/ai/src/auth-storage.ts#L108)，ApiKeyCredential / OAuthCredential | 首批只实现 Go 所需的 API Key；其他订阅确定后在凭据实现内扩展，不加空 OAuth 系统 |
| 跨协议统一请求身份 | [inference-headers.ts](https://github.com/can1357/oh-my-pi/blob/e3106be68f778635da3a17106835ce2e0e6992af/packages/ai/src/providers/inference-headers.ts#L35)，OpenCode 服务使用自身 User-Agent 和 x-opencode-session | 采用真实 Yudao 身份和稳定会话；不复用 OMP 的产品标识 |
| 协议注册与扩展分离 | [api-registry.ts](https://github.com/can1357/oh-my-pi/blob/e3106be68f778635da3a17106835ce2e0e6992af/packages/ai/src/api-registry.ts#L19) | 用有限内置适配器满足三协议，不先建插件市场 |
| Go 用量作为单独能力 | [usage/opencode-go.ts](https://github.com/can1357/oh-my-pi/blob/e3106be68f778635da3a17106835ce2e0e6992af/packages/ai/src/usage/opencode-go.ts#L19)，注释明确标为 undocumented，处理缺失窗口 | 查询与推理解耦；不照搬按额度排序凭据、自动轮换和静默使用旧数据的逻辑 |

重要差异：本地 OMP catalog 的 CHANGELOG 曾将 deepseek-v4-flash 固定为 Responses，而当日 Go 官方表列为 Chat Completions。证据来自不同时间/接口行为，不能只复制 OMP 的特例或按字符串猜协议。Yudao 的采用模型需固定来源版本并做真实工具往返；路由不符明确报错，不在一次失败后自动换协议。

## 5. 现有依赖与设计取舍

Yudao 的 pyproject.toml / uv.lock 当前只有 OpenAI SDK、HTTPX 等既有依赖，没有 Anthropic SDK 或 python-dotenv。

- Responses 保留官方 SDK 路径；Chat Completions 优先复用已安装 OpenAI SDK，不自写流式协议。
- Anthropic Messages 在该协议工作包选择官方 Python SDK；不假设 OpenAI SDK 支持另一套 wire protocol。
- HTTPX 复用于模型发现及可选只读状态，不承担新的 Agent loop。
- .env 解析/原子保存先比较维护中的 python-dotenv 能力与当前文件提交要求，避免自行定义不完整 dotenv 语法。
- OMP 的 TypeScript 包不作为 Python 运行依赖，不引入一个代理进程转发全部模型请求。

## 6. 研究限制

本次核对证明接入方式、协议区别与可借鉴分层，不证明真实账户可用。不能把公开 models 返回 200 称为认证成功或订阅有效。没有做付费调用、购买订阅、账户设置修改或 Go 余额消耗。

研究子代理因模型服务 503 未启动，本报告由主代理按上述公开来源完成。
