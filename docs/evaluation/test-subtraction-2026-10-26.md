# 测试做减法记录（2026-10-26）

状态：2026-10-26 总架构师做，用户在场。口径是[测试分层设计说明](../design/test-pyramid.md)第 13 节；删除的 PR 是 [#1024](https://github.com/bender2333/yudao/pull/1024)。总图位置：第五节验收表（内核、缝、真实场景三层），第二节三环。本文记录删前删后的数字、总架构师对判定员拿不准的几处的裁定、留给用户的几件事，以及逐文件逐用例的删除清单。

## 1. 做法

十二个判定员并行读完全部测试（`harness/tests` 十组、客户端单元、客户端端到端与 `evals/tests` 各一组），按第 13 节的口径给每个文件判「留、整个文件删、删几个用例」，写明理由与删后由哪个用例接替，把握低的单列。总架构师逐组读了低把握清单做裁定（第 3 节），再用脚本按清单删除：Python 用 `ast` 删函数，客户端用 TypeScript 编译器接口按用例标题删，连带删除没人调用的辅助函数与未使用的导入。用例由架构师直接删（`CLAUDE.md`、测试分层第 4.4 节）。

## 2. 数字

删前取 main 5b950795 的收集结果（CI 逐项用时取 8e638be3 一次运行）：

| | 删前 | 删后 | 差 |
| --- | --- | --- | --- |
| harness 单元层 | 338 项 / 22 个文件 | 275 / 19 | −63 |
| harness 模块层 | 576 / 51 | 339 / 46 | −237 |
| harness 集成层 | 1314 / 114 | 892 / 105 | −422 |
| harness 合计 | 2228 / 187 | 1506 / 170 | −722（−32%） |
| 客户端单元 | 415 / 60 | 270 / 44 | −145 |
| 客户端端到端 | 157 / 26 | 71 / 16 | −86 |
| evals/tests | 158 / 11 | 125 / 9 | −33 |

集成层按 CI 的逐项用时估算：串行合计约 3750 秒降到约 2740 秒（约 62 分钟到约 46 分钟），CI 四路并行的实测：合并前约 16 分钟，合并后 main（c5f86025）上的集成层 10 分 15 秒，全部通过。降得比用例数少，因为最慢的两块没有动：`test_release_script.py` 一个文件 432 秒（时间花在夹具里装 wheel，删用例不省时间），事件序列基准 157 秒（基准这套机制是骨架重写的验收依据，只删了 8 个重复场景）。再往下降靠 #598（往下层移）和发布脚本夹具的改写，不靠删。

事件序列基准删了 8 个场景：`http_chat_cancel_while_provider_holds`、`http_messages_cancel_while_provider_holds`（与 responses 版逐字相同）、`http_chat_stream_broken_then_success`、`http_messages_stream_broken_then_success`、`http_responses_retry_after_then_success`、`http_responses_server_error_then_success`、`http_responses_timeout_then_success`、`text_only_reply`（协议级的失败与重试由 `test_provider_protocols.py`、`test_responses.py` 守着）。终态基准剩 31 个，满足内核测试的 `> 30`。

## 3. 总架构师的裁定

判定员对下面各处拿不准，总架构师定：

| 处 | 判定员 | 裁定 | 理由 |
| --- | --- | --- | --- |
| `prompt_snapshot.json` 与它的测试 | 删（钉提示词文字） | 留 | 测试分层第 11 节是把说明文字的改动集中在这一个文件，审查者从快照差异读出改了什么，删了反而让文字改动散开 |
| `test_basis_hash_rules.py` | 删（钉私有函数） | 留 | 单元层、最便宜；删了留下较重的模块层那份不合 D3「留层更低的」 |
| `test_capabilities.py` | 删，要在重放场景补两行 | 留 | 归档与恢复两个事件种类没有别的核对，补场景要运行才能确认，不如留着 |
| `test_demo.py` | 删 | 留 | README 写了 `harness demo` |
| `test_issue_250.py` | 删 | 留 | Windows 8.3 短路径，在 CI 的运行机上回归过一次 |
| `test_lesson_candidates.py` | 整个文件删 | 只留「候选不进入部门上下文」一项 | 控制核心里的候选记录器还在跑，这条不变式要有人守，其余是候选内容的细节 |
| `test_github_app_token.py` | 整个文件删 | 只留「私钥缺失写明变量与路径」一项 | 这是静默回退成仓库所有者身份的防回退；`test_github_app_entries.py` 整个删 |
| `test_context.py` | 删 16 项 | 删 15 项，留 `test_superseded_delivery_is_not_injected_as_current` | 被取代的交付不当作现行的，属于独立证据 |
| `test_department_guidance.py::test_product_guidance_during_engineering_is_full_product_turn` | 删（重复） | 留 | #561 要整体改写这个文件的指导用例，不另外动 |
| 工具微语义约 18 项 | 全删 | 留 `test_ambiguous_expected_text_is_rejected_without_a_matching_start_line` | 「原文出现多次时拒绝」防的是改错地方 |
| 检查工作区清理、会话间后台任务隔离、产品在检查工作区跑现有代码 | 删，无人接替 | 留三项：`test_the_inspection_workspaces_are_removed_when_the_run_reaches_done`、`test_cross_activation_read_output_stop_job_and_department_isolation`、`test_product_bash_views_and_runs_the_snapshot` | 前两项关系到独立性，第三项接入已有仓库要用 |
| 访问令牌、Host、Origin、CORS、命令只收 JSON 一簇 | 只去重复 | 同意，整簇留 | 路线图把接口访问令牌放在阶段三的守卫，代码已在，是局域网访问的入口；到阶段三再复核 |
| 内核路径采纳门 4 项（`test_projects.py`） | 留 | 同意 | 总图第五节写了「内核改动生效前要你批准」，代码与内核清单已在 |
| `definitions_changed` 决定请求 5 项 | 留 | 同意 | #894 昨天刚补进接口合同 |
| `test_current_queries_cover_the_old_read_scenarios` | 留 | 同意 | 没法拆着判，留 |
| smoke 审计的变异用例（`test_smoke.py` 35 个函数等） | 删，留 2 个正向 | 同意 | 它们伪造事件要求审计报错，新运行产生不了这种输入；工具与子命令不动，退役与否是第 4 节的事 |
| 模型准入的冻结快照两项 | 删 | 同意 | ADR-0005 之后调用目标每次请求解析一次，活的合同是 `test_call_target_per_request.py` |
| 像素画面与回放的测试 | 删 | **不动** | ADR-0021 把逐像素对原型 v13 定为画面验收办法，#951 至 #959 在改写它们；删不删是第 4 节的事 |
| 连接复用与排空、`test_import_without_sdk.py` | 删 | 同意 | 性能安排，不是合同 |
| 客户端「读取失败」一批 | 删 | 同意 | 单元层有一一对应的用例 |

在途的旧清理工单：#969、#970 表里的用例与辅助已经由这次删掉（它们的执行者不再删用例），#973 表里的 6 个重复用例也删了，「补断言」「改名」「删永远成立的断言」仍归执行者。

## 4. 留给用户的

1. **像素逐像素对照原型要不要一直守**（ADR-0021）。要守，#956、#957 照做，那几个文件由它们改写；不要守，这些测试连同 #956、#957 的大部分一起可以删，画面验收改靠 #959 的诚实性检查和端到端。我没删，因为这是画面验收办法的取舍。
2. **内核测试的下限 `> 30`**（`harness/tests/kernel/test_every_stop_has_reason.py`，只由用户改）。降到 `> 25` 才能再删 4 个重复的终态场景（`concurrent_departments`、`http_chat_credential_rejected_then_continue`、`http_messages_credential_rejected_then_continue`、`history_exceeds_the_window`），每个是一次完整循环。
3. **`harness smoke` 要不要退役**。工具与测试里留下的 2 个正向用例没动；README、AGENTS.md、测试分层第 4 节都提到它，另有 6 个测试文件导入它。退役要另开工单改这些地方，评测验收运行器（#830）建成后更自然。

## 5. 没删但记下的

- 阶段一的交付验证（在页面下意图、等到事项被采纳）在端到端里没有对应用例，这是缺口，不是减法；补了以后可以替掉不少页面级的保留项。
- `test_writeback_branch.py` 从 `test_writeback.py` 导入辅助函数，违反「测试文件之间不互相导入」，现有的导入检查只覆盖单元层。
- `test_workspace_boundary.py` 按十个文件名钉着 `orchestrator.py`、`engine.py`，S1 搬走这些文件时要改它的文件清单。
- `test_release_script.py` 的夹具里真实的 npm 与 Vite 可以换成假目录（CI 的客户端作业每个 PR 已经构建一遍），这是改写，省约 6 分钟的串行时间。
- `unknown_action` 的行为（交还发出它的会话，没有决定请求，ADR-0038）与路线图阶段二写的「通过决定请求交给你」不一致，由子架构师对齐。
- 事件序列基准里 `ask_answer_with_spec_revision` 与 `proposal_rejected` 都以脚本用完的 `run_failed` 收尾，场景说明写的是走到放行；该补全脚本、按 11.2 只重写这两份。
- `evals/tests/test_milestone_records.py` 在总图与路线图里没有位置，但 `/retro` 靠它出数，留。

## 逐文件清单

理由列开头的 D1 到 D5 是第 13.1 节的删除理由；「接替」是删除以后继续守着这个行为的用例。

### harness/tests

**整个文件删除**

| 文件 | 理由 | 接替 |
| --- | --- | --- |
| `test_collaboration_rules.py` | D4 加 D2。它是 #560 删「只回应指导」分支以前写的对照（「正常提案种类仍然可用」），原来旁边那条会被拒绝的用例已删；剩下这条手造 `RunProjection`、`ProductSpec`、`DeliverySpec` 的位置参数去核对 `collaboration.allowed_pro… | test_event_sequence.py::test_event_sequence_matches_its_baseline[handoff_release]（产品提交 PRD、工程交付、质检放行… |
| `test_contracts_plans.py` | D3。只有一个用例，脚本与 `test_materials_status.py::test_materials_prd_versions_follow_the_product_decision_path` 逐行相同（同一条产品决定路径），断言的三块分别已有守着：交付、质检结论绑定同一份有效合同的哈希… | `test_materials_status.py::test_materials_prd_versions_follow_the_product_decision_path`；`test_inter… |
| `test_delivery_tree_engine.py` | 6 项全部命中 D3 或 D1。还原封存树、封存失败不接纳、没有写工具的部门不能 delete 与 move，别处都有更全的用例；delete 与 move 的事件字段是工具微语义。 | - test_accepted_delivery_restores_complete_tree_without_the_original_workspace：test_workspace_delive… |
| `test_department_language_rule.py` | D2。只断言三个部门的提示词里有「用中文写」与「代码、命令、路径、标识符与引用的原文保持原样」两个原文片段；文件头自己写着「检查的是规则还在不在，不是那句措辞」，但断言就是逐字找原文，措辞一改就失败。测试分层第 10 节第 3 条：测试不决定产品的文字。#732 要守的结论（质检的叙述不要用越南语）… | 无人接替 |
| `test_github_app_entries.py` | D1，被测的是 scripts/github-app 下 gh.exe 与 git.exe 入口，自主推进里执行者与审查者用的 GitHub App 令牌包装（运行配置第 2 节），是开发流程的运维脚本，总图与路线图里没有位置，也不是产品的一部分。唯一一项「提交的入口与生成器逐字节相同」是 #526… | 无人接替 |
| `test_import_without_sdk.py` | D2：只核对「openai 与 anthropic 两个 SDK 只在目录用到对应协议时才导入」，是第一环实现的启动性能安排，总图、路线图与设计说明里都没有这一条；换一套适配实现，外面看不出区别，测试却会失败。四个用例都命中这一条。 | 无人接替（不是合同）。 |
| `test_initial_prd_summary.py` | D2：只核对决定请求与候选事件里 `prd.summary` 这句拼出来的中文摘要「目标：…；要求 N 条；边界 M 条」，是显示文字。两轮建档的往返与候选事件本身已由别处守着。 | test_onboarding_confirmation_round.py::test_revision_round_trip_over_http（两轮建档、候选事件与决定请求带轮次）；摘要里有目标与… |
| `test_issue_298.py` | D3、D4。#298 的行为是「`--data-dir X` 启动的服务把目录文件与准入文件写在 X 内」，这是一张已关闭工单的回归（D4）。路径怎么求出，已有单元用例守着；准入文件与目录文件同目录，已有集成用例守着；本文件两个用例各起一个真实服务子进程，启动等待上限 300 秒，是整组里最重的两个… | - 路径求出：test_cli_entry.py::test_the_catalog_and_credentials_default_to_the_data_directory、::test_an_e… |
| `test_issue_669.py` | D4。#669 把事项级窗口改成调用目标的属性，这两项分别核对「新写的 `run_created` 不带 `context_window`，窗口记在模型请求里」与「旧版本写下的 `run_created` 带着这个字段，读的时候忽略」。第一项由调用目标相关测试覆盖（D3）；第二项是为一次迁移（一个已… | 第一项：`test_call_target_per_request.py::test_missing_credential_blocks_until_the_dotenv_file_is_fixed`… |
| `test_legacy_unknown_action_requests.py` | D4，只为 #582 与 ADR-0038 删除「结果未知的动作」决定请求之前的旧数据目录写的：第一项造一条旧 `unknown_action` 请求验证启动时撤回并交还，第二项造旧请求与旧 `resolution: continue` 核实记录验证事件流与导出能读。没有需要读它的使用者（见文首）。 | - 交还行为：`test_unknown_action_handed_back.py` 五项（真实终止进程）。 |
| `test_onboarding_baseline_check_command.py` | D4：工单 #504 的现场回归（读侧 `BaselineCheck` 漏迁，带检查回执的建档候选在 decisions.list 与 work_item.materials 上返回 500）。它守的「这两个查询对带回执的建档候选能解析」已被 R2 测试覆盖。 | test_onboarding_confirmation_round.py::test_decisions_list_carries_the_initial_prd_materials_and_the… |
| `test_read_model_derivation.py` | D4 加 D2。工单 #684 为「修复以前写下来的旧行」写的回归：直接改写 `read-models.sqlite` 的 `app_attempts`、`app_read_meta` 表，断言推导版本常量 `DERIVATION_VERSION`，核对重建以后用量分项重新算出。读取模型属应用的投影… | test_saved_projections.py::test_replaying_after_deleting_saved_projections_gives_the_same_projection… |
| `test_single_write_path.py` | D3。与 `kernel/test_single_write_path.py` 逐字相同（两个函数、同一个正则），内核清单认的是 `kernel/` 那份。 | kernel/test_single_write_path.py::test_only_the_write_path_calls_the_event_log_write_functions、::tes… |
| `test_smoke_eval_settings.py` | D1。全部测的是 `harness smoke` 子命令怎样用 `YUDAO_EVAL_*` 三个环境变量建模型目录（#593）：目录里一个连接一个模型三个绑定、缺哪个变量就报哪个、连接测试失败就停、桩化的准入。凭据只以引用形式出现（R3 的一半）已由模型目录与凭据的专门测试守着，这里只是在 smo… | 凭据不进事实与导出：`test_call_target_per_request.py::test_missing_credential_blocks_until_the_dotenv_file_is_… |
| `test_smoke_guidance_audit.py` | D4 加 D3。整个场景建在「部门指导的正式回应」上（`guidance_response`、`DEPARTMENT_GUIDANCE_RESPONDED`、`guidance_results`、`explained` 状态），这套机制正由 #561 删除（#561 的第 1 条：删除指导的正式回应… | - 指导的送达与顺序：`test_department_guidance.py`（`test_guidance_is_persisted_bound_to_target_and_entered_bef… |
| `test_smoke_retries.py` | D5 加 D2。六个函数里五个是「删掉或改写保存的重试事件字段（`max_attempts`、`next_attempt`、`root_step_id`、`retry_of_step_id`），审计必须报未通过」，另一个核对审计的计数器（`prepared_count`、`request_count… | 失败的部分输出不进重试的请求：`test_responses.py::test_server_overloaded_stream_error_retries_after_partial_output_… |
| `test_stream_progress.py` | D2 加 D3。第一项核对 `model_stream_progress` 的 `observed_at`、`source == "sdk_decoded_stream"`、阶段名 `response_created`、`output_item_done` 与流工件里每行的字段，全是 OpenAI … | `test_stream_deltas.py::test_stream_progress_with_deltas_writes_one_event_per_stage`；阶段名与时间字段：无人接替，D… |

**删除其中的用例**

- `test_access.py`（1 个）：Host、Origin、命令只收 JSON、同源且不发 CORS 头、页面文件、局域网访问方式，这些是接口层对外的 HTTP 行为（总图第四节「接口」缝），不命中 R1 到 R3 的字面，但守着已发布的网页入口，按「拿不准判留」留 9 项；一项是 D3。
  - test_access_rejects_an_origin_that_is_not_the_service_itself
- `test_access_tokens.py`（3 个）：访问令牌在路线图里是阶段三第 3 项「接口的访问令牌」，代码已在（#348 B7，局域网访问方式依赖它）。这里只做去重：HTTP 层（局域网每条接口路径要令牌、本机不要令牌、提出者是令牌名称且令牌不进事件、撤销立即生效）与命令行留，令牌仓库的内部接口三项删。整套令牌该不该现在有测试，留给总架构师（低把握清单第 1 条）。
  - test_a_revoked_token_stops_working_at_once
  - test_a_token_is_accepted_once_per_name_and_lists_its_time
  - test_an_unknown_token_is_not_accepted
- `test_activation_accounting.py`（1 个）：取消不等模型调用返回且不收它迟到的错误、已完成的观察与用量在运行中就能读到且停止后保留、取消别的 run 不影响当前调用、停止时记下的厂商与模型与适配器分开，属 R1 与 R2。`test_large_provider_usage_is_recorded_without_stopping_handoff` 与 `test_provider…
  - test_large_provider_usage_is_recorded_without_stopping_handoff
- `test_activation_responses.py`（1 个）：真实 HTTP 桩经真实适配器走完整循环：每次请求逐字记进事实且与发出的一致、用量与未报告用量、失败的尝试与部分流只留事件备查不进重试输入、同一响应里重复的 call_id 在工具开始前被拒、超时与重试，属 R1 与 R2。`test_host_failure_to_record_a_stream_event_names_the_actu…
  - test_host_failure_to_record_a_stream_event_names_the_actual_error_type
- `test_adjudication.py`（3 个）：留两项 R1，这是裁决模块里仅有的直接核对：取消或事项结束以后工具许可变成停止，模型还没见到新输入时正式成果推迟；校验以后工作区变了，提交被拒绝，回执不能重新绑定到已改变的快照上（`commit_decision`）。删三项：按部门拒绝工具（模型收到原因）在事件层已有，这一项还钉英文拒绝文字与 `WorkBasis`（D3）；交付文件清单…
  - test_the_delivery_file_list_comes_from_the_sealed_snapshot
  - test_tool_permission_denies_with_a_reason_the_model_receives
  - test_write_permission_uses_the_canonical_path_from_the_environment
- `test_assembly.py`（1 个）：删的一项是 D2（宽窗口保留 15%、窄窗口最多保留一半，是阈值公式）。留下的两项是装配契约「同样的事件重放出同样的请求」：按记录的事件逐步重建请求与压缩检查点，与记录的字节、清单摘要、检查点逐项一致（R1、R3，装配缝）。它们走的是 `ContextAssembly` 的 `pin`、`request`、`department_hist…
  - test_model_limits_use_the_call_target_window_and_reserve_half_of_a_narrow_one
- `test_bash.py`（4 个）：R3 留 5 项：回执的退出码与输出、超时与取消结束整个进程树、环境继承与密钥脱敏、超限输出按编号分页取回。D2 删 4 项：窥探私有 `_run_process`、`_BASH_PATH`、argv 里有没有 `-l`，以及断言 `.checks/tool-output` 目录布局。
  - test_bash_does_not_start_a_login_shell
  - test_missing_bash_reports_the_cause
  - test_saved_output_stays_outside_the_public_tree
  - test_timeout_default_and_max_come_from_rules
- `test_bash_jobs.py`（4 个）：后台命令设计里有（执行环境设计 4.1 节），质检操作网页（阶段二 · 3）要用，留 3 项：启动、读输出、结束的整体路径；放行、暂停、取消时后台进程树不留（R3 边界，留着进程会占端口，让下一次独立核验连到上一次的服务）；重启后旧编号回答已结束（阶段二「进程重启后接续」）。其余是 D2 或 D3。
  - test_environment_without_session_context_rejects_background_and_truncation
  - test_inspection_workspace_rebuild_stops_jobs_and_returns_ended
  - test_stop_job_on_already_exited_process_preserves_exit_code_and_receipt_shape
  - test_work_item_run_with_background_bash_port_access_read_output_and_stop
- `test_call_target_per_request.py`（1 个）：这份文件直接守总图「每次请求解析一次调用目标」：凭据缺失时停在这次请求之前、修复后下一次请求才重新解析；请求进行中改了默认，这次请求与它的重试仍发往原目标；准入作废后各部门各发一条决定请求。都是 R3。只有一项是另一项的子集。
  - test_request_event_records_requested_and_sent_tier
- `test_cli_entry.py`（4 个）：命令行的默认路径与选项位置是发布版本的使用合同，但四项是重复或钉内部默认值：
  - test_default_data_dir_follows_the_user_data_root
  - test_smoke_takes_the_data_directory_from_either_position
  - test_smoke_without_a_data_directory_keeps_its_own_default
  - test_the_default_data_directory_keeps_the_previous_locations
- `test_compaction.py`（14 个）：D2 为主。压缩算法里的 85%、15%、窄窗口一半、摘要上限 4096、分片尺寸、经验基线（36 个源、token 数 26916、摘要哈希）、摘要请求的提示词结构、token 估算的「每四个字符一个」，第一环重写以后都会变；留下的是不变式：原件不被改动或丢失（`records == original`、分片连续拼合与原始字节一致）、请…
  - test_estimate_tokens_counts_characters_not_bytes
  - test_estimate_tokens_rounds_up_in_groups_of_four_characters
  - test_long_tool_result_is_summarized_in_rounds_that_each_leave_half_the_narrow_window_for_output
  - test_narrow_window_compacts_once_the_input_reaches_the_response_reserve
  - test_narrow_window_keeps_half_of_itself_for_the_summary_response
  - test_opaque_reasoning_stays_in_original_history_and_is_cited_in_summary_material
  - test_preflight_check_prevents_oversized_prompt_from_being_sent
  - test_reasoning_is_not_misread_as_summary_text
  - test_response_reserve_is_15_percent_for_wide_windows_and_up_to_half_of_a_narrow_window
  - test_summary_output_tokens_cap_applies_regardless_of_model_output_limit
  - test_summary_request_contains_no_tools_and_no_reasoning_options
  - test_summary_request_opens_as_summarizer_then_pins_department_material_then_sources
  - test_wide_window_compaction_trigger_stays_at_85_percent
  - test_wide_window_slicing_is_unchanged_by_the_narrow_window_reserve
- `test_compaction_engine.py`（1 个）：这个文件通过 `activate_once` 检查压缩的结果事件与重放：原件保留、清单摘要与保存的请求字节一致、控制器重启后检查点接续、合同换版本后从保留的原件重建、取消时不采纳迟到的摘要、未声明的工具调用不执行并作证据保留、截断的摘要不采纳、步数上限在压缩中途暂停、连续空摘要以 `compaction_failed` 停止、询问带回新合…
  - test_single_empty_summary_does_not_fail_the_run_and_department_continues
- `test_concurrent_departments.py`（1 个）：PRD 被接纳后工程与质检同时工作、质检预测性探索、通知送达、检查工作区重建、两边同时询问、两个检查各用各的工作区，都是 R3（按成果开工、询问、独立证据）。`test_cancel_stops_every_session` 是 D3：断言被 test_issue_856.py 里同名主题的用例包含，后者还覆盖了「检查在跑时取消」与「取消…
  - test_cancel_stops_every_session
- `test_context.py`（15 个）：D2 为主。这个文件断言的是装配实现的内容选择：上下文清单里的来源名（`current_product_decisions`、`prior_delivery`、`current_delivery_spec`、`other_department_transcript`、`expired_product_decisions`、`invalid…
  - test_assembler_records_budget_and_digest
  - test_compaction_request_with_widened_output_limit_stays_within_the_window
  - test_each_department_has_its_own_session
  - test_effective_decision_keeps_explicit_requirement
  - test_narrow_window_work_request_spends_the_window_left_after_its_input
  - test_new_spec_does_not_inject_stale_product_decisions
  - test_product_and_quality_do_not_receive_write_tools
  - test_proposal_contract_and_binding_refs_are_injected
  - test_quality_runs_its_checks_through_run_check
  - test_requests_carry_no_remaining_cycles_while_the_host_enforces_the_limit
  - test_rework_engineering_keeps_only_one_active_delivery
  - test_two_formal_product_decisions_reach_engineering_and_quality
  - test_validation_feedback_is_injected_after_rejection
  - test_validation_feedback_is_not_kept_after_successful_proposal
  - test_wide_window_work_requests_keep_the_declared_output_limit
- `test_contracts_plans_module.py`（1 个）：四个用例里三个守着有效合同与 PRD 工件（R3/R1）：补充决定改变合同、新 PRD 逐条处置有效决定（`retain/integrate/retire` 三个参数）、PRD 工件写失败时不接纳产品与合同并以 `host_commit_error` 停止、重放一致。留下。剩下一个守 #470 删除工程计划这一次迁移。
  - test_writes_without_a_plan_are_allowed
- `test_decision_projection.py`（2 个）：这个文件测的是决定请求保存的投影（`decisions` 表）。留一项 R1：事务没有提交（期望版本过期、判断中途抛错）时，决定请求也不保存。删两项：按项目、事项、种类、状态列出的筛选与保存行的字段形状，筛选已由接口层 `test_decision_api.py` 守，字段形状是内部（D3、D2）；删光保存的投影以后由重放补建、以及重放核…
  - test_decision_requests_are_rebuilt_from_events_and_the_replay_check_compares_them
  - test_decision_requests_are_saved_with_their_events_and_listed_by_project_work_item_kind_and_status
- `test_definition_rules.py`（3 个）：留 `test_shipped_definitions_are_loaded_once_at_import`（R2，定义的版本是内容摘要，格式 `sha256:` 加 64 位）。其余三个命中 D2。
  - test_check_timeout_is_six_hundred
  - test_compaction_coverage_exposes_seq_range_and_covered_through
  - test_onboarding_prompts_state_the_two_material_kinds
- `test_definitions.py`（1 个）：这个文件是「定义」缝的主体：版本取内容摘要且与格式无关、各定义文件校验时报错写明文件与条目、部门与角色互相引用、规则登记的八项字段与界限、提案合同与提交工具对得上、停止原因封闭清单（写入口拒绝清单外的原因）、事项创建时记定义版本、启动时定义不合法则失败，都是 R2（字段合同）与 R1（停止原因封闭）。其中一个用例钉的是内部不可变实现，另有…
  - test_loaded_definitions_are_read_only_and_hand_out_plain_copies
- `test_department_guidance.py`（0 个）：设计说明 department-guidance.md 第 3 节已经写明「没有单独的回应」，#561 删除工具、提案与校验，下面 17 个函数断言的都是正式回应的状态（completed、explained、result_event_ids 绑定、放行前核对），整体属 D4。另有一项 D3。留下的 10 项断言的是送达（R3：在一轮工作…
- `test_department_prompts.py`（4 个）：`save_department_prompt` 是 `materials.save_text_material` 外面一层，加一句「部门必须是已知部门」。文件里六个用例，四个是把 `test_materials.py` 对同一条存储路径的检查换成部门提示再测一遍，命中 D3。留两个：提示原文按字节保存、改写不影响定义里的默认提示（`te…
  - test_failed_prompt_storage_is_not_returned_as_a_saved_prompt
  - test_invalid_prompt_is_rejected_without_writing
  - test_prompt_reference_is_scoped_to_its_run
  - test_prompt_save_verifies_existing_artifact_bytes
- `test_department_providers.py`（3 个）：保留的八项是 R3 的核心：按部门选模型、每个部门用自己的连接与凭据、凭据不进事实与导出、请求记录与实际发送的字节一致、重启后按当前凭据解析、取消只作用于自己的运行、三种协议混用的完整运行。删掉的三项与别处重复。
  - test_cancelled_http_request_keeps_bound_identity_without_a_response
  - test_retry_stays_on_the_bound_provider_and_model
  - test_small_bound_model_uses_its_own_compaction_request
- `test_department_states.py`（1 个）：外环状态（等待工作、一轮工作中、询问中、核验中、等用户）经三个查询给出，核对三处一致，属 R3 与 R2（查询字段、刷新清单）。`test_the_departments_do_not_read_the_run_projection_or_decisions_more_often` 数 `store.projection` 被调用几次，是…
  - test_the_departments_do_not_read_the_run_projection_or_decisions_more_often
- `test_drain_upgrade.py`（1 个）：排空在下一次启动时结束、排队的事项这一次开始，是 R3（排空与升级）；第三项只核对新事件种类的中文说明里含「排空结束」，D3 加 D2。
  - test_the_new_drain_event_can_be_read_back
- `test_engine.py`（3 个）：取消的三个时点（装配后、工具开始前、命令运行中、许可之后）属 R1，重启后接续属 R3，请求逐字记进事实并与发出的一致属 R1。删三项：`test_fake_adapter_has_no_workspace_and_does_not_execute_tools` 测的是假模型这个测试替身自己（`hasattr(adapter, "invo…
  - test_fake_adapter_has_no_workspace_and_does_not_execute_tools
  - test_large_history_requests_compaction_and_rejects_submit_in_summary_response
  - test_original_intend_is_preserved_verbatim_outside_the_delivery_tree
- `test_environment_establish.py`（2 个）：留 2 项：从封存快照建工作区（树、摘要、事实查询一致，`.checks` 不在内；R3「工作区每次从封存快照建」）；`verify_tree` 接受取自快照的树并拒绝变动（动作缝的核实方法在环境一侧的入口）。删 2 项：空快照（D3，几乎每个流程用例的起点）、已存在目的地被拒（D3，同一规则在 test_public_tree.py 里…
  - test_establish_refuses_an_existing_destination
  - test_establish_without_a_snapshot_creates_an_empty_public_tree
- `test_event_classification.py`（1 个）：留九项：每种事件种类声明属于项目流、run 流或目录流并两侧比对、三份清单互不相交、两条流的关键种类抽查（ADR-0019，项目流跨版本保存）、每种事件有中文说明与说明模板只用载荷里有的字段（这是路线图阶段二·4「声明式对照表全覆盖，缺行即失败」的前身）。删一项：常量 `RUN_EVENT_VERSION` 是正整数，恒真（D5）。
  - test_the_run_event_version_is_a_positive_integer
- `test_event_sequence.py`（0 个）：留 `test_event_sequence_matches_its_baseline[场景]`：每个场景核对「重放得到的状态等于现状态」「每条载荷符合合同」「事件种类、顺序、因果与关键字段同基准」，是 R1 加 R2，也是骨架与应用重写（#824 至 #864）验收写的「事件序列基准不变」的依据。删 `test_prompt_snaps…
- `test_event_sequence_compare.py`（4 个）：这是基准比较器（`event_sequence.py` 的 `compare_documents`、`normalized_run`）的自检，属测试基础设施，比较器还在，默认留。留八项：会话间交错仍通过、会话内调换失败、因果边反向失败（两处）、只改投影失败、只改载荷字段失败、交错的会话规整以后相等、会话内引用换指向失败。删四项都是重复：一…
  - test_baseline_references_are_session_positions
  - test_baselines_keep_session_totals_only
  - test_event_difference_reported_before_projection
  - test_normalized_references_are_session_positions
- `test_event_store_batch.py`（2 个）：留 R1 两项（一批事件版本与位置连续；后一条写入失败整批与投影一起回滚）。删两项：一项靠 `state_after=None` 触发 SQLite 的 NOT NULL 约束，钉内部表约束（D2），整批回滚已由留下的第二项守；另一项直接调 `store.commit` 测过期期望版本，同一件事 `test_write_path.py` …
  - test_commit_with_a_stale_expected_version_is_rejected_without_writing
  - test_invalid_batch_entry_cannot_begin_a_partial_commit
- `test_event_store_read_only.py`（1 个）：只读打开是接口层只读子命令的底座（`app/application.py` 的 `ReadOnlyCore`），「只读打开写不进去、缺文件不建库、读得出来」是 R1，留三项。删一项：经私有的 `store._connection()` 去核对 SQLite 的报错文字，钉实现（D2）；Python 层拒绝写入已有一项守。
  - test_read_only_event_store_connection_enforces_query_only
- `test_event_stream.py`（2 个）：R2 事件流合同：补发与范围筛选等于读日志、位置连续且 previous 衔接、续接无遗漏无重复、位置超出日志末尾即 resync 并关闭、队列写满即 resync、空闲时发检查点，留。两个用例命中 D2。
  - test_an_event_without_a_label_does_not_break_the_stream
  - test_live_events_arrive_within_a_hundred_milliseconds
- `test_events_api.py`（1 个）：R2 事件流的对外合同：按位置补发带位置、previous、说明、旧事件的被删字段被忽略且被删种类不转发、`Last-Event-ID` 优先、筛选与读日志一致、位置超出日志末尾以 resync 回应、不是数字的位置以 resync 回应、保活注释、live 与非 live 连接的片段、能力清单里的流声明。一个用例是同文件与 test_e…
  - test_event_stream_resumes_after_the_last_received_position
- `test_git_engine.py`（5 个）：D16 要求任务内变化用 Git 管理，这是总图之外的需求。留 4 项：版本准备失败则事件不接纳、材料不发布（R1 写入原子）；规格与合同的事件写入失败时整批接纳回滚；工作区工具碰不了 `.git`（写入逃逸边界，4 种大小写与嵌套形式）；用户停止不依赖输入保存成功（10 项展开，把握低）。删 5 项：整条历史的条数与文件集（D2）、事件…
  - test_cancel_notifies_model_before_waiting_for_git_storage
  - test_git_delivery_and_archive_share_binary_bytes_and_complete_directory_manifest
  - test_new_input_and_requirement_diff_form_one_accepted_history_through_redelivery
  - test_nonformal_event_cannot_advance_git_version_projection
  - test_sqlite_input_failure_leaves_only_candidate_and_next_parent_is_still_accepted
- `test_git_versions.py`（26 个）：版本存储是总图第一环的实现（可整体重写），合同只剩「封存后可读回、可核验、被篡改能发现、仍是标准 git 版本库」。留 7 项：往返字节与重开、材料补丁与交付替换代码的语义、正式父提交由调用方给出且孤儿快照不改它、真实的新增修改删除与二进制差异、同一输入再准备得到同一提交（幂等）、对象被篡改按名称读不出一致内容（3 项展开）、git 建的…
  - test_a_loose_object_that_no_longer_matches_its_digest_is_rejected
  - test_alternate_object_store_is_rejected
  - test_arbitrary_missing_or_invalid_revisions_are_rejected
  - test_copied_objects_and_refs_cannot_be_used_by_another_run
  - test_existing_snapshot_ref_pointing_to_another_commit_is_rejected
  - test_failed_readback_does_not_return_a_revision
  - test_failed_reference_binding_does_not_return_a_revision
  - test_file_directory_and_case_collisions_are_rejected
  - test_git_ignores_global_environment_filters_textconv_hooks_and_autocrlf
  - test_gitignore_and_gitattributes_do_not_change_complete_code_capture
  - test_internal_failures_hide_private_paths
  - test_invalid_run_ids_are_rejected
  - test_invalid_update_paths_are_rejected_before_repository_creation
  - test_linked_repository_is_rejected
  - test_linked_root_is_rejected_before_git_runs
  - test_material_updates_reuse_validated_code_objects
  - test_missing_file_is_an_explicit_version_error
  - test_read_operations_do_not_write_repository_objects_or_refs
  - test_readback_failure_followed_by_identical_retry_accepts_existing_snapshot
  - test_root_parent_traversal_is_rejected
  - test_snapshot_write_starts_no_process_and_binds_one_reference
  - test_updates_cannot_mutate_the_code_namespace
  - test_writes_no_temporary_files_inside_the_repository_root
  - test_written_blob_is_rejected_when_its_loose_object_does_not_match_the_digest
  - test_written_tree_is_rejected_when_its_loose_object_does_not_match_the_digest
  - test_wrong_tree_parent_extra_fields_and_unbound_snapshot_are_rejected
- `test_github_app_token.py`（7 个）：D1，同上，测 yudao_github_app.py 的令牌换取、缓存、凭据助手，不是产品，总图没有位置。是 #513 验收的逐条对应，属一张已关闭工单的验收测试。
  - test_cached_token_is_reused_and_renewed_near_expiry
  - test_credential_helper_ignores_other_hosts
  - test_gh_and_git_requests_carry_the_installation_token
  - test_gh_receives_the_token_in_place_of_the_login
  - test_git_credential_helper_answers_for_github_over_https
  - test_token_and_key_never_reach_the_output
  - test_unset_variables_pass_through_to_the_real_binaries
- `test_inspection_workspace.py`（13 个）：检查工作区就是「质检在独立副本上跑检查」的承载（R3、总图第一节「独立的证据」）。留 4 项：质检用 bash 读到的是封存交付、写入不进运行工作区与封存树；产品与质检两个会话互不可见；启动时保留未结束事项的检查工作区（重启后接续）；交付以前质检从事项起点建、产品看当前快照。删 15 项：目录布局（D2）、清理重试与报错（D2）、各条路径…
  - test_a_cancelled_run_removes_its_inspection_workspaces
  - test_cleanup_is_idempotent_for_a_missing_root
  - test_cleanup_reports_a_handle_that_never_releases
  - test_cleanup_retries_while_a_handle_is_still_open
  - test_close_run_removes_every_session_inspection
  - test_close_run_reports_a_session_that_could_not_be_removed
  - test_engineering_delivers_from_the_run_workspace_and_quality_from_its_own
  - test_establish_is_idempotent_for_an_existing_root
  - test_establish_materializes_the_delivery_tree
  - test_inspection_root_is_outside_the_run_workspace
  - test_inspection_writes_do_not_reach_the_run_workspace
  - test_sessions_have_independent_inspection_roots
  - test_startup_removes_inspections_of_a_run_that_already_finished
- `test_interaction_engine.py`（1 个）：用户输入、停止命令、取消与终态后拒收、输入作为通知在下一步送达（#964 已改）、放行等输入处理完、压缩与输入同时、需求更新后走新交付再独立质检，属 R3 与 R1，且都有重放一致断言。`test_failed_intend_publication_preserves_previous_original_and_received_stat…
  - test_failed_intend_publication_preserves_previous_original_and_received_state
- `test_issue_127.py`（2 个）：R2 查询按位置回放（同一位置读得同样结果、超出日志末尾拒绝、回放不写入），离开期间的报告与「已看过」，决定列表与状态项对得上，命令 `home.mark_seen`，命中 R1、R2、阶段二 · 4 的离开期间报告，留。两个用例被 test_api.py 与 test_issue_127.py 其他用例包含。
  - test_a_query_that_is_not_replayable_refuses_at_by_its_contract
  - test_capabilities_mark_replayable_queries_and_expose_the_interface_version
- `test_issue_146.py`（1 个）：R3（能力表预填、输入方式不触动准入、查询不含 Key）。删 1 个：断言「模型测试不改输入方式」，模型测试只写准入记录，这点已被「准入与目录分开保存」覆盖，而且这条用例没有核对准入（D3）。
  - test_model_test_keeps_input_modalities_and_admission
- `test_issue_16_recovery.py`（2 个）：整体是 R3「进程重启后接续、执行权、不复活已取消事项」的主干，留 12 项；其中两项是 D3。
  - test_resume_does_not_grant_a_free_activation
  - test_resumed_runs_are_distinct_from_runs_stopped_for_an_upgrade
- `test_issue_17_action_recovery.py`（1 个）：结果未知的动作交还会话、部分执行的响应只补剩余动作、采纳结算跨恢复幂等都是 R3，留 4 项；第一项是 D3，已有真实终止进程的同一结论。
  - test_a_lost_write_action_is_handed_back_and_is_not_blindly_redone
- `test_issue_18_recovery_observation.py`（4 个）：`run.recovery`、`projects.list`、`project.loop`、`run.actions` 的恢复观察状态是查询合同（R2）并且守着恢复的状态词（总图第三节），大部分留；删 4 项，其中 2 项已在 #973，2 项是新判的。
  - test_an_unknown_action_is_observed_as_pending_verification
  - test_run_actions_reports_the_unknown_status_and_snapshots
  - test_system_status_counts_match_the_event_log
  - test_the_event_stream_reconnect_only_adds_observation
- `test_issue_203.py`（2 个）：`project.set_goal` 在设计里（app-and-interface.md 第 3.2 节、第 10 节第 12 项，2026-09-30 用户决定），写项目流事件、基准版本过期拒绝、归档的项目拒绝、新事项用新目标而进行中的事项用开始时的目标，属 R2 与 R3。删两项 D3。
  - test_run_created_records_the_goal_at_creation
  - test_set_goal_is_listed_in_capabilities_and_openapi
- `test_issue_204.py`（1 个）：no_tool_call 与 workspace_unrepresentable 暂停时发决定请求、回答继续从停下的位置接着、不处理再暂停、回答停止保持原因、继续后计数从零，属 R3 与 R1，文件虽以工单号命名，守的行为都在路线图（决定请求、封闭的停止原因）里，留下 13 项。`test_pause_decision_kinds_are…
  - test_pause_decision_kinds_are_registered
- `test_issue_299.py`（1 个）：回答待恢复决定后继续、启动自动继续的 run 停止后都要结算采纳，是 R3（重启接续加采纳写回），这两项留；第三项「已结算的 run 再走入口不重复写采纳」是 D3。
  - test_a_settled_run_does_not_write_another_adoption
- `test_issue_308_file_action_verification.py`（3 个）：R3：文件动作结果未知的核实。三项重复的（写入没发生、写入已发生、重试仍未知）已被 #973 列为删，由 test_unknown_action_handed_back.py 接替；留两项独有的：别处有变化时核实结论为 unclear（交还会话）、编辑与删除与移动的判据（`verify_file_action` 的单元判断）。
  - test_a_retry_that_stays_unknown_after_the_chance_is_gone_asks_the_user
  - test_a_write_that_happened_is_recorded_as_auto_verified
  - test_a_write_that_never_happened_is_retried_once_without_asking_the_user
- `test_issue_317_onboarding_upgrade.py`（3 个）：留 2 项（修改轮强制升级带同一份候选与意见；取消等待确认的建档事项后重启仍是已撤销），是 R1/R3；删 3 项：两项是 D4（只为一次「较早 run 事件版本」的数据目录写的建档场景），一项是 D3（入口不同、实现同一个函数）。
  - test_force_upgrade_restarts_the_first_onboarding_round_from_the_snapshot
  - test_starting_from_an_older_version_can_ask_for_a_revision
  - test_starting_from_an_older_version_can_confirm_the_candidate
- `test_issue_321.py`（4 个）：项目的起始文件夹是「事项从快照开始」的一种起点，属 R3 的从封存快照建工作区：起始文件夹快照写进项目流、拒绝时不建项目不写事件、第一个事项从起始文件夹开始、采纳以后起点改为采纳成果、升级重启与进程中断后仍带着起始文件夹、旧事件读作没有起始文件夹，留。4 个用例命中 D2 与 D3。
  - test_create_without_initial_directory_leaves_the_event_as_it_was
  - test_project_overview_reports_the_start_point_until_the_first_adoption
  - test_the_create_command_rejects_an_unreadable_directory_with_source_invalid
  - test_the_start_point_function_serves_the_three_call_sites
- `test_issue_374.py`（1 个）：服务进程的启动、停止与接续：Ctrl+C 停止后数据目录锁释放且再启动成功（R1/R3 单进程）、打开的事件流不拖住退出、启动序列在真实 uvicorn 事件循环里接续进行中的 run（R3），留；LAN 打开地址一项是 D3。
  - test_the_lan_access_mode_opens_the_address_of_this_machine
- `test_issue_475.py`（1 个）：(a) 分支会话重启后继续、(b) 提交交付后被杀质检核验这份交付、(c) 会话与事项已用量连续累计，是 R1/R3（询问嵌套加重启接续），留；(d) 已在 #973。
  - test_an_unknown_action_is_handed_back_to_the_session_that_issued_it
- `test_issue_562.py`（4 个）：R2、R3（经 catalog.connection.save 拒绝缺容量的定义并写明缺哪一项）。其中 `ModelInput.from_candidate` 与它的别名 `model_input_from_candidate` 在生产代码里没有任何调用者（`git grep` 只有本文件），5 个用例里 4 个或者只在核对这个测试专用的…
  - test_definition_from_candidate_uses_prefilled_capacity_and_source
  - test_missing_single_capacity_field_names_that_specific_field
  - test_modifying_window_keeps_admission
  - test_plain_row_with_full_capacity_without_confirmation_marker_saves_successfully
- `test_issue_740.py`（2 个）：R2：422 的响应体里 `detail`（机器读）不变、`error`（页面读）是一句中文、409 的拒绝不受影响。留三个。两个命中 D3 与 D5。
  - test_an_empty_goal_is_refused_with_the_field_it_names
  - test_the_capability_list_still_reports_the_same_interface_version
- `test_issue_84.py`（2 个）：这份文件是 #84 的验收。留下三项：连接声明协议的目录文件被拒绝且保留上一个有效目录（R2，#969 明确要留）、同一服务方案三种协议的路径与身份头走完整链路（连接测试、准入、解析、调用）、预置表查询的版本与来源且不含模型与容量（R2）。
  - test_full_system_run_with_fake_adapter
  - test_same_service_preset_connections_share_credential_reference
- `test_issue_842.py`（2 个）：询问分支的激活不改写事项的所在部门、不占轮次（department-loop.md 第 110 行已写入设计），属 R3 与 R1。其中两项被同文件里断言更全的一项包含，D3。
  - test_active_department_stays_with_the_asking_department_after_the_answer
  - test_ask_branch_activation_does_not_count_as_a_cycle
- `test_issue_85.py`（3 个）：R3（获取模型列表与连接测试带凭据、失败原因、凭据不进事件）。删 3 个：其中 2 个的前提「没有填模型列表地址就报未知」已被 #384 取代（现在按服务地址加 /models 读取，两个用例靠连接本机 9 号端口失败才偶然通过，D4）；1 个是对三种协议重复同一条检查，连接已不带协议（ADR-0033，D3）。
  - test_collect_candidates_is_unknown_without_a_models_url
  - test_connection_test_sends_a_real_request_for_each_protocol
  - test_connection_test_without_a_models_url_reports_the_reason
- `test_issue_86.py`（8 个）：R3（准入记录只由模型测试写入、按受影响字段作废、部门默认只能引用已准入定义），主体留。删 8 个：3 个已在 #969；`test_editing_capacity_in_json_counts_as_confirmation` 说的「JSON 里改容量等同确认」是 #562 删掉行内确认以前的前提（D4），断言只剩「存进去能读出来」；…
  - test_changing_connection_address_makes_all_models_candidates
  - test_changing_protocol_makes_that_model_candidate
  - test_department_default_accepts_admitted_model
  - test_editing_capacity_in_json_counts_as_confirmation
  - test_fake_protocol_allowed_on_demo_startup
  - test_fake_protocol_rejected_on_normal_startup
  - test_model_without_output_cap_is_rejected
  - test_system_with_adapter_factory_reads_catalog_in_test_mode
- `test_issue_90.py`（2 个）：R3（修改前的影响列表、删除与导入时的引用检查）。删 2 个：导入移除被引用定义的三个变体里，被部门默认与项目同时引用的那条（D3，被另两条合起来覆盖）；进行中事项影响列表四种分支里「只有工程选中」那条（D3，被「工程与质检都选中」那条与主用例覆盖）。
  - test_import_removing_referenced_definition_is_rejected_as_a_whole
  - test_work_item_impact_lists_engineering_when_only_engineering_selects_the_definition
- `test_issue_91.py`（3 个）：R3（编辑 JSON 与表单对同一份无效内容给出相同字段位置、外部修改后目录回到候选、删除目录文件后事项进入待恢复并可恢复）。删 3 个：同一结论在同文件或 test_startup_reload.py 里已经有测试（D3）。
  - test_document_referencing_a_candidate_is_rejected_as_a_whole
  - test_external_capacity_change_keeps_admission_and_uses_the_new_value
  - test_invalid_external_content_keeps_the_last_version_and_reports_the_reason
- `test_issue_92.py`（1 个）：R2、R3（department.workspace 的生效模型与来源、run.attempt 的调用目标不含密钥、project.attempts 的筛选）。删 1 个：「查询不追加事件」每张工单各写一遍，已有一条覆盖全部已登记查询的通用用例（D3）。
  - test_queries_do_not_append_events
- `test_lesson_candidates.py`（5 个）：D1。name-map 观察者一行写明：教训候选现在由 `Orchestrator._record_lesson_candidate` 在控制核心里写，事件 `lesson_candidate_recorded`，不经观察者缝；总图第四节与路线图阶段四、#987 的结论是观察者在系统之外、经接口只读订阅、经写入口以提案提交。骨架与应用设计…
  - test_evidence_source_export_and_replay_keep_the_same_candidate
  - test_failure_candidate_has_only_existing_evidence_and_keeps_failure
  - test_qa_candidate_preserves_actual_source_contract_and_evidence
  - test_release_with_defect_keeps_existing_rejection_and_does_not_create_candidate
  - test_success_cancel_pause_and_rejected_review_do_not_invent_candidates
- `test_malformed_tool_arguments.py`（1 个）：保留两项假模型用例：截断的工具参数在记入历史与下次请求回放时恒为有效 JSON 对象（R1：工具调用先过检查、不执行；一旦回放坏 JSON 上游会拒绝整条请求），以及有效调用照常执行。删掉用本机 Chat 服务重现同一故障现场的那一项。
  - test_truncated_chat_stream_never_replays_invalid_assistant_arguments
- `test_materials.py`（11 个）：留 2 项：用户输入原文逐字保存、字节范围能还原每一段输入（R3，总图的「意图」与「一份事实只追加」；这是 `user_input_received` 里 `byte_start`、`byte_end`、`input_ref`、`intend_ref` 字段的来源，这些字段的值只在这里核对）；追加新快照不改旧输入与旧快照（只追加）。删 1…
  - test_existing_corrupt_destination_is_not_acknowledged_as_stored
  - test_initial_input_and_snapshot_share_bytes_without_extra_storage
  - test_invalid_input_is_rejected_before_any_artifact_is_written
  - test_invalid_run_id_cannot_write_before_rejection
  - test_modified_previous_bytes_are_rejected_before_append
  - test_non_utf8_previous_snapshot_is_rejected
  - test_previous_snapshot_cannot_be_borrowed_from_another_run
  - test_previous_snapshot_must_be_an_intend_artifact
  - test_readback_failure_is_not_acknowledged_as_a_successful_append
  - test_storage_failure_returns_no_material_and_preserves_previous_snapshot
  - test_wrong_previous_reference_is_rejected_without_persisting_new_input
- `test_observability.py`（7 个）：留下 5 项：尝试与用量的查询合同（缺用量为空、查询不改变投影，R2）、非法用量数值读为未知（R2，原始工件路径，唯一经真实适配器走原始用量的一项）、两项凭据脱敏（R3「凭据不进事实与导出」：错误信息与头里的凭据、模型输出文本里的凭据，都不得出现在尝试详情与流工件里）、导出与查询一致且不改运行（R2）。删的 7 项：钉 OpenAI Re…
  - test_context_parts_are_verified_and_missing_current_parts_do_not_fallback
  - test_department_prompt_reports_the_version_recorded_by_the_model_request
  - test_partial_stream_failure_keeps_stream_artifact_and_actual_identity
  - test_project_attempts_filters_provider_and_models
  - test_project_queries_are_run_scoped_and_query_only
  - test_responses_capture_complete_sdk_json_and_decoded_events
  - test_stream_events_keep_provider_order_and_type_in_attempt_detail
- `test_observability_module.py`（8 个）：留下的是 R2/R3：用量汇总只累加上报的尝试、未上报不转成 0（总图判据二「能度量」，评测说明第 5.2 节「`unknown` 不转换为零」）、失败与取消的尝试的部分输出只作观察、不产生被接纳的材料、不进部门历史（总图第三节「失败的尝试记成事件供回查，不执行、不进有效历史」）、适配器失败保留流证据。删的 8 项：直接调用 `attem…
  - test_a_summary_that_does_not_report_stays_unknown
  - test_cancelled_attempt_is_independently_filterable
  - test_chat_completions_raw_usage_names_are_read
  - test_cost_totals_follow_reported_provider_values
  - test_stream_artifact_cleanup_closes_temp_file_before_cleanup
  - test_the_raw_usage_decides_which_items_were_reported
  - test_the_summary_is_used_when_the_raw_usage_is_gone
  - test_unreported_normalized_usage_keeps_unknown_source_and_is_not_counted_as_reported
- `test_onboarding.py`（2 个）：R3 接入已有仓库：建档 run 以基线核验结束、工作区树始终等于快照、质检看不到现有结构说明（错误独立）、基线核验裁决的各条规则（有未佐证条目不得 consistent、失败检查必须解释、超时当失败、设计中的能力不得记为缺陷）、结构说明的要求覆盖与树摘要核对，留。两个用例命中 D2 与 D5。
  - test_design_only_capability_goes_to_boundary_with_mark
  - test_repository_overview_is_generated
- `test_onboarding_confirmation_queries.py`（1 个）：建档材料按轮列出、确认后基线采纳的字段、普通采纳没有基线字段（R2、R3）留；等待确认标记的用例被 test_onboarding_commands.py 里同名断言包含。
  - test_projects_list_marks_the_item_awaiting_initial_prd_confirmation
- `test_onboarding_confirmation_round.py`（2 个）：修改轮往返、第三轮仍允许、确认第一轮与第二轮采纳的树、等待确认时取消、等待确认时重新开始与新建与归档被拒、决定请求带材料与「说明必填」、等待确认的决定不占执行槽位也不挡排空，命中 R3。两个用例是别处用例的子集。
  - test_non_git_source_records_no_provenance
  - test_queries_do_not_write_events
- `test_orchestrator.py`（1 个）：整条循环从意图走到放行或停止，断言的是投影与事件里的结果，属于 R3 与 R1，留下 12 项。`test_cycle_limit_pauses_after_work_without_provider_usage` 是 D3：同一个「轮次上限暂停」。
  - test_cycle_limit_pauses_after_work_without_provider_usage
- `test_project_and_work_item_commands.py`（1 个）：项目命令的期望版本与 stale_base、追加输入按命令身份去重、取消、事项在接口进程里跑到结算、启动补结算且查询不结算，命中 R1、R2、R3，留。只有一个用例钉私有的任务表。
  - test_busy_does_not_block_on_in_process_task_table_after_terminal_event
- `test_project_parameters.py`（1 个）：项目级参数覆盖全局、事项创建时冻结、没有设置的项目用全局现值、建档单轮上限按项目值、不能按项目设置的参数与超界被拒绝，属 R3（检查时限与单轮上限是路线图阶段二写明的定义参数）。`test_project_value_does_not_change_runs_created_before_it` 是 D3：同一个「创建后改项目值不影响已创…
  - test_project_value_does_not_change_runs_created_before_it
- `test_project_queries.py`（8 个）：只读快照与位置、查询不写事件、重建读模型得同样结果且不调模型、询问三种状态、流转记录按成果命名、交付文件只限封存路径、封存损坏即拒绝、事项范围校验、恢复位置，都命中 R2 或 R3，留。以下 8 个函数命中 D2 或 D3。
  - test_an_upgrade_stopped_run_puts_the_door_sign_on_the_room
  - test_event_detail_http_reports_unreadable_git_references
  - test_event_detail_reads_only_the_recorded_git_reference
  - test_event_detail_reads_the_recorded_contract_shape_from_git
  - test_overview_does_not_settle_a_released_run
  - test_query_time_does_not_grow_with_unrelated_history
  - test_read_models_write_only_their_own_database
  - test_the_flow_records_are_rebuilt_when_the_derivation_version_changed
- `test_project_stream_fields.py`（2 个）：项目流事件种类与字段的清单：删字段、删种类、改类型、删取值时失败，新增时通过并要写明旧事件里的缺省含义（ADR-0019，R2：字段只增、旧版本能读）。前四项静态核对与写入路径拒绝删除、改类型、删取值的用例留。删两项：`test_writing_the_committed_manifest_is_a_no_op` 不带 `--write-…
  - test_writing_rejects_changing_the_base_type_of_a_fixed_value_field
  - test_writing_the_committed_manifest_is_a_no_op
- `test_projects.py`（7 个）：主体是 R1 与 R3：项目流自有流与全局位置、采纳继承上一个成果的树、基线在放行前变了就挂起、停止的 run 不采纳、两表重建等于在线、归档只读、中断后补做结算、伪造的跨项目事件不被推导、部门设置的期望版本。其中 7 个函数命中 D2 或 D3。
  - test_cli_project_list_and_show
  - test_compaction_pinned_input_contains_project_part
  - test_create_run_rejects_mixed_ownership_parameters
  - test_project_context_guidance_stays_before_department_rules
  - test_project_context_part_is_pinned_between_current_work_and_department_rules
  - test_project_context_text_is_deterministic_and_ordered
  - test_status_queries_keep_work_item_states_without_reading_run_histories
- `test_proposal_version_check.py`（6 个）：这个文件守「引用的版本是不是最新」（R1）：校验以后另一方写入则提交被拒绝并重新判断；正式成果声明依据的版本，缺失、过期、首份不是 null 都拒绝并给出当前版本，重交以后接纳。留八项：两项并发（输入、取消），经主机的缺失、首份、过期重交三条，以及放行前交付依据的 PRD 已被取代时不放行（唯一核对「放行绑定当前有效 PRD」，R3）。删…
  - test_a_delivery_bound_to_a_stale_spec_is_rejected
  - test_a_first_spec_must_declare_a_null_basis
  - test_a_missing_basis_declaration_rejects_the_submission
  - test_a_review_bound_to_a_stale_delivery_is_rejected
  - test_a_spec_may_declare_the_current_basis
  - test_a_spec_that_declares_the_wrong_basis_is_rejected_with_the_current_version
- `test_protocol_belongs_to_definition.py`（1 个）：整体是 ADR-0033 的合同（R2：模型访问定义的协议字段、调用目标、准入作废），是 #969 指定的「保留的那一份」，其中「连接上出现协议字段被拒绝」按特别规则 3 是防回退护栏，必须留。只删 1 个：它的断言是 test_a_custom_connection_uses_its_own_address_for_every_prot…
  - test_bound_target_carries_the_protocol_of_the_definition
- `test_provider_catalog.py`（6 个）：整体 R3（目录校验、准入、凭据不进事实、推理档位声明）。删 6 个：3 个已在 #969；`test_model_with_protocol_is_accepted` 是 ADR-0033 用例的子集（D3）；换模型限档那条被按次解析的整条路径完全覆盖（D3）；未知窗口那条与按次解析的单元用例同一结论（D3）。
  - test_each_target_is_independent_and_frozen_after_publish
  - test_model_definition_requires_a_protocol
  - test_model_with_protocol_is_accepted
  - test_provider_config_rejects_a_protocol
  - test_swapping_to_a_model_with_other_levels_keeps_the_saved_tier_and_limits_the_request
  - test_unknown_model_capacity_is_rejected_for_a_bound_department
- `test_provider_protocols.py`（19 个）：留下每种协议一份线格式基线（R2）、推理参数的三种映射（design 7.4）、取消、流断开不算完成、空输出与凭据被拒的重试与停止（R1）。其余是同一结论的重复（D3）、单个服务偶然行为的钉死（D2）、新运行里不会出现的输入（D5）。
  - test_anthropic_base_url_does_not_duplicate_v1
  - test_cancel_before_start_holds_only_within_the_activation
  - test_chat_chunk_identity_that_is_not_a_string_is_not_recorded
  - test_chat_finish_reason_is_visible_in_the_persisted_attempt_details
  - test_chat_sends_tool_result_paired_by_tool_call_id
  - test_error_reply_broken_while_the_request_is_created_is_a_retryable_connection_failure
  - test_facade_adapter_accepts_chat_targets
  - test_go_preset_base_url_reaches_the_official_protocol_path
  - test_messages_budget_sends_budget_tokens_by_level
  - test_messages_http_error_code_is_read_from_the_anthropic_error_type
  - test_messages_requires_max_output_tokens_before_connecting
  - test_model_test_admits_a_chat_model
  - test_model_test_sends_no_reasoning_parameters_without_a_declaration
  - test_model_test_uses_its_own_diagnostic_session
  - test_partial_stream_is_retryable
  - test_request_the_client_refuses_to_send_is_not_retryable
  - test_responses_requests_carry_identity_headers
  - test_responses_sends_reasoning_effort_for_the_sent_tier
  - test_stream_that_ends_without_any_visible_output_is_a_retryable_empty_output_failure
- `test_provider_retry_engine.py`（3 个）：这份文件用假模型测引擎的重试，几乎都是 R1（重试上限、重试等待可取消、不可重试的不重试、失败尝试只记不执行、停止原因来自封闭清单）。只有三项是同一结论在别的文件已经守着。
  - test_provider_timeout_retries_without_a_logical_time_budget
  - test_retry_reassembles_context_before_each_attempt
  - test_retryable_attempts_stop_at_the_32_step_limit
- `test_provider_tls.py`（2 个）：证书校验属于第一环里真实服务会触发、一旦回退整条路径出错的行为（企业证书库、MITM），保留三项：不受信的证书不放行、受信来源里的证书放行、模型列表读取同一信任来源。删掉的两项只是同一结论的错误文字（D3、D2）。
  - test_model_list_reports_the_certificate_verification_failure
  - test_model_test_reports_the_certificate_verification_failure
- `test_providers_module.py`（8 个）：删 8 个。2 个已在 #969。`test_facade_surface_usable` 只核对方法名存在（D2，门面方法名是模型缝一侧可重写的内部）。`test_frozen_snapshot_immutable` 钉的是 `FrozenInstanceError` 与 `MappingProxyType`（D2），冻结快照来自 D2…
  - test_facade_surface_usable
  - test_frozen_snapshot_immutable
  - test_missing_credentials_reported_per_item
  - test_model_requires_a_protocol
  - test_provider_config_rejects_a_protocol
  - test_secret_never_in_public_view_or_logs
  - test_structural_save_without_ready_credential
  - test_unsupported_protocol_rejected_before_request
- `test_public_tree.py`（15 个）：公开树是封存快照的内容与摘要的承载（R1/R3 边界、独立证据）。留 11 项：整树字节往返、整树核验（多文件、少目录、改字节）、私有回执与时间戳不改公开身份（回执绑定摘要的前提）、不安全路径（28 项展开）、符号链接（5 种）、硬链接、Windows junction、采集时树变动即拒绝、还原不覆盖已有目的地（每次从封存建干净工作区）、…
  - test_a_capture_over_a_workspace_without_ignore_files_never_opens_a_probe
  - test_a_nested_git_directory_keeps_its_own_ignore_rules
  - test_an_ignore_file_in_a_nested_directory_only_excludes_paths_under_it
  - test_capture_rejects_a_file_rewritten_during_its_read
  - test_capture_rejects_special_files_without_trying_to_read_them
  - test_captured_tree_cannot_hide_mutable_or_unvalidated_file_contents
  - test_empty_public_tree_can_be_restored
  - test_ignore_rules_are_decided_for_a_workspace_deep_in_the_file_system
  - test_ignore_rules_exclude_nothing_when_the_workspace_has_no_ignore_file
  - test_ignore_rules_exclude_the_paths_the_project_lists
  - test_manifest_rejects_ambiguous_or_incomplete_tree_structure
  - test_restore_rejects_a_linked_destination_parent
  - test_restore_verifies_written_bytes_before_reporting_success
  - test_the_probe_repository_lives_outside_the_workspace_and_stays_clean
  - test_unicode_file_names_and_contents_remain_exact
- `test_qa_test_materials.py`（4 个）：质检的测试材料是独立证据的一部分（local-tools 设计）。留 4 项：质检写测试再跑检查、材料先保存后检查、检查回执与放行带材料摘要；下一个质检会话拿到已保存的材料；材料目录不进公开树、交付、工程工作区，工程的文件工具读写它被拒（防工程拿质检的测试作弊，R3「交叉演进」）；质检改了材料后，带旧回执的放行被拒，重跑后才放行。删 4 …
  - test_no_event_when_unchanged_or_empty_initial
  - test_pause_and_resume_preserves_qa_tests
  - test_persistence_and_reload_survives_new_loopsystem
  - test_qa_emptying_test_materials_allows_release
- `test_quality_facts.py`（1 个）：质检在对当前交付下结论以前只看到工程内容的事实部分，三条通道，属 R3「独立的证据」（independent-verification.md，#554 已实施）。第二项只是第一项加预测性探索那一轮，D3。
  - test_predictive_exploration_asks_carry_only_the_facts
- `test_range_edit.py`（11 个）：留 4 项：回执带新摘要与区间（R3）、读后文件已变则拒绝且不改（起点快照前置条件）、符号链接不能被写穿、检查通过后树变动则通过结论失效（R3 绑定）。删 12 项：#719 的原文定位启发与各种错误分支（D1 无位置）、路径规则的第三份重复（D3）、与别处重复的整轮用例（D3）。
  - test_a_span_that_does_not_exist_is_located_by_the_text_instead
  - test_a_unique_text_is_edited_after_the_lines_above_it_moved
  - test_adopted_baseline_applies_to_next_work_item_and_replay_verifies
  - test_ambiguous_expected_text_is_chosen_by_start_line
  - test_changed_tree_after_delivery_rejects_the_stale_release
  - test_encoding_difference_is_rejected_without_modification
  - test_link_made_by_a_command_during_a_run_is_refused_as_a_tool_result
  - test_missing_target_is_rejected_without_modification
  - test_mutated_check_copy_does_not_become_the_tested_delivery
  - test_two_edits_in_one_activation_produce_a_complete_delivery_tree
  - test_unsafe_paths_are_rejected_without_modification
- `test_release_archive_integrity.py`（4 个）：放行前核验封存的交付树、放行绑定当前交付与快照，是 R1 与 R3 的核心，留 3 项：交付树清单或 blob 缺失与损坏时放行被拒、交付摘要与当前快照对不上时放行被拒、提交前快照变化时放行被拒。删 4 项：正例（D3）、两项篡改引用的边角（D3，同一规则在 test_tree_archive.py）、还原（D3）。
  - test_persisted_delivery_tree_restores_independently_of_workspace
  - test_release_rejects_a_delivery_archive_bound_to_another_run
  - test_release_rejects_a_same_run_reference_that_is_not_a_tree_manifest
  - test_release_verifies_the_persisted_tree_before_marking_done
- `test_release_check.py`（2 个）：R1，发布检查由已安装的实例提供，内核差异、行数、导入方向、评测专有内容，以及「待发布提交里改清单与检查改不动结果」都是第三环的不变式；决定请求「实例升级」的查询合同与 changed_by 属 R2。两项只是同一个结论的内部写法：D3 加 D2。
  - test_the_report_is_carried_by_the_instance_upgrade_decision_request
  - test_answering_the_instance_upgrade_decision_records_the_choice
- `test_release_script.py`（1 个）：R1/R3，发布脚本是第三环的评价材料（在内核清单里），「wheel 带页面文件、拒绝脏工作区、已发布标签、不在 main、未推送、发布检查不过不上传」都要留。只有一项是同一个 wheel 的重复侧面：D3 加 D5。
  - test_the_wheel_carries_no_installer_or_update_manifest
- `test_request_time_limit.py`（4 个）：保留的四项守「时限只计等待模型的时间、按两段数据之间的间隔算」这条边界（R1：时间上限、封闭的停止原因 provider_timeout），三种协议都核对。删掉的四项只是启动性能：SDK 模型是否已构建、平台识别次数、SSL 上下文复用、新进程第一次请求的用时，属于 D2，总图与路线图里没有这类合同。
  - test_calls_reuse_one_ssl_context_instead_of_loading_certificates_each_time
  - test_first_request_in_a_new_process_fits_provider_delay_plus_one_second
  - test_platform_is_identified_when_the_catalog_uses_the_protocol
  - test_sdk_stream_models_are_built_when_the_catalog_uses_the_protocol
- `test_responses.py`（33 个）：留下 Responses 协议的基线（请求字节、无多余上下文、无状态的工具往返）、重试同一输入、流错误事件分类、用量与流条目只记一次、实发请求体与记录的一致且不含凭据、HTTP 错误白名单与回显不落库、非完成终态、终态到达即返回、取消。其余是连接复用与排空、传输阶段名、SDK 与服务偶然形状（D2），或在更低层与别的文件已经守着（D3），…
  - test_cancel_during_completed_stream_drain_has_priority_and_closes_the_loop
  - test_compaction_output_limit_is_sent_to_the_sdk_without_hidden_prompt_changes
  - test_completed_stream_tail_read_error_keeps_terminal_success_and_closes_connection
  - test_completed_stream_with_done_marker_finishes_promptly_but_does_not_reuse_connection
  - test_completed_stream_with_segmented_eof_is_reused_and_does_not_observe_tail
  - test_concurrent_request_is_rejected_without_disturbing_registered_request
  - test_config_requires_explicit_values_and_never_reads_environment
  - test_connection_loop_closes_clients_when_it_closes
  - test_connection_loop_drops_failed_keepalive_connection_before_next_request
  - test_connection_loop_reuses_http11_connection_across_adapters
  - test_http_400_gemini_status_keeps_sanitized_type_without_message
  - test_http_400_keeps_bounded_redacted_error_identity
  - test_http_429_insufficient_quota_is_permanent_and_keeps_only_safe_diagnostics
  - test_http_retry_after_preserves_long_server_delay_for_engine
  - test_invalid_timeout_is_unavailable_without_exposing_secrets
  - test_malformed_stream_json_is_an_explicit_provider_error
  - test_missing_usage_is_unknown_not_a_provider_estimate
  - test_null_terminal_output_is_explicit_error_and_preserves_usage
  - test_nullable_reasoning_content_is_preserved_through_sdk_and_next_request
  - test_observation_host_io_error_is_not_reclassified_as_retryable_connection
  - test_product_spec_change_record_schema_has_object_type_for_responses
  - test_request_observation_failure_stops_before_network_send
  - test_sdk_connection_error_with_local_protocol_cause_is_not_retryable
  - test_server_overloaded_stream_error_is_exhausted_at_three_attempts
  - test_server_overloaded_stream_error_retries_after_partial_output_without_running_tools
  - test_silent_network_times_out_and_keeps_completed_output
  - test_stream_disconnect_does_not_turn_partial_output_into_success
  - test_stream_error_maps_context_overflow_without_echoing_the_error_body
  - test_stream_item_observation_does_not_invent_the_returned_model
  - test_terminal_near_request_deadline_is_not_reclassified_during_drain
  - test_transport_failure_diagnostics_capture_safe_trace_boundary
  - test_transport_failure_without_trace_keeps_boundary_unknown_and_makes_one_call
  - test_transport_trace_state_is_isolated_between_adapter_calls
- `test_retry_input_boundaries.py`（1 个）：重试等待、输入作为通知带进重试（#964 已改）、指导同样、取消唤醒长等待、运行时间在等待中用完、重试计入模型步数，属 R1 与 R3。`test_input_during_a_retry_wait_does_not_end_it_and_the_retry_carries_it` 与 `test_input_during_retry_b…
  - test_input_during_a_retry_wait_does_not_end_it_and_the_retry_carries_it
- `test_run_check.py`（7 个）：R3 留 5 项：带依赖的项目里检查回执绑定快照、命令字符串必填且自报退出码不算证据、时限缺省与钳位、工程检查被接纳且质检在自己副本上重跑并放行、交付引用 bash 回执被拒。删的是重复与副本目录清理（D3、D2）。
  - test_cancel_stops_a_running_check
  - test_check_copy_is_deleted_after_timeout
  - test_check_copy_is_deleted_when_check_finishes
  - test_check_copy_mutation_does_not_bind_pass_to_original_snapshot
  - test_environment_inherited_and_secrets_redacted
  - test_run_check_runs_at_the_copy_root_with_bash
  - test_timed_out_check_stops_the_process_tree
- `test_run_event_version.py`（2 个）：留第一项：run 创建事件记下当前 run 事件版本，这是测试分层第 11.2 节说「由一条单独的测试核对当前值」的那一条（R2）。删两项：经事项创建的 run 也记版本，与第一项同一条 `create_run` 路径（D3）；合同的载荷类型带这个字段，`assert_payloads_follow_contract` 对每条载荷严格校验…
  - test_a_work_item_run_records_the_version_too
  - test_the_contract_carries_the_version_field
- `test_run_time_limit.py`（9 个）：留 4 项：运行时间用完以 time_limit 失败（R1）、两次激活之间的等待不计入运行时间（R1）、默认步数上限不拦 40 步（R1）、小的步数上限仍暂停（R1）。删 9 项：两个「收敛」用例是 D5（脚本有限，用尽即失败，终态永远成立）；两个 max_cycles 暂停是同一场景的逐字复制（D3）；`test_loosened_d…
  - test_convergence_with_defaults_always_terminates
  - test_convergence_with_long_script_reaches_terminal
  - test_explicit_small_max_cycles_with_large_time_limit
  - test_loosened_defaults_allow_more_than_old_cycle_limit
  - test_per_request_timeout_still_applies_inside_step
  - test_run_time_limit_sec_projected
  - test_small_cycle_limit_still_pauses
  - test_time_limit_event_recorded
  - test_time_limit_stored_in_run_created_event
- `test_saved_projections.py`（1 个）：留三项 R1：删光保存的投影以后重启补建，补建结果逐字相同，不调模型、不执行工具、不写事件；`rebuild` 用重放替换保存的投影；保存的投影与重放不一致时重放核对报错。删一项：读取运行状态不因历史变长十倍而变慢，用计时（取四十次最小值，三倍内）与内部字段 `tool_count` 核对，是保存的投影的性能优化，总图与路线图没有这条要求…
  - test_reading_the_run_state_does_not_slow_down_with_ten_times_the_history
- `test_search_tools.py`（8 个）：留 2 项：搜索回执带路径、行号与工作区摘要（读动作的回执绑定起点快照）、搜索看不到私有树（`.checks`）。其余是读工具的微语义（作用域、游标分页、read_range 区间、稳定性）和路径规则的重复，D1/D3。
  - test_read_range_full_middle_and_beyond_eof
  - test_read_range_truncation_cursor_returns_every_line_exactly_once
  - test_repeated_search_is_stable_and_change_reports_new_digest
  - test_search_scope_covers_every_file_inside_without_silent_skips
  - test_search_tools_are_read_only_for_all_departments
  - test_search_truncation_cursor_returns_every_match_exactly_once
  - test_symlink_paths_raise_verifiable_errors
  - test_unsafe_paths_raise_verifiable_errors
- `test_service_lock.py`（2 个）：同一个数据目录只允许一个服务进程（`test_two_service_processes_cannot_use_the_same_data_directory`）是 R1（一份事实只有一个写入者）与 R3（进程停了又起后锁释放），留；另两项是 D3。
  - test_the_api_only_listens_on_a_loopback_address
  - test_the_api_serves_the_local_network_with_the_lan_access_mode
- `test_smoke.py`（35 个）：见文件开头对 smoke 的整体判断。删的 35 个函数里：审计工具自身的输出与退出码规则（D1）、改事件或工件后审计须报未通过（D5、D2）、审计自己写的提示文字（D2）、与其他文件重复（D3：交付封存审计 ↔ `test_release_archive_integrity.py`，git 审计 ↔ `test_git_audit.py…
  - test_actual_inputs_are_checked_even_when_artifact_hash_is_valid
  - test_archive_audit_rejects_missing_or_modified_persisted_bytes
  - test_archive_audit_rejects_unrelated_delivery_digest
  - test_archive_audit_restores_from_persisted_bytes_after_workspace_changes
  - test_ask_audit_rejects_answer_before_start
  - test_ask_audit_rejects_ask_still_in_progress
  - test_ask_audit_rejects_mismatched_ask_parties_or_events
  - test_ask_audit_rejects_missing_pre_spec_ask
  - test_ask_audit_rejects_missing_revision_in_answer
  - test_ask_audit_rejects_revision_outside_ask_window
  - test_ask_audit_verifies_ask_pairs_and_revisions
  - test_audit_does_not_replace_missing_run_artifact_with_another_runs_copy
  - test_audit_preserves_department_history_when_request_returns_to_product
  - test_audit_rejects_missing_new_work_message_after_product_reactivation
  - test_compaction_audit_rejects_invented_sources_summary_or_visible_history
  - test_consistently_relabelled_steps_must_still_match_activation_event
  - test_directory_fake_protocol_is_flagged_and_never_passes_as_real
  - test_failed_run_without_requests_has_no_context_evidence
  - test_git_audit_rejects_valid_same_run_commit_with_wrong_accepted_material
  - test_model_input_audit_rebuilds_summary_scope_after_contract_changes
  - test_model_input_audit_rejects_changed_received_original
  - test_model_input_audit_rejects_changed_work_basis
  - test_model_input_audit_rejects_forged_adopted_versions
  - test_model_input_audit_rejects_forged_injected_source_metadata
  - test_model_input_audit_rejects_private_material_in_rehashed_pinned_text
  - test_model_input_audit_uses_the_project_department_prompt
  - test_native_audit_checks_every_step_and_actual_host_receipts
  - test_receipt_audit_rejects_new_contract_even_with_unchanged_spec_and_tree
  - test_smoke_does_not_merge_a_previous_runtime_report
  - test_smoke_markdown_reports_model_input_audit
  - test_smoke_reads_the_catalog_in_its_data_directory
  - test_smoke_requires_current_input_audit_and_host_receipts
  - test_tool_history_must_match_recorded_result
  - test_unbound_or_missing_request_cannot_certify_run
  - test_unmatched_host_receipt_does_not_pass
- `test_snapshot.py`（4 个）：R3 接入已有仓库：采集不改源目录、封存快照的身份与独立恢复、工作区与源目录互不影响、拒绝链接与宿主私有路径、封存清单里的保留名拒绝恢复、源目录删了仍能从工件恢复、忽略文件不进封存、不能打开的仓库以 source_invalid 拒绝，留。以下 4 个命中 D2 与 D3。
  - test_ingest_snapshot_function_writes_nothing_to_source
  - test_project_onboard_http_entry
  - test_provenance_is_empty_for_directories_that_are_not_work_trees
  - test_provenance_reads_a_repository_created_by_git_without_any_process
- `test_startup_reload.py`（3 个）：R3（热加载、没有文件与被删除的区别、外部损坏编辑保留上一个有效版本、凭据来源链、密钥卫生、未就绪时的启动与第一次请求进入待恢复）。删 3 个：`test_no_config_start` 与 `test_structural_partial_save` 的断言被同文件与别处覆盖（D3）；`test_frozen_snapshot_imm…
  - test_frozen_snapshot_immutability
  - test_no_config_start
  - test_structural_partial_save
- `test_startup_run_version.py`（1 个）：R3 启动时版本不同的未结束 run 按强制升级处理、从采纳成果或空树重新开始、版本相同与已结束的不受影响、建档事项按记录的快照重新开始，留 5 项；最后一项 D3。
  - test_a_work_item_created_by_the_user_has_the_user_priority
- `test_stream_deltas.py`（2 个）：留 2 项：步骤驱动把输出片段按调用尝试发布到通道、带偏移与范围、片段不写入事件日志（`harness.deltas` 与应用层「输出片段转发」之间的边；事件流的 `delta` 帧由 `test_events_api.py` 在接口层守着，R2）；`model_stream_progress` 同一阶段只写一条（日志不随流事件数增长）。…
  - test_delta_buffers_reject_out_of_order_and_repeated_fragments
  - test_delta_pump_merges_until_drained_and_reports_live_text
- `test_tool_contracts.py`（12 个）：留 3 个：`test_tools_are_host_tools_or_environment_actions`（R1，工具类别与动作类别决定许可）、`test_answer_prd_revision_parameter_definitions_match_submit_product_spec`（R2，提案合同参数一致）、`test_e…
  - test_bash_description_separates_action_receipts_from_delivery_check_receipts
  - test_guidance_tool_contract_lists_explained_and_requires_host_results_for_completed
  - test_normalize_scope_rejects_paths_outside_public_workspace
  - test_offers_with_input_filters_tools_that_need_images
  - test_quality_prompt_mentions_qa_tests_dir
  - test_read_output_and_stop_job_are_offered_to_all_departments
  - test_run_check_requires_a_command_string
  - test_scope_matches_files_and_directory_boundaries
  - test_smoke_exit_code_does_not_accept_fake_or_missing_evidence
  - test_submit_delivery_description_states_that_check_receipts_come_from_run_check
  - test_submit_review_description_rejects_engineering_receipts_as_quality_evidence
  - test_write_tool_descriptions_state_engineering_only
- `test_tools.py`（14 个）：这个文件是动作缝与独立证据的主体。R3/R1 留 13 项：质检检查只经 run_check、动作与回执可序列化、主机进程退出码不信自报、智能体读写不了 `.checks`、检查进程伪造不了回执、密钥脱敏、检查改了副本不绑定原快照、超时与取消的回执、取消先于开始不起进程、没有写工具的部门写不动文件、检查副本取自已封存的字节、检查中源工作区…
  - test_check_copy_does_not_follow_hardlink_into_external_file
  - test_check_does_not_keep_workspace_mutations
  - test_check_keeps_process_evidence_when_postcheck_capture_fails
  - test_failed_check_copy_does_not_leave_a_copy
  - test_failed_check_records_real_exit_code
  - test_list_files_is_recursive_and_prefix_is_a_plain_string_prefix
  - test_missing_check_command_does_not_leave_a_copy
  - test_module_import_check_preserves_complete_tree
  - test_read_file_returns_the_whole_file_without_line_numbers_and_rejects_non_utf8
  - test_refactoring_tools_move_and_delete_regular_files
  - test_refactoring_tools_require_explained_reason
  - test_run_check_requires_command
  - test_successful_and_failed_checks_do_not_leave_copies
  - test_write_file_creates_parents_and_replaces_the_whole_file
- `test_tree_archive.py`（4 个）：封存归档的加载核验是「封存内容与摘要对得上」的直接守卫（R1/R3）。留 4 项：原目录删除、存储搬家后仍能还原且不执行命令；坏 blob 或缺 blob 拒绝加载；清单与 blob 不一致的 9 种篡改拒绝；清单引用只在本事项内有效。删 4 项：严格 JSON 解析的细节、写后回读与既存坏 blob 的内部件数断言、事项编号校验（事项编…
  - test_archive_requires_strict_utf8_json
  - test_invalid_run_id_is_rejected_before_artifact_write
  - test_readback_failure_does_not_return_an_archive_reference
  - test_store_detects_preexisting_corrupt_blob_before_publishing_manifest
- `test_user_facing_labels.py`（1 个）：这些是封闭清单覆盖检查：运行状态、停止原因（对定义）、决定种类的中文名必须与核心同一份取值；83 个事件标签里每个占位都是该事件载荷的字段、渲染后没有空白占位。事件流的 `label` 是对外的字段，覆盖检查缺行即失败，符合路线图阶段二「声明式对照表全覆盖」的做法，R2。留。只有一个点状回归命中 D4。
  - test_adoption_line_shows_the_adopted_result_instead_of_a_missing_version
- `test_workspace_delivery.py`（8 个）：这个文件是封存快照与工作区边界的主体。留 7 项：新数据目录里归档并还原公开树的每个字节、交付封存失败不接纳、封存后源变动则不接纳也不替换已采集字节、改过树的检查回执即使摘要之后对上也不沿用、所有工作区文件操作共用路径规则（40 项展开）、所有操作拒绝硬链接、所有操作拒绝 junction 祖先（仅 Windows）。删 8 项：Work…
  - test_file_mutations_do_not_recursively_operate_on_directories
  - test_file_operations_preserve_legal_leading_spaces_in_names
  - test_move_and_delete_preserve_binary_bytes_and_do_not_delete_old_archives
  - test_move_never_overwrites_a_destination_created_after_validation
  - test_move_refuses_existing_destination_without_changing_either_file
  - test_move_rolls_back_its_destination_when_source_removal_fails
  - test_workspace_snapshot_and_copy_derive_from_one_capture
  - test_write_file_stores_the_given_bytes_without_newline_conversion
- `test_workspace_unrepresentable.py`（3 个）：停止原因 workspace_unrepresentable 在 stop_reasons.json 的封闭清单里（R1）。留 4 项：被忽略目录里的链接不暂停、也不进快照与封存与交付；命令留下链接则回执照常记录再暂停且不含主机绝对路径；提案提交时出现链接同样暂停；写入被忽略路径被拒。删 3 项：装配时出现链接（钉内部检查点，D2，与上面…
  - test_delivery_adoption_tree_excludes_ignored_directories
  - test_link_during_request_assembly_pauses_with_the_same_reason
  - test_read_of_an_ignored_regular_file_is_refused_with_the_ignore_rule_reason
- `test_writeback.py`（1 个）：R3 路线图阶段二第 2 项的主体：三树合并保留独立修改与可执行位、三种冲突即停、最终树核验（失败、缺检查、超时都停止）、目标分支在核验期间推进则停止并可重试、建档采纳不写回与变更已在目标里不写回与前序采纳未合入则挂起、推送结果未知后核实而不重复建分支、目标只按源目录解析、命令层拒绝理由。唯一一个用例被另一个用例完全包含。
  - test_writeback_with_an_empty_remote_works_outside_any_repository
- `test_writeback_branch.py`（2 个）：目标分支、四棵树摘要各自保留（R3 三树合并）、缺起点依据则停止（R3 冲突即停之外的封闭原因）、采纳登记的检查命令也进检查清单、未开启写回不产生写回，留。两个用例被 test_writeback.py 的用例包含。
  - test_writeback_executable_flag_follows_tree_manifest
  - test_writeback_failing_check_command_stops

### evals/tests

**整个文件删除**

| 文件 | 理由 | 接替 |
| --- | --- | --- |
| `test_baseline.py` | D4 加 D1。被测是 evals/baseline/collect.py 与 compute.py，也就是「Stage 3 里程碑下的 omp 流程基线」：抓取参数写死 `--stage-parent 9`、里程碑前缀 "Stage 3"，Stage 3 已归档被路线图取代。最大的一块（7 项）读… | 无人接替 |
| `test_regen_scenario3.py` | D4 加 D2。它守的是一次迁移：从提交 aaa91883 的旧版 JSON（evals/data/scenario-3-yudao-historical.json，「不可修改」）重算 docs/evaluation/scenario-3-yudao.json 与 .md，逐字节比对；另有一项 gr… | 无人接替 |

**删除其中的用例**

- `test_scenario2_scorer.py`（1 个）：R3，场景 2 判分器属于阶段二 · 2：用真实 pytest 跑临时仓库，junit 解析、失败三分类、聚合、隐藏测试盖掉交付改写的测试（评价材料不可被被测方改）、清单条数与条数对不上就报错。一项是同一个结论的弱写法：D3。
  - test_regression_failures_do_not_move_completion
- `test_yudao_runner.py`（5 个）：R3，路线图阶段二 · 2 的「Yudao 一侧运行器、五项过程检查点、噪声与费用、版本比较」都是它：隔离与作废（数据目录在仓库外、材料路径、上游仓库、摘要被改）、未知用量不记 0、五项检查点、报告、改进/无差别/退化/受阻。其中 5 项是重复或钉文字。
  - test_a_tampered_check_voids_the_scoring_run
  - test_stray_bytecode_in_the_checks_does_not_change_the_digest
  - test_requirement_text_names_the_missing_start_file
  - test_missing_usage_fields_are_unknown
  - test_release_checkpoint_fails_on_a_cancellation

### client/tests

**整个文件删除**

| 文件 | 理由 | 接替 |
| --- | --- | --- |
| `e2e/access-token.spec.ts` | D1。局域网访问令牌在路线图阶段三第 3 条（「接口的访问令牌」），总图第四节接口缝只有命令、查询、事件流三种，没有令牌。服务端「无令牌、无效令牌 401，撤销后 401，有效令牌放行」已有 harness 测试。 | `harness/tests/test_access_tokens.py`（约 122 至 189 行：无令牌与无效令牌返回 401、有效令牌放行、撤销后 401）。页面侧的「填写令牌」表单与令牌存 … |
| `e2e/command-invalid.spec.ts` | D4。一张已关闭工单（#740）的现场回归，断言的是「这次请求被拒绝：……不能为空」这句页面文案，而且守的行为（422 变成中文说明）在更低的层有测试。 | `unit/command-problem.test.ts::422 的响应体按接口层校验错误认，页面上显示服务端给的那句话`、`::反馈组件渲染出来的段落不是空的：页面上看得见那一句说明`；服务端 … |
| `e2e/kernel-guard.spec.ts` | D1。路径守卫与内核清单在路线图阶段三第 3 条，原型 v14 待办第 4 条也明说「内核修改的决定卡片现在不做」。服务端「改了内核路径的交付不自动采纳，批准以后采纳，拒绝以后不采纳」有 harness 测试。 | `harness/tests/test_projects.py::test_release_touching_kernel_paths_is_not_adopted_without_approval`… |
| `e2e/materials-read-failure.spec.ts` | D3 加 D4。「读不出来写读取失败、不写没有原文」是 #714 的现场回归，判断逻辑在单元层已经有一一对应的用例。不在路线图阶段一、二里（见低把握清单第 4 条）。 | `unit/materials-read.test.ts::读不出来时是「读取失败」，不是「没有原文」`、`::交付文件：读不出来时是「读取失败」，读到了才给内容`；`unit/optional-re… |
| `e2e/models-read-failure.spec.ts` | D3 加 D4，同上（#776）。 | `unit/models-read-failure.test.ts` 全部三项（目录文档读不出来、没有失败、空文档不让保存）。 |
| `e2e/page-version.spec.ts` | D1。「页面与服务同出一个发布，版本不同自动重新加载」属于网页的发布与升级（工单 #374），不在路线图阶段一、二，总图接口缝管的是接口版本（`shell.spec.ts` 保留的「接口版本不同时页面只显示版本不同的提示」已经守着）。第二项用固定的 15 秒等待。 | 接口版本不同的提示：`shell.spec.ts::接口版本不同时页面只显示版本不同的提示（写明两边的版本），不打开页面、不执行命令`、`unit/page-version.test.ts`。自动重新… |
| `e2e/read-failure-pages.spec.ts` | D3 加 D4（#775）。七页逐页把查询拦成 500，断言写「读取失败」；判断「读不出来」与「本来没有」的逻辑在单元层已有，一一对应；本批工单关心的是页面文案，路线图阶段一、二没有这一项（见低把握清单第 4 条）。 | `unit/page-read-failure.test.ts::读不出来：写「读取失败」与服务端给的原文`、`::观测页：总数读不出来时说明读不出来，不安静地少一句数字`；`unit/read-fa… |
| `e2e/read-failure.spec.ts` | D3 加 D5。第一项同上（#728）；第二项「项目列表读得出来时不写读取失败」几乎恒真，后端预置了四个项目，别的用例每次都在读这个侧栏。 | `unit/read-failure.test.ts`、`unit/view-sync.test.js`。 |
| `e2e/runtime-slots.spec.ts` | D3 加 D2。第一项只核对侧栏有「运行与执行槽位」入口并能点开，`shell.spec.ts` 保留的「能力清单缺少某个查询时……」已经核对该入口存在；第二项钉一句副标题「当前一次只执行一个事项；不同项目并行在多项目并行完成以后开放」，路线图里并行是阶段四的事，这句话会随之改。 | `shell.spec.ts::能力清单缺少某个查询时，依赖它的页面入口不出现`；排空与强制升级的文字：`unit/drain-text.test.ts` 六项；排空行为：`harness/tests… |
| `e2e/service-outage.spec.ts` | D3 加 D4。第一项（服务停了以后页面变灰、重连、恢复）与 `shell.spec.ts` 保留的「事件流断开时窗口整体变灰并写明断开的时间，重新连上以后恢复」是同一件事（R3 阶段二「进程重启后接续」的页面侧），多出来的「重连间隔递增」由单元测试守，还要固定等 20 秒；第二项是 #777 的现… | `shell.spec.ts::事件流断开时窗口整体变灰并写明断开的时间，重新连上以后恢复`；`unit/reconnect-backoff.test.ts::连不上：等待时间按 1、2、4……秒递增… |
| `unit/attempt-failure.test.ts` | D4 为 #305（空输出按失败处理）的现场写的两行（失败类型、结束原因）；D2 钉的是请求详情这两行的取值先后（记录上的分类先于诊断里的错误种类）。 | e2e/project.spec.ts 第 701 行附近「失败类型与结束原因（工单 #305）」守详情里这两行。 |
| `unit/floor-screen-model.test.ts` | D2 它走的是 `floorModelOf` 加楼层驱动，断言 `status === "running"`、小人姿势 `type`、`sit_wait`、`ACTIVE`、`IN_ROOM`。#952 把状态对应搬进 `translate/tables.ts`，#953 把楼层模型换成画面合同的楼… | 已在 #952（translate-tables.test.ts）与 #953（translate-floor.test.ts、pixel-floor.test.ts 里「进行中的事项进房间」）。 |
| `unit/flow-segments.test.ts` | D4 钉的是流转种类「版本交付/询问/问题反馈」的分段规则（#866 的现场）；原型 v14 待办第 7 条说服务端要改成每种成果一种流转；覆盖层本身是 #950「不做」的范围（#396、#398、#400）。D2 分段规则是覆盖层自己的显示规则。 | e2e/floor.spec.ts::流转覆盖层：同一对部门的两种非返工流转合成一段，返工另成一段，PRD 新版本各成一段，标签互不遮挡。 |
| `unit/item-department.test.ts` | D3 与 D2 为 #842 用真实浏览器挂载看板读回文字；分列与部门中文名已经由 board-columns.test.ts 的纯函数项守着；第二项断言看板文字里一个英文字母都没有，很脆。 | unit/board-columns.test.ts::部门列按部门分列，已放行与已采纳各自一列；unit/board-columns.test.ts::停止的事项没有部门时不写「未知部门」，页面自己… |
| `unit/materials-download.test.ts` | D2 交付文件下载链接的拼写（data URL、文件名）是页面的便利功能，不是合同；#748 的现场。 | e2e/project.spec.ts 第 629 行「文本交付文件也有下载入口：下载到的内容与展开框里看到的逐字相同」。 |
| `unit/materials-read.test.ts` | D3 资料页的读取状态（读取失败、没有原文、有原文、读取中）与共用的 read-failure 合同重复；这一条「读不出来与本来没有内容分开」由 contract 层的 read-failure.test.ts 守，页面一侧有 e2e。 | unit/read-failure.test.ts::读不出来与本来就没有内容，说的是两句话；e2e/materials-read-failure.spec.ts。 |
| `unit/models-collect-candidates.test.ts` | D2 与 D4 为 #843 的页面提示句（获取模型列表要先保存连接），断言的是页面自己的文案，并且要求句子里没有任何英文字母。 | e2e/models.spec.ts。 |
| `unit/models-read-failure.test.ts` | D3 e2e 已经逐项守着：目录读不出来时页面写读取失败；目录文档读不出来时编辑器说明读不出来并且不让保存空文档。这里的函数只是页面内部的两个小判断。 | e2e/models-read-failure.spec.ts。 |
| `unit/observe-department-filter.test.ts` | D2 页面路由的拼写（?dept=、?w=）、筛选初值与中文提示句，都是观测页自己的东西；#801 现场。 | e2e/project.spec.ts 第 775 至 778 行（部门筛选条件带进观测页，页面写「只看质检的请求」）。 |
| `unit/overview.test.ts` | D2 用真实浏览器挂载新事项输入区，核对两个输入框的草稿、两个按钮的禁用与清空、离开再回来草稿保留，全是一个页面组件的内部状态；#652 现场。 | e2e/project.spec.ts 与 e2e/initial-files.spec.ts（点「作为新事项开始」创建事项）。 |
| `unit/page-contact-sheet.test.ts` | D1 与 D4 为 #376 的截图联系表工具写的清单，对照的是原型 v10 的档位表与页面清单（当前定稿是 v13）；它测的是一个开发辅助脚本，不是产品。 | 无人接替（脚本自己不是合同）。 |
| `unit/path-label.test.ts` | D2 顶栏路径写成「项目名 / 页名」的拼写，是页面标题。 | e2e/project.spec.ts、e2e/timeline.spec.ts 里的顶栏路径断言（未逐条核对）。 |
| `unit/pixel-device-resolution.test.ts` | D3 整数倍缩放在 e2e/device-resolution.spec.ts 与 e2e/pixel.spec.ts 里用真实画布核对；文件自己写明「真实页面上的画布尺寸……由端到端用例检查，这里不重复」；字体栈等于原型的那一项是 D2 钉画法。 | e2e/device-resolution.spec.ts；e2e/pixel.spec.ts::像素画面按容器宽度取整数倍缩放，缓冲区是逻辑尺寸的整数倍。 |
| `unit/routing-replay.test.js` | D2 页面路由里 at 与 round 参数的解析与拼写（#296 现场）；名字带 replay 但只是页面地址，不是像素回放。 | e2e/timeline.spec.ts::回放位置写在路径的 at 参数里：刷新以后回到同一位置，回到现在清除参数；e2e/timeline.spec.ts::概览页的回放位置写在路径的 at 参数… |
| `unit/scope-paths.test.ts` | D2 事项范围写在 ?w= 里的地址拼写与换范围留在当前页，是页面路由自己的约定（#746 现场）。 | e2e/project.spec.ts、e2e/home.spec.ts、e2e/floor.spec.ts 里带 ?w= 的页面跳转（未逐条核对）。 |
| `unit/slot-view.test.ts` | D4 与 D2 为 #727 写的：现在一次只执行一个事项，参数是 8 页面也显示 1，副标题的句子；多项目并行是阶段四，到那时这个页面要重写。 | e2e/runtime-slots.spec.ts::这一页显示 1 个槽位，副标题不再承诺并行（同一句副标题）。 |

**删除其中的用例**

- `e2e/department-settings.spec.ts`（3 个）：留四项，命中 R3「按部门选模型」「模型准入」与 R1「期望版本」：另选模型以后工作间随事件更新并可改回跟随默认（撤回）、版本冲突时不覆盖别人的修改、运行中更换模型以后最近一次请求用新模型、所选模型准入作废时显示「无法使用」。其余三项是 D4 与 D3。
  - 不改任何内容直接保存：服务端按「没有改动」接受，页面上没有错误
  - 把项目写过的部门 Prompt 恢复成内置默认：来源说内置默认，文字回到内置的那一段
  - 1920×1080 与深色下弹窗与工作间照常渲染，无横向滚动
- `e2e/home.spec.ts`（7 个）：留两项：「回答一个等待中的决定请求」（R3 决定请求：命令带版本、事件到达后移出列表、run 按回答继续）与「离开期间的报告」（R3 阶段二·4「离开期间的报告」与来源回链：展开来源事件）。其余是 D3、D2、D4。
  - 状态项「待你决定」的数量与 decisions.list 中等待回答的数量一致
  - 首页「待你决定」列出等待回答的决定卡片，卡片头写明种类、项目与挡住的对象
  - 回答一个已经回答过的决定请求时，卡片显示原因并刷新
  - 首页项目区块的说明不出现接口名
  - 项目列表的每个字段与 projects.list 一致
  - 项目标签栏的「待你决定」只列出本项目的决定请求，点击展开卡片
  - 1920×1080：离开期间的报告横向排成多列，不出现横向滚动；控制台错误为零
- `e2e/initial-files.spec.ts`（2 个）：留第一项「填写起始文件夹新建项目，概览写明起点，开始事项以后部门工作间读到起点文件」：它走通「工作区从封存快照建」与「动作与回执」（总图动作缝：工作区每次从封存快照建、每个动作有回执；R3 本机改文件与跑命令带回执），是端到端里唯一读回执载荷的用例。其余两项是 D3。
  - 填写不存在的起始文件夹时表单显示原因，没有出现新项目；留空时概览没有起点行
  - 1920×1080：表单与起点行没有横向滚动
- `e2e/models.spec.ts`（15 个）：模型目录、准入、按部门选模型、凭据不进事实是 R3 阶段一明写的行为，留六项：候选取自上游并经模型测试准入、Key 不回填且页面与网络响应都没有 Key（R1 凭据不进事实）、部门默认只列已准入的定义、改地址使准入作废（影响列表与确认）、新建连接获取候选勾选加入后自动测试并进入部门默认、手动添加模型的失败与修正（失败留在候选，修正后准入）…
  - 页面显示连接摘要、模型表与部门默认，且没有横向滚动
  - 模型测试的真实上游返回 401，模型行显示未通过与原因
  - 新建连接表单的超时默认值与后端一致
  - 编辑表单恢复服务方案与协议，选方案与协议自动填入请求基址，缺少容量的行不能保存
  - 新建自定义连接、模型测试通过后改协议保存，这条定义回到候选
  - 编辑 JSON 打开目录文档，格式化与保存走真实校验
  - 编辑 JSON 带准入字段或引用候选时保存被拒绝，页面指出字段位置
  - 删除被引用的连接时显示引用方并拒绝，删除没有引用的连接时确认框列出将一并删除的定义
  - 引用作废的定义时下拉框显示「无法使用：准入已作废」，所选模型未声明档位时禁用档位
  - 自定义方案添加连接、获取候选、预填的 ID 保存成功；缺一项容量写明缺少且不能保存；添加与保存都有成功提示
  - 新建表单选择 OpenCode Go 与无协议头自定义地址自动填写字段
  - 获取模型列表失败时页面显示请求的地址与状态码（工单 #384）
  - 新建连接时点「获取模型列表」：页面说明先保存，不发请求
  - 新建自定义连接保存 Key 后直接获取模型列表并测试空连接
  - 从项目页进入模型管理，点「返回原界面」回到项目页
- `e2e/notifications.spec.ts`（3 个）：留第一项「决定请求、等待模型服务、标签页标题与没有通知权限时的页面」：用户不在场是常态，决定请求到达时通知用户，通知写明项目与事项、同一件事两个页面只发一条、点击以后打开那张卡片；它是「你回答停在写入口的决定请求」的唤醒路径，端到端里只有这一处走真实的 Notification。两边的道理：路线图与总图没有写通知，原型 v12 只有「标签…
  - 等待模型服务时发出通知（工单 #375）
  - 标签页的标题随待决定的数量变化，没有待决定的事时不显示数字（工单 #375）
  - 没有通知权限时页面照常工作，控制台没有错误（工单 #375）
- `e2e/onboarding-prd.spec.ts`（2 个）：留第一项「说明为空的修改不提交，填了修改意见出现第二轮，确认以后概览显示建档基线」：R3 阶段二·1「接入已有仓库」「初始 PRD，你确认以后它是之后事项的基准合同」。其余两项是 D2、D3。
  - 1440×900：提出修改等到第二轮后，资料页按轮列出第 1、2 轮与确认记录，链接定位到第 2 轮
  - 1920×1080：宽屏下卡片与资料页可用，没有横向滚动
- `e2e/onboarding.spec.ts`（3 个）：留第一项「经对话框完成一次接入，建档状态标记随事件变化，部门房间出现阅读已有项目」（R3 阶段二·1 接入已有仓库）。其余三项是 D3。
  - 填写无效的源目录时对话框显示原因与相对路径，没有出现新项目
  - 放弃等待确认的建档以后重新开始建档可用，点击以后出现新的建档事项
  - 1920×1080：经对话框完成一次接入，项目列表显示建档状态标记，没有横向滚动
- `e2e/project.spec.ts`（15 个）：留六项。概览（摘要、看板、流转记录、点开原始事件：R3 来源回链）、概览里记录原文与新的要求并新建事项（页面里唯一一处下意图、开始事项，见低把握清单第 3 条）、资料页（intend、PRD、交付文件：只读事实的核心页面）、观测页（尝试与用量，模型缝）、成果写回的页面入口（R3 阶段二·1，只验入口与拒绝）、界面上的部门指导（R3 中途的…
  - 缺少部门默认时新事项被拒绝：提示是中文并带两个去处
  - 概览：没有进行中的事项时，记录原文写入事件流
  - 侧栏：显示归档的项目以后能取回归档的项目
  - 部门工作间：标题区、检查区页签、部门消息与部门设置弹窗
  - 工程与质检部门：没有配置部门 Prompt 时用内置默认 Prompt
  - 三个部门的页签切换：标题区的色条与强调色随部门变化，房间在深色舞台中
  - 部门工作间：本部门的模型请求只显示这个部门的请求
  - 顶栏的事项范围：换一个范围留在本页，切页签不丢范围
  - 设置页：基本信息、部门设置与源目录
  - 设置页：改完部门设置并保存以后部门设置那一节自己更新（工单 #674）
  - 设置页：基准版本过期时提示重新读取
  - 草稿：切换页面、刷新以后仍在，切换项目以后不串
  - 外壳：状态项、项目菜单、事项选择与侧栏跳转
  - 深色配色：背景随系统偏好改变，页面内容照常渲染
  - 宽屏：每个页面无横向溢出、深色下同样成立
- `e2e/shell.spec.ts`（9 个）：留六项，命中 R2：页面打开读能力清单进入外壳；能力清单缺某个查询时依赖它的入口不出现（总图接口缝「字段只增、旧新兼容」）；顶栏待决定数量与 `decisions.list` 一致；事件流驱动视图刷新（命令到事件到页面）；接口版本不同时只显示版本提示（「改了合同版本必升」）；事件流断开恢复（R3 重启后接续的页面侧）。其余九项是 D3、D…
  - 页面连接以后直接显示状态项与离开期间的报告
  - 从想法新建：提交成功、项目出现在列表以后表单关闭，重新打开时字段为空
  - 接口版本相同而能力清单多出查询时，客户端正常使用（新增查询不要求更新客户端）
  - 视口 1920×1080 下外壳可用，没有横向滚动条，控制台错误为零
  - 初次连接期间顶栏写连接中，事件流连上以后写已连接
  - 订阅位置超过日志末尾时服务端发送 resync，客户端据此重新同步快照
  - 1920×1080 下内容区宽 1280 并在主区居中
  - 浏览器缩放 150% 时页面没有横向滚动条
  - 切换浅色与深色主题以后刷新页面，主题保持
- `e2e/timeline.spec.ts`（5 个）：留两项。「首页时间轴的刻度与 home.away_report 的关键事实一一对应」是离开期间的报告与来源回链（R3 阶段二·4）；「概览时间轴的刻度只含本项目的关键事实，拖动刻度时画面显示该时刻的状态」是「画面与回放一致」（阶段一交付验证）：带 `at` 的 `project.loop` 与页面逐项一致。其余五项是 D5、D3、D2。
  - 首页拖动刻度回到过去：楼层的状态与带 at 的查询结果一致，报告项与刻度互相高亮
  - 回放期间到达的事件没有丢失：回到现在以后画面与实时的查询结果一致
  - 回放位置写在路径的 at 参数里：刷新以后回到同一位置，回到现在清除参数
  - 概览页的回放位置写在路径的 at 参数里：刷新以后回到同一位置
  - 1920×1080 下时间轴不溢出、控制台错误为零
- `unit/action-table.test.ts`（2 个）：D2 列头清单与整行数组钉的是表格版面；「命令一列写命令原文」「结果按回执写成功/失败/没有回执」「没有部门不写未知部门」是词来自事实，留。
  - 表格没有「登记名」一列，有「命令」一列
  - 每一行的内容是工具、命令、部门、状态、结果与输出引用
- `unit/attempts-summary.test.ts`（2 个）：总数与已显示的行数分开说、总数没读到不猜（诚实显示）留；「点加载更多继续」「进行中请求数写最前面」是版面，D2。
  - 还有下一页时说明可以继续加载
  - 进行中的请求数照旧写在最前面
- `unit/board-columns.test.ts`（1 个）：取消的事项进已停止列、按部门与状态分列、停止原因词表只覆盖封闭清单、决定阻塞范围写中文、没有部门不写未知部门，是事实到词与分类，留。看板列名的字面清单是版面，D2；它顺带断言的 run 状态词表与 cancelled-item-status.test.ts 重复，D3。
  - 看板列名与状态词表一致，run 状态只有进行中与三个终态
- `unit/card-logic.test.js`（5 个）：R3 决定请求的卡片材料按种类整理、挡住的对象、要求写说明的选项不提交、初始 PRD 的材料，留；防回退的最后一项（unknown_action 与 pending_verification 已删）留（规则 3）。删的五项是等待秒数算术、跳转地址拼写、排序，D2；它们的取值在 face 的两项里已经断言。
  - 等待时长：按发出时间到现在的差，负差按零
  - 「在项目中查看」的目标：待恢复落到该事项的恢复页，没有事项时落到项目概览
  - 待恢复的决定：材料里的跳转前往模型管理与本项目的部门设置
  - 等待回答的请求按发出时间排列
  - 初始 PRD 的两个链接都指向资料页并带上轮次，「在项目中查看」也落到资料页
- `unit/command-problem.test.ts`（2 个）：R2 命令失败的三种分类（接口层校验、应用层拒绝、其余），服务端那句话原样给页面，基准过期带当前版本，留。删的两项渲染一个组件的标记（class、role、段落是否为空），D2，是 U89 现场回归。
  - 反馈组件渲染出来的段落不是空的：页面上看得见那一句说明
  - 没有失败时反馈组件不渲染任何东西
- `unit/connection-status.test.ts`（1 个）：事件流连接三档由 `nextStreamState` 的状态本身给出（R2 事件流的客户端一侧），其余七项留；一项只断言常量的 kind 等于它自己写的字符串，D5 恒真。
  - 状态本身能分辨「还没连上过」与「连上以后断了」，不靠断开时间猜
- `unit/department-prompt.test.ts`（3 个）：留的四项是：草稿区分写入与不写入（含旧服务端缺字段按已写入，R2 字段只增向后兼容）、来源按项说、清空后发的是「不写入」而不是会被 422 挡的空串、保存载荷带期望版本（R1/R2 命令合同）。删的三项是两个按钮的名字、说明句、空文本框，D2（渲染标记）。
  - 两个动作各做各的事：撤销本次修改只撤销本次编辑，使用内置默认才是不写入
  - 表单里有一行中文说明说清这一段写不写，两个按钮的名字说它们做的事
  - 这一段不写入时说明写明用内置默认，文本框是空的
- `unit/drain-text.test.ts`（1 个）：R3 排空与强制升级是阶段二明写的行为，页面要把后果与剩下的那条路说清（不再开始新事项、回不去、强制升级、起点重新开始、排空期间新事项只排队），这几项留；按钮措辞是文案，D2。
  - 确认与取消两个按钮的措辞是用户看得懂的话
- `unit/item-status-words.test.ts`（2 个）：第一项（not_started 与 held 是两个说法）是词来自事实，留；后两项断言 `sceneStatus`、`floorStatus` 与 `BUILDING_STATUS`，它们在 `pixel/building/model.ts`，#952 删 `sceneStatus`、#955 删整个 model.ts，D2。
  - 楼层画面：排队中的事项写「排队中」，成果被挂起的写「成果已挂起」
  - 楼层的状态词表里，「排队中」只属于排队中的事项
- `unit/model-logic.test.js`（22 个）：模型管理页的表单逻辑。R3「模型目录、准入、凭据不进事实」由服务端与 e2e/models.spec.ts 守；这里留的八项是词来自事实（凭据来源用词、准入摘要与准入列显示、模型测试与连接测试的结果写用时与服务端给的原因）、载荷合同（提交的形状、请求时限留空不提交让后端默认值生效、客户端不写第二个数）和部门默认只列已准入且未作废的定义。其…
  - 协议清单与预置表的请求基址：三种协议都能取到基址
  - 新建连接按服务方案与地址填写标识、名称和凭据引用，保留用户修改
  - 容量有效性：缺少或无效的行不能保存（验收第 3 项）
  - 预填取上游模型列表优先，其次能力表，来源逐项标明（设计说明第 4.3 节）
  - 协议按能力表、服务方案默认与 Chat Completions 三级预填，来源逐项标明（设计说明第 4.3 节）
  - 默认档位只能从已选的支持档位中选择；推理参数方式只列出与协议相符的选项（验收第 4 项）
  - 影响列表按第 4.4 节读回：受影响定义、引用方与进行中事项
  - 删除 Provider 配置与移除定义的文字按第 4.5 节：被引用时列出引用方，无引用时列出将一并删除的定义
  - 表单能否构成合法目录文档：必填项与容量关系（第 4.6 节）
  - 表单的取舍值：空文本与非法数字都交回 null
  - 添加时的表单为空，编辑时恢复服务方案、协议与已保存的定义（验收第 2 项）
  - 点击候选预填并标明来源；缺少容量的行不能保存（验收第 3 项）
  - 候选就地填写容量并构造行（设计说明第 4.3、9.1 节）
  - 勾选候选的加入门槛校验：缺少或无效时写明哪一项（设计说明第 9.1 节）
  - 提交时地址补全协议头：粘贴后直接点添加也能保存（设计说明第 4.2 节）
  - 模型选项排序不随系统语言变化（工单 #519）
  - 连接测试使用自定义服务地址推导的模型列表地址
  - 预填来源的文字标注
  - 容量的缺项与非法关系在界面写明（工单 #294）
  - 上游模型 ID 带斜杠时预填的访问定义 ID 是合法标识符，上游 ID 保持原值（工单 #302）
  - 添加与保存的成功提示用词不同（工单 #302）
  - 自定义服务的默认模型列表地址与实际生效地址（工单 #384）
- `unit/onboarding.test.js`（7 个）：R3 接入已有仓库。建档状态标记（建档中、等待建档、等待确认初始 PRD，决定已回答或属于别的项目不覆盖）与每个拒绝原因都有中文说明，是词来自事实，留。删的七项：把服务端英文拒绝信息按分号分行（钉的是服务端文本格式，D2）、哪几个工具名驱动「阅读已有项目」的演法（旧事件适配的内部，#953/#954 之后在翻译层，D2）。
  - 拒绝说明按分号分行，每条相对路径各占一行
  - 只有一条原因时分行给出这一条，空段落不出现
  - 接口层校验错误没有路径可列（工单 #740）
  - 读取、搜索与区间阅读三种工具驱动阅读已有项目，其他工具不驱动
  - 只有 tool_started 事件驱动阅读已有项目，其他事件不驱动
  - 页面打开以前已经发生的读取按动作列表读出最近一次
  - 动作列表里没有读取时没有已发生的读取
- `unit/optional-read.test.ts`（1 个）：读取的失败有去处、没有原文时写「这次读取没有成功」，留；最后一项与 read-failure.test.ts 的同名项逐字重复，D3。
  - 读不出来与本来就没有内容，说的是两句话
- `unit/page-read-failure.test.ts`（2 个）：前两项与 read-failure.test.ts 的最后两项逐字重复，D3；第三项（总数读不出来时观测页副标题说读不出来，不安静地少一句数字）是唯一的，留。
  - 读不出来：写「读取失败」与服务端给的原文
  - 读出来且为空：写原来的空态文案
- `unit/pixel-view.test.js`（3 个）：留的两项是防回退护栏（规则 3）：动作图鉴不在正式路径表里，已删除的连接页回到未找到。删的三项：整数倍缩放两项在 pixel-device-resolution 与 e2e 里重复，D3；画面对象的状态机用的是没有调用者的 `view-state.ts`，已在 #974。
  - 整数倍缩放：1440×900 与 390×844 下都是整数倍，缓冲不小于设备像素
  - 缩放随视图尺寸改变：窗口变窄时倍数下降，变宽时上升，始终是整数
  - 画面对象的状态机与原型一致：setModel、playEvent、focus、resize、destroy 的入参与效果
- `unit/project-list.test.ts`（1 个）：归档开关作用到查询参数（include_archived）与归档项目的可见性，是查询参数与事实的反映，留；搜索词按名称与目标过滤是页面自己的筛选，D2。
  - 搜索词照旧按名称与目标过滤
- `unit/rejection-text.test.ts`（2 个）：留四项：顶栏项目菜单的拒绝提示只给服务端的消息、基准版本过期给出当前版本、没有登记的原因也只给服务端的消息、渲染进程源文件里没有把原因标识写进页面的写法（防回退护栏，规则 3）。删的两项是接入表单自己的拒绝文案，覆盖已在 onboarding.test.js 的「接入的每个拒绝原因都有中文说明」里。
  - 接入表单的拒绝提示给中文说明，不出现内部原因标识
  - 每一种拒绝原因的中文说明里都不出现原因标识本身
- `unit/running-background-commands.test.ts`（3 个）：只显示运行中的后台命令，结束的不再显示为运行中，是状态照实写，留「混合状态」那一项；其余三项断言一个组件的标记文字（「正在运行的后台命令（1 条）」、列名），D2。
  - 运行中的后台命令在动作列表中显示命令原文与运行中状态
  - 后台命令结束以后不再显示为运行中
  - 没有后台命令时不渲染任何内容
- `unit/snapshot-view.test.ts`（3 个）：留四项：视图没打开不显示加载中、参数变了新快照到达前算读取中且不给上一处的数据、参数没变按快照本身给、读取失败把原因带出来（R2 查询快照的客户端合同，页面不会把上一处的数据当这一处的）。删的三项：拒绝说明只写服务端消息与 rejection-text.test.ts 重复，D3；两条去处提示是页面自己的导航，D2。
  - 拒绝的说明只写服务端的中文消息，不带英文的原因标识
  - 部门没有选模型时给出两个去处：模型管理页与本项目的设置页
  - 其余拒绝原因不给去处
- `unit/timeline-logic.test.js`（6 个）：留五项：关键事实的种类（交接已不是刻度的防回退）、刻度按位置排列相同位置合并、质检的放行与缺陷记录按应用层给的种类区分、按项目筛选、报告项与刻度按来源事件位置高亮对应（回链到事件，对应画面合同的回链）。删六项：三档速度与基准时长、折断符号、时长写法、时间差、着色的十六进制值，都是「与原型 v10 一致」的常量或版面，D2。
  - 三档速度与基准时长与原型 v10 的 replay.js 一致
  - 刻度之间的折断符号：相隔超过阈值时插入一段
  - 相邻刻度相隔不超过阈值时不插入折断符号
  - 时长写法按秒、分、小时、天给出
  - 时间差：无法解析的时间返回零
  - 刻度按种类着色：着色值与原型 v10 的 KEY_KINDS 相同
- `unit/usage-text.test.ts`（1 个）：R3 用量（判据二能度量）：上报了总量就写总量、没上报才写未上报、coverage 说没报的那一项即使有数值也不写、不出现英文内部标识，留。有一项断言 `usageText(x) === usageText(x)`，永远成立，D5。
  - 请求记录表与请求详情给出同一句话
- `unit/writeback.test.ts`（3 个）：R3 采纳写回：写回成功写分支与目标分支、合并请求只记在本地时不说已创建、冲突写出冲突的文件、核验没通过写原因、无需写回与等待各有说法、不出现英文内部标识，留。源目录的写回设置怎么写（未打开、已打开加目标分支与远端、没有填目标分支）是设置页的文案，D2。
  - 源目录的写回设置：没有打开时写未打开
  - 源目录的写回设置：打开以后写目标分支与远端
  - 源目录的写回设置：打开了却没有目标分支时照实写明
