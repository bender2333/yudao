import json
import re

import pytest
from conftest import ROLES_TABLE

from doc_consistency.rulefacts import canon as rf

WF = "docs/agents/workflow.md"
AE = "docs/agents/acceptance-evidence.md"
T4 = f"{WF}#工作方式 > 4. 状态与标签 > 表1"
T5 = f"{WF}#工作方式 > 5. 证据评论 > 表1"
T7 = f"{WF}#工作方式 > 7. 出问题往哪交 > 表1"
T2 = f"{WF}#工作方式 > 2. 角色 > 表1"
T1 = f"{WF}#工作方式 > 1. 事实放在哪 > 表1"
T9 = f"{WF}#工作方式 > 9. 技能 > 表1"
TAE = f"{AE}#交付、审查与阶段验收的证据 > 1. 记录身份与结论 > 表1"

# 第 1 节：四列（事实、位置、谁定、谁改）；谁改里只写「按第 5 节」的格子是引用，CI 是机器，谁定里空着的是没写
TABLE1 = (
    "| 事实 | 位置 | 谁定 | 谁改 |\n| --- | --- | --- | --- |\n"
    "| 规则 | `CLAUDE.md` | 用户 | 总架构师 |\n"
    "| 每次状态变化的证据 | 那张工单上一条带前缀的评论 | | 按第 5 节 |\n"
    "| 代码达到合同的证据 | PR 与 CI | | 执行者、审查者、CI |\n"
)
WORKFLOW = (
    "# 工作方式\n\n## 1. 事实放在哪\n\n" + TABLE1 + "\n"
    "## 2. 角色\n\n" + ROLES_TABLE + "\n## 4. 状态与标签\n\n"
    "| 状态 | 意思 | 谁改成它 |\n| --- | --- | --- |\n"
    "| `waiting` | 在等前提 | 架构师 |\n"
    "| `in-progress` | 有人在做 | 执行者领取时 |\n"
    "| `needs-triage` | 交回架构师：设计问题、规则矛盾、验收做不到。新报告的问题也标它 | 执行者或报告的人 |\n"
    "| `ready-for-human` | 要用户做 | 任何角色 |\n\n"
    "## 5. 证据评论\n\n"
    "| 前缀 | 写什么 | 谁写 |\n| --- | --- | --- |\n"
    "| `DELIVERY:` | 改了哪些文件 | 执行者<br>审查者 |\n"
    "| `TRIAL:` | `TRIAL: <达到 \\| 复盘 \\| 试用>` | 架构师 |\n\n"
    "## 7. 出问题往哪交\n\n"
    "| 卡在 | 交给 | 怎么交 |\n| --- | --- | --- |\n"
    "| 执行环境、要用户提供的条件 | 用户 | `ready-for-human` |\n"
    "| `needs-triage` 的理由（第 4 节） | 子架构师或架构师循环 | `ARCHITECT:` 评论，`needs-triage` |\n\n"
    "## 9. 技能\n\n用户在场与不在场是同一个入口，权限不同：\n\n"
    "| | 用户在场 | 用户不在场（架构师循环） |\n| --- | --- | --- |\n"
    "| 改规则、CI 工作流 | 可以，改完告诉用户 | 不可以，开一张 `architecture` 工单 |\n"
    "| 关闭试用工单与里程碑 | 用户确认以后 | 不可以 |\n"
)
EVIDENCE = (
    "# 交付、审查与阶段验收的证据\n\n## 1. 记录身份与结论\n\n"
    "| 结论 | 证据 | 负责角色 |\n| --- | --- | --- |\n"
    "| 实现完成 | 提交 | 执行者 |\n"
    "| 审查通过 | 批准 | 审查者（只有内核 PR） |\n"
    "| CI 通过 | 运行 | CI |\n"
    "| 集成通过 | 范围 | solo 执行者（`touches-core` 合并之前）、架构师（试用之前） |\n"
    "| 真实验收通过 | 场景 | 该验收工单的执行者与独立审查者 |\n"
)


@pytest.fixture
def rf_repo(scaffold_repo):
    """角色表、四张正本表；总架构师等读两份正本，solo 执行者与审查者只读 workflow.md。"""
    scaffold_repo.write(WF, WORKFLOW)
    scaffold_repo.write(AE, EVIDENCE)
    scaffold_repo.write("CLAUDE.md", "# 适用范围\n\n总架构师、子架构师、架构师循环读 [工作方式](docs/agents/workflow.md) 与 [验收证据](docs/agents/acceptance-evidence.md)。\n")
    scaffold_repo.write("AGENTS.md", "# 适用范围\n\nsolo 执行者与审查者读 [工作方式](docs/agents/workflow.md)。\n")
    scaffold_repo.commit("规则事实线的最小仓库")
    return scaffold_repo


def facts(c, table=None):
    return {(x.key, x.fact, x.value) for x in c.cells if table in (None, x.table)}


def test_cells_become_facts_with_roles_expanded(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 合称「架构师」展开成三个角色；「任何角色」展开成 roles.json 里列的六个（agent 试用者不在其中）
    assert {v for k, f, v in facts(c, T4) if (k, f) == ("waiting", "由谁改成")} == {"总架构师", "子架构师", "架构师循环"}
    assert {v for k, f, v in facts(c, T4) if (k, f) == ("ready-for-human", "由谁改成")} == set(c.roles) - {"agent 试用者"} and len(c.roles) == 7
    # 一格里用「或、、与」分开的是多个值
    assert {v for k, f, v in facts(c, T7) if (k, f) == ("needs-triage 的理由（第 4 节）", "交给")} == {"子架构师", "架构师循环"}
    assert {v for k, f, v in facts(c, TAE) if (k, f) == ("集成通过", "由谁负责")} == {"solo 执行者", "总架构师", "子架构师", "架构师循环"}
    # <br> 分开多个值；别名「执行者」落到 solo 执行者
    assert {v for k, f, v in facts(c, T5) if k == "DELIVERY:"} == {"solo 执行者", "审查者"}


def test_who_decides_column_is_read_into_a_canon_fact(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 第 1 节的「谁定」读成「由谁定」，和「谁改」并列；空格子不出事实
    assert facts(c, T1) >= {("规则", "由谁定", "用户"), ("规则", "由谁改", "总架构师")}
    assert {k for k, f, v in facts(c, T1) if f == "由谁定"} == {"规则"}
    assert ("规则", "由谁定", "用户") in {(x.key, x.fact, x.value) for x in c.cells} and ("规则", "由谁定", "用户") in c.canon


def test_role_table_only_names_its_keys_and_states_no_facts(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 「做什么」「不做什么」两列是摘要，不是正本：角色表不出事实，只有键是角色
    assert facts(c, T2) == set() and not any(x.table == T2 for x in c.notes + c.unparsed)
    assert {r for t, r in c.named if t == T2} == set(c.roles)
    # 用户不是 agent，不读规则文件：点名了，但不算读不到
    assert "用户" in {r for t, r in c.named if t == T4}
    assert "用户" not in {r for r, t in c.unreachable}
    assert ("agent 试用者", T2) in c.unreachable
    rc, out = rf_repo.cli("rules", "canon")
    assert "键是角色，点名 7 个" in out and "词表「事」未封闭" not in out and "定走向" not in out


def test_permission_table_reads_yes_or_no_and_strips_the_rest_into_notes(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert facts(c, T9) == {
        ("改规则、CI 工作流", "在场可否", "可以"),
        ("改规则、CI 工作流", "不在场可否", "不可以"),
        ("关闭试用工单与里程碑", "不在场可否", "不可以"),
    }
    assert {x.text for x in c.notes if x.table == T9} == {"可以，改完告诉用户", "不可以，开一张 `architecture` 工单"}
    # 读不出可以还是不可以的，原样报出，不猜
    assert [(x.key, x.column, x.text) for x in c.unparsed if x.table == T9] == [("关闭试用工单与里程碑", "用户在场", "用户确认以后")]


def test_escaped_pipe_in_a_cell_does_not_shift_columns(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert {v for k, f, v in facts(c, T5) if k == "TRIAL:"} == {"总架构师", "子架构师", "架构师循环"}


def test_parentheses_and_qualifiers_become_notes_not_facts(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert {x.text for x in c.notes} == {
        "可以，改完告诉用户",
        "不可以，开一张 `architecture` 工单",
        "执行者领取时",
        "审查者（只有内核 PR）",
        "solo 执行者（`touches-core` 合并之前）",
        "架构师（试用之前）",
        "该验收工单的执行者",
        "新报告的问题也标它",  # 理由清单在句号处停，句号后面的话是附注
    }
    assert ("in-progress", "由谁改成", "solo 执行者") in facts(c)
    assert not any("只有内核" in x.value or "领取" in x.value for x in c.cells)


def test_unreadable_parts_are_reported_verbatim_while_readable_parts_are_read(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # CI 是机器，读得出了；报告的人、独立审查者不在词表里，原样报
    assert {(x.key, x.column, x.text) for x in c.unparsed} == {
        ("needs-triage", "谁改成它", "报告的人"),
        ("真实验收通过", "负责角色", "独立审查者"),
        ("关闭试用工单与里程碑", "用户在场", "用户确认以后"),
    }
    assert ("needs-triage", "由谁改成", "solo 执行者") in facts(c)
    assert ("真实验收通过", "由谁负责", "solo 执行者") in facts(c)
    assert not any(x.value in ("报告的人", "独立审查者") for x in c.cells)


def test_reference_cells_are_listed_apart_and_are_neither_facts_nor_unreadable(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 整格只写「按第 5 节」：引用。不出事实，不在读不出里，单独列一段
    assert [(x.key, x.column, x.text) for x in c.refs] == [("每次状态变化的证据", "谁改", "按第 5 节")]
    assert not any(k == "每次状态变化的证据" and f == "由谁改" for k, f, v in facts(c, T1))
    assert not any(x.key == "每次状态变化的证据" for x in c.unparsed)
    rc, out = rf_repo.cli("rules", "canon")
    out = out.replace("\r\n", "\n")
    assert "引用 1 条" in out and "== 引用：1 条" in out
    assert re.search(rf"{WF}:\d+  每次状态变化的证据 / 列「谁改」：按第 5 节", out.split("== 引用：")[1].split("== 读不出")[0])
    # 引用要整格才算：夹在别的话里的「按第 5 节」读不出角色，照旧原样报出
    rf_repo.write(WF, rf_repo.read(WF).replace("| 按第 5 节 |", "| 总架构师，按第 5 节 |"))
    rf_repo.commit("引用混在别的话里")
    c = rf.read_canon(rf_repo.path)
    assert c.refs == [] and [x.text for x in c.unparsed if x.key == "每次状态变化的证据"] == ["按第 5 节"]
    assert ("每次状态变化的证据", "由谁改", "总架构师") in facts(c)


def test_machines_are_values_in_role_columns_but_are_not_roles(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 第 1 节与验收证据表各有一个 CI：读成值
    assert ("代码达到合同的证据", "由谁改", "CI") in facts(c, T1) and ("CI 通过", "由谁负责", "CI") in facts(c, TAE)
    assert {v for k, f, v in facts(c, T1) if k == "代码达到合同的证据"} == {"solo 执行者", "审查者", "CI"}
    # 它们不是角色：不在角色表里，named 不含它们，没有阅读范围所以也不会被报读不到
    assert "CI" not in c.roles and not any(r == "CI" for t, r in c.named) and not any(r == "CI" for r, t in c.unreachable)
    # 不在词表里的机器仍然读不出
    rf_repo.write(WF, rf_repo.read(WF).replace("执行者、审查者、CI |", "执行者、审查者、机器人 |"))
    rf_repo.commit("不认识的机器")
    c = rf.read_canon(rf_repo.path)
    assert "机器人" in {x.text for x in c.unparsed}


def test_reason_list_is_read_after_the_colon_and_stops_at_the_full_stop(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 「交回架构师：」后面按「、」切，遇到「。」结束；「。」后面的话不进理由，记成附注给人看
    assert {v for k, f, v in facts(c, T4) if (k, f) == ("needs-triage", "理由")} == {"设计问题", "规则矛盾", "验收做不到"}
    assert [x.text for x in c.notes if x.table == T4 and x.fact == "理由"] == ["新报告的问题也标它"]
    # 第 7 节那一行是引用（「`needs-triage` 的理由（第 4 节）」），不再出理由；别的行的「意思」没有「交回架构师：」，也不出
    assert {f for k, f, v in facts(c, T7)} == {"交给"}
    assert {k for k, f, v in facts(c) if f == "理由"} == {"needs-triage"}


def test_there_is_no_dup_canon_when_each_fact_has_one_table(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert c.dup == [] and c.only_in == []
    rc, out = rf_repo.cli("rules", "canon")
    assert "== 一条事实两处正本：0 条 ==" in out and "一条事实两处正本 0 条" in out


def test_dup_canon_reports_the_same_fact_in_two_tables_and_which_values_differ(rf_repo, monkeypatch):
    # 机制本身还在：给第 7 节再声明一列理由（key_from 取反引号里的标签），needs-triage 的理由就有了两处正本
    real = rf.load_json

    def two_places(name):
        cfg = real(name)
        if name == "canon.json":
            cfg["tables"][T7]["columns"]["怎么交"] = {"fact": "理由", "many": True, "key_from": {"column": "怎么交", "tags": ["needs-triage"]}}
        return cfg

    monkeypatch.setattr(rf, "load_json", two_places)
    c = rf.read_canon(rf_repo.path)
    assert c.dup == [("needs-triage", "理由", T4, T7)]
    assert {t for k, f, v, t in c.only_in} == {T4, T7}
    out = "\n".join(rf.format_canon(c))
    assert "== 一条事实两处正本：1 条 ==" in out and re.search(rf"{WF}:\d+  4\. 状态与标签 > 表1：设计问题", out)


def test_unreachable_when_a_named_role_does_not_read_the_canon_file(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # solo 执行者与审查者读不到验收证据规则，试用者读不到工作方式（角色表点名了它）；用户不是 agent，不算
    assert {(r, t.split("#")[0]) for r, t in c.unreachable} == {
        ("solo 执行者", AE),
        ("审查者", AE),
        ("agent 试用者", WF),
    }
    # 补上入口里的指向，读不到的就少了
    rf_repo.write("AGENTS.md", "# 适用范围\n\nsolo 执行者与审查者读 [工作方式](docs/agents/workflow.md) 与 [验收证据](docs/agents/acceptance-evidence.md)。\n")
    rf_repo.commit("补指向")
    c = rf.read_canon(rf_repo.path)
    assert {(r, t.split("#")[0]) for r, t in c.unreachable} == {("agent 试用者", WF)}


def test_canon_command_prints_every_section_and_exits_zero(rf_repo):
    rc, out = rf_repo.cli("rules", "canon")
    assert rc == 0
    for head in ("== 附注：8 条", "== 引用：1 条", "== 读不出：3 条", "== 一条事实两处正本：0 条", "== 读不到正本：3 条"):
        assert head in out
    assert f"waiting / 由谁改成 / 总架构师    {WF}:" in out
    assert f"{AE}:" in out and "报告的人" in out and "agent 试用者  读不到  docs/agents/workflow.md" in out


def test_canon_command_fails_when_the_declared_table_is_missing(rf_repo):
    rf_repo.write(AE, "# 交付、审查与阶段验收的证据\n\n没有表。\n")
    rc, out = rf_repo.cli("rules", "canon", check=False)
    assert rc != 0 and "找不到表" in out


def test_group_members_must_be_roles(rf_repo, monkeypatch):
    real = rf.load_json
    def bad(name):
        cfg = real(name)
        if name == "roles.json":
            cfg["groups"]["架构师"].append("不存在的角色")
        return cfg
    monkeypatch.setattr(rf, "load_json", bad)
    with pytest.raises(SystemExit, match="不是角色的成员"):
        rf.role_aliases()


def page_json(repo):
    text = repo.read(".tmp/doc-index/rulefacts.html")
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def c_roles(repo):
    return set(rf.read_canon(repo.path).roles)


def test_view_page_carries_matrix_and_graph_data(rf_repo):
    rc, out = rf_repo.cli("rules", "view")
    data = page_json(rf_repo)
    rows = {(r["tableName"], r["key"], r["fact"]): r for r in data["matrix"]}
    row = rows[("4. 状态与标签 > 表1", "ready-for-human", "由谁改成")]
    assert row["src"] == f"{WF}:{row['src'].split(':')[1]}" and row["marks"]["总架构师"] == "read"
    assert row["marks"]["用户"] == "na" and "solo 执行者" in row["marks"] and "agent 试用者" not in row["marks"]
    assert rows[("4. 状态与标签 > 表1", "waiting", "由谁改成")]["marks"].get("solo 执行者") is None  # 没点名，没有标记
    assert rows[("1. 记录身份与结论 > 表1", "审查通过", "由谁负责")]["marks"] == {"审查者": "miss"}  # 审查者读不到验收证据规则
    assert rows[("1. 记录身份与结论 > 表1", "集成通过", "由谁负责")]["marks"]["solo 执行者"] == "miss"
    assert rows[("1. 记录身份与结论 > 表1", "集成通过", "由谁负责")]["marks"]["总架构师"] == "read"
    # 规则图：边就是表里的事实，一条不多
    g = data["graph"]
    edges = {(e["source"], e["fact"], e["target"]) for e in g["edges"]}
    assert ("角色:solo 执行者", "由谁改成", "标签:in-progress") in edges
    assert ("角色:审查者", "由谁写", "证据前缀:DELIVERY:") in edges
    assert ("卡在项:needs-triage 的理由（第 4 节）", "交给", "角色:子架构师") in edges
    assert ("结论:审查通过", "由谁负责", "角色:审查者") in edges
    # 第 1 节的「谁定」「谁改」也画边（角色→键），边上标「定」「改」；规则图的角色节点保留
    labels = {(e["source"], e["label"], e["target"]) for e in g["edges"]}
    assert ("角色:用户", "定", "事实:规则") in labels and ("角色:总架构师", "改", "事实:规则") in labels
    # 机器（CI）不是角色，没有节点也没有边；事实仍挂在键的节点上。引用格没有事实，也没有边
    assert not any("CI" in e["source"] for e in g["edges"]) and not any(n["label"] == "CI" for n in g["nodes"])
    ci_node = next(n for n in g["nodes"] if n["id"] == "事实:代码达到合同的证据")
    assert any(f["text"] == "代码达到合同的证据 由谁改 CI" for f in ci_node["facts"])
    n_role_facts = sum(1 for c in rf.read_canon(rf_repo.path).cells if c.edge and c.value in c_roles(rf_repo))
    assert len(g["edges"]) == n_role_facts
    assert {r["key"] for r in data["matrix"] if r["fact"] == "由谁改"} >= {"规则", "代码达到合同的证据"} and "每次状态变化的证据" not in {r["key"] for r in data["matrix"]}
    # 角色表不出事实：矩阵里没有它那一组行，规则图的角色节点还在；权限表没有图节点，只进矩阵
    assert not any(r["tableName"] == "2. 角色 > 表1" for r in data["matrix"])
    assert {n["label"] for n in g["nodes"] if n["kind"] == "角色"} == set(rf.read_canon(rf_repo.path).roles)
    assert not any(n["label"].startswith("改规则") for n in g["nodes"])
    assert rows[("9. 技能 > 表1", "改规则、CI 工作流", "在场可否")]["marks"] == {}
    # 机器不是角色，矩阵的标记里没有它
    assert all("CI" not in r["marks"] for r in data["matrix"])
    assert set(g["kinds"]) == {"角色", "事实", "标签", "证据前缀", "卡在项", "结论"}
    # needs-triage 的理由只在第 4 节一处，挂在标签节点上
    node = next(n for n in g["nodes"] if n["id"] == "标签:needs-triage")
    assert len({f["src"] for f in node["facts"] if "理由" in f["text"]}) == 1
    assert len(data["dups"]) == 0 and len(data["notes"]) == 8 and len(data["unparsed"]) == 3 and len(data["unreachable"]) == 3
    assert [(x["key"], x["column"], x["text"]) for x in data["refs"]] == [("每次状态变化的证据", "谁改", "按第 5 节")] and data["stat"]["refs"] == 1
    assert data["stat"]["facts"] == len(rf.read_canon(rf_repo.path).cells)


def test_same_input_gives_byte_identical_output(rf_repo):
    _, a = rf_repo.cli("rules", "canon")
    rf_repo.cli("rules", "view")
    page1 = (rf_repo.path / ".tmp/doc-index/rulefacts.html").read_bytes()
    _, b = rf_repo.cli("rules", "canon")
    rf_repo.cli("rules", "view")
    page2 = (rf_repo.path / ".tmp/doc-index/rulefacts.html").read_bytes()
    assert a == b and page1 == page2
