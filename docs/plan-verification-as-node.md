# Yudao 改动方案：部门名出内核，验证成为节点

2026-10-30 · Bender

这份文件由 Claude Docs 里的同名文档转成 markdown，内容以那份文档为准。方案只读仓库得出（提交 2c55040），行号按那个提交。

## 结论

这份方案把第 1、2 件一起做完。做法是两步。第一步，把质检、产品、工程各自的特殊行为，换成定义里角色身上的几个属性。第二步，让每条路由在自己的定义里写明事项什么时候结束。

默认定义不变，三部门的行为和事件一字不差。换一份不带验证节点的定义，就是普通的 do-everything agent，什么都不用记。

分两期。第一期 8 步，前 5 步是纯重构，验收标准是现有测试和事件序列基准都不变；做完就支持单 agent 和三部门。第二期 3 步，补上按工作流的多 agent、观察者和分形。内核一共动三处，按「分级：尺子归你，内核过关自动」一节的规矩走，只有一处会浮现给你。有一处要你拍板，是基础规则文件里「质检放行不外包」那一行的口径，见「要你定的」一节。

## 先更正排查文档里的一处

排查文档说加一种协作模式要动四个文件，说重了。仓库里已经有第二种路由的证明：任务池（harness/tests/second_routing.py，工单 #864）。它有自己的成果种类、提议方式和结束原因 pool_drained，骨架一行没改。第二种装配也有（harness/tests/second_assembly.py）。

所以「全员直做」这条退化路由可以照任务池的样子写。真正挡路的，是默认的装配与执行实现里对部门名的判断，加上内核里的一行。

## 部门名现在在哪

| 位置 | 做什么 | 换成什么 |
| --- | --- | --- |
| adjudication.py:141（内核） | 质检的写工具只能写检查材料目录 | 角色的 workspace |
| environment.py:773 | 别的部门不能写检查材料目录 | workspace |
| environment.py:1190、:1232 | 检查时带上检查材料，并算它的摘要 | workspace |
| engine.py:802 | 质检改了检查材料就保存 | workspace |
| recording.py:806 | 非质检写文件让当前交付失效 | workspace |
| context.py:173、:275、:772-776 | 交付只通知质检；质检先看事实，下结论后才看解释；工程与质检的问答分事实与解释 | 角色的 verifies |
| engine.py:595-610 | 只有产品能在回答里修订 PRD | 提案合同里谁能提 product_spec |
| context.py:740 | 交付说明的合同写死在工程名下 | 提案合同里谁能提 delivery_spec |
| context.py:614-628 | 每个部门一句任务说明 | 角色的 task |
| context.py:528-540 | 建档修改轮给产品和工程上一轮材料 | 角色的 visibility |
| providers/facade.py:60 | 默认绑定三个部门 | 读定义里的部门清单 |

这些不改：tightening.py、watched_outputs.py、projects.py 的建档步骤、app/payloads.py 里的 issuer 字面量、app/read_models.py、app/project_queries.py。它们属于成果驱动这一个应用，点自己的部门名是对的。payloads 是事件结构，只能增不能改。

## 定义里加什么

roles.json 每个角色只增字段，旧文件不写就等于今天的行为：

- workspace：run 或 check。check 表示写入只进检查材料目录，写了不让交付失效，检查时带上检查材料。今天只有 quality 是 check。
- verifies：它核验谁的成果。被核验方的解释部分要等核验方下了结论才给，双方的询问按事实与解释分开。它代替 app/project_queries.py:205 的 VERIFIER_OF。
- task：按事项种类写一句任务说明，从 context.py:614-628 原样搬过来。
- visibility 增两项：prior_initial_prd 和 prior_structure。

routings.json 每条路由只增 ends_on，写明什么结论结束事项：

- watched_outputs：质检放行与基线核验一致，就是今天 tightening.py:379、:477 写死的两条。
- 新路由 all_hands（全员直做）：任一角色交完成说明就结束，结束原因写在它自己的定义里，比如 declared_done。

```json
// roles.json（片段）
"quality": {
  "workspace": "check",
  "verifies": ["engineering"],
  "task": {
    "normal": "独立验证当前交付，提交放行或返工决定。",
    "onboarding": "独立核验初始 PRD 与现有行为是否一致，提交基线核验。"
  }
}

// routings.json（片段）
{ "id": "watched_outputs",
  "ends_on": [ {"kind": "qa_review", "verdict": "release"},
               {"kind": "baseline_review", "verdict": "consistent"} ] }
{ "id": "all_hands",
  "ends_on": [ {"kind": "completion"} ],
  "end_reasons": { "declared_done": { "outcome": "done" } } }
```

## 步骤

1. 先加一条会失败的测试。用一份把三部门改了名的测试定义（比如 quality 改叫 qa），跑同一个事项，期望事件序列除了名字以外不变。今天它会失败，因为内核只认 "quality"。
2. 定义加字段。definitions/__init__.py 的模型和 roles.json、routings.json 只增字段，默认值等于今天的行为。这个文件在内核清单里，按基础规则 4，开发仓库里改它走 CI 的内核测试和覆盖核对，不用事前批准。
3. 改内核那一行。adjudication.py:141 改成看角色的 workspace，补一条内核测试。内核测试只增不删。
4. 改执行与环境。environment.py:773、:1190、:1232，engine.py:802，recording.py:806 改看 workspace。engine.py:595-610 和 context.py:740 改成按提案合同找能提这个种类的角色。
5. 改装配。context.py 的任务说明读 task，通知和事实与解释的分隔读 verifies，修改轮材料读 visibility；facade.py 读部门清单。到这一步第 1 件就完成了，第 1 步那条改名测试应该通过。
6. 结束条件进定义。tightening.py:132-134 的 _is_release_submission 和 :379、:477 改读 ends_on。成果驱动路由在选中时校验自己的定义里至少有一个带 verifies 的角色，这条校验只属于这条路由，不在骨架里。
7. 加 all_hands 路由。先像任务池一样只放在测试里：harness/tests/ 下一份实现加一份 all_hands_definitions/。测试三条：没有验证节点的事项能跑完并以 declared_done 结束；产品代码不导入它；它的定义缺结束原因时被拒绝。
8. 改文档。system-intent.md:15 去掉「独立的证据」；architecture.html:203「只有它能放行、不能外包」和 :371「末端有独立证据」改成成果驱动路由自己的规矩；外包角色「只限有下游独立核验的角色」也归到这条路由；foundation-rules.md 那一行见「要你定的」。

建议分四张工单、四个 PR，见下面的「第一期交接清单」。工单 1、2 是纯重构，合起来是第 1 至 5 步。

## 第一期交接清单

这一节可以直接拆成工单交给执行者。每张照仓库的流程做：开分支，日记写在 agents_jour/<工单号>.md，交付说明写在 PR 上。工单正文只写摘要，链接这份方案。行号按提交 2c55040，搬了家的照 AGENTS.md 的规矩找现在的位置。

### 每张都要过的关卡

- 装依赖：`uv sync --frozen`。
- 内核覆盖：动手前、改完后各量一次，TOTAL 不低于动手前，改动的内核行不落在 Missing 里。命令照仓库里执行者用过的写法：

```
uv run --with pytest-cov python -m pytest -m "unit or module" \
  --cov=harness.write_path --cov=harness.event_store --cov=harness.kernel_events \
  --cov=harness.adjudication --cov=harness.validation --cov=harness.minimal_projection \
  --cov=harness.contracts --cov=harness.path_rules --cov=harness.actions \
  --cov=harness.bounds --cov=harness.tools --cov=harness.definitions \
  --cov-report=term-missing
```

- 内核测试：`uv run python -m pytest harness/tests/kernel`。只增不删、断言不放宽，test_only_grows.py 守着；内核 Python 总行数不超过清单里的 4096，现在按原始行数粗算约 3718。
- 两项固定检查：`uv run python -m pytest harness/tests/test_layers.py harness/tests/test_openapi_snapshot.py`。
- 新测试文件在 harness/tests/layers.toml 登记一行。
- 工单 1 至 3 不许加 `--write-event-baselines`。基准比对不过，就是改错了，不是基准该改。
- 只单进程跑列出的文件，不跑整个 harness/tests。

### 工单 1：定义加属性，内核那一行改读属性（第 1 至 3 步）

- 只改：harness/definitions/__init__.py（Role 在 :203，Routing 在 :500，规则核对在 :800 附近）、roles.json、routings.json、harness/adjudication.py:141 与 :212、新测试文件。
- 改法一：Role 增 workspace（run 或 check，默认 run）、verifies（角色名列表，默认空）、task（事项种类到一句话，默认空）；visibility 可选值增 prior_initial_prd、prior_structure。Routing 增 ends_on，每条写 kind 和可选的 verdict，默认空。
- 改法二：加载时核对 verifies 指向的角色存在，ends_on 的 kind 在这条路由的 outcome_kinds 里。
- 改法三：roles.json 只给 quality 写 workspace check 和 verifies engineering；routings.json 给 watched_outputs 写 ends_on 两条（qa_review 放行、baseline_review 一致），这一张只写不读。
- 改法四：adjudication.py:141 改成看 definition.role(department).workspace 是不是 check；_quality_write_error 改名 _check_workspace_write_error，拒绝的文字不变。
- 先提交会失败的测试：harness/tests/test_renamed_departments.py（module 层），照 task_pool_definitions 的做法在 harness/tests/renamed_definitions/ 放一份 quality 改叫 qa 的定义，断言 qa 写测试材料目录以外被拒，原因和今天 quality 相同。
- 内核测试新增一条：workspace 为 check 的角色写测试材料以外被拒，run 的角色不受这条限制，换什么角色名都一样。
- 跑：test_adjudication.py、test_renamed_departments.py、kernel/test_definitions_decide.py、test_definitions.py、test_qa_test_materials.py。
- 验收：默认定义下已有测试照常过；不写新字段的旧定义加载结果等于今天；改名测试通过。
- 分级：内核，纯重构，过关自动。

### 工单 2：执行、环境、记录、装配改读属性（第 4、5 步）

- 只改：harness/environment.py:773、:1190、:1232；harness/engine.py:595-610、:802；harness/recording.py:806；harness/context.py:173、:275、:528-540、:611-628、:740、:772-776；harness/providers/facade.py:60 与用到它的 :638、:805、:1100；harness/app/project_queries.py:205；roles.json；rules.json。
- 改法一：判断 department == "quality" 的地方，改成判断角色的 workspace 是不是 check。
- 改法二：engine.py:595-610 和 context.py:740 按提案合同找能提 product_spec、delivery_spec 的角色，不写名字。
- 改法三：context.py:173、:275、:772-776 按 verifies 走：交付通知给核验方；核验方先看事实，下了结论才看解释；双方问答分事实与解释。
- 改法四：context.py:611-628 每个部门的一句任务说明原样搬进 roles.json 的 task，按 onboarding 和 normal 分。
- 改法五：context.py:528-540 修改轮的上一轮材料改读 visibility；roles.json 给 product、engineering 加 prior_initial_prd、prior_structure，rules.json 里 roles.<部门>.visibility 的现值同步（definitions/__init__.py:809 会核对两边相同）。
- 改法六：facade.py 的 REQUIRED_DEPARTMENTS 改从定义的部门清单读，名字留着给旧引用；project_queries.py:205 的 VERIFIER_OF 从 verifies 反推。
- 测试：把工单 1 的改名测试扩成整件事项。在改名定义下跑 event_scenarios 里一个现有场景，事件序列把 qa 换回 quality 以后，和 event_sequences 的基准逐条相同。
- 跑：test_renamed_departments.py、test_event_sequence.py（比对 event_sequences 和 prompt_snapshot.json）、test_prompts.py、test_qa_test_materials.py、test_concurrent_departments.py、test_second_routing.py、test_second_slot_implementations.py。
- 验收：event_sequences/*.json 和 prompt_snapshot.json 一字不变；改名测试通过；上面这些文件里不再出现对部门名的判断。
- 分级：可以整体重写的一环，过关自动。

### 工单 3：结束条件进路由定义，加 all_hands 测试路由（第 6、7 步）

- 只改：harness/tightening.py:132-134、:379、:477；harness/watched_outputs.py:450 的 check_definition；新文件 harness/tests/all_hands_routing.py、harness/tests/all_hands_definitions/、harness/tests/test_all_hands_routing.py。
- 改法一：_is_release_submission 和两处 ends_run 改成：这次提交的种类和结论在本路由的 ends_on 里，事项就结束。
- 改法二：watched_outputs 的 check_definition 增两条核对：至少一个角色带 verifies，ends_on 不为空。核对只在这条路由里，骨架不管。
- 改法三：all_hands 照 second_routing.py 写。定义里一个角色、成果种类 completion、一个提交工具、ends_on 写 completion、结束原因 declared_done（outcome 为 done）；item_end 在 completion 被接纳时结束。注册方式也照任务池，不进产品代码。
- 测试 test_all_hands_routing.py（module 层）四条：没有验证节点的事项跑完，以 declared_done 结束；产品代码不导入它；定义缺 ends_on 或结束原因时被拒；watched_outputs 选中一份没有 verifies 角色的定义时被拒。
- 跑：test_all_hands_routing.py、test_tightening.py、kernel/test_tightening_only_rejects_or_waits.py、test_second_routing.py、test_routing_contract.py、test_event_sequence.py。
- 验收：event_sequences 不变；四条通过；一个角色的 all_hands 定义就是单 agent，能跑完。
- 分级：可以整体重写的一环，过关自动。all_hands 只在测试里，不换默认路由，不用浮现给你。

### 工单 4：文档（第 8 步）

- 执行者起草：system-intent.md:15 去掉「独立的证据」；architecture.html:203、:371 和外包角色那一句，改成成果驱动路由自己的规矩。这两份是意图与总图，PR 停在草稿，浮现给你看。
- 只由你改：foundation-rules.md 规则 3 和规则 4 那两行、trusted-kernel.md 第 5 节最后一行。PR 正文只附建议的写法，执行者不碰这两个文件。
- 验收：文档里不再说三部门和独立证据是固定结构，成果驱动路由的规矩写在路由那一节。

### 交回架构师的情形

照 AGENTS.md 的四种情形写 ARCHITECT: 交回。这份方案里最可能碰到的一种：某处判断部门名的地方，改成读属性以后事件序列变了，说明它不只是名字，而是带了这一条路由的规矩，那一处就留在路由里，登记到 docs/architecture-issues.md。

## 受影响的测试

- 回归基准：harness/tests/event_sequences/ 下的事件序列和 harness/tests/prompt_snapshot.json。第 1 至 6 步做完，它们必须一字不变。任务说明搬进定义以后提示快照不变，就证明搬对了。
- 会直接改到的：test_adjudication.py、test_qa_test_materials.py、test_tightening.py、test_concurrent_departments.py、test_definitions.py。test_second_routing.py 的任务池用自己的结束方式，不受影响，只要确认照常通过。
- 内核测试：harness/tests/kernel/ 里有 4 个文件用到部门名，是 test_minimal_projection.py、test_definitions_decide.py、test_tightening_only_rejects_or_waits.py、test_limits_survive_restart.py。它们只增不删，已有断言不放宽。
- 新增的：改名测试（第 1 步）、内核 workspace 测试（第 3 步）、all_hands 三条（第 7 步）。
- harness/tests 里一共 177 个文件出现部门名，大多是成果驱动应用自己的测试，行为不变就不用动。这个数是按字面量搜出来的，没有逐个跑测试。

## 整段形态：每一种都只换定义

| 形态 | 组织 | 路由 | 验证节点 | 还要什么 |
| --- | --- | --- | --- | --- |
| 单 agent | 一个角色 | all_hands | 没有 | 第一期就够 |
| 按工作流的多 agent | 几个角色 | workflow：定义里写顺序，前一位交完轮到下一位，最后一位交完结束 | 可有可无 | 第 9 步，照任务池写一条路由 |
| 三部门 | 产品、工程、质检 | watched_outputs | 质检 | 今天就是 |
| 观察者、维护者 | 观察者不进路由；维护者是普通角色 | 不变 | 不变 | 第 10 步，观察者作为写入来源 |
| 分形 | 任一角色可以指向一份子组织 | 父事项的路由能开子事项 | 各层自定 | 第 11 步，子事项 |

五种形态可以互相套。三部门的工程角色可以指向一个 all_hands 子组织，单 agent 也可以把一件大活交给一个三部门子组织。

一个限制要知道：事件结构里的部门类型是模块加载时的部门清单（harness/app/payloads.py:14、harness/models.py:37）。所以换形态现在是按进程换整份定义。想让同一实例里不同事项用不同形态，还得做「写入口按事项冻结的定义核对」那一条，分形的子事项尤其需要它。

## 第二期步骤

9. workflow 路由。定义里写角色顺序和每一位交什么；前一位的成果被接纳就轮到下一位，最后一位交完结束。想要验证就把带 verifies 的角色放在最后，ends_on 写它的放行。照任务池写，骨架不改。
10. 观察者作为写入来源，见「设计二」。
11. 子事项，见「设计一」。

顺序按从小到大：第 9 步只是一条路由；第 10 步动写入口一处；第 11 步要新增骨架事件，而且要你先想清楚分形的意思。

## 设计一：子事项（分形）

- 定义：角色增一个可选字段 organization，指向一份组织定义（含它自己的路由）。写了，这个角色的活就由一个子组织做；不写，就是今天的一个模型。
- 开子事项：work_item_created 只增两个可选字段：parent（父事项、父 run、开它的角色与步骤）和 depth。子事项创建时冻结它自己那份定义。
- 收子事项：子事项结束时，主机在父 run 流里写一条新的骨架事件 child_item_finished：子 run、停止原因、子事项的最终成果引用。父路由把它当成那个角色交的提案，照常过裁决。对父组织来说，子组织就是一个慢一点的角色。
- 边界：rules.json 增 organization.item_max_depth，和现有的 organization.ask_chain_max_depth 同一种。子事项的时间与循环上限从父事项剩下的里面扣，所以整棵树一定会停。父事项停，子事项跟着停，这是基础规则 6 里已有的「取消沿调用链立即生效」。
- 重放：父子各自一条流，父流里只有 child_item_finished 这一条引用，各自仍是纯折叠。
- 碰哪一环：两个事件属于只能向后兼容的骨架事件，只增；深度和预算扣减在 harness/bounds.py，是内核，按分级过关自动（新增的是收紧）。
- 待你定：分形是「角色里套组织」这一种，还是也包括「部门内多角色」那种中心型协作（docs/requirements/department-roles.md:21）。后一种可能不需要子事项，用一个子组织就够。

## 设计二：观察者作为写入来源

- 定义：organization.json 增 observers 列表，每一个写 id、读取范围、能写的种类。观察者不在 departments 里，路由不给它派活，这一点 docs/requirements/meta-observer.md 已经确认。
- 写入口：write_path.py:329 现在只认部门。改成来源分两类，部门查 departments，观察者查 observers。观察者只能写总图 :376 定的三种：统计证据、改进提案、振荡信号，写不了成果接纳。
- 读取范围：接口的事件流（harness/app/event_stream.py）按观察者的范围过滤：哪些流（run、项目、目录）、哪些事件种类、哪些部门。默认最小。读不写事件，和排查文档里重放那一节的结论一致。
- 提案怎么生效：改定义的提案走现有的候选、对照、限定采用、撤回（docs/design/rules-and-parameters.md）。改到 verifies、ends_on 这类权威关系的，按分级浮现给你。观察者不能提改它自己的定义和读取范围，这是「被谁评价就不能改谁」。
- 振荡信号是边界的输入，内核按定义停下受影响的分支交给你，总图已定。
- 碰哪一环：写入口是内核，多了一种写入来源，浮现给你；observers 定义只增字段；事件流过滤在接口层，属于可以整体重写的那一环。
- 维护者：如果是运维那样干活的，就是多一个角色；如果只看不做，就是一个观察者。

## 每处改动碰哪一环

| 改动 | 环 | 按分级 |
| --- | --- | --- |
| 角色属性、路由 ends_on、角色 organization、observers | 定义，只增字段 | 过关自动 |
| adjudication.py:141 一行 | 内核 | 过关自动：纯重构，基准不变 |
| 写入口认观察者（write_path.py:329） | 内核 | 浮现给你：多了一种写入来源，属于权威关系 |
| 子事项的深度与预算（bounds.py） | 内核 | 过关自动：新增的是收紧 |
| work_item_created 增字段、child_item_finished | 骨架事件，只增 | 过关自动 |
| 执行、环境、装配、记录改读属性 | 可以整体重写 | 过关自动 |
| all_hands、workflow 路由 | 可以整体重写 | 过关自动；换成默认路由时浮现给你 |
| 观察者的读取范围 | 接口层 | 过关自动；放大范围时浮现给你 |
| system-intent.md、architecture.html | 意图与总图 | 浮现给你 |
| foundation-rules.md、评测材料 | 尺子 | 只由你做 |

## 分级：尺子归你，内核过关自动

分级按「尺子」这条线切。尺子归你做，系统碰不到。尺子以内的改动，包括内核，过了关就自动采纳，只有少数几类浮现给你。这接替掉上一版说的「内核每次改都由你逐项批」。

### 尺子是什么，只由你做

- 评测材料：外部场景、隐藏检查、参考解法、评分器、留出场景。
- 关卡本身：什么算退化、噪声范围多大、哪些检查必须过。
- 基础规则文件。
- 「哪些路径属于尺子」这份清单本身。

这条线仓库里已经有了：harness/definitions/kernel-manifest.json 把条目分成 module（裁决模块）和 material（评价材料与守卫自身）。material 就是尺子。

### 三级

1. 过关自动采纳。关卡全过就采纳，不问你。关卡是：内核测试只增不删、已有断言不放宽；内核覆盖率不低于动手前；事件序列基准不变，或者变化在提案里逐条说明；外部场景和留出场景不退化到噪声以外。采纳后进观察期，指标变差就自动撤回，用的是 docs/design/rules-and-parameters.md 已有的撤回。
2. 浮现给你。关卡过了，但属于下面几类，就用一条决定请求交给你，附证据摘要，你回一句就行；你不回就不采纳。几类是：改权威关系（谁能拒绝谁、谁的结论结束事项、谁能往写入口写）；放宽上限或边界；换默认路由或默认组织；关卡结果落在噪声里说不清。
3. 不允许。碰尺子的路径；让内核测试变少或变松；让一样东西改到评价它自己的东西。这些不由你判，是机械地拒绝。

### 「会不会改掉评价自己的尺子」靠什么挡

靠三样机制，不靠你逐项看：

- 路径守卫：系统交的改动只要碰到尺子的路径就被拒绝。manifest 里 material 本来就由路径守卫保护。
- 尺子从已发布版本取：评测时评分器与隐藏检查取自当前运行的已发布版本（docs/design/trusted-kernel.md 第 6 节），候选版本带不进自己的尺子。
- 尺子只由你改，改了也是新版本；候选和基线用同一把尺子比。

### 要改的文字，都只由你改

- foundation-rules.md 基础规则 4 那一行：「运行中的实例改内核由用户经决定请求批准……修改内核路径的交付不自动采纳」。
- docs/design/trusted-kernel.md 第 5 节表格最后一行：「不放开 内核：每次修改由用户逐项批准」。
- docs/architecture.html「只由你批准」那一环拆成两块：「尺子：只由你做」和「内核：过关自动，关键浮现」。

## 改完以后 Yudao 还是 Yudao

不会变成 LangChain。LangChain 是把调用串起来，上一步的输出直接喂给下一步，状态在内存里。Yudao 改完保留五样，最差的退化配置也一样不少：

- 事件日志是唯一事实，能完整重放。
- 模型只提议，主机裁决以后经写入口写。
- 路由按已记录的事实决定谁下一个干、什么时候结束。这份方案让路由更重了：结束条件从代码搬进了路由的定义，五种形态都是换路由和定义得到的。
- 边界一定会停。
- 定义是带版本的数据，在事项创建时冻结，能限定采用、能比较、能撤回。

退化配置丢掉的只有验证节点，所以它是「跑在事实日志上的普通多 agent」，不是一条链。

## 要你定的

1. foundation-rules.md 基础规则 3 下面「质检放行与产品取舍不外包，也不交给判定点」这一行。这个文件只由你改。建议改成「路由有放行时，放行与产品取舍不外包，也不交给判定点」，这样 all_hands 不违反它。
2. 基础规则 3 本身不用改。它说的是生成的模型只能提议，不能宣布状态已改变（system-intent.md:85）。all_hands 里模型交的「完成」也是提案，由路由按定义结束事项，不算自己裁决自己。任务池把规则 3 读成「完成者不能宣布合格」，那是它自己这条路由的规矩。
3. 基础规则 2「没有传感器的地方明说是开环」也不受影响：事项冻结的定义里没有验证节点，这本身就是明说，不用另记。

## 不在这份方案里

- 写入口按事项冻结的定义核对（write_path.py:14、:329、:357，architecture-issues.md 记的那条）。想在同一个实例里让有的事项带验证、有的不带，得先做它；整份换定义今天就能用。
- 第 3 件，装配记下取法版本和回忆位置，单独做。
