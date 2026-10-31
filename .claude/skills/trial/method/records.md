# 试用记录与命令

本文件由协调者在准备本轮记录、整理报告或回查历史时读取。各段代理只接收自己需要的字段。`result.json` 中的文件路径相对该文件所在目录，实例清单里的机器路径保留本地；发布片段另行脱敏。

## 命令

```powershell
node .claude/skills/trial/scripts/readout.mjs <导出...> --json
node .claude/skills/trial/scripts/report.mjs --init <归档>/result.json --task-set trial-tasks@4 --material scenario-3@2 --commit <实际提交> F1=<F1导出> R1=<R1导出>
node .claude/skills/trial/scripts/report.mjs --check <归档>/result.json --json --render <归档>/facts.md
```

`--init` 只根据真实导出建待填写的记录，已有文件不覆盖。显式使用 `F1=路径`、`R1=路径`、`X1=路径`；复现导出在相应问题的 reproduction 中引用。初始化成功不代表记录已经完整。

`--check` 返回 `0` 表示可以生成事实表（complete 或 partial），`1` 表示身份、证据、数字、结构或脱敏错误，`2` 表示命令用法或文件读取错误。`--render` 与检查一起用，检查失败不写事实表。脚本不联网、不发布，https 裁决来源仍要由协调者实际读回核对。

`readout.mjs` 同时导出 `readExport`、`summarize`、`loadExport`、`compareConfigs`。内部计算在 `records.mjs`，报告使用同一份函数。

## 实例清单与阶段快照

`instance.ps1 -Action Start|Inspect|Restart|Stop -Manifest <控制清单>` 管理本轮进程。Start 需要 Python、Wheel、Commit、DataDir、Port、MaterialVersion、SkillCommit；TaskSet 默认 @4，WorkingDirectory 默认临时目录。

模型配置后，协调者从目录与实际调用记录取得 models，保存 JSON 数组：

```json
[
  {"department":"product","model":"<实际模型>","protocol":"chat_completions","context_window":128000,"max_output_tokens":8192},
  {"department":"engineering","model":"<实际模型>","protocol":"chat_completions","context_window":128000,"max_output_tokens":8192},
  {"department":"quality","model":"<实际模型>","protocol":"chat_completions","context_window":1048576,"max_output_tokens":8192}
]
```

这里的数值只是格式例子，填写本轮实际值；model 可以是本地定义名或请求模型名，两种名字都从导出保留，不能推测供应商返回名代表同一配置。

目录声明的 reasoning_mode、default_reasoning_level、input_modalities 一并保存，报告逐部门与实际调用核对。input_modalities 按内容比较，排列顺序不影响结论。models.requested_tier 保存部门工作请求选择的档位，可以为空；它与工作请求核对，并用于比较两次运行的部门计划。

导出中 call_target.requested_tier 是本次调用请求的档位，按部门和用途分别保留。整理请求按 `docs/design/model-management.md`「压缩与测试」使用最低支持档位，可以与工作请求不同；重试或整理记录中实际出现的不同档位如实显示，不据此推定部门设置发生改变。两次运行的工作请求档位不同仍影响同条件判断，整理档位的差异单独提示。

```powershell
pwsh -NoProfile -File .claude/skills/trial/scripts/instance.ps1 -Action Inspect -Manifest <控制清单> -ModelsFile <models.json>
Copy-Item -LiteralPath <控制清单> -Destination <归档>/instances/f1.json
```

每个任务和每次复现保存自己的身份快照。控制清单在重启、停止时会更新，不直接把这个可变文件当作所有历史任务的身份。R1 重启以后再留 R1 快照，原 F1 快照保留原样。

清单字段由脚本产生：schema_version、commit、wheel 的 path 和完整 sha256、python、package_path、working_directory、data_dir、port、pid、process_started_at、identity_checked_at、status、task_set、material_version、skill_commit、models，以及核对明细。身份是实测值，不能为旧导出补造进程或加载记录。没有可核对身份的旧材料仍可用 readout 离线分析，不能据此生成带有已验证版本结论的新发布报告。

重启保留 process_history。tool_sha256 保存当时的技能资源摘要，skill_worktree_dirty 说明工作区是否含未提交修改；有修改时不能仅用 HEAD 冒充实际工具版本。

刚启动尚未配模型时 models 可以为空；早期受阻报告须明确 model_configuration 缺项。已有调用则逐项与实例声明核对。独立复现同时核对包、材料版本、任务集和完整部门计划，并检查实际调用；新数据目录与新 run 都要独立。

## result.json

```json
{
  "schema_version": 1,
  "task_set": "trial-tasks@4",
  "material_version": "scenario-3@2",
  "tested_commit": "<实际提交>",
  "title": "<本轮事实>",
  "instances": ["instances/f1.json", "instances/r1.json"],
  "tasks": [
    {
      "id": "F1", "kind": "fixed", "export_path": "run.export", "instance_path": "instances/f1.json",
      "novice_path": "novice.md", "expert_path": "expert.md",
      "score": {"status": "missing", "reason": "<实际缺项原因>"},
      "missing": []
    },
    {
      "id": "R1", "kind": "fixed", "export_path": "run-r1.export", "instance_path": "instances/r1.json",
      "novice_path": "novice-r1.md", "expert_path": "expert.md", "missing": []
    }
  ],
  "findings": [], "history": [], "first_impressions": [], "missing": [],
  "handoffs": [], "publish": []
}
```

这些是待填格式，不是运行结果。task id 用 F1、R1、X1、X2 等，X 的 kind 为 exploration。缺少整个固定任务时，顶层 missing 写 `{"item":"task:F1","reason":"<原因>"}`，不能默认为通过。任务尚未创建 run 时 export_path 可为空，该任务 missing 写 run_export 及原因。

可选 phase_started_at、phase_finished_at 必须含时区，表示观察者实际起止；事件墙钟由导出另算。两个区间不同会分别呈现，不给自报时间任意加宽容差。

F1 的 score.status 为 done、missing 或 not_applicable：done 引用评分器 JSON 的 path，脚本读取 completion、correctness、material_version、scorer_version；missing 写原因；没有交付时才可明确 not_applicable，已有交付不能用它绕过评分缺项。R1 不要求隐藏评分。

每个固定任务需要 novice、expert 记录，缺少则在该任务 missing 写对应 item 和 reason。第一眼没有收录时写 first_impressions 及原因；已有记录由专家逐项核对并给下面的行引用。覆盖结论在 expert 的承诺清单中逐项保存，未覆盖项也要在 missing 中列明。

## 第一眼与原话引用

```json
{"path":"novice-r1.md","task_id":"R1","start_line":37,"end_line":44}
```

first_impressions 是上述引用的数组。行号指向实际原话片段（可以包含原始表头）；工具只核对行范围、读取并引用原文，不解释 Markdown 或推断表格行数。专家确认引用涵盖本轮实际记录，不能把“没收录”写成“没有记录”。原始文件内的其他内容留在原处，发布只检查引用的片段。

handoffs 列本轮给各代理的任务书路径，用于核对其中的凭据；publish 列实际待发布的正文和附件文字路径。原始导出、novice 与 expert 不因被引用就自动成为发布产物。生成的事实表还会单独扫描路径与凭据。

## 试用发现、复现与裁决

每条 findings 至少有 id、kind、title、task_id、steps、expected、actual、evidence、reproduction、judgment、repair、verification。编号固定为本轮被测提交下的问题，kind 为 defect（缺陷主张）或 experience（体验候选）。影响、绕过办法、查重关系由协调者在同一条记录中保存并用于问题正文。

证据例子：`{"path":"run.export","event_id":"evt_..."}` 或 `{"path":"shots/page.jpg"}`、`{"path":"expert.md","line":12}`。事件与尝试编号必须存在于该导出，行号必须有效。使用完整原始文件引用保留可核对性，发布时只附脱敏片段。

reproduction.status 的含义见 [reproduce.md](reproduce.md)：reproduced、not_observed、not_triggered、conditions_differ、evidence_review、not_run。not_run、not_triggered、conditions_differ、evidence_review 写明 reason；not_triggered 的 trigger_reached 为 false。尚未执行的复现是报告缺项。

reproduced 与 not_observed 同时需要：独立的 export_path、instance_path、trigger_reached=true、复现运行中证明触发及结果的 event_id 证据。包、部门计划、实际配置、任务和材料一致，且新数据目录、新 run 均可核对。重读原 run 只能标 evidence_review。

judgment.status 为 confirmed、rejected、pending；前两种必须给实际架构师裁决的 source（已读回的 https 链接或本地快照路径）。缺陷 confirmed 表示成立，体验候选 confirmed 表示采纳改进。修复状态 repair 为 none、planned、in_progress、fixed、wontfix、unknown，fixed 需要修复来源。

verification.status 为 not_run、passed、failed、partial、unknown；passed、failed、partial 需要验证来源、对应 commit 或 instance_path，以及 fixed 的修复记录。验证实例同样列在顶层 instances；同时填写 commit 和 instance_path 时，两者提交必须相同。一次成立但尚未修复的问题仍是命中，关闭工单和未复验都不能自动改写裁决。

history 复用问题 id、kind、title、judgment、repair、verification，可附 tracker.state、tracker.reason、tracker.source。它只保存本轮回查，旧归档不覆盖。命中率分母只含明确的 confirmed 和 rejected，分母为零输出未知，体验候选另列采纳情况。

## 检查的边界

身份或数字与来源矛盾时，先修正记录或核对真实来源。添加 acknowledged 字段不会把错误改成警告。评分、复现、观察和覆盖的缺项注明实际原因，可以生成 partial 表格。

工具检查实际可机械核对的范围：引用、状态、身份、配置和数字。专家判断截图、要求与体验，架构师判断问题是否成立。脚本不会仅凭文字里出现“已关闭”给出确认，也不会仅凭一个已存在的文件就证明根因成立。
