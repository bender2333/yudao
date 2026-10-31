# D31 部门内的外包角色

状态：有效。依据：[总图](../architecture.html)第四节「执行」的缝（外包角色是执行的一种实现）与「动作」的缝；[ADR-0044](../adr/0044-verifier-role-and-open-loop.md)（外包不要求下游有核验角色）；设计：[外包角色设计说明](../design/outsourced-roles.md)；相关记录：D26 [部门内多角色与多循环](department-roles.md)、D29 [远程执行环境](remote-execution.md)。路线位置：[总体路线图](../program-roadmap.md)阶段四「子事项承接部门内多角色，外包角色」，第 3 节道 02 角色与外包。

## 已确认

- 部门内会有外包角色，外包角色由外部 agent 担任，例如 Claude、pi。
- 这项需求一定要做。
- 外包不要求下游有核验角色，最差退化成调用一次 OpenCode 这类外部 agent。没有核验角色时，事项以开环完成结束并注明外包；有核验角色时，放行仍只由 Yudao 自己的核验角色给出（[ADR-0044](../adr/0044-verifier-role-and-open-loop.md)）。

## 待定

- 哪些角色允许外包。
- 凭据与用量：使用订阅账号还是 API 密钥。
