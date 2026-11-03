# Uncle Bob 的 ub-mode 调研

日期：2026-11-03。用途：为内核的更高要求（变异测试与复杂度）提供外部做法的事实依据。

## 做法与参数速查

出处写法：仓库名@短提交号 文件 行号。仓库都在 GitHub 账号 unclebob 名下：ub-mode@3da62bf、crapper@6fd92c4、dryer@66ff6d2、mutator@a5a0cb8、uml-viewer@f65dafe、swarm-forge@f4f5fbc、negative-test-experiment@faf9df0；pstack 在 cursor/plugins@c742dd6。标「二手」的是报道、论坛与转录页，只作线索。速查表只放一手来源能确认的内容，不确定的在文末「未能确认的事项」。下载的原件在 `.tmp/ub-research/`（已被 git 忽略）。

### 参数表

| 参数名 | 取值 | 含义 | 来源 |
| --- | --- | --- | --- |
| ub-mode：调用命令 | `/ub-mode` | 在代理里启动技能 | ub-mode@3da62bf SKILL.md L6；README.md L20 |
| ub-mode：安装位置 | `~/.claude/skills/ub-mode/SKILL.md`、`~/.cursor/skills/ub-mode/SKILL.md`、`~/.grok/skills/ub-mode/SKILL.md` | 把 SKILL.md 复制到代理技能目录的 ub-mode 子目录 | README.md L20 |
| ub-mode：三段顺序 | First Make it Work → Then Make it Right → Follow Practice | 每次改动都按此顺序 | SKILL.md L11-14 |
| ub-mode：CRAP 上限 | 10 | 每个函数低于 CRAP 10，用拆分、补测试或两者并用 | SKILL.md L111；README.md L6, L13 |
| ub-mode：case 语句 | 无数字 | 由代理考虑 case 语句是否值得降低 | SKILL.md L112 |
| ub-mode：重复相似度 | 不低于 0.8 | 达到这一档的重复要消除；README 一处写 `< 0.8`，一处写 `>= 0.8` | SKILL.md L116；README.md L6, L14 |
| ub-mode：变异测试 | 无 | 补上未覆盖的、杀死存活的、删除死代码；没有分数目标和存活上限 | SKILL.md L120-123 |
| ub-mode：覆盖率 | 无 | 全文没有覆盖率百分比 | SKILL.md L1-152 |
| ub-mode：工具命令与范围 | 无 | 只写 Use the crapper/dryer/mutator tool，没有命令、选项、改动范围 | SKILL.md L110, L114, L120 |
| ub-mode：工具次序 | Crapper → Dryer → Mutator → Refactoring | 文中排列次序，没有写必须按此运行 | SKILL.md L108-129 |
| ub-mode：测试先行 | 4 步 | 先写失败的测试；确认它因预期的原因失败；最小改动使其通过；做不出诚实的测试就不写坏测试 | SKILL.md L31-34 |
| ub-mode：无效测试 | 条件 | 全部函数返回空仍能通过的测试要扔掉 | SKILL.md L106 |
| ub-mode：攻击前提的触发 | 2 个修复 | 共享同一前提的两个修复在同一道检查失败后，先写出前提再修 | SKILL.md L43-45 |
| ub-mode：提交 | small ordered commits | 每个提交写明为什么、改了什么、怎样证明；无数字 | SKILL.md L150-151 |
| ub-mode：推送 | 最后 | Push to the main line at the end | SKILL.md L152 |
| ub-mode：配套工具 | 4 个 | crapper、dryer、mutator、uml-viewer | README.md L13-16 |
| ub-mode：许可证 | MIT | 2026-11-02 随提交 3da62bf 加入 | LICENSE L1-3 |
| crapper：公式 | CRAP = CC² × (1 − coverage)³ + CC | 覆盖率取 0 到 1 | crapper@6fd92c4 README.md L7-9；src/crapper/crap.py L17 |
| crapper：分级说明 | 1–5；5–30；高于 30 | 低风险；值得看；复杂且测试不足 | README.md L11 |
| crapper：CC 计法 | 1 + 决策点个数 | Python 计 if、elif、for、while、except、match 的 case、推导式的 if 过滤、条件表达式、每个 and 与 or；不计 with、assert、推导式的 for、lambda | src/crapper/languages/python.py L21-38；src/crapper/languages/treesitter.py L60-76 |
| crapper：嵌套函数 | 并入外层函数 | 类里的方法各成一项 | python.py L41-42, L79-89 |
| crapper：覆盖口径 | 行覆盖；LCOV 里有 BRDA 分支记录时改按分支 | 函数行范围内被命中的比例；Python 的覆盖命令行不带 `--branch`；报告里没有该函数记 0% | src/crapper/coverage.py L205-218, L281-297, L442-469；analyze.py L12-25；runners.py L379-381；README.md L45, L66 |
| crapper：Python 覆盖命令 | `<python> -m coverage run --data-file=<文件> [--source=<顶层目录>] -m pytest`，项目没用 pytest 时改为 `-m unittest discover -s .`；再 `coverage lcov -o target/coverage/python/lcov.info` | 先运行整个项目的测试，再生成 LCOV | runners.py L376-387；README.md L83 |
| crapper：解释器 | `.venv/bin/python`，其次 `venv/bin/python`，最后 `python3` | 寻找项目自己的 Python | runners.py L333-338 |
| crapper：缺包 | `pip install --disable-pip-version-check <coverage 或 pytest>` | 缺包时装进项目解释器，不改项目依赖文件 | runners.py L390-401 |
| crapper：覆盖重建 | 每次运行 | 删除旧报告并重新运行测试 | README.md L74；runners.py L540-541 |
| crapper：覆盖失败 | 记 0% | 缺工具或测试失败时该语言记 0%，仍写出快照 | README.md L85 |
| crapper：`./crapper` | 无参数 | 从项目根遍历全部源文件 | README.md L16-22 |
| crapper：`--changed` | 开关 | git status 里新增与修改的源文件（含未跟踪），以文件为单位 | src/crapper/cli.py L55-56, L185-241 |
| crapper：`--threshold N` | 默认无；README 示例 30 | 最差 CRAP 高于 N 时退出码 2 | cli.py L61, L294-304；README.md L30 |
| crapper：`--no-coverage` | 开关 | 只算复杂度，覆盖与 CRAP 为 N/A | cli.py L57；README.md L25 |
| crapper：`--use-existing-coverage` | 开关 | 读磁盘上已有报告，不重跑测试 | cli.py L58；README.md L26 |
| crapper：`--coverage-command <命令>` | 自定 | 代替各语言默认覆盖命令；不能与 `--no-coverage` 并用 | cli.py L59-60, L158-163 |
| crapper：`--root`、`-s` | 默认当前目录；`-s` 可重复 | 项目根与遍历目录 | cli.py L51-54 |
| crapper：路径或片段参数 | 可多个 | 存在的路径按文件或目录分析（命名测试路径时也计入）；不存在的当作片段，只留路径含该文本的源文件 | cli.py L63-67, L222-233 |
| crapper：默认跳过 | 目录 test、tests、spec、specs、__tests__、vendor、node_modules、target、dist、build、out、coverage、.venv、venv、.git、.metrics、testdata、__pycache__ 等；文件 test_*.py、*_test.py、conftest.py | 不计入分析 | src/crapper/discover.py L25-45, L77-90；README.md L19 |
| crapper：输出 | stdout 表（最差在前）；`.metrics/crap.edn` | 每次成功分析覆盖写 | README.md L21-22 |
| crapper：退出码 | 0；1；2 | 正常；用法错误；超过 `--threshold` | cli.py L157, L303 |
| crapper：一次运行的顺序 | 选文件 → 生成覆盖 → 计算 → 写 crap.edn → 打印报告 → 判阈值 | 没有文件时直接返回 0 | cli.py L307-326 |
| crapper：语法文件 | 首次解析某语言时调用 `download([语言])` | 联网情况见文末 | src/crapper/languages/treesitter.py L7-12 |
| crapper：其他语言的覆盖命令 | Clojure `clj -M:cov --lcov`；Java 每个 pom.xml 模块用 JaCoCo Maven 插件 0.8.12；Go `go test ./... -coverprofile=...`；TypeScript `npm run coverage`、Vitest `--coverage` 或 `npx c8 ... npm test`；Rust `cargo llvm-cov` 或 `cargo tarpaulin` | Rust 两个工具都缺时运行 `cargo install cargo-llvm-cov --locked` | README.md L76-82；runners.py L303-309 |
| dryer：得分 | 共有指纹数 ÷ 两者指纹并集 | Jaccard 相似度，1.0 表示归一化结构相同 | dryer@66ff6d2 README.md L7-11；src/dryer/shape.py L104-108 |
| dryer：`--threshold` | 默认 0.82 | 报告相似度不低于该值的候选对 | src/dryer/cli.py L43, L79 |
| dryer：`--min-lines` | 默认 4 | 候选函数的最少源码行数 | cli.py L44-45, L80 |
| dryer：`--min-nodes` | 默认 20 | 候选的最少归一化语法节点数 | cli.py L46, L81 |
| dryer：`--format`、`--edn`、`--text` | 默认 text | 输出格式 | cli.py L47-49, L82 |
| dryer：`--changed` | 开关 | git status 里新增与修改的源文件，只在这些文件之间比较 | cli.py L41-42, L249-250, L306-309 |
| dryer：`--root`、`-s`、路径或片段参数 | 默认当前目录；`-s` 可重复 | 含义同 crapper | cli.py L37-40, L51-55 |
| dryer：默认跳过 | 目录 test、spec、vendor、node_modules、target 等；文件 *_test.go、*.test.cts、*.spec.cts、*.spec.ts、test_*.py、*_test.py | 不参与比较 | README.md L50；cli.py L57-59 |
| dryer：归一化 | 保留调用名、运算符、树形 | 丢掉局部名、字段名、字面量、关键字 | README.md L42 |
| dryer：Python 比较单位 | 函数与方法 | 嵌套函数不单列；只与同一语言的比较 | README.md L5, L103 |
| dryer：命令 | `./dryer`、`./dryer --changed`、`./dryer --threshold 0.9 src` | 示例 | README.md L46-61 |
| dryer：输出 | stdout 报告（最接近的在前）；`.metrics/dry.edn` | 每次成功分析覆盖写 | README.md L52-53 |
| dryer：退出码 | 0；1；2 | 写出报告；用法错误；未知格式。没有按阈值失败的开关 | cli.py L64-67, L316 |
| mutator：`./mutator` | 命令 | 无参数遍历项目；首次运行执行全部覆盖到的变异，README 写明从正在改的文件开始 | mutator@a5a0cb8 README.md L12-17 |
| mutator：一次运行的顺序 | 检查 crapper → 选文件 → 恢复遗留备份 → 生成覆盖 → 逐文件：找位点、选位点、基线、并行变异、写快照 | 缺 crapper 时退出码 2 | src/mutator/cli.py L529-560, L563-587；engine.py L263-324 |
| mutator：Python 算子 | `+`↔`-`、`*`↔`/`、`<`↔`<=`、`>`↔`>=`、`==`↔`!=`、`and`↔`or`、删 `not`、删一元 `-`、`True`↔`False`、`0`↔`1` | 共 10 类 | README.md L96, L100；src/mutator/sites.py L14-52, L298-315 |
| mutator：不变异的内容 | 字符串、注释 | 没有字符串替换、返回值替换、语句删除这类算子 | README.md L91；sites.py L14-52, L298-315 |
| mutator：判定 | killed；survived；uncovered | 测试失败或超时算杀死；测试通过算存活；变异后无法编译算杀死；覆盖未命中的行不运行 | README.md L7, L91 |
| mutator：分数 | killed ÷ (killed + survived) | uncovered 不计入 | README.md L7 |
| mutator：基线 | 变异前先运行一次 | 失败则退出码 2，不改快照 | README.md L32, L40, L104 |
| mutator：`--timeout-factor` | 默认 10；下限 2 秒 | 单个变异的超时 = 基线时长 × 倍数 | cli.py L91-93；README.md L104 |
| mutator：`--max-workers` | 默认每核一个 | 同一文件的变异并行，取（上限、核数、选中位点数）的最小值；文件逐个处理 | cli.py L96-99；README.md L36 |
| mutator：`--mutation-warning` | 默认 50 | 一个文件选中的覆盖位点超过该数时警告 | cli.py L94-95 |
| mutator：`--changed` | 开关 | git status 里新增与修改的源文件 | cli.py L72-73 |
| mutator：`--scan` | 开关 | 只列位点，不运行测试，不写快照 | cli.py L74-75 |
| mutator：`--mutate-all` | 开关 | 连已杀死的变异一起重跑 | cli.py L76-77 |
| mutator：`--since-last-run` | 有快照时为默认 | 重跑存活变异与文本改变过的函数的全部位点 | cli.py L78-80, L110-111；README.md L30 |
| mutator：`--lines n,n,...` | 行号列表 | 只运行这些行上的变异 | cli.py L81 |
| mutator：`--no-coverage` | 开关 | 所有位点视为已覆盖 | cli.py L82 |
| mutator：`--use-existing-coverage`（同 `--reuse-coverage`） | 开关 | 读已有覆盖，不重新生成 | cli.py L83-85 |
| mutator：`--coverage-command <命令>` | 自定 | 代替默认覆盖命令 | cli.py L86-87 |
| mutator：`--test-command <命令>` | 自定；README 示例 `pytest -q tests/test_demo.py` | 代替基线与每个变异的测试命令，工作目录为项目根 | cli.py L88-90；README.md L26 |
| mutator：`--verbose` | 开关 | 打印每条测试命令与每个变异 | cli.py L100 |
| mutator：`--root`、`-s`、路径或片段参数、默认跳过 | 默认当前目录；`-s` 可重复 | 含义同 crapper；跳过的目录取自 crapper 的 SKIP_DIRS 与 TEST_DIRS，测试路径不变异 | cli.py L18-51, L68-71, L102-108 |
| mutator：Python 默认测试命令 | `<.venv 或 venv 的 python> -m pytest`（有 pytest.ini、conftest.py，或 pyproject.toml、setup.cfg 提到 pytest），否则 `-m unittest discover`；不加 `-x` | 在最近含 pyproject.toml、pytest.ini 或 setup.cfg 的目录运行 | src/mutator/runner.py L153-177, L220-222 |
| mutator：其他语言的默认测试命令 | Clojure `clj -M:spec --tag ~no-mutate`、`clj -M:test` 或 `bb spec`；Java `mvn -q test -DexcludeTags=no-mutate`；Go `go test -count=1 <包>`；TypeScript `npm test`；Rust `cargo test` | 都在最近的项目文件所在目录运行 | README.md L106-113 |
| mutator：工作副本 | `target/mutation-workers/run-<uuid>`；备份在 `target/mutator-backup/` | 被变异文件是私有副本，其余用符号链接 | README.md L36-40；workers.py L84, L89-93；engine.py L44-50 |
| mutator：快照 | `.metrics/mutate/<namespace>.edn` | 有快照后默认差异运行 | README.md L15, L30, L44 |
| mutator：退出码 | 0；1；2；3 | 全部杀死或无事可做；用法错误；基线失败；有存活 | cli.py L119-123, L521-526, L570 |
| mutator：依赖 crapper | `../crapper` 或已安装 | 函数名与覆盖命令取自 crapper | README.md L15；src/mutator/crapper_link.py L13-27 |
| mutator：Python 排除标记 | 无 | no-mutate 只用于 Clojure 与 Java 的测试命令 | runner.py L143, L147, L202；README.md L108-109 |
| 三个工具：运行环境 | Python >= 3.11；tree-sitter >= 0.24；tree-sitter-language-pack >= 0.7 | 三个仓库的依赖声明相同 | crapper@6fd92c4 pyproject.toml L8-12；dryer@66ff6d2、mutator@a5a0cb8 同 |
| 三个工具：许可证 | 0BSD | 三个仓库相同 | 各仓库 pyproject.toml L7 |
| uml-viewer：CRAP 色阶 | μ+σ ≤ 8 绿，≤ 12 黄，其余红；评分刻度在 20 处到最差 | 查看器配色，SKILL.md 不调用 | uml-viewer@f65dafe src/uml_viewer/domain/config.clj L3-7 |
| uml-viewer：变异色阶 | 分数 ≤ 0.80 红，≤ 0.90 黄，其余绿 | 同上 | config.clj L9-13 |
| uml-viewer：缺数据与刻度 | 缺数据按红色；评分刻度 1、5.5、10 | 同上 | config.clj L15-17, L20-21, L64-67 |
| uml-viewer：许可证 | 无 | GitHub 许可证字段为空 | GitHub API repos/unclebob/uml-viewer |

### 做法清单

ub-mode 条目末尾的行号指 ub-mode@3da62bf SKILL.md；其他来源在条目末尾注明。

- 三段顺序："First Make it Work. Then Make it Right. Follow Practice"（先让它工作，再做对，再遵守实践）。L11-14
- 懒惰协议："One decision lives in one place." "Ship the smallest edit that solves the problem."（一个决定只放一处；只交付能解决问题的最小改动）。L20-21
- 数据与并发："Get the data shape right before you write the logic."（先定对数据形状再写逻辑）；"If a concurrent writer would matter, do not share state."（有并发写入者就不共享状态）。L25, L27
- 测试先行："Write the failing test before you change the code." "See it fail for the reason you expect."（先写失败的测试，确认它因预期的原因失败）。L31-32
- 重新设计："Do not bolt a new requirement onto the old design."（不把新需求硬接在旧设计上）；按"需求从一开始就在"重新思考，分批交付（"deliver it in pieces"）。L38-39
- 攻击前提：两个共享同一前提的修复在同一道检查失败后，写出前提（限一句）；"Do not start another fix until you have done that."（做完之前不开始下一个修复）。L43-45
- 先减后加："Take complexity out before you add anything."（添加之前先拿掉复杂度）。L49
- 以可检查的终态为目标："A break in the middle is allowed when you planned it and can undo it."（中途破坏只在事先计划且能撤销时允许）。L53-54
- 造工具："Do one unit by hand, then make the tool match that unit."（先手工做一个单元，再让工具与它一致）。L58-59
- 领域建模："Put the domain in a structure that makes the illegal states impossible." "Maintain a glossary of domain terms."（用结构让非法状态不可能；维护领域词汇表）。L65-66
- 边界："Check the data where it enters. Inside, trust it. Keep the business logic in a pure function."（入口检查，内部信任，业务逻辑放在纯函数里）。L71-73
- 类型："Parse outside data once, where it comes in." "Do not silence the compiler."（外部数据在入口只解析一次；不压制编译器）。L78-79
- 幂等与共享状态："Running it twice, or running it after a crash halfway through, ends in the same state."（运行两次或中途崩溃后再运行，结果相同）；"allow one writer, and enforce that in the structure"（只许一个写入者，并在结构上保证）。L83, L88
- 修根因："A guard that only hides the crash is not a fix."（只掩盖崩溃的保护算不上修复）。L94-96
- 小单元："Finish one small unit and check it. Then start the next."（做完一个小单元并检查，再做下一个）。L100-101
- 测试行为："If the test would still pass when every function returned nothing, throw it out."（函数全部返回空测试仍通过，就扔掉）。L105-106
- Crapper："Reduce each function under CRAP 10 by splitting it, by testing it, or both."（拆分、补测试或两者并用，使每个函数低于 CRAP 10）。L110-112
- Dryer："eliminate duplication that rank 0.8 or above"（消除相似度不低于 0.8 的重复）。L116
- Mutator："Cover the uncovered. Kill the survivors. Delete dead code."（补上未覆盖的，杀死存活的，删除死代码）。L120-123
- 重构："Pin what the code does. Change the structure. Prove the behavior did not change."（先固定行为，再改结构，再证明行为没变）。L127-129
- 日志与上下文："Keep a log of every action you take and the reason you took it." "Report that log upon completion."；"Keep the main thread small. Send the bulk elsewhere, and keep the summary."。L135-136, L140-141
- 清理工作树："Find what is safe to remove, confirm nothing still in use needs it, then reclaim the disk." "Uncommitted work waits for a decision."（未提交的工作等待决定）。L145-146
- 提交与推送："Commit often, in small ordered commits." "Each commit says why, what changed, and how you proved it." "Push to the main line at the end."。L150-152
- mutator 的用法："Start with the file you are working on."（从正在改的文件开始）；有快照后差异运行；基线必须先通过。mutator@a5a0cb8 README.md L17, L30-32, L104
- crapper 的用法：每次重新生成覆盖；报告里没有的函数记 0%；`--threshold` 只在显式给出时才让命令失败。crapper@6fd92c4 README.md L45, L74；cli.py L294-304
- 工具逐个运行（swarm-forge，同一作者的多代理仓库，使用 crap4clj、clj-mutate 等前身工具，不属于 ub-mode 调用）："Run constitution tools one at a time."；并行上限 "`--max-workers 4`"；"Function mutation is differential against the source manifest. Do not pass `--mutate-all`."；"Do not invent project-local CRAP, DRY, mutation, or coverage proxies."；"Do not edit mutation testing ... manifests by hand"。swarm-forge@f4f5fbc swarmforge/constitution/articles/engineering.prompt L43-45, L53-54
- 变异位点数不当拆分依据：2026-09-02 先写成"超过 100 个变异位点就拆分"（提交 1ef0cd6），当天改为"位点数只提示模块可能混了多件事；单一职责的模块不为位点数而拆"（提交 cc8d63b；现行文字 engineering.prompt L46）。

## A. ub-mode 是什么

- 仓库 https://github.com/unclebob/ub-mode，所有者 unclebob（GitHub 资料：姓名 Robert C. Martin，简介 "Uncle Bob. Author of Clean Code."，博客 cleancoder.com）。创建于 2026-10-25T16:04:09Z，最近提交 3da62bf（2026-11-02T15:08:29Z，加入 MIT 许可证），默认分支 master，没有标签与发布版本；2026-11-03 读到 6580 星、372 复刻、10 个开放的议题或合并请求。（GitHub API repos/unclebob/ub-mode、users/unclebob）
- 文件只有 SKILL.md（152 行）、README.md（20 行）、LICENSE（21 行）。共 5 个提交：7d7720c 加入 SKILL.md 与 README.md，ff4e602、826dab6、57a8bdd 只改 README.md，3da62bf 加 LICENSE；SKILL.md 自 7d7720c 起没有改动。（GitHub API 各提交的文件列表）
- 支持的代理与安装：README.md L20 点名三个技能目录，分别属于 Grok、Claude Code、Cursor；没有声明版本、平台或其他代理。议题 #6「Add to OpenCode」与合并请求 #1「Support installing the skill with npx skills」仍开放，均由第三方提出。（README.md L20；GitHub API issues）
- 结构：原文列出三项 "First Make it Work"、"Then Make it Right"、"Follow Practice"（L11-14），对应三个一级标题 L16、L90、L131（第三个标题写作 "Practice"），共 24 个小节（13、7、4，不计 Architecture 这个分组标题）。"先做对、再做干净"在原文没有对应：原文是三项，第二项写作 "Make it Right"，全文没有 clean 一词，只有小节标题 Worktree Cleanup。三个质量检查小节 Crapper、Dryer、Mutator 都在第二项里（L108-123）。（SKILL.md）
- 内容：每个小节 1 至 4 条短句，全文的阈值数字只有 CRAP 10 与相似度 0.8，没有命令行、工具地址和覆盖率数字；工具地址只在 README.md L13-16。具体条文见上面的速查表与做法清单。（SKILL.md L1-152）
- 与 poteto-mode / pstack 的关系：README.md L3 原话 "It is loosely based on [@poteto](https://github.com/poteto)'s rules (`poteto-mode` / `pstack`), reduced and paired with deterministic quality-gate tools"；提交 826dab6（2026-10-25T16:07:11Z）的说明是 "Note that ub-mode is loosely based on portions of @poteto's rules"。pstack 在 cursor/plugins 的 pstack 目录，版权人与作者署名 Lauren Tan，README 自称 poteto，MIT，版本 0.15.36（cursor/plugins@c742dd6 pstack/LICENSE L3、plugin.json L4, L6-8, L11、README.md L3）。poteto-mode 列出 24 条原则（pstack/skills/poteto-mode/SKILL.md L45-80），其中 16 条与 ub-mode 的小节同名；ub-mode 的条文更短，例如 pstack 的 Laziness Protocol 是 "Consolidate decisions." 与 "Minimize the diff. Make the smallest change that solves the problem."（principle-laziness-protocol/SKILL.md L9-10），对应 ub-mode L20-21。ub-mode 没有取的 8 条：Minimize Reader Load、Experience First、Exhaust the Design Space、Migrate Callers Then Delete Legacy APIs、Prove It Works、Explain the Number、Never Block on the Human、Encode Lessons in Structure。pstack 里另有 tdd 技能（skills/tdd）和 refactoring、worktree cleanup、opening a PR 三个剧本（pstack/README.md L77, L91-92），与 ub-mode 的 TDD、Refactoring、Worktree Cleanup、Commit and Push 相近。Crapper、Dryer、Mutator 三节在读到的 pstack 文件里没有对应；对 cursor/plugins 的 pstack 目录做 GitHub 代码搜索，"mutation testing"、"mutant" 零命中，"CRAP" 只命中 Scrap 一词。pstack 的 Minimize Reader Load 写道 "LOC, cyclomatic complexity, and "clean architecture" are proxies. Reader load is the thing that matters."（principle-minimize-reader-load/SKILL.md L9）。ub-mode L43 的 "count which actors hold the imbalance" 在读到的 pstack 版本（principle-attack-the-premise/SKILL.md）中检索不到。

## B. 它调用的质量检查工具

- 三个工具（SKILL.md L110、L114、L120 点名，README.md L13-15 给地址）：crapper 量每个函数的圈复杂度、覆盖率与 CRAP 分；dryer 量函数之间的结构相似度；mutator 对源码做小改动、运行测试，统计杀死、存活与未覆盖。README 另列 uml-viewer 做可视化，SKILL.md 不调用它。（见速查表）
- 仓库信息（GitHub API，2026-11-03）：crapper 2026-09-30 创建，最近提交 6fd92c4（2026-10-21），189 星，0BSD；dryer 2026-09-30 创建，最近提交 66ff6d2（2026-10-03），80 星，0BSD；mutator 2026-09-30 创建，最近提交 a5a0cb8（2026-10-21），100 星，0BSD；uml-viewer 2026-09-13 创建，最近提交 f65dafe（2026-10-07），483 星，无许可证。
- 语言：三个 README 的 L3 都写 Clojure、Java、Go、TypeScript、Rust、Python（crapper README L66 注明 TypeScript 一类包含 JavaScript）。Python 项目可以用：crapper 取 coverage.py 的 LCOV，mutator 默认运行 pytest 或 unittest，dryer 比较函数与方法。Clojure、Java、Go 各有前身工具 crap4clj、crap4java、crap4go、clj-mutate、mutate4java、mutate4go、dry4clj、dry4java、dry4go；ub-mode 的 README 曾引用 crap4clj 与 clj-mutate，提交 57a8bdd 删除了这两处。
- 范围：默认遍历整个项目；`--changed` 取 git status 的新增与修改文件，crapper 与 mutator 以文件为单位，dryer 只在这些文件之间比较；mutator 有快照后默认按函数文本变化重跑。三个工具都没有"相对某个提交的差异"这一选项。（cli.py 各处，见速查表）
- 运行时间：三个 README 与 `--help` 没有给时间数字。mutator README L17 写 "The first run of a tree executes every covered mutant. Start with the file you are working on."；crapper 每次重新运行项目测试来生成覆盖（README L74）。直播里的时间说法见 C（二手）。
- Windows：三个 README 与 `--help` 没有写平台。入口脚本是 POSIX sh，指向 `.venv/bin/python`（crapper、dryer、mutator 各自的启动脚本 L1、L4）。crapper 找项目解释器只认 `bin/python`，否则 `python3`（runners.py L333-338）。mutator 以 `start_new_session=True` 启动测试进程（runner.py L98），超时分支调用 `os.killpg(…, signal.SIGKILL)`（L110），并用符号链接建工作副本（workers.py L93）。Python 文档：`os.killpg` 的 Availability 是 "Unix, not WASI, not iOS"，`signal.SIGKILL` 是 "Unix"，`start_new_session` 标 POSIX，Windows 创建符号链接需要开发者模式或 SeCreateSymbolicLinkPrivilege（CPython@bd3be61 Doc/library/os.rst L5287、L4156-4161；CPython@7c653e2 Doc/library/subprocess.rst L592-595；https://docs.python.org/3/library/signal.html）。依赖 tree-sitter 0.26.0 与 tree-sitter-language-pack 1.23.1 在 PyPI 上有 win_amd64 安装包（https://pypi.org/pypi/tree-sitter/json、https://pypi.org/pypi/tree-sitter-language-pack/json）。作者的缺陷记录使用 /Users/unclebob/projects/... 路径（mutator@a5a0cb8 bugs/python-tests-run-with-mutators-virtualenv.md L7-10）。没有 Windows 的声明，也没有实测。
- 其他可核对的行为：crapper 缺 coverage 或 pytest 时用 pip 装进项目解释器（runners.py L390-401）；mutator 的 Python 默认测试命令是整个 pytest 且不加 `-x`（runner.py L176）；mutator 的 Python 算子里没有字符串、返回值、语句删除（sites.py L14-52）；mutator 要求 crapper 在 `../crapper`（README.md L15）。第三方议题 ub-mode#10 提到对 crapper 自动安装 Vitest 覆盖插件与解析 JaCoCo XML 两处的加固补丁 crapper#27，未核对（二手）。

## C. 他本人关于不读代码、靠自动检查的说法

- 原帖一（一手）：2026-07-23T11:44:38Z，账号 unclebobmartin（显示名 Uncle Bob Martin；cleancoder.com 首页链接到该账号的帖子），回复 @ori_pomerantz。后者在 2026-07-22T20:17:25Z 写道 "I just don't feel comfortable letting it edit my files ... If I am responsible for code, I NEED to understand it ... Started programming in 1983. Old?"。他的原文开头："I’m significantly older than you. I started coding in the late 60s. My current strategy is to not read any of the code written by my agents. That’s the only way I can take advantage of their productivity. What I do instead is to surround the agents with extreme constraints. Unit"（接口只返回前约 280 个字符，帖子带长文标记，之后的检查项清单没有读到）。来源：https://x.com/unclebobmartin/status/2080257779395154409，经 https://cdn.syndication.twimg.com/tweet-result?id=2080257779395154409 读取，未读取 x.com 页面本身。
- 原帖二（一手）：2026-07-02T17:39:18Z，同一账号："I’ve been pushing very hard on overloading with tests. Gherkin test unit test QA test mutation test gherkin mutation test. It’s easy to make the AI’s do these things. But just because we can do them doesn’t mean we actually should. Lots of times I just use unit tests and crap"（同样只返回前约 280 个字符；小写 crap 推测指 CRAP 分，帖内未展开）。来源：https://x.com/unclebobmartin/status/2072736888478175413，经同一接口读取。
- 他列出的检查项：一手只有上面两帖里的部分，即 Gherkin 测试、单元测试、QA 测试、变异测试、Gherkin 变异测试和 "unit tests and crap"。二手（startupfortune.com 与 inside.com.tw，均 2026-07-25）转述为单元测试、Gherkin 验收测试、QA 流程、圈复杂度阈值、模块大小限制、依赖结构分析、变异测试、测试覆盖；inside.com.tw 称覆盖率、依赖结构、圈复杂度、模块大小、变异测试出自另一条帖，该帖未找到。
- 理由：一手为 "That’s the only way I can take advantage of their productivity."（原帖一）。二手（startupfortune.com）另引两句 "Humans are slow at code. To get productivity we humans need to disengage from code and manage from a higher level." 与 "In the end, I have very high confidence in the code they produce ..."（后半句未转述），出处帖未找到。
- 承认的局限：一手为原帖二的 "just because we can do them doesn’t mean we actually should"，即他在收缩叠加的测试种类；原帖一用的是 "My current strategy"。二手（explainx.ai 的博客，2026-07-23）转述他在同一串帖里的回复：单元测试由代理写、他不审；Gherkin 验收测试他审，有时仔细、有时抽查；他还定期做最终手动测试。
- 实验记录（一手）：negative-test-experiment@faf9df0（2026-08-17，提交作者 Robert C. Martin）用 Hunt the Wumpus 做了 8 次从空目录开始的实现，比较四种测试纪律和是否把 CRAP 压到 4 以下。experiment-conclusion.md L126："CRAP never raised a design score. It bought coverage (especially None: 1 → 5) and spent cleanliness (every on-row is 1 or 2)."；L139：变异测试 "produced a second suite aimed at operators — never a different Wumpus"；experiment-policy.md L33：满覆盖时 CRAP 等于圈复杂度，上限低于 4 要求每个函数的复杂度不超过 3。
- 2016 年的博客（一手）：https://blog.cleancoder.com/uncle-bob/2016/06/10/MutationTesting.html 写道 "All it proves is that you have executed every line and every branch. Pull out all the asserts from your tests, and your coverage remains unchanged!"；"I have found pitest to be pretty easy to operate, and relatively fast."；结尾称使用变异测试保证 test-after 测试集语义稳定的团队 "highly professional"。
- 他的网站与公司（一手）：cleancoder.com 列出一组 "Morning Bathrobe Rants" 视频帖，题目含 "Code Reviews"（2025-05-14）、"Testing Discipline"（2025-06-03）、"Disengage from the Syntax"（2026-05-06）、"20X"（2026-07-26）、"Rethinking Harnesses"（2026-09-12），帖子正文只有题目和短链接，视频内容未读。cleancoders.com 的 Agentic Discipline 一集（上传日期 2026-04-03）描述为 "distilled four months of intense research into Agentic Development into a one-hour lecture ... From Testing and BDD to Coverage and Mutation testing"（https://cleancoders.com/episode/agentic-discipline-4）。
- 直播（二手）：YouTube 视频 https://www.youtube.com/watch?v=zcLPGC-tvgk，标题 "LIVE: Uncle Bob on Software Fundamentals in the Age of AI"，频道 Matt Pocock（YouTube oEmbed 确认标题与频道；podwise.ai 列为 2026-08-19）。视频没有读到。转录页 sozai.app 称他说：人类要把 CRAP 压在 4 以下，代理放宽到 6、也许 8；变异测试原先隔夜运行，用代理约 30 分钟；让变异测试的代理把覆盖补满；依赖规则写进代理不得违反的规格文件，结束时由检查器核对；架构检查 "I'm having not a lot of luck so far"；复杂度上限 "Obviously there has to be a case where there's too much"。
- 质疑（二手）：Grady Booch 称自己审查代理生成的全部代码，认为覆盖率与复杂度指标不能显示漏洞、死代码和性能上的遗漏分解，并写 "Trust but verify"（startupfortune.com，2026-07-25；Booch 原帖未找到）。Hacker News 条目 49074693（2026-07-27 提交，53 分，条目及其全部评论共 65 项）里的主要意见：代理把功能实现反了并写出全部通过的测试（andai，评论 49075994）、是否读过这些测试与约束（remywang 49075952、jubilanti 49075955）、缺陷常在规格本身（0xedwen 49075046）、他靠咨询为生（jvanderbot 49075294）、诉诸资历（paxys 49075761）。
- 他的回应：该条目全部评论的 52 个作者账号里没有名为 unclebob 或 unclebobmartin 的；他对 Booch 与其他质疑的直接回应，未在一手来源中找到。

## D. 与本仓库设想的对照

对照材料：program-roadmap.md L56「内核的代码质量门槛」、design/trusted-kernel.md、本目录 complexity-and-mutation-testing.md（下称调研）、AGENTS.md、design/test-pyramid.md、requirements/self-hosting.md（D35）、agents/shared-rules.md。

### (1) 有对应的检查

| 项 | ub-mode 一侧 | 本仓库一侧 |
| --- | --- | --- |
| CRAP | 每个函数低于 10；crapper 默认量全项目，`--changed` 取改动文件的全部函数，`--threshold` 默认关闭；覆盖按行（LCOV 有分支记录时按分支），取自整个项目的测试 | 改到的函数 CRAP 分小于 10，挡合并，只用于内核清单里的模块（program-roadmap.md L56）；调研另记圈复杂度默认阈值 10（mccabe、ruff 的 C901）与 complexipy 认知复杂度默认阈值 15（调研 L86-87） |
| 重复 | dryer 相似度不低于 0.8 的要消除；工具默认报告阈值 0.82，最少 4 行、20 个节点，只报告，退出码恒为 0 | 结构重复的相似度低于 0.8，挡合并（program-roadmap.md L56） |
| 变异 | 补上未覆盖的、杀死存活的、删除死代码；无数字；10 类算子；有快照后差异运行；有存活时退出码 3 | 变异测试没有存活的变异，挡合并（program-roadmap.md L56）；手动方法用 poodle 逐模块运行，存活的变异三选一：增加测试、删除代码、写明理由，不设分数目标（调研 L58-59, L72-74） |
| 范围与上线 | 每次改动都适用，所有代码，没有按模块上线的条件（SKILL.md L11-14） | 只用于内核清单的模块；上线要同时满足：所在缝在总图第四节是已定且 seam-diff 报告立住无越界；最近两周改动行数少于模块行数的一成；内核以外不上（program-roadmap.md L56） |
| 测试覆盖 | 没有覆盖率数字；mutator 对未覆盖位点不运行，单列为 uncovered | 内核模块合计行覆盖率不低于动手前；新增或改动的内核代码每一行都有测试执行到；内核清单行数上限只降不升（AGENTS.md L11-14） |
| 测试质量 | Test Behavior, Not Implementation；全部函数返回空仍通过的测试扔掉（SKILL.md L106） | 断言做成了什么，不数模型调用次数（test-pyramid.md L257-258）；删除口径含断言内部实现（D2）与断言恒真（D5）（L334, L337） |

### (2) ub-mode 有而本仓库设想里没有的做法

- 差异运行与快照：mutator 在 `.metrics/mutate/` 保存每个函数的状态，有快照后默认只重跑存活变异与文本改变过的函数（mutator README L30）。路线图第 3 节与可信内核说明没有写差异运行；调研第 3 节记 mutmut「再次运行时只重新测试源码改变过的函数」（L83），poodle 一条没有写。
- uncovered 单列：覆盖未命中的位点不运行，也不计入分数（mutator README L7）。路线图第 3 节没有这一类。
- 测试先行四步（SKILL.md L31-34）与 Attack the Premise（L43-45）：在 shared-rules.md、AGENTS.md、CLAUDE.md、test-pyramid.md 中检索 TDD、先写测试、失败的测试、前提，没有对应条款。
- case 语句是否值得降低（SKILL.md L112）：路线图与调研没有对应说法。

### (3) 阈值或步骤不同

- 范围的单位：路线图写「改到的函数」；crapper 与 mutator 的 `--changed` 以文件为单位（crapper cli.py L236-241），crapper 对选中文件里的全部函数打分，mutator 另按函数文本变化选位点（README L30）。
- 重复的数字：路线图与 SKILL.md 都是 0.8，dryer 默认 0.82，得分在 0.80 与 0.82 之间的候选默认不报告（dryer scan.py L77-79）；dryer 只报告不失败（cli.py L316），`--changed` 只在改动文件之间比较（L306-309）。
- 复杂度口径：radon 对 with、assert、推导式各加 1（https://radon.readthedocs.io/en/latest/intro.html 的构造表），crapper 不计这三项（python.py L21-38）；调研里 1322 个函数中超过 10 的有 109 + 27 + 19 = 155 个，是 radon 6.0.1 的结果（调研 L11），crapper 口径下的个数没有量。
- CRAP 10 的含义（由公式推算）：CRAP 不小于 CC，所以每个函数 CC ≤ 9；CC 为 9 时覆盖率须高于 76.9%，CC 为 5 时高于 41.5%，CC 不超过 2 时不要求覆盖。D35 为单独的圈复杂度阈值写的数字是 10，注明与 mccabe、ruff 的默认值相同（self-hosting.md L87）。
- 变异时用哪些测试：mutator 对 Python 默认每个变异运行整个 pytest 且不加 `-x`，可用 `--test-command` 缩小（runner.py L176）；调研的手动方法每个模块只用该模块的测试并加 `-x -q`（L69），整套测试带覆盖记录约 13 分钟（L30）。
- 变异算子：mutator 的 Python 算子没有字符串类；调研记 mutmut 的存活变异里改字符串占一半到三分之二（L22），poodle 能生成字符串变异（L44），cosmic-ray 没有（L43）。
- 存活的处理：SKILL.md 没有例外条款，mutator 有存活时退出码 3；调研允许「写明理由」并禁用排除标记（L74）；mutator 的 Python 一侧也没有排除标记。
- 平台：D35 第 4、9 条要求现在与以后都能在 Windows 与 Linux 上运行（self-hosting.md L10, L15）；三个工具没有声明 Windows，源码有 POSIX 专用调用（见 B）。
- 环境：crapper 缺 coverage 或 pytest 时直接 pip 安装到项目解释器；AGENTS.md L33 用 `uv sync --frozen` 按锁文件建环境。
- 执行方式：ub-mode 是写给代理的做法，没有写 CI 或合并检查；路线图要求三道检查都挡合并。本仓库有而 ub-mode 没有的步骤：内核清单与路径守卫、导入方向与行数上限检查、探针、按缝上线的条件（trusted-kernel.md L43-91、L123-145）。

### (4) 与共同规则的冲突

- 推送时机：SKILL.md L152 "Push to the main line at the end."；shared-rules.md L49（第 10 条）要求做完小功能后及时 commit 和 push；AGENTS.md L8 写执行者的日记随工单的分支提交，不直接推送到 main。
- 做不出诚实测试时：SKILL.md L34 "If an honest test is impractical, do not write a bad one."；shared-rules.md L96 要求任何功能的实现都要实施、运行、测试，测试是不可缺少的部分。
- 中途破坏：SKILL.md L54 "A break in the middle is allowed when you planned it and can undo it."；shared-rules.md L42（第 3 条）"绝不为了未完成的复杂度拆掉能跑的东西"，L46（第 7 条）"不接受「先这样以后再换」的临时方案"。
- 造工具：SKILL.md L58-59 "If the work is not obvious at a glance, build the tool that does it."；shared-rules.md L44-45（第 5、6 条）要求优先用成熟的库、先翻已有依赖，L84 禁止造轮子绕过依赖。pstack 同名原则另有限定 "build the smallest script that does or proves the job, never a framework"（principle-build-the-lever/SKILL.md L21），ub-mode 没有这一句。
- 其余小节（共 24 个，已全部对照）与共同规则对照后，没有发现文字上的直接冲突。

## 未能确认的事项

- 原帖一 "Unit" 之后的检查项清单：X 的嵌入接口只返回前约 280 个字符，x.com 页面需要登录，没有读取。
- 他在同一串帖里的其他回复、他对 Booch 的回应、inside.com.tw 所说"另一条帖"里的监控项（覆盖率、依赖结构、圈复杂度、模块大小、变异测试）：只有二手转述，原帖链接未找到。Booch 的原帖与措辞只见于 startupfortune.com。
- 直播视频 zcLPGC-tvgk 的内容：字幕没有读到（页面请求返回空内容，下载字幕的命令被拒绝执行）。CRAP「人 4、代理 6 或 8」、变异测试「隔夜、约 30 分钟」、依赖规格文件、架构检查等只见于 sozai.app 转录页；直播日期 2026-08-19 来自 podwise.ai。
- "Morning Bathrobe Rants" 视频与 Clean Coders 的 Agentic Discipline 一集的内容：未读；cleancoders.com 页面记的时长是 PT63S，与描述中的一小时不一致，原因不明。
- ub-mode 的发布说明或公告帖：未找到一手来源；thecode.media 与 DOU 的报道没有读到内容。议题和合并请求 #1–#11 来自第三方，只记了标题与状态。
- 三个工具在 Windows 上的实际表现和运行时间：没有运行任何下载的代码，没有实测。
- crapper 首次解析是否联网下载语法文件（treesitter.py L9-12 调用 download）；其依赖声明 tree-sitter-language-pack >= 0.7 与 PyPI 上的 1.23.1 是否兼容：未验证。
- 0.8（SKILL.md）与 0.82（dryer 默认）的取舍原因，以及 CRAP 10 与 uml-viewer 色阶 8、12、20 的关系：作者没有说明。
- 调研第 4 节写 swarm-forge 的「CRAP 阈值只检查改动过的文件」：在 swarm-forge@f4f5fbc 的文件与最近 100 条提交说明中找不到阈值数字或这句话。
- 与 pstack 的逐条对应：读了 pstack/README.md、poteto-mode/SKILL.md 和六个原则文件（laziness、attack-the-premise、subtract、test-behavior、build-the-lever、minimize-reader-load），其余原则文件没有逐条读；GitHub 代码搜索不保证覆盖全部文件。
