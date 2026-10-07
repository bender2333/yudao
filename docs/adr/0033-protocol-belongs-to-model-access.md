# 调用协议属于模型访问定义

[ADR-0004](0004-one-protocol-per-connection.md) 把调用协议放在连接（Provider 配置）上，同一服务方案要用另一种协议时另建一份连接。M1 试用（0.1.1）时用户用 OpenCode Go 的 Key 无法完成配置。models.dev 中 `opencode-go` 的 34 个模型，22 个使用服务的默认协议 Chat Completions（`@ai-sdk/openai-compatible`），7 个单独声明 Responses（`@ai-sdk/openai`），5 个单独声明 Anthropic Messages（`@ai-sdk/anthropic`）。按一份连接一种协议，同一个 Key 要建三份连接，用户还要自己知道每个模型用哪种协议；连接默认 Responses 时只有 7 个模型能用。OpenCode 与 models.dev 把 OpenCode Go 作为一个服务，个别模型单独声明协议。2026-10-07 用户采纳推荐，决定：

- 调用协议是模型访问定义的字段，取值为 Responses、Chat Completions、Anthropic Messages。连接不声明协议：一份连接是一个服务方案下的地址与凭据引用。
- 新建访问定义时预填协议：内置服务方案取模型能力表中这个模型的协议，能力表从 models.dev 每个模型的 `provider.npm` 取得，没有单独声明的模型取服务方案的默认协议；自定义服务预填 Chat Completions。用户可以修改。
- 请求时，基址取所属连接的地址；内置服务方案按这个模型的协议取预置表中的请求基址。请求路径与认证方式由协议的适配器决定：Responses 与 Chat Completions 在基址后拼接 `/responses`、`/chat/completions`，使用 Bearer；Anthropic Messages 去掉基址末尾的 `/v1` 后拼接 `/v1/messages`，使用 `x-api-key`。
- 获取模型列表与连接测试按服务方案规定的认证方式带上凭据；自定义服务使用 Bearer。
- 修改一个访问定义的协议，只使这个定义回到候选；修改连接的地址或凭据引用，使该连接下全部定义回到候选。
- 目录文档在连接上声明协议时，读取直接报错，不迁移。

考虑过的做法：保持一份连接一种协议，从 OpenCode Go 的模型列表加入模型时，按能力表把它放进对应协议的连接，没有就自动建立，几份连接共用同一个凭据引用。用户只填一次 Key，但同一个订阅在界面上出现最多三份连接，系统还要多出自动建立与命名连接的规则。

理由：

- 协议是一个模型在这个服务上的调用方式，属于每个模型。放在连接上，用户要为一个订阅维护几份连接，并且自己查每个模型的协议。
- 与 OpenCode 和 models.dev 的数据结构相同，能力表可以直接取得每个模型的协议。

后果：

- 模型能力表的每个模型增加协议，提取脚本从 models.dev 的 `provider.npm` 映射；服务方案预置表增加默认协议。
- 准入记录中的协议取自访问定义；[模型管理设计说明](../design/model-management.md)第 4.1 至 4.4 节与第 9.1 节随之修改。
- 只接受 `x-api-key` 的自定义服务，获取模型列表会失败，界面写明请求的地址与状态码，用户可以手动添加访问定义。
- ADR-0004 由本决定取代。
