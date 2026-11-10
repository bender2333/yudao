# 三圈循环：职能之内、看着循环、第一圈的特例，现在各有什么

查证对象：GitHub 工单 #1688。只依据仓库里的一手材料（代码、测试、设计说明、总图、对照表），没有查 GitHub 上别的工单与 Discussions。

四种分类：**有且有测试** / **有但没接上**（代码在，没有被运行路径用到）/ **只有设计** / **都没有**。路径前缀：Python 在 `harness/`，页面在 `client/src/renderer/src/`。

## 结论

1. 职能之内的循环（子事项、子组织）只有设计：`docs/design/department-roles.md` 与 `forms-and-verifier-role.md` 第 4.6 节写到了规矩，代码里没有子事项的事件、字段、路由与页面。对照表（`docs/design/architecture/name-map.md`）也记着「子事项、子组织」「开子事项的请求」「外包角色」都是「代码里还没有」。
2. 嵌套深度 `loop.nesting_max` 在规则登记里有值，但 `parameters.py` 明写没有代码读取。
3. 看着循环并修改循环：观察者缝代码里没有；离线的经验候选已经在写事件并折进投影，有测试，但没有查询、页面或命令读取它。第二层自举的通道（`definition.propose`、候选、隔离对照、撤回）只有设计与需求；现有的 `parameter.set` 与 `organization.adopt` 是用户发起的改动，不是系统提案。
4. 第一圈的特例做得最实：单角色直做、几个角色直做、开环完成在后端有路由、定义、停止原因、测试，页面有形态区、看板列、循环图终点文字与测试。发布带登记三份形态。
5. 没查到的地方：没有运行测试，只核对了测试文件与用例名；没有读总图第五节第二层的全文。

## 一、职能之内的循环

| 项目 | 分类 | 依据 |
| --- | --- | --- |
| 子事项、子组织的规矩（创建事件带上一层引用与层数、时间与用量从上一层扣、层数上限、上一层停则子事项停、成果作为普通提案回上一层） | 只有设计 | `docs/design/forms-and-verifier-role.md` 第 4.6 节「子组织（位置与规矩）」；`docs/design/department-roles.md` 第 4.2 节「子组织怎样被指向」；`docs/design/loops-and-convergence.md` 子事项一行与「嵌套深度」 |
| 职能内多角色的角色材料（中心角色、探索者、主程、审查者） | 只有设计 | `docs/design/department-roles.md`；`harness/definitions/roles.json` 只有 `product`、`engineering`、`quality` 三个角色 |
| 子事项的事件、事件流 | 都没有 | `docs/design/skeleton-and-application.md`「执行契约」写明现在不预留；`harness/` 的骨架事件里没有子事项相关类型；对照表「子事项、子组织」行 |
| 定义里「角色指向子组织」的格式 | 都没有 | `harness/definitions/__init__.py` 第 221、753、831 行注释写明子事项这次不预留；`harness/organization_compose.py` 第 16 行「子组织（第 7 条）这个阶段不做」 |
| 事项来源「上一层交来的任务」 | 都没有 | 同上；`harness/definitions/event_sources.json` 只有用户输入等现有来源 |
| 开子事项的请求（执行缝的出） | 都没有 | 对照表「开子事项的请求」行；`harness/execution_contract.py` 的结果没有这一项 |
| 路由：子组织用直做路由 | 有且有测试（直做本身）；作为子组织用没有 | `harness/direct.py` 的 `Direct`；`harness/tests/test_direct_routing.py`、`test_direct_several_roles.py`。直做目前只是第一圈的形态 |
| 边界里的时间与用量从上一层扣、嵌套深度 | 只有设计（登记有值，没读取） | `harness/definitions/rules.json` 的 `loop.nesting_max`（值 2，范围 1 至 8）；`harness/parameters.py` 第 142 行：「没有代码读取这条登记的取值：子循环与嵌套深度还没有实现」；`stall.rounds`（停滞与重新规划）同样「还没有实现」 |
| 外包角色（ACP） | 只有设计 | `docs/design/outsourced-roles.md`；对照表「外包角色」行；`harness/` 下没有外包执行者 |
| 页面 | 都没有 | `client/src/renderer/src/views/project/` 里没有子事项、子组织视图；`loop-graph-model.ts` 画职能之间的图。`docs/design/project-organization.md` 写的「外包与分形」入口页面没有 |
| 任务池（工作单元的参数化） | 有但没接上 | `harness/tests/second_routing.py`（文件头写明只在测试里用，产品代码不导入）与 `harness/tests/task_pool_definitions/`；对照表「任务池、工作单元、认领」行为「代码里还没有」 |

## 二、看着循环并修改循环

| 项目 | 分类 | 依据 |
| --- | --- | --- |
| 观察者缝（只读订阅、写入证据与提案、振荡信号） | 只有设计 | `docs/design/architecture/overall-architecture.md` 观察者缝；`docs/requirements/meta-observer.md`；对照表「观察者」「读取范围、振荡信号」行；`docs/requirements/self-hosting.md` 第二层前置条件第 5 条把观察者的订阅与提案接口排在阶段五第一个薄片 |
| 只读订阅的材料 | 有且有测试（通用事件流，不是观察者缝） | `harness/app/event_stream.py` 的 `EventScope`、`EventStream`；`harness/tests/test_event_stream.py`。范围由连接参数给出，不在定义里声明，没有「观察者不能扩大」的核对 |
| 离线的经验候选 | 有且有测试 | `harness/submissions.py` 的 `SubmissionWriter.record_lesson_candidate`；`harness/orchestrator.py` 的 `record_lesson_candidate`；事件 `lesson_candidate_recorded`（`harness/app/payloads.py` 的 `LessonCandidateRecordedPayload`）；`harness/projection.py` 第 449 行折进 `lesson_candidates`；`harness/tests/test_lesson_candidates.py`。来源两种：质检退回、运行失败 |
| 经验候选被谁读 | 有但没接上 | `harness/app/` 下没有查询或命令读取 `lesson_candidates`；页面只有 `views/project/floor-text.ts` 里事件的一句文字「记下经验候选」；`views/system/reserved.tsx` 的「元观察」「演化」「经验」是预留入口，文字写在客户端，没有查询来源 |
| 教训发现、元观察、演化、振荡检测、降解信号 | 只有设计 | `docs/requirements/meta-observer.md`；`docs/design/semantic-system.md`；`docs/design/loops-and-convergence.md` 的振荡信号；代码里没有 |
| 判定点 | 只有设计 | 对照表「判定点」行为「代码里还没有」 |
| 第二层自举的通道（候选、隔离对照、限定采用、撤回） | 只有设计 | `docs/requirements/self-hosting.md`「第二层的前置条件与完成条件」；`docs/requirements/system-intent.md` N-G4；`docs/design/app-and-interface.md` 的 `definition.propose`（`harness/` 下没有这条命令）；对照表「限定采用的范围」行 |
| 相邻的、用户发起的改动通道 | 有且有测试（不是第二层） | `harness/app/form_commands.py` 的 `organization.adopt`（理由、版本冲突检查、历史）；`harness/tests/test_organization_adopt.py`、`test_organization_freeze.py`；`harness/app/parameter_commands.py` 的 `parameter.set`（带界限）；`harness/tests/test_parameter_set.py`。提出者是用户，不是系统 |

## 三、第一圈的特例

| 项目 | 分类 | 依据 |
| --- | --- | --- |
| 单角色直做（只有工程） | 有且有测试 | `harness/direct.py` 的 `Direct`、`DirectTightening`；定义 `harness/definitions/forms/single_role_direct/`；`harness/tests/test_direct_routing.py` |
| 几个角色直做（产品 · 工程） | 有且有测试 | `harness/definitions/forms/several_roles_direct/`；`harness/tests/test_direct_several_roles.py`（含加上质检后等放行） |
| 开环完成（后端） | 有且有测试 | 事项创建时标记 `open_loop`（`harness/app/payloads.py` 第 369 行）、`Definitions.is_open_loop`、停止原因 `open_loop`、`harness/app/home.py` 离开报告把开环完成与放行分开计；`harness/tests/test_open_loop_completion.py`、`test_onboarding_open_loop.py` |
| 开环完成（页面） | 有且有测试 | `views/project/labels.ts` 的 `isOpenLoopCompleted`、`OPEN_LOOP_STATUS_TEXT`；`views/project/board.ts` 开环完成一列；`views/project/loop-graph-model.ts` 终点文字；`views/project/form-section.tsx`；`client/tests/unit/board-columns.test.ts`、`loop-graph-model.test.ts`、`form-section.test.ts`、`away-report-coverage.test.ts` |
| 发布带的几份形态 | 有且有测试 | `harness/app/form_queries.py` 的 `release_forms`；`harness/tests/test_direct_routing.py` 的 `test_the_forms_are_registered_and_the_release_keeps_the_default`：登记三份，默认 `three_departments`、`single_role_direct`、`several_roles_direct`。路线图写的是「工程」「产品 · 工程」「产品 · 工程 · 质检」三份，与登记一致（默认那份即产品 · 工程 · 质检）；「产品 · 工程 · 质检 · 运维」没有（对照表） |
| 形态与组织的页面（选形态、采用、历史、加减核验角色） | 有且有测试 | `harness/app/form_commands.py`、`form_queries.py`（`project.organization`、`organization.draft`）；`harness/tests/test_organization_adopt.py`、`test_organization_compose.py`、`test_forms_per_item.py`、`test_form_setting.py`；页面 `views/project/form-section.tsx`、`form-section-logic.ts`，`client/tests/unit/form-section.test.ts` |
| 核验角色成为角色的性质（任何形态都能放） | 有但没接上（部分） | 声明与读取：`harness/definitions/__init__.py` 的 `VerificationDeclaration`、`rejection_edges`、`verifier_roles`；`harness/tests/test_direct_with_verifier.py`。使用方仍写死职能名：对照表「核验角色」行记着 `app/project_queries.py` 的 `VERIFIER_OF`、`path_rules.py` 的 `QA_TESTS_DIR` |
| 职能名随定义（不依赖默认三职能） | 有但没接上（部分） | 对照表「职能与角色」行：`models.py` 的 `DEPARTMENTS`、`providers/facade.py` 的 `REQUIRED_DEPARTMENTS` 取自模块加载时的默认定义 |

## 没有核对到的

- 没有运行任何测试，「有测试」指测试文件与用例存在并覆盖这项，不代表现在通过。
- 没有读总图第五节第二层的全文，也没有逐条读 `docs/requirements/`；第二层的通道依据取自 `self-hosting.md`、`system-intent.md`、`meta-observer.md`。
- 页面项只核对了源码与单测，没有在真实页面里看过。
- 对照表由子架构师维护；凡引用它的行，已用 grep 在代码里印证子事项、观察者、`definition.propose`、`lesson_candidates` 的有无，但没有穷尽所有目录。
