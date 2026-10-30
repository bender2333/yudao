# agent 试用技能修订与验证

日期：2026-10-29。依据：[ADR-0039](../adr/0039-agent-trial-observation-reproduction-and-judgment.md)、[实施方案](skill-revision-plan.md)及用户回复「可以」。Q1–Q11 已实施，三项原生 subagent 复核与相关本地行为验证完成；整轮真实模型试用未重跑。

## 复盘依据与修订结果

复盘读取 #839、#1153、#1212、#1231 四篇试用帖及相关裁决快照；重新核算本机两组归档中的五份导出，共 11,401 条事件、931 次模型尝试。#839、#1212 的结论来自帖子和裁决，未核对这两轮的全部原始日志。原始复盘及来源保存在本机 `.tmp/trial-skill-review-2026-10-29/`。

| 复盘发现 | 当前技能与工具的行为 |
| --- | --- |
| wheel 声明与实际服务代码、部门配置不一致 | 核对实际解释器、导入位置与安装文件内容，保存 wheel SHA-256、进程身份和逐部门配置；每段保留身份快照 |
| 工单关闭、修复进度与问题裁决混算 | 裁决、修复、修复后验证分别记录；缺陷命中率仅由明确成立与不成立的裁决生成，体验采纳单列 |
| 未触发、条件变化、重读旧证据混为复现结论 | 区分复现到、触发后未出现、未触发、条件不同、证据复核及尚未执行；复现者只接收操作与待观察现象 |
| 固定任务夹带探索，模型分工存在冲突 | 采用 `trial-tasks@4`；F1、R1 与探索分别记录；复现保持原部门配置；R1 交接准备、四步、上限和异常处理 |
| 数字、评分状态与第一眼记录遗漏 | 从结构化记录生成事实表，核对事件、评分、原文行引用与明确缺项；观察耗时、事件跨度和请求耗时分开 |
| 凭据在交接与输出中泄露 | 凭据使用环境变量引用输入，报告及错误输出脱敏；发布材料与原始本地证据分别处理 |

主入口为 [trial/SKILL.md](../../.claude/skills/trial/SKILL.md)，各段方法按条件读取。任务集的四段 R1 输入与修订前提交 `0cec98920f2cb4c6ab0422d76b3c361048b92c0a` 逐行比较，数量均为四段，内容未变。

## 实际验证

| 对象或入口 | 结果 | 本机证据 |
| --- | --- | --- |
| `node .tmp/trial-skill-revision/verify.mjs` | 13/13 通过，核对五份真实导出、时间、配置差异、整理检查点、裁决、身份、引用与脱敏 | `.tmp/trial-skill-revision/assertions/checks.json` |
| `node .tmp/trial-skill-revision/native-report/check.mjs` | 23/23 通过，覆盖异常结构、空身份及评分、推理配置、输入模态、复验来源、凭据脱敏和五份导出的合法档位变化 | `.tmp/trial-skill-revision/native-report/checks.json` |
| 浏览器输入，实际 headless Chrome | 7/7 通过，覆盖凭据、错一位与恢复、多行输入、参数冲突及日志脱敏 | `.tmp/trial-skill-revision/browser/result.json` |
| 已安装 wheel 的模型页面 | 3/3 通过，输入后恢复，没有保存测试凭据 | `.tmp/trial-skill-revision/browser/installed-page.json` |
| 实际 wheel 实例的初次验证 | 六项通过：重启保留数据及历史、Inspect、预检、拒绝 editable、拒绝同版本不同 wheel、停止后端口关闭 | `.tmp/trial-skill-revision/runtime-checks/result.json` |
| 原生 subagent 实例工具复核 | 14/14 通过，包含无效目录、端口、wheel 和进程时间的拒绝；最后一次正常启停七项通过 | `.tmp/trial-skill-revision/native-runtime/instance-results.json`、`final-lifecycle-results.json` |
| 原生 subagent 浏览器复核 | 9/9 通过，核对时间、凭据输入、错误参数、eval 与 watch 输出脱敏 | `.tmp/trial-skill-revision/native-runtime/browser-results.json` |
| 预检与启动超时 | 常规及相对数据目录预检均退出 0；一秒就绪上限按预期退出 1，清理后无后代进程或监听 | `.tmp/trial-skill-revision/native-runtime/preflight-results.json`、`preflight-relative-results.json`、`startup-timeout-results.json` |
| 原生 subagent 收尾与脱敏 | 自建服务及浏览器的记录进程全部退出，五个记录端口无监听；120 份检查材料未发现凭据泄露 | `.tmp/trial-skill-revision/native-runtime/cleanup-results.json`、`redaction-results.json` |
| 原生 subagent 规则一致性复核 | Q1–Q11 均覆盖；21 个必要引用目标存在；当前任务集引用统一为 @4；R1 交接已复读 | `.tmp/trial-skill-revision/native-skill-review/review.md` |
| 最终版本、语法与收尾核对 | 七份受控文件及十一份验证脚本的 SHA-256 与审查记录一致；四份 Node 与两份 PowerShell 脚本语法通过；主会话核对的三份实例记录均无进程及端口遗留 | `.tmp/trial-skill-revision/final-integrity/hash-agreement.json`、`node-syntax.json`、`powershell-syntax.json`、`cleanup.json` |
| 任务输入保留 | 四段原话与修订前版本一致 | `.tmp/trial-skill-revision/final-integrity/task-inputs.json` |

实例验证使用真实 wheel `yudao_harness-0.1.1-py3-none-any.whl`，构建提交 `f61ac6a6d87ccce9dc3b4bb065bbc873a7d5818c`，SHA-256 为 `388e58e4550f6d009d8bd005ce186a22e9d238394f10b43cc9242184bf1295ba`。这用于验证辅助工具的包身份与运行行为；未将其记为当前 main 产品的验收。五份历史导出保留其原任务集身份。

模型目录声明与单次调用值分别核对。部门工作请求的档位选择保持一致，整理请求按用途使用最低档位，实际档位逐次保留；整理档位不同单独提示。五份真实导出的全部用途配置均经过正向核对，工作档位或模型声明实际改变时仍阻止认定同条件。历史运行没有完整实例清单，本次没有补造旧身份；合法部分完成报告的行为使用真实独立实例另行验证。

## 独立复核与前向试验

按用户要求使用三个原生 subagent：`runtime_review` 负责实例、预检与浏览器工具，`report_review` 负责读数和报告工具，`skill_consistency` 只读核查规则与消费方。文件修改范围分别指定，主会话汇总并核对实际文件。技术复核不替代项目 PR 审查或用户试用结论。

此前的首次独立前向试验通过本地 Claude CLI 执行，给出技能和必要原始材料，未提供预期结论；随后按观察结果做了定向复测。它们验证任务书、配置差异与证据边界，定向复测不计为全盲测。产物位于 `.tmp/trial-skill-revision/forward/` 与 `forward-second/`。

## 适用范围与限制

- 本次辅助工具检查向产品部门模型发送的请求数为零，没有重新运行整轮 F1/R1，没有给出新的产品验收或 CI 通过结论。完整试用仍按新版技能执行，并记录当轮实际包和配置。
- 通用 Codex `quick_validate.py` 对修订前后技能均报告不支持已有的 Claude `argument-hint` 字段；该检查未通过。保留此调用提示，检查结果见 `.tmp/trial-skill-revision/skill-validator.json`。语法、实际工具行为与文档一致性分别核对。
- 工具核对能够机械确定的身份、数字、引用、结构与脱敏；架构师裁决网页的内容仍须由协调者读回，问题成立及体验建议采纳由维护者明确判断。
- 检查以实际工作区文件为准，原始归档保持原样；本机 `.tmp/` 证据不进入版本控制。其他会话的修改与已有安装保持原样。
