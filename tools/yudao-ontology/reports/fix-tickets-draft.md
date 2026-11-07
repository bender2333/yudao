# 三张修复工单（草稿）

本体第一步第 4 批查出的三处代码问题，各写一张子工单的正文，格式照 `.claude/skills/to-children/SKILL.md` 的模板与 `docs/agents/ticket-spec.md`。这里只是草稿：没有建 GitHub 工单，父工单编号、里程碑与标签等你定了再填。

依据统一核对过 main `37e9d68`（11-07 夜）。三处代码在 `eb8429e` 之后一行没改。

| 工单 | 改哪里 | 要你先定的 | 放出前要不要先改设计说明 |
| --- | --- | --- | --- |
| 一：内核里的旧核验关系 | `harness/definitions/__init__.py` 等 | 1a 还是 1b | 1a 不要；1b 要（改「旧文件照旧能读」） |
| 二：几个角色交完成时的开环 | `harness/direct.py` 等 | 2a 还是 2b | 两种都要，句子草稿写在工单里 |
| 三：检查材料位置的加载检查 | `harness/definitions/__init__.py`、`harness/environment.py` 等 | 无 | 不要，设计已经写了 |

一和三都改 `harness/definitions/__init__.py`，但改的是不同区块（一改 `LEGACY_VERIFICATION` 与读它的三处，三改 `WriteScope` 与 `verification_issues`）。照 ticket-spec「同时可做的工单不改同一处代码」，可以同时放；如果你选 1a 时把旧声明挪进定义文件，那份文件里的 `paths` 要按三的规矩写成固定目录，建议三设为一的前置。

---

## 工单一：[定义的缝 · 形态] 旧定义的核验兜底移出内核模块

### Parent
#<待定：形态与核验角色的父工单；父工单已关时挂阶段二工单>

### What to build
依据：`docs/design/forms-and-verifier-role.md`「验收」第 3 条（main `37e9d68`）；总图：第二节第三环（内核只认通用的成果），第四节「定义」的缝
环：需你批准（改内核路径，按 ticket-spec「内核路径」不事前批准）；做法：切片

验收第 3 条原句：「事实与裁决、循环两层的代码里不出现部门名，也不出现 PRD、交付、质检结论这些成果种类的判断」。

现在内核模块 `harness/definitions/__init__.py` 第 272 至 276 行写死了一份 `LEGACY_VERIFICATION`：质检核验工程的 `delivery_spec`，质检的写入范围是检查材料。它是旧定义（`organization.json` 没有 `verification` 字段）的兜底，读它的地方有四处：
- `Definitions.verification`（第 855 至 858 行）
- `workspace_writer_issues`（第 1376 行）
- `harness/organization_compose.py` 的 `write_scopes`（第 186 行）
- 测试 `harness/tests/test_definitions.py`、`harness/tests/kernel/test_definitions_decide.py` 断言默认定义的核验声明等于它

`harness/tests/test_thin_driver_names.py` 用 `EXEMPT_BLOCKS` 把这个区块从部门名检索里遮掉，`ALLOWED` 里还为 `delivery_spec` 留了一条例外。发布带的三份 `organization.json` 都已经写明了 `verification`，兜底只给没写这个字段的旧文件用。

两种做法，放出前定一种：

- **1a 把兜底挪成定义文件（建议）。** 旧声明写进 `harness/definitions/` 下的一份 JSON（例如 `legacy_verification.json`），加载时读成 `VerificationDeclaration`；内核代码只写「没有声明时用那一份」，不写任何部门名与成果种类名。旧文件照旧能读，只增环不破。
- **1b 去掉兜底。** 没写 `verification` 的定义不再按三部门解释。要先定没写时怎么办：加载时整份拒绝，或者读作没有核验角色（以开环完成结束）。两种都会改变旧文件的意思，违背 `Organization.verification` 注释里写的「字段只增，旧文件照旧能读」。所以先要查清旧文件从哪里来（项目里存的定义版本、重放旧事项时读的冻结版本），给出迁移办法，并把这一句改进设计说明。

我建议 1a：它直接满足验收第 3 条，不碰旧数据。1b 更干净，但代价落在旧项目与重放上，这一步还没人量过。

现有代码：只动兜底的写法和读它的四处；核验声明的结构（`VerificationDeclaration`、`VerifierRole`、`WriteScope`）不动。

### 只改
- 1a：`harness/definitions/__init__.py`、新增 `harness/definitions/legacy_verification.json`、`harness/organization_compose.py`、`harness/tests/test_thin_driver_names.py`、`harness/tests/test_definitions.py`、`harness/tests/kernel/test_definitions_decide.py`
- 1b：上面除新增 JSON 以外的几份，加上迁移所需的文件（定了以后列）
- `touches-core`：是（`harness/definitions/`）

### Acceptance criteria
- [ ] `harness/definitions/__init__.py` 的代码里不再出现 `quality`、`engineering`、`delivery_spec`；`test_thin_driver_names.py` 的 `EXEMPT_BLOCKS` 删掉这一项，`ALLOWED` 里 `delivery_spec` 那一条删掉，用例照旧通过
- [ ] 1a：一份没写 `verification` 的旧 `organization.json` 加载后，核验声明与今天的 `LEGACY_VERIFICATION` 相同（质检核验工程的交付，质检写检查材料）
- [ ] 1b：没写 `verification` 的旧定义按定下的办法处理（拒绝时写明缺哪个字段），迁移办法有用例守着
- [ ] 内核路径的覆盖读数不降，改动的行有测试执行到（`AGENTS.md`「内核路径的测试覆盖」）
- [ ] 验收层：内核，`harness/tests/kernel/test_definitions_decide.py`、`harness/tests/test_thin_driver_names.py`、`harness/tests/test_definitions.py`
- [ ] 本体复核：合并后在 `research/ontology-step1-r2` 上跑 `python3 tools/yudao-ontology/codecheck.py <合并后的提交>`，分层检查（layer-name）对 `harness/definitions/__init__.py` 不再报违例，整份结果没有违例

---

## 工单二：[路由与粒度 · 直做] 几个角色都能交完成、只有部分被核验时，开环判得一致

### Parent
#<待定：直做的父工单；父工单已关时挂阶段二工单>

### What to build
依据：`docs/design/forms-and-verifier-role.md`「直做」第 3 条、「定义的校验」中「开环的标记」、「验收」第 12 条（main `37e9d68`）；总图：第三节外环（开环时交完成），第四节「路由」的缝
环：可重写（路由与定义两层）；做法：切片

设计里两句在这种定义上判得相反：
- 「直做」第 3 条按交完成的那个角色判：「指定的角色交了完成，事项结束：没有核验角色核验它，结束原因是开环完成」。
- 「定义的校验」第 4 条与验收第 12 条按最后采纳的成果种类判：核验角色核验最后采纳的那种成果，就不标开环。

代码也是两种判法：
- 事项创建时，`harness/orchestrator.py` 第 551 行用 `Definitions.is_open_loop`（`harness/definitions/__init__.py` 第 895 行）按成果种类算出开环标记，记进创建事件。
- 交完成时，`harness/direct.py` 第 814 行按交的那个角色决定结不结束：`ends_run=not verified_outcome(request.department, definitions)`。
- 结束原因由 `direct.completion_reason`（第 425 至 434 行）只读创建时的标记。

所以，几个角色都能交完成、只有一个被核验时，没被核验的那个交了完成，事项直接结束，结束原因既不是放行也不是开环完成。

复现（11-07 在副本上做过）：拿测试用的 `harness/tests/direct_with_verifier_definitions/`，加一个部门 `product`，它只有 `submit_completion` 一个工具（避开「运行工作区只有一个写入者」那条拒绝），补上它的提案合同，把它列进 `direct` 路由的部门清单。
- `load_definitions` 与 `direct.check_definition` 都接受这份定义。
- `is_open_loop("completion")` 是 False；`verified_outcome("engineering")` 是 True，`verified_outcome("product")` 是 False。
- 结束原因那一步是读代码得出的，没有跑整个事项。

发布带的形态走不到这里：几个角色直做只有工程能交完成。合成加核验角色时也会把所有交完成的角色都写进核验（`organization_compose.py` 的 `_delivering`）。手写的定义，或者加了核验角色之后再加一个能交完成的部门，就走得到。

两种做法，放出前定一种，并先把对应的句子改进设计说明（设计改动不走工单）：

- **2a 加载时拒绝（先止血）。** 设计在 「直做」第 5 条后补一句，草稿：「直做的定义里有核验角色时，每个能交完成的角色都要在核验范围里；有不在的，加载时整份拒绝：它交的完成没有人核验，事项却已标为不开环。」代码在 `direct.check_definition` 里加这一条。改动小，跟 「直做」第 5 条是同一个路子。
- **2b 开环在交完成时按交的那个角色判（建议的最终形态）。** 设计把 「定义的校验」第 4 条与验收第 12 条改成按每次交完成判，草稿：「事项以开环完成结束，当且仅当结束它的那份完成没有核验角色核验；创建时的标记只说这份定义里有没有可能以开环完成结束。」代码让 `completion_reason` 看结束事项的那份完成是谁交的，不再只读创建时的标记；创建事件里的 `open_loop` 字段照旧写（只增）。name-map「放行或开环完成，事项完成」一行随之改写。

建议先做 2a 关上这个口子，2b 等下一次动开环时一起做。2b 更贴开环的意思（这一次的结论有没有人核验），但改动面大：页面统计、重放读法、name-map 都要跟。

现有代码：核验声明的结构、`verified_outcome`、打回与放行的流程都不动。

### 只改
- 2a：`harness/direct.py`（`check_definition`）、`harness/tests/test_direct_with_verifier.py`
- 2b：`harness/direct.py`（`completion_reason`、`recorded_open_loop` 的读法）、`harness/orchestrator.py`（只在创建标记的注释与含义需要改时动）、`harness/tests/test_direct_with_verifier.py`、`harness/tests/test_direct_several_roles.py`
- `touches-core`：2a 否；2b 动到 `orchestrator.py` 时是

### Acceptance criteria
- [ ] 上面复现里的那份定义：2a 加载时整份拒绝，原因写明哪个能交完成的角色不在核验范围里；2b 照常加载，`product` 交完成时事项以开环完成结束（结束原因 `open_loop`），`engineering` 交完成时等核验结论
- [ ] 所有能交完成的角色都被核验的定义、没有核验角色的定义，行为与今天相同（`test_direct_with_verifier.py`、`test_direct_several_roles.py` 照旧通过）
- [ ] 验收层：缝，`harness/tests/test_direct_with_verifier.py`、`harness/tests/test_direct_several_roles.py`、`harness/tests/test_direct_routing.py`
- [ ] 本体复核：设计说明改好以后，在 `research/ontology-step1-r2` 上把新句写进 `tools/yudao-ontology/rules/openloop-<那个提交>.ttl`，跑 `python3 tools/yudao-ontology/openloop.py <那个提交>`。「有核验角色、最后的成果被核验、交完成的角色被核验、另有一个不被核验的能交完成的角色」这一行，2a 应变成「加载时整份拒绝」，2b 应变成一致的「标开环」，整份结果没有违例

---

## 工单三：[定义的缝 · 形态] 定义写了别的检查材料位置，加载时整份拒绝

### Parent
#<待定：形态与核验角色的父工单；父工单已关时挂阶段二工单>

### What to build
依据：`docs/design/forms-and-verifier-role.md`「核验角色」第 1 条（main `37e9d68`）；总图：第四节「定义」与「写入口」的缝
环：可重写（定义一层的加载核对；`environment.py` 只收紧取值）；做法：切片

设计原句：「检查材料放在哪里是主机的固定约定，公开树、交付快照与检查副本都按这一处排除与收录；定义只声明哪个角色得到这块写入范围，不另选位置，写了别的位置的定义在加载时整份拒绝。」

现在的代码：
- `WriteScope`（`harness/definitions/__init__.py` 第 231 至 243 行）只要求 `check_materials` 带上 `paths`，不核对它是不是固定目录。`verification_issues`（第 1279 行）也不核对。
- `harness/environment.py` 第 905 至 909 行按定义里声明的第一个目录定这个事项的检查材料目录；`adjudication.py` 也按声明的目录限写入（name-map「写入范围」一行记为一致）。
- `harness/public_tree.py` 第 366 行排除检查材料时调 `is_qa_tests_path(relative)`，不带目录，只排除固定的 `.yudao-qa-tests`（`harness/path_rules.py` 的 `CHECK_MATERIALS_DIR`）。

结果是，一份定义把检查材料写到别的目录，照样加载；核验角色写进那个目录，公开树不排除它，检查材料就进了公开树和交付。

顺带一处：`harness/organization_compose.py` 第 450 行在发布里的核验部门没有写入范围时写 `list(CHECK_MATERIALS_DIR)`，对一个字符串取 `list` 得到的是一个个字符，不是一个目录。发布带的定义都写了写入范围，今天走不到这一句，但它和这张单是同一件事：位置只有一处。

现有代码：`WriteScope` 的字段不删（只增：旧文件写了 `paths` 照旧能读，只要等于固定目录）；`path_rules.py` 的判断函数不改签名。

### 只改
- `harness/definitions/__init__.py`（`verification_issues` 加一条核对）
- `harness/environment.py`（检查材料目录取固定的那一处）
- `harness/organization_compose.py`（第 450 行写成 `[CHECK_MATERIALS_DIR]`，或者不写 `paths`）
- `harness/tests/test_definitions.py`、`harness/tests/test_organization_compose.py`、`harness/tests/test_public_tree.py`
- `touches-core`：是（`harness/definitions/`、`harness/environment.py`）

### Acceptance criteria
- [ ] 一份 `organization.json` 的 `verification.write_scopes` 里 `check_materials` 的 `paths` 不是 `[".yudao-qa-tests"]`：加载时整份拒绝，原因写明哪个角色写了哪个位置；写的正是固定目录、或者没写 `paths` 的照常加载
- [ ] 发布带的三份定义与测试用的几份定义照常加载
- [ ] 合成加核验角色得到的写入范围是固定目录（`test_organization_compose.py` 有一条用例守着，包括发布里的核验部门没写写入范围的那一种）
- [ ] 公开树、交付快照与检查副本排除与收录检查材料，用的是同一处固定目录（`test_public_tree.py`）
- [ ] 验收层：缝，`harness/tests/test_definitions.py`、`harness/tests/test_organization_compose.py`、`harness/tests/test_public_tree.py`
- [ ] 本体复核：这一条今天在本体里只是原句（`batches/batch2-eb8429e.ttl`），没有变成检查。修好以后在 `research/ontology-step1-r2` 上给第 3 批加一条：定义里写入范围的位置不等于主机的固定目录，记违例；再加一处埋错（定义副本里写别的位置），确认查得出
