---
name: doc-scan
description: 全量扫描 docs 与根目录文档，核对与总图、路线图、术语表、规则是否一致，产出带位置与改法的报告。
argument-hint: "[范围：全部 | docs/design | docs/requirements | <路径>]，省略时扫全部"
disable-model-invocation: true
---

# 文档与设计扫描

一次扫完仓库里的活动文档，找出与正本矛盾的、彼此冲突的、引到已归档文件的、用了不该用的词的地方，交一份每条都带位置与改法的报告。

## 什么时候用

用户说「把文档扫一遍」「看有没有矛盾」「检查与总图和路线图不一致的地方」；总图或路线图改过名之后核对改名跟到没跟到底；里程碑结束时整体核对一遍。单份文档的小改直接改，不用这个。

## 扫描六步

### 1 划定范围

列文件：`Get-ChildItem -Recurse -File -Include *.md,*.html`，跳过 `.venv/`、`node_modules/`、`.tmp/`、`.claude/worktrees/`、`.ralph/`、`.yudao/`、`docs/archive/`。

后面这三个是上回踩到的坑：`.claude/worktrees/` 下是整份旧检出，`.ralph/`、`.yudao/` 是循环账本与试用现场，混进来会让文件数翻一倍、链接核对八成是噪音。

**判据**：报出文件总数与各目录份数，数字与用户预期量级相符。

### 2 读正本，写核对清单

正本是 `docs/architecture.html`、`docs/program-roadmap.md`、`CONTEXT.md`、`docs/foundation-rules.md`、`docs/agents/shared-rules.md`。把要点抄成 `.tmp/doc-scan/canonical.md`：十三道缝（名字、两侧、已定/未定）、三环归属、外环九个状态词、内环六步、五个阶段各立哪几道缝、十条内容道、五条判据名、术语正名与 _Avoid_ 词，再加一张「硬检查点」表。

**判据**：每条检查点都能指回正本的一节或一行；内容多到审查员只读这一份就够，不必各自读正本。

### 3 分组并发派发

同主题的一到三份放一组（设计说明、需求、根目录规则、角色规则、ADR、调研、原型、评测各成组），一组一个审查员。组数跟着文件数走，二十组一块跑不嫌多。

派发模板（`workflow` 工具，`args.groups` 传 `[{id, title, files}]`）：

```js
const groups = args.groups;
phase("核对");
await parallel(groups.map(g => () => agent(`你在核对 Yudao 的文档一致性。
先读 .tmp/doc-scan/canonical.md（正本要点与硬检查点），再逐份读：${g.files.join("、")}。
逐条核对：与正本矛盾的、与本组或别处冲突的、引到已归档文件或不存在路径的、用了 CONTEXT.md 里 _Avoid_ 词的、文件自己前后不一致的。
用 write 工具把结果写成 JSON 数组到 .tmp/doc-scan/${g.id}.json，每项字段 file、line、quote、kind、counterpart、why、fix、confidence；kind 只用 冲突、不一致、失效引用、含糊 四个词。
回复只写「${g.id} 共 N 条」，不要贴条目。`)));
```

条目写进文件而不写进回复，是这一版的硬要求：几十组的长 JSON 一起返回会被截断，回收就得重跑。

**判据**：每份文件恰好出现在一组；每组 JSON 都落盘；`scripts/merge-findings.ps1` 跑通，没有缺字段的条目。

### 4 机器核对

在仓库根运行两个脚本，结果直接进报告：

- `scripts/check-links.ps1 -Out .tmp/doc-scan/links.md`：逐条解析 md 链接与 html 的 href，解析不到的列出来。
- `scripts/term-audit.ps1 -Out .tmp/doc-scan/terms.md`：从 CONTEXT.md 抽 _Avoid_ 词，找活动文档里的用法；数九个状态词确认没被改名；数 Stage、M、工作包旧编号的分布，找出改名没跟到底的文件。

**判据**：两份表都生成；每条命中要么进报告，要么写清为什么不算（通用词命中多不奇怪，少而集中的才是用错了）。

### 5 合并与抽查

`scripts/merge-findings.ps1 -Out .tmp/doc-scan/tables.md -Csv .tmp/doc-scan/findings.csv` 合成报告要用的明细表。

**自己抽查，每组至少一条**：打开文件与行号，看引文是否真的在那、判断是否成立。审查员报的假阳性不少——用户级 `~/.claude/skills/` 里存在的技能算有效引用，`DONE` 这类运行结束状态不是外环状态词。核不住的条目删掉，别让用户替你验证。

**判据**：报告里没有未核实的条目；抽查条数与结论写进报告。

### 6 写报告

路径 `docs/consistency-scan-<日期>.md`，结构固定：

```
状态行（日期、范围、扫了多少份、查出多少条）
1 怎么扫的
2 结论：最该先改的几件事（每件事带条数与文件数），以及哪几处归用户改、哪几处归架构师改
3 机器核对结论（链接、编号、术语三类）
4 明细表：按组分表，每行「位置 | 类别 | 矛盾点 | 改法」
```

路径一律用反引号写，不做成 Markdown 链接：报告在 `docs/` 下，链到 `docs/design/` 的相对写法很容易写错，下回扫描就变成它自己报失效。

**判据**：每条有位置与改法；结论里的事能对上明细里的条数。

## 边界

扫描只读。被扫的文件、CONTEXT.md、规则、ADR 都不动，唯一的新文件是报告。用户说「顺手改」时再按报告里的几件事分批改，一次一类，一类一次提交。

判断回到道理上：拿总图、路线图、术语表、代码现状当依据，不引 ADR 编号当论据，也不给「稳妥版」与「激进版」两套方案。

## 已知的坑

- PowerShell 把路径字符串数组管进 `Select-String`，会当成「要搜索的文本」，永远零命中；传 `Get-ChildItem` 的文件对象或 `-LiteralPath`。
- `git ls-files` 输出的中文路径带引号转义，不能直接喂给 `Select-String`。
- 脚本的 `-Root` 默认取当前目录，在仓库根运行；从别处运行要显式给 `-Root`。
- 报告里的示例位置用反引号，写成链接会给自己制造失效链接。

## 脚本

三个脚本都在 `scripts/`，PowerShell，从仓库根运行，输出 Markdown 表：

| 脚本 | 作用 |
| --- | --- |
| `check-links.ps1` | 全仓 md/html 链接可解析性核对，默认排除上面那批目录 |
| `term-audit.ps1` | _Avoid_ 词命中、九个状态词计数、旧编号分布 |
| `merge-findings.ps1` | 把各组 JSON 合成明细表与 CSV，字段大小写不敏感 |
