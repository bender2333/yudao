# 三部门 Web 原型讨论记录

## 2026-09-06

### 用户已确认

- 当前只讨论并制作独立原型，不修改项目代码、数据和运行现状。
- 主要不满是现有工作方式，需要重新组织页面与操作。
- 原型分为两个层次：总览，以及可进入的部门内部页面。
- 总览需要显示三部门的数据循环、信息流动、当前任务状态，并提供面向整个任务的用户输入。
- 部门内部需要查看 Context、Provider 和 Prompt，提供发给当前部门的追加对话与指导。
- 部门指导采用追加方式，不编辑或删除历史消息。
- 部门内部可以使用全新的独立页面。

### 用户已认可的首版界面

- 点击部门后替换整个主工作区，提供返回总览和切换部门的入口。
- 部门内部以工作对话为主区，以 Context、Provider、Prompt 为检查区。
- 区分部门工作记录与本次实际上下文；显示消息来源以及用户指导的处理状态。
- 采用中性界面，以局部颜色标示活动、等待和异常。

### 新增可观测性讨论

- 用户认可现有工作界面，并要求增加可观测性，展示原始模型请求、Raw Data、LLM Token 统计。
- 用户指定参考 Oh My Pi，描述为输入 status 后打开的后端 Web 页面；正在核对实际界面。
- 本轮原型提案：单独设置观测入口，包含模型请求记录、单次尝试详情、用量统计，并从部门 Context 直达对应模型请求。
- 请求重试的各次尝试需要分别可见。缓存 Token 属于输入 Token 的一部分，汇总不重复计数；区分估算、供应商上报与未上报。
- 可观测性仍仅制作示例原型，不连接实际日志或模型，不实施项目后端采集。

### 已核对的数据边界

- 项目目前保存步骤级 model_request、输出 item 和 provider usage；完整 Provider response envelope 尚未保存。原型里完整响应 JSON 必须明确为示例，不能宣称来自当前运行。
- Provider 原始 usage.input_tokens 包含缓存；项目归一化 Usage.input_tokens 不含缓存。观测界面采用“输入（含缓存）”口径，缓存读作为其中的子项展示。
- 模型请求尝试按 activation、step、attempt 关联；部门协作 request_id 是另一种请求，界面需要区分名称。
- 耗时是本地测量；费用尚未提供时显示“未上报”，不写成零费用。

### OMP 参考依据

- 已核对公开仓库 https://github.com/can1357/oh-my-pi 的 packages/stats，文档中的启动入口为 omp stats。本机未找到 omp 命令；本轮未启动该服务。
- RequestsRoute：按模型、时间、Token、费用估算、耗时、状态浏览请求；RequestDrawer 展示指标、Output Payload、Raw Request Metadata。
- TracesRoute / TraceView / SpanDrawer：从 session trace 下钻到 span 与 Raw Entry JSON。
- aggregator.getRequestDetails 当前仅取一个 journal entry，仍有取得父消息/上下文的 TODO；OMP 的 Raw Request Metadata 不能直接视为完整上游网络请求。
- 本原型借鉴“请求列表 → 请求指标与原始内容 → 执行事件原文”的查看路径，增加部门与当前任务的关联。

### 原型边界

- 原型及验证文件保存在本目录，位于 D:/codes/yudao 项目之外。
- 使用示例任务和示例配置；发送仅更新原型内存，不连接任何项目 API。
- 不对真实部门发消息，不启动项目服务，不修改已有 jour.md，不提交或推送项目。
- 真实系统如何接收部门指导、何时处理、如何影响后续工作，留待页面交互确定后讨论。
