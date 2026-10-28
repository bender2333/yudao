# D31 部门内的外包角色

确认时间：2026-09-25。状态：需求已记录，未实施。路线位置：待定。相关记录：D26 [部门内多角色与多循环](department-roles.md)、D29 [远程执行环境](remote-execution.md)。

## 用户原话

2026-09-25 讨论后端分层、RPC 与微服务化时：

> 关于RPC，我的考量是未来的分布式部署和微服务化，如果能把部门或者其中的agent 角色单独做成微服务的方式，或者说，通过集群来部署yudao，让他变得像一个云原生的应用。 还有个额外的需求，就是部门内会有外包角色，这个外包角色就是agent，比如claude /pi这种

架构师分析外包角色的接入方式与原则冲突之后，用户回答：

> 外部角色确定需要

## 已确认

- 部门内会有外包角色，外包角色由外部 agent 担任，例如 Claude、pi。
- 这项需求一定要做。

## 讨论中的分析

以下是架构师的分析，未经用户逐项确认。

1. 外包角色与自有角色使用同一个角色定义（职责、输入、输出、权限）。自有角色的步骤由控制核心驱动（[骨架与应用设计说明](../design/skeleton-and-application.md)第 5.3、6 节）；外包角色由控制核心派发给外部 agent，外部 agent 收到分派说明与该角色可以看到的资料，交回提案与证据（总图第四节「执行」缝）。外部 agent 在执行位置上以自己的进程运行，使用按内容摘要取出的工作区快照（总图第四节「动作」缝、[执行环境服务设计说明](../design/execution-environment.md)第 8 节）。
2. 接入方式使用 ACP（Agent Client Protocol），Yudao 作为客户端。Claude 通过基于 Claude Agent SDK 的 `@agentclientprotocol/claude-agent-acp` 接入；pi 通过 `pi-acp` 适配程序接入；OMP（提交 `fdfeef1f78`）自带 ACP 模式，位于 `packages/coding-agent/src/modes/acp`；OpenCode（提交 `0027387`）自带 ACP 支持，位于 `packages/opencode/src/acp`。
3. ACP 提供以下控制手段。外部 agent 调用工具之前向客户端请求许可，Yudao 按角色权限批准或拒绝。客户端声明文件与终端能力后，agent 的文件读写与命令执行交给客户端完成（OMP 的 `packages/coding-agent/src/modes/acp/acp-client-bridge.ts` 第 26 至 66 行），Yudao 把这些操作转交工具执行服务，登记命令、工具回执与工作区控制继续有效。agent 的消息、工具调用与计划以流的形式发给客户端，作为证据记录。客户端可以取消会话，也可以载入以前的会话（OMP 的 `acp-agent.ts` 第 657 行）。Claude 的适配程序是否同样把文件读写与命令执行交给客户端完成，待核实。
4. 模型调用：模型调用只通过 Provider（总图第四节「模型」缝）。Provider 对外提供兼容 OpenAI 与 Anthropic 协议的模型入口（D23 已实现 OpenAI Responses、OpenAI Chat Completions 与 Anthropic Messages 三种协议的适配），外部 agent 把模型地址指向这个入口，凭据由 Yudao 管理，调用尝试与用量照样记录。使用订阅账号还是 API 密钥、使用条款是否允许自动化调用，待核实。
5. 对确定性编排的影响：外包角色把会话内部的上下文管理与规则遵守交给外部 agent，控制核心只装配它的初始输入，每次请求重新计算的当前状态栏目不适用于它；Yudao 保留流程决定（状态主权）、信息流向（输入的资料与交出的内容）与工具：外部 agent 的工具调用经过 Yudao 的工具，工具许可、接触时附加与查询范围照样有效。外部 agent 会话内部的每一步不由控制核心驱动，它的结果由独立核验（确定性检查、质检）检验。所以外包只适合结果可以独立核验的执行类角色；作出流程决定、需求取舍、放行判断的角色由 Yudao 自己执行。外部 agent 的完整对话记录属于作者的工作过程，不越过部门边界，其他部门只看到 Yudao 整理的提案、证据与摘要。
6. 状态主权、可见范围与恢复对外包角色照样成立：外部 agent 结束一轮对话只代表交回提案，宣布完成仍由控制层决定；外部 agent 只拿到该角色可见范围内的资料；会话中断时在途动作的结果无法确定，按[恢复契约](../design/recovery-contract-and-fault-matrix.md)第 4 节处理：先自动核实，其余交还发出它的会话。

来源：

- https://github.com/agentclientprotocol/claude-agent-acp
- https://www.npmjs.com/package/@agentclientprotocol/claude-agent-acp
- https://agentclientprotocol.com/get-started/agents

## 设计中待用户确认的规则

- 哪些角色允许外包。
- 外部 agent 的模型调用是否必须经过 Provider 的模型入口。
- 外部 agent 的文件读写与命令执行是否必须由工具执行服务完成；不支持把文件与命令交给客户端的 agent 能否接入。
- 凭据与用量：使用订阅账号还是 API 密钥。
- 路线位置。

## 实现状态

未实施。
