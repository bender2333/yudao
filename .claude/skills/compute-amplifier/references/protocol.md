# 运行与护栏协议

## 可信策略与启动条件

协调者在仓库外、自己独占的运行目录保存用户意图、批准原话、时间、15 行卡、提案、模型身份、Token 预算、候选目录、执行器配置、原始证据和状态。候选进程没有这个目录的读写权限，隐藏材料另放裁判专用目录；只向工人传公开任务书。协调者和裁判的执行器从可信安装运行，不从候选提交加载代码。

把批准的阶段策略放在 `.claude/skills/compute-amplifier/policies/<阶段标识>.json`，由用户批准的准备 PR 合并，必须先于候选 PR 存在于基线。标识只允许小写字母、数字、连字符。策略的示意结构如下，示意路径需按批准清单填写：

```json
{
  "stage": "approved-stage",
  "approvers": ["bender2333"],
  "issues": {
    "123": {
      "mode": "implementation",
      "allowed": ["harness/example.py", "agents_jour/123.md"],
      "middle": ["harness/contracts.py", "harness/tests/openapi/openapi.json", "client/src/renderer/src/api/generated/"],
      "kernelApprovedPaths": []
    }
  }
}
```

`allowed` 是精确文件路径或以 `/` 结尾的目录前缀，清单包含日记与生成物。清单中只有预先批准的内核完整文件名可以放入 `kernelApprovedPaths`。`middle` 必须覆盖阶段涉及的全部契约源码、版本、快照和生成物，未涉及的仓库合同也登记，避免将它们误当外环；可信内核清单中的 material 与 module 全部接受内环检查。规则、技能、CI、评价和发布代码固定属于受保护路径。

CI 工作流 `experiment-scope.yml` 对 `experiment/` 分支运行，读取 PR 目标基线的脚本与阶段策略，获取工单完整标签事件，验证 `kernel-approved` 最后一次有效加标由批准者完成，且发生在 PR 创建以前。授权还必须匹配基线策略中的工单与完整路径。候选不能通过修改自己分支的策略或检查程序取得授权。更改策略走独立准备 PR，由用户审查批准；工人没有建立这种 PR 的权限。

WRAP 修改已经存在的 JSON 数据时，只能增加对象字段、保留旧值；数组和已有标量保持原样。已存在的 Pydantic/TypeScript 签名变更和 OpenAPI 语义兼容性需要独立的、在可信基线登记的专用检查器；通用范围检查对修改现有非 JSON 契约会拒绝，不能临时放宽。新建签名文件可以通过范围检查，旧公开签名需要在旧文件保持不变，通过新增版本与新类型扩展。独立契约检查器还必须覆盖 OpenAPI 的 required、enum、additionalProperties、默认值与版本提升等语义；JSON 字段包含关系仅是文件护栏。

启动前由独立 preflight 执行器实际核验：

- 批准对象摘要、可信策略、工单原生依赖与实验分支命名一致；候选没有 GitHub 写令牌。
- GitHub main 的有效规则要求 `experiment-scope` 成功，或协调者的合并身份有同等强制门禁；即使使用 `--admin`，合并适配器仍逐项核对。检查实际规则结果，缺少门禁就返回 blocked，禁止只看工作流文件存在。
- 候选账户对裁判材料、协调账本、其他候选目录与可信脚本实际无写权限；裁判材料对被测产品账户实际不可读。保留 ACL/容器挂载与真实权限探测证据。
- 异构模型、VLM、已锁版本的复杂度工具、浏览器、独立检查器和 GitHub 认证可用。
- 硬 Token/费用/时间预算由执行器实际限制，子代理继承限额。30/40/30 是阶段分配；尝试失败照常计入。

工作流刚加入分支时不能为自己提供可信检查。准备 PR 合并且 GitHub 规则核验完成后才能启动实验。本技能的交付不自动修改仓库线上规则或启动实验。

## 确定性筛选

独立裁判生成三个对象的数组，保存在工人无写权限的文件中。每项字段：共同 `base`、完整 `head`、整数 `pr`、`changedLines`、`complexity`、`outOfScope` 数组、`evidence` 路径和 `checks` 数组。每条检查写 `name`、同一个完整 `head`、`conclusion`；必须至少有 `check`、`experiment-scope`、`independent-contract`，还有该工单要求的全部检查。通过只能填 `SUCCESS`；其他状态保留真实值。

`changedLines` 由相同基准上的 `git diff --numstat --no-renames <base> <head>` 增加与删除行数相加，包含全部跟踪文件。二进制改动单独披露，不可填写零行进入排名；这类工单在批准卡明确替代度量，否则挂起。`complexity` 是同一锁定工具对该工单源文件范围测得的圈复杂度合计。不能只统计候选新增的函数而忽略被它改动的旧函数。合格条件先于排名，体积和复杂度都不能抵消检查失败。

```powershell
node .claude/skills/compute-amplifier/scripts/select.mjs <裁判目录>/candidates.json
```

退出码 0 表示选出赢家，2 表示没有合格候选，输入无效返回非零。脚本只选择，不合并；合并适配器必须自行从 GitHub 和证据目录核验记录，防止使用过期记录。

## 外部执行器与巡航

巡航负责轮次与工单失败的机械上限，不嵌入某一家模型服务。preflight、solo、trial、architect 使用本机已经配置的真实 agent harness 执行器。每个执行器是绝对可执行路径与参数数组，`shell:false` 启动；需要 PowerShell 时显式指定 `pwsh.exe` 和 `-NoProfile -File <可信脚本>`。任务文字通过标准输入 JSON 传入，凭据从对应账户环境取得，不放在配置、参数、结果和日志里。适配器及其后代受操作系统任务对象、容器或运行器超时约束，单独结束父进程不能视为终止全部工作。

执行器读入 `{version,role,identity,round,config,resultFile}`，执行相应技能后，在指定的新文件写结果，退出码为 0。返回公共字段 `identity`、`round`、`evidence`（已经存在的绝对路径）和以下角色字段：

| 角色 | status 与必需结果 | 成功条件 |
| --- | --- | --- |
| preflight | passed / blocked | 上述权限、门禁与硬预算均实际核验，证据保留全部检查结果 |
| solo | completed / failed / blocked；issues: `[{number,status:passed或failed}]` | completed 表示范围内实施队列已经清空；每轮每张尝试过的工单只记录一次结果；同一工单三个候选全部失败只算一次 |
| trial | passed / failed / blocked；commit、wheel_sha256、unresolved | 调用 `/agent-trial`，绑定实际 main 和 wheel，全项通过才能 passed |
| architect | ready / blocked；issues: `[工单编号]`、unresolved: `[]` | 调用 `/trial-architect`，修复规格、依赖已写入且核验完毕 |

solo 内部每轮每张工单最多一次候选批次，不运行自己的无限重试循环。控制器将失败的轮次与当前工单计数交给执行器；未尝试的工单不重置失败计数。状态中 `rounds` 在启动执行器以前保存，成功工单清零连续失败数，第三次失败直接挂起；第三轮试用失败不再调用架构师开第四轮修复。一个轮次的 solo 没完成时跳过试用、转架构师；环境问题立即挂起。

配置在运行目录外或同目录均可，但候选不可读取；启动以后按原始字节 SHA-256 固定身份，修改任何字段需要新授权、新目录。配置字段：

```json
{
  "runDir": "C:/实验记录/已批准阶段-唯一运行身份",
  "repository": "bender2333/yudao",
  "issue": 123,
  "worktrees": ["C:/实验工人/a", "C:/实验工人/b", "C:/实验工人/c"],
  "approval": "批准记录绝对路径",
  "budget": {"totalTokens": 1000000, "planning": 0.3, "implementation": 0.4, "trial": 0.3},
  "adapters": {
    "preflight": {"executable": "C:/可信执行器/preflight.exe", "args": [], "timeoutMs": 60000},
    "solo": {"executable": "C:/可信执行器/agent.exe", "args": ["experiment-solo"], "timeoutMs": 14400000},
    "trial": {"executable": "C:/可信执行器/agent.exe", "args": ["agent-trial"], "timeoutMs": 14400000},
    "architect": {"executable": "C:/可信执行器/agent.exe", "args": ["trial-architect"], "timeoutMs": 14400000}
  }
}
```

这些路径展示配置结构，不能作为可用安装执行。协调者必须选用已安装 harness 的真实入口，编写并实际验证适配器和权限探测后填写配置。禁止用固定成功 JSON 代替执行器、测试、试用或权限核验；缺少执行器时保留准备产物并返回受阻。

预先创建真实运行目录，启动或恢复使用同一个命令：

```powershell
pwsh -NoProfile -File .claude/skills/compute-amplifier/scripts/milestone-autopilot.ps1 -Config <配置文件绝对路径>
```

启动以前可以运行 `node .claude/skills/compute-amplifier/scripts/run.mjs --validate <配置文件绝对路径>`，只验证配置、可执行文件存在与目录相互独立，不启动代理、不修改 GitHub、不创建账本。输出 `preflight:not-run`，配置验证不代表权限或硬预算已经通过运行时核验。

控制器退出码 0 表示试用 passed，2 表示挂起。`state.json` 采用临时文件加原子更名保存，`coordinator.lock` 排斥同目录重复启动。正在运行时中断，恢复立即挂起并保留轮次、已有产物；不会重复执行未知结果的合并或建单。操作系统强制结束留下锁时，先确认原协调者与全部子进程已经停止，核对身份，再由协调者手动删除本运行的锁文件，重新执行以上命令。挂起只允许补发远端通知，不能继续编码；用户重新授权后新建运行并引用旧证据。

通知用运行身份去重，先改流程标签再发评论；失败保留 `notificationPending`。GitHub 结果未知时恢复先读回当前标签与评论，不重复写入已有评论。原始证据留运行目录，公开评论只给脱敏摘要和证据索引。
