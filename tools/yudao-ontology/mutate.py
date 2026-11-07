"""检验模型本身之一：在副本上埋错，看检查能不能查出、落在哪一栏。

不动 batches/ 里的原文件：每种改法在内存里改一份图再跑同一套推理与 SHACL。
「改一个名字」模拟的是文档副本里换了一个词、重新抽取以后标签变了。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, Literal, URIRef

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run  # noqa: E402

YD = run.YD


def drop(g, s):
    for t in list(g.triples((s, None, None))):
        g.remove(t)
    for t in list(g.triples((None, None, s))):
        g.remove(t)


def set_one(g, s, p, o):
    g.remove((s, p, None))
    g.add((s, p, o))


def relabel(g, s, new):
    g.remove((s, RDFS.label, None))
    g.add((s, RDFS.label, Literal(new, lang="zh")))


def add_decl(g, iri, verifier, verified, outcome, form):
    d = YD[iri]
    g.add((d, RDF.type, YD.VerificationDecl))
    g.add((d, YD.verifier, YD[verifier]))
    g.add((d, YD.verified, YD[verified]))
    g.add((d, YD.forOutcome, YD[outcome]))
    g.add((d, YD.inForm, YD[form]))


def add_cycle(g):
    d = YD["decl-mutant-cycle"]
    g.add((d, RDF.type, YD.VerificationDecl))
    g.add((d, RDFS.label, Literal("（埋的）工程核验质检的缺陷记录", lang="zh")))
    g.add((d, YD.verifier, YD["dept-engineering"]))
    g.add((d, YD.verified, YD["dept-quality"]))
    g.add((d, YD.forOutcome, YD["ok-defect"]))


# id, 批, 改法, 怎么埋, 应该落在（种类, 检查名或空位路径的开头）
MUTATIONS = [
    ("self-judge", 1, "生成者裁决自己", "把质检核验工程交付的那份声明，核验者改成工程自己",
     lambda g: set_one(g, YD["decl-default-quality"], YD.verifier, YD["dept-engineering"]), ("不一致", None)),
    ("cycle", 1, "核验成环", "加一份声明：工程核验质检的缺陷记录（质检本来核验工程）",
     add_cycle, ("违例", "verify-acyclic")),
    ("drop-verifier-b1", 1, "删审查者（第 1 批）", "删掉质检核验工程交付的那份声明",
     lambda g: drop(g, YD["decl-default-quality"]), ("提示+不知道", "交付 → 以放行结束的成果必有一份核验声明")),
    ("rename", 1, "改一个名字", "文档副本里「事项」改成「任务」，重新抽取后标签变了",
     lambda g: relabel(g, YD["c-workitem"], "任务"), ("不知道", "name-unknown")),
    ("avoid-word", 1, "用了要避免的词", "文档副本里「部门」改成「团队」（词表写明避免）",
     lambda g: relabel(g, YD["c-department"], "团队"), ("违例", "name-avoid")),
    ("drop-verifier-b2", 2, "删审查者（第 2 批）", "删掉质检核验工程交付的那份声明；第 2 批已承诺形态里的核验声明",
     lambda g: drop(g, YD["decl-default-quality"]), ("提示+确实缺", "交付 → 以放行结束的成果必有一份核验声明")),
    ("reviewer-sees-author", 2, "审查者看得到作者的历史", "给工程的审查者加上「看得到作者的历史」",
     lambda g: g.add((YD["role-eng-reviewer"], RDF.type, YD.SeesAuthorHistory)), ("不一致", None)),
    ("reviewer-outsourced", 2, "审查者外包", "把工程的审查者改成外包角色",
     lambda g: g.add((YD["role-eng-reviewer"], RDF.type, YD.OutsourcedRole)), ("不一致", None)),
    ("reviewer-is-author", 2, "审查者就是中心角色", "部门内那份核验声明的核验者改成工程架构师自己",
     lambda g: set_one(g, YD["decl-eng-review"], YD.verifier, YD["role-eng-architect"]), ("不一致", None)),
    ("direct-verifies-noncompleter", 3, "直做核验一个交不出完成的角色",
     "几个角色直做里加一份核验声明：工程核验产品交的完成（产品交不出完成，4.3 第 5 条该在加载时拒绝）",
     lambda g: add_decl(g, "decl-mutant-sev", "role-sev-engineering", "role-sev-product", "ok-sev-completion", "form-several"),
     ("违例", "direct-verified-can-complete")),
    ("source-unreceived", 2, "来源没人接", "删掉「工程架构师接上一层交来的任务」这一条",
     lambda g: g.remove((YD["role-eng-architect"], YD.receives, YD["src-subtask"])), ("确实缺", "source-received")),
]


CROSS_MUTATIONS = [
    ("x-drop-completer", "定义里直做没人交完成", "一个角色直做的定义去掉交完成的工具",
     lambda g: g.remove((YD["form-min"], YD.canSubmitCompletion, None)), ("确实缺", "能交完成")),
    ("x-final-wrong", "最后采纳的成果写错", "三部门的定义把最后采纳的成果从交付改成 PRD",
     lambda g: set_one(g, YD["form-default"], YD.finalOutcome, YD["ok-prd"]), ("违例", "最后采纳的成果")),
    ("x-rotation-wrong", "轮转方式写错", "几个角色直做的定义把轮转方式改成成果驱动",
     lambda g: set_one(g, YD["form-several"], YD.rotation, YD["rm-by-outcome"]), ("违例", "轮转方式")),
    ("x-source-dropped", "定义里建档没人接", "一个角色直做的定义去掉建档的来源",
     lambda g: g.remove((YD["role-min"], YD.receives, YD["src-onboarding"])), ("确实缺", "接")),
]


# 第 4 批：代码（codecheck.py）。在内存里改一份内核模块的源码或 name-map 的行，再转写、跑 SHACL
CODE_MUTATIONS = [
    ("c-kernel-dept-name", "内核写部门名", "在 harness/adjudication.py 的副本末尾加一个按部门名判断的函数（department == \"quality\"）",
     {"override": "harness/adjudication.py"}, ("违例", "layer-name")),
    ("c-drop-namemap-row", "删一行对照", "从 name-map 的副本里删掉「事项」这一行",
     {"drop_rows": {"事项"}}, ("不知道", "term-unmapped")),
]


def outcome(br, g):
    if not br.consistent:
        return {"kind": "不一致", "detail": br.error[:160]}
    hits = [f'{r["result"]}:{r["check"]}:{r["label"]}' for r in br.shacl if r["result"] != "不知道" or r["check"] in ("name-unknown", "released-has-decl", "source-received")]
    slots = [run.slot_row(g, s)["path"] for s in br.slots]
    return {"kind": "一致", "shacl": hits, "slots": slots}


def judged(exp, res, base_res):
    kind, key = exp
    if kind == "不一致":
        return res["kind"] == "不一致"
    if res["kind"] != "一致":
        return False
    new_shacl = set(res["shacl"]) - set(base_res["shacl"])
    new_slots = set(res["slots"]) - set(base_res["slots"])
    if kind == "违例":
        return any(h.startswith(f"违例:{key}") for h in new_shacl)
    if kind == "确实缺":
        return any(h.startswith(f"确实缺:{key}") for h in new_shacl)
    if kind == "不知道":
        return any(h.startswith(f"不知道:{key}") for h in new_shacl)
    if kind.startswith("提示"):
        slot_ok = any(s.startswith(key) for s in new_slots)
        tail = kind.split("+")[1]
        shacl_ok = any(h.startswith(f"{tail}:released-has-decl") for h in new_shacl)
        return slot_ok and shacl_ok
    return False


ASSUMPTION_CHECKS = {"halfopen-written-release", "halfopen-depends"}


def main():
    rows = []
    base = {}
    for b in (1, 2, 3):
        br, g, _ = run.run_batch(b, 3)
        base[b] = outcome(br, g)
        assert base[b]["kind"] == "一致", f"原样的第 {b} 批不一致"
        # 假定带出的违例（读作假定与设计的写法冲突）是已知的，对照只看设计本身
        # 第 3 批的两条「确实缺」是真的发现（设计里有、发布的定义文件里没有的两份形态），对照里单列，不算误报
        known_findings = {"form-defined"} if b == 3 else set()
        bad = [h for h in base[b]["shacl"] if h.startswith(("违例", "确实缺"))
               and h.split(":")[1] not in ASSUMPTION_CHECKS | known_findings]
        known = [h for h in base[b]["shacl"] if h.split(":")[1] in ASSUMPTION_CHECKS | known_findings]
        rows.append({"id": f"control-b{b}", "batch": b, "name": "不改（对照）", "how": "原样跑一次",
                     "expected": "没有违例、没有确实缺（假定带出的不算）",
                     "got": ("；".join(bad) or "没有违例、没有确实缺") + ("；已知的（假定带出或真的发现）：" + "；".join(known) if known else ""),
                     "detected": not bad})
    for mid, b, name, how, fn, exp in MUTATIONS:
        br, g, _ = run.run_batch(b, 3, extra=fn)
        res = outcome(br, g)
        new = ([res["detail"]] if res["kind"] == "不一致" else
               sorted(set(res["shacl"]) - set(base[b]["shacl"])) + ["空位：" + s for s in sorted(set(res["slots"]) - set(base[b]["slots"]))])
        ok = judged(exp, res, base[b])
        rows.append({"id": mid, "batch": b, "name": name, "how": how, "expected": "：".join(x for x in exp if x),
                     "got": res["kind"] + ("；" + "；".join(new[:4]) if new else ""), "detected": ok})
        print(("OK  " if ok else "MISS"), b, name, "|", rows[-1]["got"][:150])
    # 第 3 批：设计与定义文件逐条对照（crosscheck.py）。在内存里改一份定义的转写结果
    import crosscheck
    design, defs_g = crosscheck.design_graph(), crosscheck.definitions_graph()
    base_x = {json.dumps(r, ensure_ascii=False, sort_keys=True) for r in crosscheck.compare(design, defs_g)}
    bad = [json.loads(r) for r in base_x if json.loads(r)["result"] in ("违例", "确实缺")]
    rows.append({"id": "control-b3-crosscheck", "batch": 3, "name": "不改（对照，逐条对照）", "how": "原样跑一次",
                 "expected": "没有违例、没有确实缺（缺陷记录按假定算进质检结论）",
                 "got": "；".join(f'{r["result"]}:{r["subject"]} {r["property"]} {r["object"]}' for r in bad),
                 "detected": not bad})
    for mid, name, how, fn, exp in CROSS_MUTATIONS:
        x = rdflib.Graph() + defs_g
        fn(x)
        new_rows = [r for r in crosscheck.compare(design, x)
                    if json.dumps(r, ensure_ascii=False, sort_keys=True) not in base_x]
        ok = any(r["result"] == exp[0] and r["property"] == exp[1] for r in new_rows)
        got = "；".join(f'{r["result"]}:{r["subject"]} {r["property"]} {r["object"]}' for r in new_rows)
        rows.append({"id": mid, "batch": 3, "name": name, "how": how, "expected": "：".join(exp), "got": got, "detected": ok})
        print(("OK  " if ok else "MISS"), 3, name, "|", got[:150])
    import codecheck
    key = lambda r: json.dumps(r, ensure_ascii=False, sort_keys=True)
    base_c = {key(r) for r in codecheck.check(codecheck.facts(codecheck.DEFAULT))}
    for mid, name, how, spec, exp in CODE_MUTATIONS:
        kw = {}
        if "override" in spec:
            path = spec["override"]
            kw["override"] = {path: codecheck.show(codecheck.DEFAULT, path)
                              + "\n\ndef _mutant(department):\n    return department == \"quality\"\n"}
        if "drop_rows" in spec:
            kw["drop_rows"] = spec["drop_rows"]
        new_rows = [r for r in codecheck.check(codecheck.facts(codecheck.DEFAULT, **kw)) if key(r) not in base_c]
        hit = any(r["result"] == exp[0] and r["check"] == exp[1] for r in new_rows)
        # 删一行对照：信息少了只能退到不知道，新冒出确实缺或违例就算没过
        stray = [r for r in new_rows if r["result"] in ("确实缺", "违例") and exp[0] == "不知道"]
        ok = hit and not stray
        got = "；".join(f'{r["result"]}:{r["check"]}:{r["focus"]} {r["detail"][:1]}' for r in new_rows)
        rows.append({"id": mid, "batch": 4, "name": name, "how": how, "expected": "：".join(exp), "got": got, "detected": ok})
        print(("OK  " if ok else "MISS"), 4, name, "|", got[:150])
    (HERE / "reports/mutations.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
