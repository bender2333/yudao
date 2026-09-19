# 端点按协议建模，厂商不进数据结构

Stage 2.7 从「只接 OpenCode Go」放开到多厂商与自定义接入，先要回答厂商是不是数据结构的一个维度。决定：保持三层——服务方案、Provider 配置、模型访问定义；一份连接的端点能力按**协议**表达（Responses / Chat Completions / Anthropic Messages），厂商只作为服务方案预置的命名与来源出现，不出现在任何字段里。

理由：同一品牌的订阅与 API 是两套端点、两套认证，按品牌建模会把它们挤进同一份配置；而一个中转可以同时供多条协议，协议放在连接级装不下。Cherry Studio v1 的 `{apiHost, models[]}`（单端点、模型内嵌）在 v2 被 `endpointConfigs: Record<EndpointType, …>` 取代；cc-switch 把 `apiFormat` 放在 provider 级，是同一个坑的另一处。

后果：新增厂商等于新增一行预置数据，不新增代码分支或适配器类；一个模型访问定义只声明一条协议，需要多协议时在同一模型上建多条定义。
