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
| `impact <文件或小节>` | 引用它、提到它的节点，按角色分组（必读范围内的先列，其次是只是可达的） |
| `pending` | 上游变了而下游没变、也没确认的引用。范围（`check` 里的待核对用同一套）：上下游都不是记录文档（清单在 `data/record-docs.json`：`CHANGELOG`、`decision`、日记、`adr`、`research`、`evaluation`、`archive`）；只算指向小节、表格行、总图的节或缝的引用，指向整份文件的引用只由死引用检查查文件在不在。这些边仍在索引里，`who`、`impact` 照常能查 |
| `confirm <下游> [上游]` | 记一条确认（下游看过，不用改）；追加到 `.doc-index/confirmed.jsonl` |

## 范围与索引

- 范围：git 跟踪的 `.md`、`.html`，排除 `docs/archive/`、`agents_jour/`、`.claude/worktrees/`、`docs/prototypes/` 与 `evals/scenarios/` 下的 HTML（代码）、图谱页面模板 `assets/graph.html`。
- 节点：文件，和小节（Markdown 标题、总图的节与缝）；脚手架文件里的表格每一行也是一个节点（身份是「表 + 首列」）。hash 在行尾统一以后算，只代表内容版本。
- 边：Markdown 链接、HTML href、反引号路径、`` `路径`「小节」 ``、设计说明的「总图位置」行（落到总图的节和缝）。
- 一份源文件一个索引文件：`.doc-index/files/<路径>.json`；不记行号，`who`、`impact` 查询时现算。
- 索引里的 `seen` 是下游最后认可的上游 hash，是状态，不能重建：删掉索引等于把基线重置成现状。`confirmed.jsonl` 只追加。

## 规则与数据

- `rules/*.lp`：clingo 规则（只用分层写法），Python 只负责把事实喂给 clingo 并输出结论。
- `data/known-external.json`：内置技能与用户级技能的白名单（检查不依赖本机的 `~/.claude`）；约定路径清单（写入时才创建的具体文件，如 `agents_jour/其他.md`，不算死引用，只写文件不写目录）；哪个表头的首列是标签或技能。
- `data/roles.json`：角色的别名、入口规则文件、入口技能。角色名取自 `docs/agents/workflow.md` 的角色表，两边对不上会报错。

## 阅读范围怎么算

链接可达不等于必读。入口是 `data/roles.json` 里的规则文件与入口技能。一条引用算必读，要同时满足：它的子句（两个逗号、分号、句号或表格竖线之间）里有「读、遵守、遵循、为准、正本」或「按[链接]」，或者它在技能的「先读什么」一节里；并且这个子句不是只对别的角色说的（子句里出现别的角色的别名而没有本角色的）。必读只走一步：入口文件的指令算必读，必读文件里再指向的文件是按需查阅。

局限：条件性的阅读（「某某时读」）和只读一节（`「小节」`）都按整份文件计字符；一步以外的必读不计；没有指令词的「见某某」不计。

## 测试

```
uv run --project tools/doc-consistency pytest tools/doc-consistency/tests
```

测试用真实的 git 仓库、真实的 clingo、真实的文件，图谱页面用真实的 Chrome（`channel="chrome"`，需要本机装有 Chrome）。工具自己的 `pyproject.toml` 配了 pytest，不会加载仓库根的 `conftest.py`。

## 依赖

`markdown-it-py`（Markdown）、`clingo`、HTML 用 Python 自带的 `html.parser`；图谱用 cytoscape.js 3.34（MIT，`doc_consistency/assets/cytoscape.min.js`，打包进页面，不联网）。
