"""规则事实线第 6 步收尾：测试分层表、「冲突时以谁为准」表（canon_prevails）、键别名与角色别名。
夹具是 test_rulefacts.py 的 WORKFLOW、EVIDENCE（里面已有新表与新行），真文法、真 clingo、真文件。"""

import re

import pytest
from test_compare import CANON_EDGES
from test_patterns import RESTATE, restate, rich
from test_rulefacts import T7, T11, TAE, TAE3, WF, facts, page_json, rf_repo  # noqa: F401

from doc_consistency.rulefacts import canon as rf

KEY_ISSUE = "工单正文、依赖、子工单"
KEY_MS = "阶段工单与里程碑：建、关、改名"
KEY_PR = "合并 PR 与推送 main"
KEY_TRIAL = "试用结论与试用工单、里程碑的关闭"
KEY_SEAM = "系统的形状、三环、缝，缝的已定未定"


# ---------- 测试分层表：层 × 谁跑 ----------


def test_test_layer_table_reads_who_runs_into_the_responsible_fact(rf_repo):
    c = rf.read_canon(rf_repo.path)
    got = facts(c, TAE3)
    # 「谁跑」读成「由谁负责」，和结论表的「负责角色」同一个事实名；机器（CI）读成值；合称「架构师」展开
    assert {v for k, f, v in got if k == "单元层、模块层"} == {"CI"}
    assert {v for k, f, v in got if k.startswith("与改动相关的测试文件")} == {"solo 执行者", "审查者"}
    assert {v for k, f, v in got if k == "集成层"} == {"CI", "solo 执行者", "总架构师", "子架构师", "架构师循环"}
    assert {f for k, f, v in got} == {"由谁负责"}
    # 括号里的限定进附注，不进事实；「什么时候」一列不是事实
    texts = {x.text for x in c.notes if x.table == TAE3}
    assert texts == {"solo 执行者（`touches-core` 合并之前）", "架构师（试用之前）"}
    assert not any("合并之前" in v or "每次推送" in v for k, f, v in got)
    # 机器不是角色：规则图里没有 CI 的节点；这张表没有读不出的格子
    assert not [x for x in c.unparsed if x.table == TAE3]


def test_test_layer_table_is_listed_by_rules_canon_and_drawn_in_the_graph(rf_repo):
    rc, out = rf_repo.cli("rules", "canon")
    assert re.search(r"== .*3\. 测试分层的生效条件 > 表1（键列「层」，8 条） ==", out)
    assert "单元层、模块层 / 由谁负责 / CI" in out
    rf_repo.cli("rules", "view")
    g = page_json(rf_repo)["graph"]
    edges = {(e["source"], e["fact"], e["target"]) for e in g["edges"]}
    assert ("测试层:集成层", "由谁负责", "角色:solo 执行者") in edges and ("测试层:集成层", "由谁负责", "角色:总架构师") in edges
    assert not any("CI" in e["target"] for e in g["edges"] if e["source"].startswith("测试层:"))


# ---------- 新行自动生效 ----------


def test_new_rows_are_read_without_any_change_to_the_tool(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 第 7 节新写的四行交给用户
    for stuck in ("同一张工单分诊满两次", "薄片的缺陷修了两轮还在", "后台长运行重跑一次仍失败", "要放宽验收"):
        assert (stuck, "交给", "用户") in facts(c, T7), stuck
    # 验收证据第 1 节新写的两行
    assert {v for k, f, v in facts(c, TAE) if k == "阶段结束核对"} == {"总架构师"}
    assert {v for k, f, v in facts(c, TAE) if k == "父工单验收与关闭"} == {"子架构师", "架构师循环"}
    # 第 1 节「工单正文」格里的 solo 执行者读成值，「solo 只建缺陷工单」进附注
    assert {v for k, f, v in facts(c) if (k, f) == (KEY_ISSUE, "由谁改")} == {"总架构师", "子架构师", "架构师循环", "solo 执行者"}
    assert any(x.key == KEY_ISSUE and "solo 只建缺陷工单" in x.text for x in c.notes)
    assert [x for x in c.unparsed if x.key in (KEY_ISSUE, "阶段结束核对", "父工单验收与关闭")] == []


# ---------- 冲突时以谁为准：canon_prevails ----------


def test_precedence_table_is_read_into_canon_prevails_and_the_odd_row_into_notes(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert {(p.winner, p.loser) for p in c.prevails} == CANON_EDGES and len(c.prevails) == 7
    assert all(p.table == T11 and p.file == WF for p in c.prevails)
    # 「D38 与其他需求记录」：其他需求记录读成载体「需求记录」；「`CLAUDE.md` 与 `AGENTS.md`（执行时）」括号进附注
    assert ("D38", "需求记录") in {(p.winner, p.loser) for p in c.prevails}
    notes = [x.text for x in c.notes if x.table == T11]
    assert notes == ["CLAUDE.md 与 AGENTS.md（执行时）", "不定优先级：交回（第 4 节 `needs-triage` 的理由）"]
    # 值不是两边之一：不出事实，也不算读不出
    assert not any("子工单" in (p.winner, p.loser) for p in c.prevails) and not [x for x in c.unparsed if x.table == T11]
    # 这张表不出普通事实，也不进「键」：规则图和矩阵里没有它
    assert facts(c, T11) == set()
    rc, out = rf_repo.cli("rules", "canon")
    assert "以谁为准 7 条" in out and "总图与设计说明 / 以谁为准 / 总图 优先于 设计说明" in out
    assert "D38 与其他需求记录 / 以谁为准 / D38 优先于 需求记录" in out


def test_precedence_row_with_an_unknown_side_is_reported_as_unreadable_not_guessed(rf_repo):
    rf_repo.write(WF, rf_repo.read(WF).replace("| 总图与画面总图 | 总图 |", "| 总图与白板 | 总图 |"))
    rf_repo.commit("两边有一个不是载体")
    c = rf.read_canon(rf_repo.path)
    assert len(c.prevails) == 6 and [(x.key, x.column) for x in c.unparsed if x.table == T11] == [("总图与白板", "以谁为准")]


def test_a_value_outside_the_two_sides_is_a_note_only(rf_repo):
    rf_repo.write(WF, rf_repo.read(WF).replace("| 总图与术语表 | 总图 |", "| 总图与术语表 | ADR |"))
    rf_repo.commit("值不是两边之一")
    c = rf.read_canon(rf_repo.path)
    assert ("总图", "术语表") not in {(p.winner, p.loser) for p in c.prevails} and len(c.prevails) == 6
    assert "ADR" in [x.text for x in c.notes if x.table == T11]


def test_restated_precedence_reversed_against_the_canon_is_reported(rf_repo):
    chk = restate(
        rich(rf_repo),
        "总图和设计说明不一致时以设计说明为准",  # 正本：总图
        "需求记录和 D38 冲突时以需求记录为准",  # 其他需求记录读成需求记录；正本 D38
        "`CLAUDE.md` 与 `AGENTS.md` 冲突时以 `CLAUDE.md` 为准",  # 正本：AGENTS.md
        "总图和术语表不一致时以总图为准",  # 与正本一致
        "设计说明与 ADR 冲突时以设计说明为准",  # 与正本一致
    )
    wrong = [c for c in chk.conflicts if c.kind == "prevails_wrong"]
    assert sorted(chk.by_node[c.nodes[0]].text for c in wrong) == sorted(
        ["总图和设计说明不一致时以设计说明为准", "需求记录和 D38 冲突时以需求记录为准", "`CLAUDE.md` 与 `AGENTS.md` 冲突时以 `CLAUDE.md` 为准"]
    )
    assert len(chk.conflicts) == 3  # 一致的两句不报，也没有成环
    c = next(c for c in wrong if "设计说明为准" in chk.by_node[c.nodes[0]].text)
    assert re.fullmatch(rf"{WF}:\d+  总图与设计说明：总图优先于设计说明", c.canon[0])
    assert "复述说设计说明优先于总图" in c.why and "正本是总图优先于设计说明" in c.why
    rc, out = rf_repo.cli("rules", "check")
    out = out.replace("\r\n", "\n")
    assert "== 以谁为准与正本相反：3 条 ==" in out and "以谁为准与正本相反 3" in out
    assert f"复述 {RESTATE}:3  总图和设计说明不一致时以设计说明为准" in out
    assert re.search(rf"  正本 {WF}:\d+  总图与设计说明：总图优先于设计说明", out) and "  差在哪：复述说设计说明优先于总图" in out


def test_restated_precedence_the_canon_does_not_pair_is_not_reported(rf_repo):
    chk = restate(
        rich(rf_repo),
        "基础规则与共同规则冲突时以基础规则为准",  # 这一对正本里没有
        "子工单和设计说明冲突时以子工单为准",  # 正本这一行是「不定优先级」，只有附注
        "总图和 ADR 不一致时以 ADR 为准",  # 总图与 ADR 正本里没有
    )
    assert chk.conflicts == [] and len(chk.groups) == 3


def test_the_precedence_graph_draws_canon_edges_solid_and_restated_edges_dashed(rf_repo):
    chk = restate(rich(rf_repo), "总图和设计说明不一致时以设计说明为准", "总图和术语表不一致时以总图为准")
    rf_repo.cli("rules", "view")
    data = page_json(rf_repo)
    edges = data["prec"]["edges"]
    assert {(e["source"], e["target"]) for e in edges if e["canon"]} == CANON_EDGES
    restated = {(e["source"], e["target"]): e["cyc"] for e in edges if not e["canon"]}
    # 复述的边：与正本相反的标红，一致的不红；正本的边都不红
    assert restated == {("设计说明", "总图"): True, ("总图", "术语表"): False}
    assert not any(e["cyc"] for e in edges if e["canon"])
    page = (rf_repo.path / ".tmp/doc-index/rulefacts.html").read_text(encoding="utf-8")
    assert "edge[canon = 0]" in page and "'line-style': 'dashed'" in page and "实线是正本" in page and len(chk.conflicts) == 1


# ---------- 键别名与角色别名 ----------


def test_key_aliases_read_restatements_that_use_a_shortened_key(rf_repo):
    chk = restate(
        rich(rf_repo),
        "缝的已定未定只由总架构师改",
        "缝的已定、未定由总架构师改",
        "试用结论由架构师改",
        "试用工单由架构师改",
        "里程碑的关闭由架构师改",
        "工单正文由架构师改",
        "依赖由架构师改",
        "子工单由架构师改",
        "缺陷工单由 solo 执行者改",
        "阶段工单由总架构师改",
        "里程碑由总架构师改",
        "合并由 solo 执行者改",
        "推送由 solo 执行者改",
    )

    def key_of(text):
        return {a[1] for g in chk.groups if g.text == text for a in g.atoms}

    assert key_of("缝的已定未定只由总架构师改") == key_of("缝的已定、未定由总架构师改") == {KEY_SEAM}
    assert key_of("试用结论由架构师改") == key_of("试用工单由架构师改") == key_of("里程碑的关闭由架构师改") == {KEY_TRIAL}
    assert {k for t in ("工单正文由架构师改", "依赖由架构师改", "子工单由架构师改", "缺陷工单由 solo 执行者改") for k in key_of(t)} == {KEY_ISSUE}
    assert key_of("阶段工单由总架构师改") == key_of("里程碑由总架构师改") == {KEY_MS}
    assert key_of("合并由 solo 执行者改") == key_of("推送由 solo 执行者改") == {KEY_PR}
    # 与正本一致的一条矛盾也没有（正本：工单正文由架构师与 solo 执行者改，合并 PR 由 solo 执行者改）
    assert chk.conflicts == []
    # 别名读到的是同一行，所以也比得出矛盾：试用工单不由 solo 执行者改
    chk = restate(rf_repo, "试用工单由 solo 执行者改", "里程碑由 solo 执行者改")
    assert sorted((c.kind, c.rows[0][0]) for c in chk.conflicts) == sorted([("extra", KEY_MS), ("extra", KEY_TRIAL)])


def test_an_alias_whose_row_is_not_in_the_table_stops_the_tool(rf_repo, monkeypatch):
    real = rf.load_json

    def typo(name):
        cfg = real(name)
        if name == "canon.json":
            tid = next(t for t in cfg["tables"] if t.endswith("1. 事实放在哪 > 表1"))
            cfg["tables"][tid]["aliases"]["没有这一行"] = ["别名"]
        return cfg

    monkeypatch.setattr(rf, "load_json", typo)
    with pytest.raises(SystemExit, match="没有这一行"):
        rf.read_canon(rf_repo.path)


def test_role_aliases_worker_reviewer_subagent_and_implementer(rf_repo):
    aliases, roles = rf.role_aliases()
    assert aliases["工人"] == aliases["实施者"] == aliases["执行者"] == ["solo 执行者"]
    assert aliases["审查子代理"] == ["审查者"]
    # 协调者、维护者、编排者不是角色表里的角色，不登记
    assert not {"协调者", "维护者", "编排者"} & set(aliases)
    chk = restate(rich(rf_repo), "`DELIVERY:` 由工人写", "`DELIVERY:` 由审查子代理写", "`in-progress` 由实施者领取时加上", "`TRIAL:` 由工人写")
    got = {g.text: [a[3] for a in g.atoms] for g in chk.groups}
    assert got["`DELIVERY:` 由工人写"] == ["solo 执行者"] and got["`DELIVERY:` 由审查子代理写"] == ["审查者"]
    assert got["`in-progress` 由实施者领取时加上"] == ["solo 执行者"]
    # 工人写 TRIAL: 正本里没有：报多说了
    assert [(c.kind, c.rows[0]) for c in chk.conflicts] == [("extra", ("TRIAL:", "由谁写"))]


def test_a_test_layer_is_now_a_key_a_restatement_can_be_compared_with(rf_repo):
    chk = restate(rf_repo, "集成层由 CI 跑", "集成层由执行者跑", "集成层由用户跑")
    assert [a for g in chk.groups if g.text == "集成层由 CI 跑" for a in g.atoms] == [("says", "集成层", "由谁负责", "CI")]
    # 正本：CI、solo 执行者、三个架构师；用户不在里面
    assert [(c.kind, chk.by_node[c.nodes[0]].text) for c in chk.conflicts] == [("extra", "集成层由用户跑")]
