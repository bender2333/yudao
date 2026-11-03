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
T9 = f"{WF}#工作方式 > 9. 技能 > 表1"
TAE = f"{AE}#交付、审查与阶段验收的证据 > 1. 记录身份与结论 > 表1"

WORKFLOW = (
    "# 工作方式\n\n## 2. 角色\n\n" + ROLES_TABLE + "\n## 4. 状态与标签\n\n"
    "| 状态 | 意思 | 谁改成它 |\n| --- | --- | --- |\n"
    "| `waiting` | 在等前提 | 架构师 |\n"
    "| `in-progress` | 有人在做 | 执行者领取时 |\n"
    "| `needs-triage` | 交回架构师：设计问题、规则矛盾；新报告的问题 | 执行者或报告的人 |\n"
    "| `ready-for-human` | 要用户做 | 任何角色 |\n\n"
    "## 5. 证据评论\n\n"
    "| 前缀 | 写什么 | 谁写 |\n| --- | --- | --- |\n"
    "| `DELIVERY:` | 改了哪些文件 | 执行者<br>审查者 |\n"
    "| `TRIAL:` | `TRIAL: <达到 \\| 复盘 \\| 试用>` | 架构师 |\n\n"
    "## 7. 出问题往哪交\n\n"
    "| 卡在 | 交给 | 怎么交 |\n| --- | --- | --- |\n"
    "| 执行环境、要用户提供的条件 | 用户 | `ready-for-human` |\n"
    "| 设计、规则矛盾 | 子架构师或架构师循环 | `ARCHITECT:` 评论，`needs-triage` |\n\n"
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
    # 合称「架构师」展开成三个角色；「任何角色」展开成角色表的全部角色
    assert {v for k, f, v in facts(c, T4) if (k, f) == ("waiting", "由谁改成")} == {"总架构师", "子架构师", "架构师循环"}
    assert {v for k, f, v in facts(c, T4) if (k, f) == ("ready-for-human", "由谁改成")} == set(c.roles) and len(c.roles) == 7
    # 一格里用「或、、与」分开的是多个值
    assert {v for k, f, v in facts(c, T7) if (k, f) == ("设计、规则矛盾", "交给")} == {"子架构师", "架构师循环"}
    assert {v for k, f, v in facts(c, TAE) if (k, f) == ("集成通过", "由谁负责")} == {"solo 执行者", "总架构师", "子架构师", "架构师循环"}
    # <br> 分开多个值；别名「执行者」落到 solo 执行者
    assert {v for k, f, v in facts(c, T5) if k == "DELIVERY:"} == {"solo 执行者", "审查者"}


def test_role_table_is_a_canon_with_an_open_vocab_and_names_its_keys(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # 「事」词表没封闭：一格按「、」「；」切开，短语原样当值；角色表的键就是被点名的角色
    assert ("总架构师", "做", "总图") in facts(c, T2) and ("子架构师", "不做", "不改总图") in facts(c, T2)
    assert {k for k, f, v in facts(c, T2)} == set(c.roles)
    assert {r for t, r in c.named if t == T2} == set(c.roles)
    # 用户不是 agent，不读规则文件：点名了，但不算读不到
    assert "用户" in {r for t, r in c.named if t == T4}
    assert "用户" not in {r for r, t in c.unreachable}
    assert ("agent 试用者", T2) in c.unreachable
    rc, out = rf_repo.cli("rules", "canon")
    assert "词表「事」未封闭" in out and "读不出：4 条" in out and "总图" in out


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
    }
    assert ("in-progress", "由谁改成", "solo 执行者") in facts(c)
    assert not any("只有内核" in x.value or "领取" in x.value for x in c.cells)


def test_unreadable_parts_are_reported_verbatim_while_readable_parts_are_read(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert {(x.key, x.column, x.text) for x in c.unparsed} == {
        ("needs-triage", "谁改成它", "报告的人"),
        ("CI 通过", "负责角色", "CI"),
        ("真实验收通过", "负责角色", "独立审查者"),
        ("关闭试用工单与里程碑", "用户在场", "用户确认以后"),
    }
    assert ("needs-triage", "由谁改成", "solo 执行者") in facts(c)
    assert ("真实验收通过", "由谁负责", "solo 执行者") in facts(c)
    assert not any(x.value in ("CI", "报告的人", "独立审查者") for x in c.cells)


def test_reason_list_is_read_from_a_cell_after_the_colon_and_from_a_key_cell(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert {v for k, f, v in facts(c, T4) if (k, f) == ("needs-triage", "理由")} == {"设计问题", "规则矛盾", "新报告的问题"}
    # 第 7 节：键本身是清单，标签取自「怎么交」一格里的反引号；其余行没有这个标签，不出理由
    assert {v for k, f, v in facts(c, T7) if f == "理由"} == {"设计", "规则矛盾"}
    assert {k for k, f, v in facts(c, T7) if f == "理由"} == {"needs-triage"}
    # 第 4 节别的行的「意思」没有「交回架构师：」，不出理由
    assert {k for k, f, v in facts(c, T4) if f == "理由"} == {"needs-triage"}


def test_dup_canon_reports_the_same_fact_in_two_tables_and_which_values_differ(rf_repo):
    c = rf.read_canon(rf_repo.path)
    assert c.dup == [("needs-triage", "理由", T4, T7)]
    assert sorted((v, t) for k, f, v, t in c.only_in) == sorted([("设计问题", T4), ("新报告的问题", T4), ("设计", T7)])
    rc, out = rf_repo.cli("rules", "canon")
    assert "== 一条事实两处正本：1 条 ==" in out
    assert re.search(rf"{WF}:\d+  4\. 状态与标签 > 表1：设计问题", out) and re.search(rf"{WF}:\d+  7\. 出问题往哪交 > 表1：设计、规则矛盾", out)
    assert "只在 7. 出问题往哪交 > 表1 有：设计" in out


def test_unreachable_when_a_named_role_does_not_read_the_canon_file(rf_repo):
    c = rf.read_canon(rf_repo.path)
    # solo 执行者与审查者读不到验收证据规则，试用者什么规则文件都没有；用户不是 agent，不算
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
    for head in ("== 附注：7 条", "== 读不出：4 条", "== 一条事实两处正本：1 条", "== 读不到正本：4 条"):
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


def test_view_page_carries_matrix_and_graph_data(rf_repo):
    rc, out = rf_repo.cli("rules", "view")
    data = page_json(rf_repo)
    rows = {(r["tableName"], r["key"], r["fact"]): r for r in data["matrix"]}
    row = rows[("4. 状态与标签 > 表1", "ready-for-human", "由谁改成")]
    assert row["src"] == f"{WF}:{row['src'].split(':')[1]}" and row["marks"]["总架构师"] == "read"
    assert row["marks"]["agent 试用者"] == "miss" and row["marks"]["用户"] == "na" and "solo 执行者" in row["marks"]
    assert rows[("4. 状态与标签 > 表1", "waiting", "由谁改成")]["marks"].get("solo 执行者") is None  # 没点名，没有标记
    assert rows[("1. 记录身份与结论 > 表1", "审查通过", "由谁负责")]["marks"] == {"审查者": "miss"}  # 审查者读不到验收证据规则
    assert rows[("1. 记录身份与结论 > 表1", "集成通过", "由谁负责")]["marks"]["solo 执行者"] == "miss"
    assert rows[("1. 记录身份与结论 > 表1", "集成通过", "由谁负责")]["marks"]["总架构师"] == "read"
    # 规则图：边就是表里的事实，一条不多
    g = data["graph"]
    edges = {(e["source"], e["fact"], e["target"]) for e in g["edges"]}
    assert ("角色:solo 执行者", "由谁改成", "标签:in-progress") in edges
    assert ("角色:审查者", "由谁写", "证据前缀:DELIVERY:") in edges
    assert ("卡在项:设计、规则矛盾", "交给", "角色:子架构师") in edges
    assert ("结论:审查通过", "由谁负责", "角色:审查者") in edges
    n_role_facts = sum(1 for c in rf.read_canon(rf_repo.path).cells if c.edge)
    assert len(g["edges"]) == n_role_facts
    # 角色表的事实挂在角色节点上；权限表没有图节点，只进矩阵
    role_node = next(n for n in g["nodes"] if n["id"] == "角色:总架构师")
    assert any(f["text"] == "总架构师 做 总图" for f in role_node["facts"])
    assert not any(n["label"].startswith("改规则") for n in g["nodes"])
    assert rows[("2. 角色 > 表1", "用户", "做")]["marks"] == {"用户": "na"} and rows[("2. 角色 > 表1", "用户", "做")]["open"]
    assert rows[("2. 角色 > 表1", "总架构师", "做")]["marks"] == {"总架构师": "read"}
    assert rows[("9. 技能 > 表1", "改规则、CI 工作流", "在场可否")]["marks"] == {}
    assert set(g["kinds"]) == {"角色", "标签", "证据前缀", "卡在项", "结论"}
    # needs-triage 的两处理由都挂在同一个标签节点上，页面底部列出分歧
    node = next(n for n in g["nodes"] if n["id"] == "标签:needs-triage")
    assert {f["src"].split(":")[0] for f in node["facts"] if "理由" in f["text"]} == {WF}
    assert len({f["src"] for f in node["facts"] if "理由" in f["text"]}) == 2
    assert len(data["dups"]) == 1 and len(data["notes"]) == 7 and len(data["unparsed"]) == 4 and len(data["unreachable"]) == 4
    assert data["stat"]["facts"] == len(rf.read_canon(rf_repo.path).cells)


def test_same_input_gives_byte_identical_output(rf_repo):
    _, a = rf_repo.cli("rules", "canon")
    rf_repo.cli("rules", "view")
    page1 = (rf_repo.path / ".tmp/doc-index/rulefacts.html").read_bytes()
    _, b = rf_repo.cli("rules", "canon")
    rf_repo.cli("rules", "view")
    page2 = (rf_repo.path / ".tmp/doc-index/rulefacts.html").read_bytes()
    assert a == b and page1 == page2
