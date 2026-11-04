import re

import pytest
from test_rulefacts import rf_repo  # noqa: F401  复用：角色表、四张正本表、最小入口文件

EXTRA = """# 额外规则

`needs-triage` 由执行者加上。
`waiting` 只由架构师加上。
架构师循环不改 `ready-for-human`。
执行者认为文件超过上限不是 `needs-triage` 的理由。
`ready-for-human` 与 `waiting` 冲突时，执行者以 `waiting` 为准。
`waiting` 谁改成它，执行者见 [工作方式](workflow.md)「状态与标签」。
执行者领取时读 `docs/agents/workflow.md`「状态与标签」，标 `in-progress`。
执行者示例：把 `waiting` 改成 `in-progress` 的命令行见下。
没有词表里的东西的句子，写得再像规则也不算。
审查者的任务书写在代码块里。

执行者在下面这些情形标 `needs-triage`：

- 设计问题
- 规则矛盾
  续行也算

下面是名单：

- 执行者标 `waiting`
- 别的条目

| 事项 | 谁做 |
| --- | --- |
| `waiting` 的处理 | 执行者改成 `in-progress` |

```
执行者标 `waiting`。
```

文件超过上限不是 `needs-triage` 的理由。
设计说明与 ADR 冲突时以设计说明为准。
"""

YAML_SKILL = """---
name: yaml-skill
description: 执行者标 `waiting` 和 `needs-triage`
---

# yaml 技能

执行者标 `waiting`。
"""


@pytest.fixture
def scan_repo(rf_repo):
    rf_repo.write("docs/agents/extra.md", EXTRA)
    rf_repo.write(".claude/skills/yaml-skill/SKILL.md", YAML_SKILL)
    rf_repo.commit("粗筛用的脚手架文件")
    return rf_repo


def run(repo, *args):
    rc, out = repo.cli("rules", "scan", *args)
    assert rc == 0
    return out.replace(chr(13) + chr(10), chr(10))  # Windows 的标准输出把换行写成 CRLF


def candidates(out):
    """候选行：文件:行  [类别/句式，...]  句子；引导句的条目缩进在下面。"""
    rows = []
    for line in out.split("\n"):
        m = re.match(r"^(\S+):(\d+)  \[([^\]]*)\]  (.*)$", line)
        if m:
            rows.append((m.group(1), int(m.group(2)), m.group(3), m.group(4), []))
        elif line.startswith("    ") and rows:
            rows[-1][4].append(line.strip())
    return rows


def mine(out):
    return {text: (tag, items) for f, n, tag, text, items in candidates(out) if f == "docs/agents/extra.md"}


def test_every_class_has_sentences_and_the_shape_is_named(scan_repo):
    got = mine(run(scan_repo))
    # 解析成功：用真正的文法读成了原子，读成哪种句式写在类别后面
    assert got["`needs-triage` 由执行者加上"][0].startswith("解析成功/由谁")
    assert got["`waiting` 只由架构师加上"][0].startswith("解析成功/只由谁")
    assert got["架构师循环不改 `ready-for-human`"][0].startswith("解析成功/谁不")
    # 没有键、角色与动作词，句式形状对上就是候选（第 3 步补的）
    assert got["文件超过上限不是 `needs-triage` 的理由"][0].startswith("解析成功/清单一员") and "句式形状补入" in got["文件超过上限不是 `needs-triage` 的理由"][0]
    assert got["设计说明与 ADR 冲突时以设计说明为准"][0].startswith("解析成功/以谁为准") and "句式形状补入" in got["设计说明与 ADR 冲突时以设计说明为准"][0]
    # 像句式但文法不认：句子前面多了「执行者认为」（主语不是被比对的那个，不猜）；「以 X 为准」的 X 不是载体（不在载体词表里）
    assert got["执行者认为文件超过上限不是 `needs-triage` 的理由"][0].startswith("不是规则事实/-")
    assert got["`ready-for-human` 与 `waiting` 冲突时，执行者以 `waiting` 为准"][0].startswith("不是规则事实/-")
    # 已是引用：纯指路，指向正本文件，并且没有「由」「不」「为准」「理由」这些陈述规则的词，而且解析不了
    assert got["`waiting` 谁改成它，执行者见 [工作方式](workflow.md)「状态与标签」"][0].startswith("已是引用/-")
    assert got["执行者领取时读 `docs/agents/workflow.md`「状态与标签」，标 `in-progress`"][0].startswith("已是引用/-")
    # 不是规则事实：命中了词表，但既不是引用也不合句式
    assert got["执行者示例：把 `waiting` 改成 `in-progress` 的命令行见下"][0].startswith("不是规则事实/-")
    assert got["审查者的任务书写在代码块里"][0].startswith("不是规则事实/-")
    # 没有键（词表里的名字）的句子不是候选：句子里有「写」，但没有任何词表里的名字
    assert "没有词表里的东西的句子，写得再像规则也不算" not in got


def test_summary_counts_add_up_and_split_narrow_from_wide(scan_repo):
    out = run(scan_repo)
    rows = candidates(out)
    assert "候选 18 条\n三类：已是引用 4，解析成功 5，不是规则事实 9\n" in out
    assert "窄口径命中 12（其中表格格子 1），宽口径命中 18（含窄口径，其中表格格子 1，涉及 1 行）" in out
    assert sum(1 for r in rows if "，窄" in r[2]) == 12
    # 标签快照里的 `needs-triage`、`waiting` 是窄口径的键；只靠正本表格首列的键（`in-progress`、`ready-for-human`）是宽口径
    got = mine(out)
    assert "，窄" in got["`needs-triage` 由执行者加上"][0]
    assert "，宽" in got["执行者领取时读 `docs/agents/workflow.md`「状态与标签」，标 `in-progress`"][0]
    assert "，宽" in got["架构师循环不改 `ready-for-human`"][0]
    # 按文件的计数表：文件、总数、引用、解析、非规则、窄、宽
    assert "\ndocs/agents/extra.md\t15\t2\t5\t8\t11\t15\n" in out
    assert "\nAGENTS.md\t1\t1\t0\t0\t0\t1\n" in out


def test_lead_in_carries_the_list_and_continuation_under_it(scan_repo):
    got = mine(run(scan_repo))
    tag, items = got["执行者在下面这些情形标 `needs-triage`："]
    assert [i.split(": ", 1)[1] for i in items] == ["- 设计问题", "- 规则矛盾", "续行也算"]
    assert not any(t in got for t in ("设计问题", "规则矛盾"))
    # 引导句自己没有键、角色、动作词，它下面的条目合起来才命中：条目也带在下面
    tag, items = got["下面是名单："]
    assert [i.split(": ", 1)[1] for i in items] == ["- 执行者标 `waiting`", "- 别的条目"]
    lines = {r[1] for r in candidates(run(scan_repo)) if r[0] == "docs/agents/extra.md"}
    assert not lines & {22, 23}  # 条目不再单独成为候选


def test_canon_rows_are_skipped_but_other_table_cells_are_scanned(scan_repo):
    out = run(scan_repo)
    # 正本表格的行是正本，不是复述：「有人在做 | 执行者领取时」那一行不出现
    assert "有人在做" not in out and not [r for r in candidates(out) if r[0] == "docs/agents/workflow.md"]
    # 别的表格一格一句；键靠所在行的首列补上
    got = mine(out)
    tag, _ = got["执行者改成 `in-progress`"]
    assert "表格" in tag


def test_code_block_is_scanned_and_marked(scan_repo):
    rows = [r for r in candidates(run(scan_repo)) if r[0] == "docs/agents/extra.md" and "代码块" in r[2]]
    assert [r[3] for r in rows] == ["执行者标 `waiting`"]


def test_yaml_head_is_skipped(scan_repo):
    rows = [r for r in candidates(run(scan_repo)) if r[0] == ".claude/skills/yaml-skill/SKILL.md"]
    # 头里的 description 同样是一句「执行者标 waiting」，不扫；正文里的才算，行号 8
    assert [(r[1], r[3]) for r in rows] == [(8, "执行者标 `waiting`")]


def test_same_input_gives_byte_identical_output_and_sample_is_seeded(scan_repo):
    a, b = run(scan_repo), run(scan_repo)
    assert a == b
    s1, s2 = run(scan_repo, "--sample", "4"), run(scan_repo, "--sample", "4")
    assert s1 == s2
    picked = candidates(s1)
    assert len(picked) == 4 and "抽样 4 条" in s1
    # 抽样出来的候选是全量候选的子集，格式相同，顺序不变
    full = candidates(a)
    assert all(p in full for p in picked)
    assert [full.index(p) for p in picked] == sorted(full.index(p) for p in picked)
    # 抽得比候选多，就是全部
    assert len(candidates(run(scan_repo, "--sample", "9999"))) == len(full)


def test_missing_label_snapshot_is_said_and_exit_code_stays_zero(scan_repo):
    (scan_repo.path / ".doc-index" / "labels.json").unlink()
    out = run(scan_repo)
    assert "没有标签快照" in out
    # 没有快照，`needs-triage` 不再是窄口径的键，但它是正本表格的键，句子照样是候选
    assert "，宽" in mine(out)["`needs-triage` 由执行者加上"][0]



def test_inline_colon_carries_the_semicolon_items_and_a_shaped_lead_in_is_added(scan_repo):
    # AGENTS.md「请架构师处理」那一段的形状：句中冒号引出「；」分开的几项，下一行又是一句不含键与角色的「不是…的理由：」
    scan_repo.write(
        "docs/agents/lead.md",
        "# 交回\n\n请架构师处理：只有两种情形交回 `needs-triage`：设计问题；规则矛盾。\n下面这些不是交回的理由：\n文件超过上限；改了名。\n",
    )
    scan_repo.commit("引导句")
    out = run(scan_repo)
    rows = [r for r in candidates(out) if r[0] == "docs/agents/lead.md"]
    assert [r[1] for r in rows] == [3, 4]
    assert rows[0][4] == ["3: 规则矛盾"]  # 句中冒号：同一句里「；」后面的分句是它的条目，不再单独成句
    assert rows[1][2].startswith("解析成功/清单一员") and "形状补入" in rows[1][2]
    assert rows[1][4] == ["5: 文件超过上限；改了名。"]
    assert "引导句只靠句式形状补入（没有键、角色或动作词）1" in out
