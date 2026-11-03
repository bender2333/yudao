# 文档一致性工具

Yudao 开发用的单独工具：给文档建一份文件和小节的索引（类似 Obsidian 的元数据缓存，不往任何文档写东西），再对脚手架文件（`CLAUDE.md`、`AGENTS.md`、`docs/agents/**`、`.claude/skills/**`）做确定性的检查。不调用任何 LLM，只提醒、不拦提交。设计依据见 `docs/research/doc-consistency-concept-model.md`。

## 运行

在仓库根目录：

```
uv run --project tools/doc-consistency doc-consistency <命令>
```

## 命令

| 命令 | 做什么 |
| --- | --- |
| `build` | 重建 `.doc-index/`。文件没变时索引文件字节不变；第一次运行把现状记成「待核对」的基线 |
| `status` | 工作区和索引比，列出新增、改动、删除的节点 |
| `who <文件或小节>` | 谁引用了它，给出位置与行号。小节写成 `路径#标题 > 子标题`，同名小节后面带 `(2)` |
| `nodes <关键词>` | 按关键词列出节点名；`who`、`impact`、`confirm` 要写完整的节点名，写错时报错也会列出相近的候选 |
| `view` | 生成离线图谱 `.tmp/doc-index/graph.html`：拖动、按目录上色、点一份文档高亮它引用的（绿）和引用它的（橙）、双击展开小节、「展开总图」显示 6 个节和 13 道缝 |
| `refresh` | 用 `gh label list` 保存标签快照到 `.doc-index/labels.json`；只有这一条命令要联网，其余都离线 |
| `check` | 汇总提醒：死引用（技能、标签、文件路径）与待核对。永远以 0 退出；规则或程序自己出错（缺标签快照、规则无解、角色表对不上）才报错退出 |
| `scope [--reach]` | 每个角色的阅读范围与字符数 |
| `rules canon` | 规则事实线：把正本表格（`data/canon.json`）读成事实，列出每张表的事实、附注、读不出的格子、一条事实两处正本、读不到正本的角色。永远以 0 退出；配置或程序出错才报错退出 |
| `rules view` | 生成离线页面 `.tmp/doc-index/rulefacts.html`：角色 × 规则矩阵与规则图（同一份事实，不手画） |
| `impact <文件或小节>` | 引用它、提到它的节点，按角色分组（必读范围内的先列，其次是只是可达的） |
| `pending` | 上游变了而下游没变、也没确认的引用。范围（`check` 里的待核对用同一套）：上下游都不是记录文档（清单在 `data/record-docs.json`：`CHANGELOG`、`decision`、日记、`adr`、`research`、`evaluation`、`archive`）；只算指向小节、表格行、总图的节或缝的引用，指向整份文件的引用只由死引用检查查文件在不在。这些边仍在索引里，`who`、`impact` 照常能查 |
| `confirm <下游> [上游]` | 记一条确认（下游看过，不用改）；追加到 `.doc-index/confirmed.jsonl` |

## 范围与索引

- 范围：git 跟踪的 `.md`、`.html`，排除 `docs/archive/`、`agents_jour/`、`.claude/worktrees/`、`docs/prototypes/` 与 `evals/scenarios/` 下的 HTML（代码）、页面模板 `assets/graph.html` 与 `assets/rulefacts.html`。
- 节点：文件，和小节（Markdown 标题、总图的节与缝）；脚手架文件里的表格每一行也是一个节点（身份是「表 + 首列」）。hash 在行尾统一以后算，只代表内容版本。
- 边：Markdown 链接、HTML href、反引号路径、`` `路径`「小节」 ``、设计说明的「总图位置」行（落到总图的节和缝）。
- 一份源文件一个索引文件：`.doc-index/files/<路径>.json`；不记行号，`who`、`impact` 查询时现算。
- 索引里的 `seen` 是下游最后认可的上游 hash，是状态，不能重建：删掉索引等于把基线重置成现状。`confirmed.jsonl` 只追加。

## 规则与数据

- `rules/*.lp`：clingo 规则（只用分层写法），Python 只负责把事实喂给 clingo 并输出结论。规则事实线的规则在 `rules/rulefacts/`。
- `data/known-external.json`：内置技能与用户级技能的白名单（检查不依赖本机的 `~/.claude`）；约定路径清单（写入时才创建的具体文件，如 `agents_jour/其他.md`，不算死引用，只写文件不写目录）；哪个表头的首列是标签或技能。
- `data/roles.json`：角色的别名、入口规则文件、入口技能，和合称 `groups`（规则事实线读格子时展开）。角色名取自 `docs/agents/workflow.md` 的角色表，两边对不上会报错。
- `data/canon.json`：规则事实线的正本表格（见下一节）。

## 规则事实线

与上面的图谱线分开：管给 LLM 读的规则文件里「谁做、谁加、谁写、能不能」这类事实。方案见 `docs/research/doc-consistency-rule-facts.md`，现在只做到第 1 步：把正本表格读成事实，不改任何文档。代码在 `doc_consistency/rulefacts/`，规则在 `rules/rulefacts/canon.lp`，数据在 `data/canon.json`；与图谱线共用的只有 `scan.py` 的解析、`scaffold.solve/pick`、阅读范围的事实（`scaffold_facts`）和打包的 cytoscape。不读 `.doc-index/`，不需要标签快照。

**正本**：`workflow.md` 的角色表（第 2 节）、状态表（第 4 节）、证据评论表（第 5 节）、出问题往哪交表（第 7 节）、用户在场与不在场的权限表（第 9 节），`acceptance-evidence.md` 第 1 节的结论表。每条事实只归一张表的一列。

**`canon.json` 怎么声明**：`tables` 的键是 `nodes` 命令查得到的表节点名（`小节 > 表N`）。一张表写：

| 字段 | 意思 |
| --- | --- |
| `key` | 首列的表头，和文档对不上会报错（权限表首列没有表头，写 `""`） |
| `key_vocab` | 写 `"角色"`：键本身是角色（角色表）；点名的角色就是键 |
| `node` | 规则图里键的节点类型；不写，这张表只进矩阵 |
| `columns` | 列名 → `{fact, many, vocab, edge, open, after, key_from}` |

列的字段：`fact` 事实名；`many` 一格是不是多值；`vocab` 值的词表，`"角色"` 取自 `roles.json`（别名与合称），写成名字的词表放在 `canon.json` 的 `vocab` 里（如 `可否`），值必须在清单里；`open: true` 表示词表还没封闭（「事」），一格按「、」「；」切开，每个短语原样当一个值，不算读不出；`edge` 在规则图里画边，`"角色→键"` 或 `"键→角色"`。两种特殊取法，都只有一个字段：

- `after`：只读格子里这段话后面的清单（状态表「意思」一格里「交回架构师：」后面是 `needs-triage` 的理由清单）。格子里没有这段话的行不出事实。
- `key_from`：事实的键不是首列，而是另一列反引号里的标签，且在 `tags` 清单里（出问题往哪交表「卡在」一格本身是清单，对应的标签在「怎么交」一格的反引号里）。找不到标签的行不出事实。

**读法**：一格里用「或」「、」「与」「；」「，」或 `<br>` 分开的是多个值（词表不是角色的列只认「、」「；」）；`\|` 转义的竖线不分格。角色按 `roles.json` 的名字与别名，合称（`groups`：`架构师`、`任何角色`）展开成各个角色。括号里的话与 `canon.json` 的 `qualifiers`（「领取时」「之前」这类限定）剥成附注 `note`，不进事实；写成名字的词表（可以、不可以）只认第一个「，」前面的词，后面的话是附注。读不出的值（不在词表里，如「报告的人」「CI」「独立审查者」）原样报 `unparsed`，不猜；一格里读得出的部分照读。

**规则**（`canon.lp`，只用分层写法）：`dup_canon` 同一条事实在两张表里都有；`only_in` 两处里只有这一处有的值；`unreachable` 正本点名的角色，必读范围里没有正本所在的文件（只算 `agent` 不为 false 的角色，用户不读规则文件，不算读不到；矩阵里用户一列只标「点名」）。键是角色的表（角色表）里，键也算被点名。

## 阅读范围怎么算

链接可达不等于必读。入口是 `data/roles.json` 里的规则文件与入口技能。一条引用算必读，要同时满足：它的子句（两个逗号、分号、句号或表格竖线之间）里有「读、遵守、遵循、为准、正本」或「按[链接]」，或者它在技能的「先读什么」一节里；并且这个子句不是只对别的角色说的（子句里出现别的角色的别名而没有本角色的）。必读只走一步：入口文件的指令算必读，必读文件里再指向的文件是按需查阅。

局限：条件性的阅读（「某某时读」）和只读一节（`「小节」`）都按整份文件计字符；一步以外的必读不计；没有指令词的「见某某」不计。

## 测试

```
uv run --project tools/doc-consistency pytest tools/doc-consistency/tests
```

测试用真实的 git 仓库、真实的 clingo、真实的文件，图谱页面用真实的 Chrome（`channel="chrome"`，需要本机装有 Chrome）；规则事实线的测试（`tests/rulefacts/`）不用浏览器，用页面里注入的 JSON 验。工具自己的 `pyproject.toml` 配了 pytest，不会加载仓库根的 `conftest.py`。

## 依赖

`markdown-it-py`（Markdown）、`clingo`、HTML 用 Python 自带的 `html.parser`；图谱用 cytoscape.js 3.34（MIT，`doc_consistency/assets/cytoscape.min.js`，打包进页面，不联网）。
