"""本体第一块：编译、自检与分层规则（方案 docs/research/yudao-ontology.md 第 10.1、11 节）。"""

from conftest import REAL_REPO

from doc_consistency.ontology import __main__ as cli
from doc_consistency.ontology.compile import compile_facts, compile_repo
from doc_consistency.ontology.layering import mentions
from doc_consistency.scaffold import pick, solve

ROLES = {
    "groups": {"架构师": ["总架构师"]},
    "roles": {"用户": {"agent": False}, "总架构师": {"aliases": ["总架构师", "主架构师"]}},
}
CANON = {
    "vocab": {"可否": ["可以", "不可以"]},
    "载体别名": {},
    "tables": {
        "a.md#文 > 1. 甲 > 表1": {
            "key": "标签",
            "node": "标签",
            "columns": {"谁改成它": {"fact": "由谁改成", "many": True, "vocab": "角色"}},
        },
        "a.md#文 > 2. 乙 > 表1": {
            "key": "层",
            "node": "测试层",
            "columns": {"谁跑": {"fact": "由谁改成", "many": False, "vocab": "角色"}},
        },
        "a.md#文 > 3. 丙 > 表1": {"key": "", "columns": {"在场": {"fact": "在场可否", "many": False, "vocab": "可否"}}},
    },
}
KEYS = {"a.md#文 > 1. 甲 > 表1": ["needs-triage"], "a.md#文 > 2. 乙 > 表1": ["单元"], "a.md#文 > 3. 丙 > 表1": ["改意图"]}


def check(facts):
    return cli.selfcheck(facts)


def test_compile_maps_canon_to_ontology():
    f = compile_facts(CANON, ROLES, KEYS)
    s = {str(x) for x in f.symbols}
    assert 'kind("标签","scaffold")' in s
    assert 'instance_of("needs-triage","标签")' in s
    assert 'instance_of("总架构师","角色")' in s
    assert 'instance_of("可以","可否")' in s
    assert 'alias("主架构师","总架构师","roles.json")' in s
    assert 'rel("由谁改成","标签","角色","multi","a.md#文 > 1. 甲 > 表1")' in s
    # 没有 node 的表：关系起点空着，键不当实例
    assert not any("改意图" in x for x in s if x.startswith("instance_of"))


def test_selfcheck_reports_card_mismatch_and_gap():
    found = check(compile_facts(CANON, ROLES, KEYS))
    assert found["rel_card_mismatch"] == [("由谁改成", "a.md#文 > 1. 甲 > 表1", "a.md#文 > 2. 乙 > 表1")]
    assert found["rel_no_domain"] == [("在场可否", "a.md#文 > 3. 丙 > 表1")]
    assert found["m3_bad_owner"] == [] and found["m3_bad_card"] == []


def test_selfcheck_reports_alias_and_group_problems():
    roles = {
        "groups": {"架构师": ["总架构师", "不存在的人"]},
        "roles": {"用户": {}, "总架构师": {"aliases": ["头"]}, "审查者": {"aliases": ["头"]}},
    }
    found = check(compile_facts(CANON, roles, KEYS))
    assert found["alias_clash"] == [("头", "审查者", "总架构师")]
    assert found["group_bad_member"] == [("架构师", "不存在的人")]


def test_mentions_finds_whole_string_constants_with_scope():
    src = 'X = "quality"\nclass A:\n    def f(self):\n        return "engineering" + "quality-x"\n'
    assert mentions(src, {"quality", "engineering"}) == [(1, "quality", "<模块>"), (4, "engineering", "A.f")]


def test_layering_rule_on_facts():
    from doc_consistency.scaffold import sym

    syms = {
        sym("kind", "部门", "organization"),
        sym("kind", "标签", "scaffold"),
        sym("instance_of", "quality", "部门"),
        sym("instance_of", "needs-triage", "标签"),
        sym("module_layer", "k.py", "kernel"),
        sym("code_mentions", "k.py", 3, "quality", "f"),
        sym("code_mentions", "k.py", 9, "needs-triage", "g"),
    }
    atoms = solve(syms, cli.SELF_RULES + ["ontology/layering.lp"])
    assert pick(atoms, "layer_violation") == [("k.py", 3, "quality", "部门", "f")]
    assert pick(atoms, "scaffold_leak") == [("k.py", 9, "needs-triage", "标签", "g")]


def test_real_repo_runs_and_m3_conforms_to_itself():
    facts = compile_repo(REAL_REPO)
    found = check(facts)
    assert found["m3_bad_owner"] == [] and found["m3_bad_card"] == []
    assert "角色" in facts.kinds
    viol, leak = cli.layering(REAL_REPO)
    assert all(len(r) == 5 for r in viol + leak)


T1 = "w.md#文 > 1. 事实放在哪 > 表1"
T9 = "w.md#文 > 9. 技能 > 表1"
T11 = "w.md#文 > 11. 写法 > 表2"
CANON2 = {
    "vocab": {"可否": ["可以"], "载体": ["总图", "设计说明", "工单正文", "子工单"]},
    "载体别名": {},
    "tables": {
        T1: {
            "key": "事实",
            "node": "事实",
            "carrier_column": "位置",
            "aliases": {"工单正文、依赖、子工单": ["工单正文", "依赖", "子工单"]},
            "columns": {"谁改": {"fact": "由谁改", "many": True, "vocab": "角色"}},
        },
        T9: {"key": "", "columns": {"用户在场": {"fact": "在场可否", "many": False, "vocab": "可否"}}},
        T11: {"key": "两边", "columns": {"以谁为准": {"fact": "以谁为准", "prevail": True}}},
    },
}
KEYS2 = {T1: ["系统的形状", "工单正文、依赖、子工单", "合并"], T9: ["改意图"], T11: ["总图与设计说明"]}
OVERLAY = {
    "tables": {T9: {"node": "动作"}, T11: {"between": "载体"}},
    "kinds": [{"name": "路径"}],
    "relations": [{"name": "关于", "from": "事实", "to": "载体", "card": "multi"}],
}
LOCATED = {T1: {"总图": "系统的形状", "docs/architecture.html": "系统的形状"}}


def remodel(**kw):
    args = dict(overlay=OVERLAY, prevails=[("总图", "设计说明")], located=LOCATED)
    args.update(kw)
    return compile_facts(CANON2, ROLES, KEYS2, **args)


def test_carrier_alias_becomes_about_not_alias():
    s = {str(x) for x in remodel().symbols}
    assert 'about("工单正文、依赖、子工单","工单正文","aliases")' in s
    assert 'about("工单正文、依赖、子工单","子工单","aliases")' in s
    assert 'alias("依赖","工单正文、依赖、子工单","w.md#文 > 1. 事实放在哪 > 表1")' in s
    assert not any(x.startswith('alias("工单正文"') for x in s)
    assert 'about("系统的形状","总图","位置")' in s
    assert 'located_in("系统的形状","docs/architecture.html")' in s
    found = check(remodel())
    assert found["alias_shadows"] == []
    assert found["fact_no_carrier"] == [("合并",)]


def test_overlay_fills_the_two_gaps_without_touching_canon():
    found = check(remodel())
    assert found["rel_no_domain"] == []
    s = {str(x) for x in remodel().symbols}
    assert 'instance_of("改意图","动作")' in s
    assert 'rel("以谁为准","载体","载体","multi","w.md#文 > 11. 写法 > 表2")' in s
    assert check(compile_facts(CANON2, ROLES, KEYS2))["rel_no_domain"] != []


def test_prevail_cycle_and_overlay_conflict():
    found = check(remodel(prevails=[("总图", "设计说明"), ("设计说明", "总图")]))
    assert found["prevail_cycle"] == [("总图", "设计说明")]
    canon = {**CANON2, "tables": {**CANON2["tables"], T9: {**CANON2["tables"][T9], "node": "事"}}}
    found = check(compile_facts(canon, ROLES, KEYS2, overlay=OVERLAY))
    assert found["overlay_conflict"] == [(T9, "动作", "事")]


def test_real_repo_has_no_word_used_two_ways():
    found = check(compile_repo(REAL_REPO))
    assert found["alias_shadows"] == [] and found["rel_no_domain"] == []
