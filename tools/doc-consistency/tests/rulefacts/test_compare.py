"""规则事实线第 3 步：复述和正本比。五类加三类矛盾各植入一条，各被报出，且只报那一条。"""

import re
from collections import Counter

from test_patterns import KEY_ZONGTU, RESTATE, STUCK_ENV, restate, rich
from test_rulefacts import WF, page_json, rf_repo  # noqa: F401

from doc_consistency.rulefacts import compare

# 植入的矛盾：种类 -> 句子
PLANTED = {
    "extra": ["`TRIAL:` 由执行者写"],  # 正本只有架构师三个角色
    "only_wrong": ["`DELIVERY:` 只由执行者写"],  # 正本还有审查者
    "denied": ["审查者不写 `DELIVERY:`"],  # 正本里审查者写
    "not_member_wrong": ["设计问题不是 `needs-triage` 的理由"],
    "precedence_cycle": ["设计说明与 ADR 冲突时以设计说明为准", "设计说明与 ADR 冲突时以 ADR 为准"],
    "may_wrong": ["用户不在场时架构师循环可以改规则"],  # 正本：不可以
    "handoff_wrong": ["执行环境的问题交给总架构师"],  # 正本：用户
    "closed_missing": ["只有设计问题是 `needs-triage` 的理由"],  # 漏了正本里的别的
    "closed_extra": ["只有设计问题、规则矛盾、验收做不到、文件超上限是 `needs-triage` 的理由"],  # 多了文件超上限；理由清单在句号处停，正本只有这三条
    "user_hands_on": ["`HANDOFF:` 由用户写"],  # 正本里任何角色都写，用户在内，所以只有这一类
}
# 与正本一致的复述：一条矛盾也不该有
CONSISTENT = [
    "`waiting` 由总架构师加上",  # 多值事实只说一部分，不报
    "`DELIVERY:` 由执行者写",
    "`DELIVERY:` 由执行者与审查者写",
    "总图只由总架构师改",
    "架构师循环不改总图",
    "用户在场时总架构师可以改规则",
    "用户不在场时架构师循环不可以关闭试用工单与里程碑",
    "执行环境的问题交给用户",
    "`needs-triage` 的理由交回子架构师",
    "代码达到合同的证据由 CI 改",  # 机器也是正本里的值
    "总图和术语表不一致时以总图为准",
    "文件超上限不是 `needs-triage` 的理由",
    "`in-progress` 由执行者领取时加上",
]


def lines(planted=PLANTED):
    return [s for ss in planted.values() for s in ss] + CONSISTENT


def reported(chk):
    """矛盾 -> (种类, 复述的原句们)。"""
    return Counter((c.kind, tuple(chk.by_node[n].text for n in c.nodes)) for c in chk.conflicts)


def test_each_class_is_planted_once_reported_once_and_nothing_else(rf_repo):
    chk = restate(rich(rf_repo), *lines())
    want = Counter({(kind, tuple(ss)): 1 for kind, ss in PLANTED.items()})
    got = reported(chk)
    assert got == want, (got - want, want - got)
    # 八类（五类加三类，穷尽清单分漏的与多的）再加用户走样，各一条
    assert Counter(c.kind for c in chk.conflicts) == Counter({k: 1 for k in PLANTED}) and len(chk.conflicts) == 10
    # 与正本一致的复述一条也不进矛盾，但都解析成功了
    in_conflict = {t for _, ts in got for t in ts}
    for s in CONSISTENT:
        assert not in_conflict & {s}
        assert any(g.text == s for g in chk.groups), s


def test_every_conflict_names_both_places_and_says_what_differs(rf_repo):
    chk = restate(rich(rf_repo), *lines())
    by_kind = {c.kind: c for c in chk.conflicts}
    # 复述：文件:行 与原句；正本：文件:行 与值
    c = by_kind["extra"]
    g = chk.by_node[c.nodes[0]]
    assert (g.file, g.text) == (RESTATE, "`TRIAL:` 由执行者写") and g.line == 3 + lines().index(g.text)
    assert re.fullmatch(rf"{WF}:\d+  TRIAL: / 由谁写：总架构师、子架构师、架构师循环", c.canon[0])
    assert "solo 执行者" in c.why and "没有这个值" in c.why
    assert "还有 审查者" in by_kind["only_wrong"].why
    assert "不「由谁写」DELIVERY:，正本里 审查者" in by_kind["denied"].why
    assert "正本的理由里有它" in by_kind["not_member_wrong"].why
    assert "设计说明" in by_kind["precedence_cycle"].why and "ADR" in by_kind["precedence_cycle"].why and "绕成一圈" in by_kind["precedence_cycle"].why
    assert by_kind["may_wrong"].why.endswith("正本说不可以") and re.search(rf"{WF}:\d+  改规则、CI 工作流 / 不在场可否：不可以", by_kind["may_wrong"].canon[0])
    assert by_kind["handoff_wrong"].canon[0].endswith(f"{STUCK_ENV} / 交给：用户") and "没有 总架构师" in by_kind["handoff_wrong"].why
    assert "漏了正本里的 规则矛盾、验收做不到" in by_kind["closed_missing"].why
    assert "文件超上限，正本的理由里没有" in by_kind["closed_extra"].why
    assert "不亲手改、建、删、写" in by_kind["user_hands_on"].why and any(re.fullmatch(rf"{WF}:\d+  规则 / 由谁定：用户", ln) for ln in by_kind["user_hands_on"].canon)


def test_group_names_are_expanded_before_comparing(rf_repo):
    # 正本只有总架构师，复述写「由架构师」：子架构师与架构师循环两条按 extra 报
    chk = restate(rich(rf_repo), "总图由架构师改")
    assert sorted(c.key[3] for c in chk.conflicts) == ["子架构师", "架构师循环"]
    assert [c.kind for c in chk.conflicts] == ["extra", "extra"] and all(c.rows == [(KEY_ZONGTU, "由谁改")] for c in chk.conflicts)
    # 正本写「架构师」，复述只写其中一个：多值只说一部分，不报
    chk = restate(rf_repo, "`waiting` 由总架构师加上", "`waiting` 由子架构师与架构师循环加上", "为什么这样定由子架构师改")
    assert chk.conflicts == []
    # 反过来，正本只有执行者一个角色时，复述写「任何角色」（roles.json 列了六个）多出的五个都报
    chk = restate(rf_repo, "`in-progress` 由任何角色加上")
    assert len(chk.conflicts) == 5 and {c.kind for c in chk.conflicts} == {"extra"}


def test_a_precedence_loop_of_three_is_one_conflict(rf_repo):
    chk = restate(
        rich(rf_repo),
        "设计说明与 ADR 冲突时以设计说明为准",
        "ADR 与需求记录冲突时以 ADR 为准",
        "需求记录与设计说明冲突时以需求记录为准",
        "总图和术语表不一致时以总图为准",
    )
    assert [c.kind for c in chk.conflicts] == ["precedence_cycle"]
    assert len(chk.conflicts[0].nodes) == 3 and "总图" not in chk.conflicts[0].why
    # 页面偏序图：三个载体成环，总图到术语表那条不在环里
    assert sorted((w, o) for _, w, o in chk.edges) == sorted([("设计说明", "ADR"), ("ADR", "需求记录"), ("需求记录", "设计说明"), ("总图", "术语表")])


def test_a_reason_list_stops_at_the_full_stop_so_what_follows_is_not_a_reason(rf_repo):
    # 第 4 节「交回架构师：…验收做不到。新报告的问题也标它」：句号后面的话不进理由，说它是理由要报多说；第 7 节是引用，不再有第二份清单
    chk = restate(rich(rf_repo), "设计问题是 `needs-triage` 的理由", "验收做不到是 `needs-triage` 的理由", "新报告的问题是 `needs-triage` 的理由")
    assert [(c.kind, chk.by_node[c.nodes[0]].text) for c in chk.conflicts] == [("extra", "新报告的问题是 `needs-triage` 的理由")]
    assert chk.canon.dup == []


def test_check_command_runs_for_real_exits_zero_and_prints_every_section(rf_repo):
    rich(rf_repo)
    restate(rf_repo, *lines())
    rc, out = rf_repo.cli("rules", "check")
    out = out.replace("\r\n", "\n")
    assert rc == 0
    for head in ("规则事实线·比对：", "解析成功 ", "矛盾 10 条。五类：", "== 多说了正本没有的值：1 条 ==", "== 「以谁为准」方向相反或绕成一圈：1 条 ==", "== 在场可否与正本相反：1 条 ==", "== 交给的角色，正本里没有：1 条 ==",
                 "== 穷尽清单：复述说只有这些，正本还有别的：1 条 ==", "== 穷尽清单：复述里有正本没有的：1 条 ==", "== 用户亲手改建删写（用户只定与确认）：1 条 ==", "== 读不到正本：", "== 一条事实两处正本：0 条 ==", "== 像在说规则但解析不了："):
        assert head in out, head
    assert f"复述 {RESTATE}:3  `TRIAL:` 由执行者写" in out
    assert re.search(rf"  正本 {WF}:\d+  TRIAL: / 由谁写：总架构师、子架构师、架构师循环", out)
    # 解析成功按句式分、附注
    m = re.search(r"解析成功 (\d+) 句（由谁 (\d+)，只由谁 (\d+)，谁不 (\d+)，清单一员 (\d+)，以谁为准 (\d+)，在场可否 (\d+)，交给 (\d+)，穷尽清单 (\d+)）；附注 (\d+) 条", out)
    assert m and int(m.group(1)) == sum(int(x) for x in m.groups()[1:9]) == len(lines())  # 一句一行，每句都解析成功
    # 解析不了的候选数 = 候选 − 解析成功 − 纯指路；前 20 条
    m = re.search(r"== 像在说规则但解析不了：(\d+) 条（候选 (\d+) − 解析成功 (\d+) − 纯指路 (\d+)），前 (\d+) 条", out)
    assert m and int(m.group(1)) == int(m.group(2)) - int(m.group(3)) - int(m.group(4)) and int(m.group(5)) == min(20, int(m.group(1)))


def test_unparsed_candidates_are_counted_and_only_the_first_twenty_are_listed(rf_repo):
    # 25 句像规则又不合句式的话（键不在词表里）
    chk = restate(rich(rf_repo), *[f"第{i}号文件由执行者加上" for i in range(25)])
    mine = [h for h in chk.unparsed() if h.file == RESTATE]
    assert len(mine) == 25
    rc, out = rf_repo.cli("rules", "check")
    out = out.replace("\r\n", "\n")
    tail = out.split("== 像在说规则但解析不了：")[1].split("\n")
    assert tail[0].startswith(f"{len(chk.unparsed())} 条") and f"前 20 条" in tail[0]
    assert sum(1 for ln in tail[1:] if ln.strip()) == 20


def test_same_input_gives_byte_identical_check_and_page(rf_repo):
    rich(rf_repo)
    restate(rf_repo, *lines())
    _, a = rf_repo.cli("rules", "check")
    rf_repo.cli("rules", "view")
    page1 = (rf_repo.path / ".tmp/doc-index/rulefacts.html").read_bytes()
    _, b = rf_repo.cli("rules", "check")
    rf_repo.cli("rules", "view")
    page2 = (rf_repo.path / ".tmp/doc-index/rulefacts.html").read_bytes()
    assert a == b and page1 == page2


def test_page_json_agrees_with_the_rule_conclusions(rf_repo):
    rich(rf_repo)
    chk = restate(rf_repo, *lines())
    rf_repo.cli("rules", "view")
    data = page_json(rf_repo)
    # 矛盾：条数、各类条数与规则结论一致
    assert len(data["conflicts"]) == len(chk.conflicts) == data["stat"]["conflicts"] == 10
    assert {k["kind"]: k["n"] for k in data["kinds"]} == {k: chk.count(k) for k, _ in compare.KINDS}
    assert Counter(c["kind"] for c in data["conflicts"]) == Counter(c.kind for c in chk.conflicts)
    # 复述处：每个（句子，正本行）一处；矩阵里一条事实在几张表里就在几行出现
    assert data["stat"]["restates"] == len(chk.restates) and data["stat"]["parsed"] == len(chk.groups)
    rows_of = Counter((r["key"], r["fact"]) for r in data["matrix"])
    assert sum(len(r["restates"]) for r in data["matrix"]) == sum(rows_of[(x.key, x.fact)] for x in chk.restates)
    # 矛盾的复述处标红，被矛盾波及的正本行标出；一致的不标
    bad = {(r["key"], r["fact"]) for r in data["matrix"] if r["bad"]}
    assert bad == {kf for c in chk.conflicts for kf in c.rows}
    assert {(x.key, x.fact) for x in chk.restates if x.conflict} == bad
    for r in data["matrix"]:
        assert r["bad"] == any(x["status"] == "bad" for x in r["restates"])
    row = next(r for r in data["matrix"] if (r["key"], r["fact"]) == ("TRIAL:", "由谁写"))
    assert [(x["status"], x["text"]) for x in row["restates"]] == [("bad", "`TRIAL:` 由执行者写")] and row["restates"][0]["src"] == f"{RESTATE}:3"
    row = next(r for r in data["matrix"] if (r["key"], r["fact"]) == ("waiting", "由谁改成"))
    assert [x["status"] for x in row["restates"]] == ["ok"] and not row["bad"]
    # 偏序图：优先的指向其次的，成环的边与节点标出
    prec = data["prec"]
    edges = {(e["source"], e["target"]): e["cyc"] for e in prec["edges"]}
    assert edges[("设计说明", "ADR")] and edges[("ADR", "设计说明")] and not edges[("总图", "术语表")]
    assert {n["id"]: n["cyc"] for n in prec["nodes"]} == {"设计说明": True, "ADR": True, "总图": False, "术语表": False}
    # 矛盾清单上有原句与正本出处
    cf = next(c for c in data["conflicts"] if c["kind"] == "handoff_wrong")
    assert cf["srcs"][0].startswith(RESTATE) and "执行环境的问题交给总架构师" in cf["texts"][0] and cf["canon"] and "没有 总架构师" in cf["why"]


def test_page_without_restatements_has_empty_conflicts_and_no_prevails_graph(rf_repo):
    rf_repo.cli("rules", "view")
    data = page_json(rf_repo)
    assert data["conflicts"] == [] and data["prec"] == {"nodes": [], "edges": []} and data["stat"]["conflicts"] == 0
    assert all(r["restates"] == [] and not r["bad"] for r in data["matrix"])
