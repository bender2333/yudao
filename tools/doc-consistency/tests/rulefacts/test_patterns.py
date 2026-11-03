"""规则事实线第 3 步：八种句式的解析。用 rf_repo 夹具（test_rulefacts.py）加我们写的复述文件，真文法、真 clingo、真文件。"""

import pytest
from test_rulefacts import ALIAS_ROWS, TABLE1 as OLD_TABLE1, WF, WORKFLOW, rf_repo  # noqa: F401  复用：角色表、四张正本表、最小入口文件

from doc_consistency.rulefacts import compare

RESTATE = "docs/agents/restate.md"
KEY_ZONGTU = "系统的形状、三环、缝"
KEY_FKJ = "一个方框或一道缝怎么做"
KEY_WHY = "为什么这样定"
KEY_RULE = "规则"
KEY_INTENT = "意图：目的、判据、基础规则的意思"
KEY_CODE = "代码与测试"
STUCK_ENV = "执行环境、要用户提供的条件"
STUCK_DESIGN = "needs-triage 的理由（第 4 节）"
EVENT_RULE = "改规则、CI 工作流"

# 第 1 节「事实放在哪」补成几行：「位置」一格里的载体名和反引号路径当键的别名（总图、设计说明、ADR、需求记录、CLAUDE.md、AGENTS.md、harness/）；
# 「谁定」列有用户；「意图：…」写成「意图」也认；最后两行是引用格与机器，和最小夹具里的一样
TABLE1 = (
    "| 事实 | 位置 | 谁定 | 谁改 |\n| --- | --- | --- | --- |\n"
    "| 系统的形状、三环、缝 | 总图 `docs/architecture.html`、画面总图 | 用户 | 总架构师 |\n"
    "| 一个方框或一道缝怎么做 | 设计说明 `docs/design/`（[设计说明规范](design-spec.md)） | | 子架构师 |\n"
    "| 为什么这样定 | 需求记录、ADR、调研、原型 | | 架构师 |\n"
    "| 规则 | `CLAUDE.md`、`AGENTS.md`、`docs/agents/` | 用户 | 总架构师 |\n"
    "| 意图：目的、判据、基础规则的意思 | [基础规则](../foundation-rules.md) | 用户 | 总架构师 |\n"
    "| 代码与测试 | `harness/`、`client/`、`evals/` | | 执行者 |\n"
    "| 每次状态变化的证据 | 那张工单上一条带前缀的评论 | | 按第 5 节 |\n"
    "| 代码达到合同的证据 | PR 与 CI | | 执行者、审查者、CI |\n"
    + ALIAS_ROWS
)
# 证据评论表补一行任何角色都能写的，让「用户」出现在正本的值里（用户走样那一类要用）
OLD_ROW5 = "| `TRIAL:` | `TRIAL: <达到 \\| 复盘 \\| 试用>` | 架构师 |\n"
NEW_ROW5 = OLD_ROW5 + "| `HANDOFF:` | 做到哪里 | 任何角色 |\n"


def rich(repo):
    """把第 1 节表补成有载体别名的四行，证据评论表补一行 HANDOFF:。"""
    text = WORKFLOW.replace(OLD_TABLE1, TABLE1).replace(OLD_ROW5, NEW_ROW5)
    assert text != WORKFLOW and TABLE1 in text and NEW_ROW5 in text
    repo.write(WF, text)
    return repo


def restate(repo, *lines, name=RESTATE):
    """写一份只有复述的脚手架文件（一句一行），提交，返回比对结果。"""
    repo.write(name, "# 复述\n\n" + "\n".join(lines) + "\n")
    repo.commit("复述")
    return compare.check(repo.path)


def by_text(chk, text):
    return [g for g in chk.groups if g.text == text]


def atoms(chk, text):
    gs = by_text(chk, text)
    assert gs, f"没解析成功：{text}"
    return [a for g in gs for a in g.atoms]


def shapes(chk, text):
    return [g.shape for g in by_text(chk, text)]


def test_eight_shapes_each_read_into_atoms(rf_repo):
    chk = restate(
        rich(rf_repo),
        # 由谁
        "`needs-triage` 由执行者加上",
        "总图由总架构师改",
        # 只由谁
        "总图只由总架构师改",
        "`waiting` 只由架构师加上",
        # 谁不
        "架构师循环不改总图",
        "审查者不推送",
        "子架构师不改总图",
        # 是或不是清单一员
        "文件超上限不是 `needs-triage` 的理由",
        "设计问题是 `needs-triage` 的理由",
        # 以谁为准
        "设计说明与 ADR 冲突时以设计说明为准",
        "总图和设计说明不一致时，以总图为准",
        # 在场可否
        "用户在场时总架构师可以改规则",
        "用户不在场时架构师循环不可以改规则",
        # 交给
        "执行环境的问题交给用户",
        "`needs-triage` 的理由交回架构师",
        # 穷尽清单
        "只有设计问题、规则矛盾是 `needs-triage` 的理由",
        "只有两种情形交回：设计问题；规则矛盾",
    )
    assert atoms(chk, "`needs-triage` 由执行者加上") == [("says", "needs-triage", "由谁改成", "solo 执行者")]
    assert atoms(chk, "总图由总架构师改") == [("says", KEY_ZONGTU, "由谁改", "总架构师")]
    assert atoms(chk, "总图只由总架构师改") == [("says", KEY_ZONGTU, "由谁改", "总架构师"), ("only", KEY_ZONGTU, "由谁改", "总架构师")]
    assert ("only", "waiting", "由谁改成", "架构师循环") in atoms(chk, "`waiting` 只由架构师加上")
    assert atoms(chk, "架构师循环不改总图") == [("says_not", KEY_ZONGTU, "由谁改", "架构师循环")]
    assert atoms(chk, "审查者不推送") == [("says_not", "推送", "做", "审查者")]
    assert atoms(chk, "子架构师不改总图") == [("says_not", KEY_ZONGTU, "由谁改", "子架构师")]
    assert atoms(chk, "文件超上限不是 `needs-triage` 的理由") == [("not_member", "needs-triage", "文件超上限")]
    assert atoms(chk, "设计问题是 `needs-triage` 的理由") == [("member", "needs-triage", "设计问题")]
    assert atoms(chk, "设计说明与 ADR 冲突时以设计说明为准") == [("prevails", "设计说明", "ADR")]
    assert atoms(chk, "总图和设计说明不一致时，以总图为准") == [("prevails", "总图", "设计说明")]
    assert atoms(chk, "用户在场时总架构师可以改规则") == [("may", "总架构师", EVENT_RULE, "在场", "可以")]
    assert atoms(chk, "用户不在场时架构师循环不可以改规则") == [("may", "架构师循环", EVENT_RULE, "不在场", "不可以")]
    assert atoms(chk, "执行环境的问题交给用户") == [("handoff", STUCK_ENV, "用户")]
    assert {a[2] for a in atoms(chk, "`needs-triage` 的理由交回架构师")} == {"总架构师", "子架构师", "架构师循环"}
    assert atoms(chk, "只有设计问题、规则矛盾是 `needs-triage` 的理由") == [
        ("only_members", "needs-triage", "设计问题"),
        ("only_members", "needs-triage", "规则矛盾"),
        ("closed", "needs-triage"),
    ]
    assert atoms(chk, "只有两种情形交回：设计问题；规则矛盾") == [
        ("only_members", "needs-triage", "设计问题"),
        ("only_members", "needs-triage", "规则矛盾"),
        ("closed", "needs-triage"),
    ]
    # 每种句式至少两句
    got = {}
    for g in chk.groups:
        got[g.shape] = got.get(g.shape, 0) + 1
    assert all(got.get(s, 0) >= 2 for s in ("由谁", "只由谁", "谁不", "清单一员", "以谁为准", "在场可否", "交给", "穷尽清单")), got


def test_group_names_expand_before_atoms_are_made(rf_repo):
    chk = restate(rich(rf_repo), "`waiting` 由架构师加上", "`waiting` 由子架构师与架构师循环加上", "`ready-for-human` 由任何角色加上")
    assert [a[3] for a in atoms(chk, "`waiting` 由架构师加上")] == ["总架构师", "子架构师", "架构师循环"]
    assert [a[3] for a in atoms(chk, "`waiting` 由子架构师与架构师循环加上")] == ["子架构师", "架构师循环"]
    assert len(atoms(chk, "`ready-for-human` 由任何角色加上")) == 6  # roles.json 的「任何角色」列了六个，agent 试用者不在其中
    # 别名：执行者 -> solo 执行者；有空格的角色名与汉字连写也认
    chk = restate(rf_repo, "`in-progress` 由 solo 执行者加上", "`in-progress` 由执行者加上", name="docs/agents/restate2.md")
    assert atoms(chk, "`in-progress` 由 solo 执行者加上") == atoms(chk, "`in-progress` 由执行者加上") == [("says", "in-progress", "由谁改成", "solo 执行者")]


def test_qualifiers_and_parentheses_become_notes_not_atoms(rf_repo):
    chk = restate(
        rich(rf_repo),
        "`in-progress` 由执行者领取时加上",
        "`ready-for-human` 由执行者在合并之前加上",
        "总图只由总架构师改（见第 3 节）",
    )
    g = by_text(chk, "`in-progress` 由执行者领取时加上")[0]
    assert g.atoms == [("says", "in-progress", "由谁改成", "solo 执行者")] and g.notes == ["领取时"]
    g = by_text(chk, "`ready-for-human` 由执行者在合并之前加上")[0]
    assert g.atoms == [("says", "ready-for-human", "由谁改成", "solo 执行者")] and g.notes == ["在合并之前"]
    g = by_text(chk, "总图只由总架构师改（见第 3 节）")[0]
    assert g.shape == "只由谁" and g.notes == ["见第 3 节"]
    rc, out = rf_repo.cli("rules", "check")
    assert "附注 3 条" in out


def test_sentences_without_a_subject_are_not_read_and_not_guessed(rf_repo):
    lines = [
        "只由总架构师改",  # 键缺失
        "不自己加方框或缝",  # 祈使句
        "你不改总图",  # 「你」不是角色
        "由执行者加上",  # 键缺失
        "可以改规则",  # 没有主语和在场与否
        "执行者认为文件超过上限不是 `needs-triage` 的理由",  # 前面多出的话带了主语
        "冒烟层由 CI 跑",  # 冒烟层不是任何正本表的键：词汇封闭（集成层现在是第 3 节测试分层表的键，读得了）
        "`needs-triage` 由谁加上",  # 谁不是角色
    ]
    chk = restate(rich(rf_repo), *lines)
    assert not [g for g in chk.groups if g.file == RESTATE], [(g.text, g.atoms) for g in chk.groups if g.file == RESTATE]
    # 它们照样是候选，也就是以后钩子要提醒的「像在说规则但解析不了」
    unparsed = {h.text for h in chk.unparsed() if h.file == RESTATE}
    assert {"只由总架构师改", "由执行者加上", "执行者认为文件超过上限不是 `needs-triage` 的理由", "冒烟层由 CI 跑"} <= unparsed


def test_machine_subjects_are_named_but_are_not_roles(rf_repo):
    chk = restate(rich(rf_repo), "`DELIVERY:` 由脚本写", "`REVIEW:` 由 CI 写", "总图只由钩子改", "单元层由 CI 在每次推送时运行")
    assert atoms(chk, "`DELIVERY:` 由脚本写") == [("says", "DELIVERY:", "由谁写", "脚本")]
    assert atoms(chk, "总图只由钩子改")[0] == ("says", KEY_ZONGTU, "由谁改", "钩子")
    # 机器主语的句子算候选，不论有没有键、角色和动作词；键不在词表里就解析不了
    rc, out = rf_repo.cli("rules", "scan")
    line = next(ln for ln in out.replace("\r\n", "\n").split("\n") if "单元层由 CI 在每次推送时运行" in ln)
    assert "机器主语补入" in line and "不是规则事实" in line
    # 机器不是角色：不在 roles.json 里，不进阅读范围
    assert "脚本" not in chk.canon.roles and "CI" not in chk.canon.roles


def test_carrier_names_in_the_location_column_are_aliases_of_the_key(rf_repo):
    chk = restate(
        rich(rf_repo),
        "总图由总架构师改",
        "设计说明由子架构师改",
        "ADR 由架构师改",
        "需求记录由架构师改",
        "CLAUDE.md 由总架构师改",
        "AGENTS.md 由总架构师改",
        "术语表由子架构师改",  # 术语表是载体，但第 1 节的位置一格没有它：不是键
    )
    assert atoms(chk, "总图由总架构师改")[0][1] == KEY_ZONGTU
    assert atoms(chk, "设计说明由子架构师改")[0][1] == KEY_FKJ
    assert atoms(chk, "ADR 由架构师改")[0][1] == atoms(chk, "需求记录由架构师改")[0][1] == KEY_WHY
    assert atoms(chk, "CLAUDE.md 由总架构师改")[0][1] == atoms(chk, "AGENTS.md 由总架构师改")[0][1] == KEY_RULE
    assert not by_text(chk, "术语表由子架构师改")
    # 正本里的键本身也认
    chk = restate(rf_repo, "规则由总架构师改", name="docs/agents/restate2.md")
    assert atoms(chk, "规则由总架构师改") == [("says", KEY_RULE, "由谁改", "总架构师")]


def test_prevails_only_knows_carriers_and_can_be_chained_to_a_carrier_subject(rf_repo):
    chk = restate(
        rich(rf_repo),
        "设计说明与 ADR 冲突时以设计说明为准",
        "`waiting` 与 `ready-for-human` 冲突时以 `waiting` 为准",  # 数据与状态的优先级是流程，不是载体
        "以账本为准",
        "总图只由总架构师改，与设计说明不一致时以设计说明为准",  # 前一个分句的主语是载体
        "与设计说明不一致时以设计说明为准",  # 没有前一个载体：不猜
        "设计说明由子架构师改，与 `waiting` 不一致时以 `waiting` 为准",
    )
    assert atoms(chk, "设计说明与 ADR 冲突时以设计说明为准") == [("prevails", "设计说明", "ADR")]
    assert not by_text(chk, "`waiting` 与 `ready-for-human` 冲突时以 `waiting` 为准") and not by_text(chk, "以账本为准")
    gs = by_text(chk, "总图只由总架构师改，与设计说明不一致时以设计说明为准")
    assert [g.shape for g in gs] == ["只由谁", "以谁为准"] and gs[1].atoms == [("prevails", "设计说明", "总图")]
    assert not by_text(chk, "与设计说明不一致时以设计说明为准")
    assert [g.shape for g in by_text(chk, "设计说明由子架构师改，与 `waiting` 不一致时以 `waiting` 为准")] == ["由谁"]


def test_lists_in_lead_in_lines_and_after_inline_colons_are_read(rf_repo):
    rf_repo.write(
        RESTATE,
        "# 复述\n\n下面这些不是交回的理由：\n手写文件超过上限（记日记，一轮做不完按上一条分多轮）；要改「只改」以外的文件。\n\n"
        "请架构师处理：只有两种情形交回，写一条说明，不绕过：设计问题；规则矛盾。\n\n"
        "下面这些是 `needs-triage` 的理由：\n\n- 设计问题\n- 新报告的问题\n",
    )
    rf_repo.commit("复述")
    chk = compare.check(rf_repo.path)
    mine = [g for g in chk.groups if g.file == RESTATE]
    assert [g.shape for g in mine] == ["清单一员", "穷尽清单", "清单一员"]
    assert [a for a in mine[0].atoms] == [("not_member", "needs-triage", "手写文件超过上限"), ("not_member", "needs-triage", "要改只改以外的文件")]
    assert mine[0].notes == ["记日记，一轮做不完按上一条分多轮"]
    assert mine[1].atoms == [("only_members", "needs-triage", "设计问题"), ("only_members", "needs-triage", "规则矛盾"), ("closed", "needs-triage")]
    assert mine[2].atoms == [("member", "needs-triage", "设计问题"), ("member", "needs-triage", "新报告的问题")]


def test_verbs_map_to_canon_facts_from_the_json_table_not_from_code(rf_repo):
    chk = restate(
        rich(rf_repo),
        "`needs-triage` 由执行者加上",  # 加上 -> 由谁改成
        "`DELIVERY:` 由执行者写",  # 写 -> 由谁写
        "总图由总架构师改",  # 改 -> 由谁改
        "`in-progress` 由执行者改",  # 改 -> 这个键正本里有的是「由谁改成」
        "实现完成由执行者负责",  # 负责 -> 由谁负责
        "实现完成由执行者做",  # 做 -> 由谁负责
    )
    facts = {g.text: g.atoms[0][2] for g in chk.groups if g.file == RESTATE}
    assert facts == {
        "`needs-triage` 由执行者加上": "由谁改成",
        "`DELIVERY:` 由执行者写": "由谁写",
        "总图由总架构师改": "由谁改",
        "`in-progress` 由执行者改": "由谁改成",
        "实现完成由执行者负责": "由谁负责",
        "实现完成由执行者做": "由谁负责",
    }


def test_who_decides_verb_maps_to_the_decided_by_fact_and_is_compared_with_section_one(rf_repo):
    chk = restate(
        rich(rf_repo),
        "总图只由用户定",  # 与第 1 节「谁定」一致
        "总图只由总架构师定",  # 谁定只有用户：多说，也漏了用户
        "规则由用户定",
        "意图只由用户定",  # 键写成冒号前的「意图」
    )
    assert atoms(chk, "总图只由用户定") == [("says", KEY_ZONGTU, "由谁定", "用户"), ("only", KEY_ZONGTU, "由谁定", "用户")]
    assert atoms(chk, "意图只由用户定")[0] == ("says", KEY_INTENT, "由谁定", "用户")
    assert shapes(chk, "规则由用户定") == ["由谁"]
    got = [(c.kind, chk.by_node[c.nodes[0]].text) for c in chk.conflicts]
    assert got == [("extra", "总图只由总架构师定"), ("only_wrong", "总图只由总架构师定")]
    assert "由谁定" in chk.conflicts[0].why and "用户" in chk.conflicts[0].why
    # 用户只定与确认：写成用户改，仍作为走样报出；写成用户定不算
    chk = restate(rich(rf_repo), "总图由用户改", "总图由用户定", name="docs/agents/restate2.md")
    assert [(c.kind, chk.by_node[c.nodes[0]].text) for c in chk.conflicts if c.kind == "user_hands_on"] == [("user_hands_on", "总图由用户改")]


def test_paths_in_the_location_column_are_aliases_of_the_key(rf_repo):
    chk = restate(
        rich(rf_repo),
        "架构师不改 `harness/` 的代码与测试",  # 载体的键：两边是同一行
        "solo 执行者不改 `harness/` 的代码与测试",  # 正本里 solo 执行者改：矛盾
        "代码与测试只由执行者改",
        "`client/` 由执行者改",
        "`docs/design/` 由子架构师改",
        "`docs/architecture.html` 只由总架构师改",
        "`docs/agents/` 由总架构师改",
        "架构师不改总图的代码与测试",  # 「的」两边不是同一行的键：不读，不猜
        "架构师不改 `harness/` 的设计说明",  # 同上
        "架构师不改 `docs/other/`",  # 不在位置一格里的路径：不是键
    )
    assert {a[1:3] for a in atoms(chk, "架构师不改 `harness/` 的代码与测试")} == {(KEY_CODE, "由谁改")}
    assert [a[3] for a in atoms(chk, "架构师不改 `harness/` 的代码与测试")] == ["总架构师", "子架构师", "架构师循环"]
    assert atoms(chk, "`client/` 由执行者改") == [("says", KEY_CODE, "由谁改", "solo 执行者")]
    assert atoms(chk, "`docs/design/` 由子架构师改") == [("says", KEY_FKJ, "由谁改", "子架构师")]
    assert atoms(chk, "`docs/architecture.html` 只由总架构师改")[0] == ("says", KEY_ZONGTU, "由谁改", "总架构师")
    assert atoms(chk, "`docs/agents/` 由总架构师改") == [("says", KEY_RULE, "由谁改", "总架构师")]
    for s in ("架构师不改总图的代码与测试", "架构师不改 `harness/` 的设计说明", "架构师不改 `docs/other/`"):
        assert not by_text(chk, s), s
    # 比对：对到第 1 节「代码与测试」那一行，只有 solo 执行者那句矛盾
    assert [(c.kind, chk.by_node[c.nodes[0]].text, c.rows) for c in chk.conflicts] == [
        ("denied", "solo 执行者不改 `harness/` 的代码与测试", [(KEY_CODE, "由谁改")])
    ]


def test_machines_in_canon_are_compared_like_roles(rf_repo):
    # 第 1 节「代码达到合同的证据」谁改里有 CI：复述写 CI 一致，写钩子是多说，写「CI 不改」是矛盾
    chk = restate(rich(rf_repo), "代码达到合同的证据由 CI 改", "代码达到合同的证据由钩子改", "CI 不改代码达到合同的证据")
    assert [(c.kind, chk.by_node[c.nodes[0]].text) for c in chk.conflicts] == [
        ("extra", "代码达到合同的证据由钩子改"),
        ("denied", "CI 不改代码达到合同的证据"),
    ]
    assert atoms(chk, "代码达到合同的证据由 CI 改") == [("says", "代码达到合同的证据", "由谁改", "CI")]
