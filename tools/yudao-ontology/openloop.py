"""开环标记的检查：两处以上文字对同一件事（标不标开环）给条件时，枚举探针，找出判定相反的那种定义。

用法：python3 openloop.py 5159317 eb8429e
每个提交读 rules/openloop-<提交>.ttl。先到那个提交里逐句核对原句还在，再按三步跑 HermiT：
  1. 只放特征的结构：推不出的组合（例如没有核验角色却核验最后的成果）去掉；
  2. 再放加载规则：被归进「加载时整份拒绝」的组合不会建出事项，不判开环；
  3. 再放判开环的规则：一份探针在这一步变得不一致，就是两条规则给它相反的判定，记违例。
结果写进 reports/openloop.json。只读仓库，不改文档。
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import rdflib
from rdflib import OWL, RDF, RDFS, Literal

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
YD = rdflib.Namespace("https://yudao.dev/onto#")
PREFIXES = ("@prefix yd: <https://yudao.dev/onto#> .\n@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
FEATURES = [(YD.HasVerifier, YD.NoVerifier), (YD.FinalVerified, YD.FinalNotVerified),
            (YD.CompleterVerified, YD.CompleterNotVerified), (YD.ExtraCompleter, YD.NoExtraCompleter)]


def doc_at(commit: str, path: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{path}"], check=True,
                          capture_output=True, text=True).stdout


def rule_graph(rules: rdflib.Graph, kinds) -> rdflib.Graph:
    g = rdflib.Graph()
    for kind in kinds:
        for r in rules.subjects(RDF.type, kind):
            g.parse(data=PREFIXES + str(rules.value(r, YD.axiomTurtle)), format="turtle")
    return g


def consistent(g: rdflib.Graph) -> tuple[bool, set]:
    """返回是否自洽，以及探针被推进了哪些类。"""
    import owlready2
    owlready2.JAVA_EXE = "java"
    g = rdflib.Graph() + g
    for s in set(g.subjects(RDF.type, YD.Probe)):
        g.add((s, RDF.type, OWL.NamedIndividual))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "p.owl")
        g.serialize(path, format="xml")
        world = owlready2.World()
        onto = world.get_ontology("file://" + path).load()
        try:
            with onto:
                owlready2.sync_reasoner_hermit(world, infer_property_values=False, debug=0)
        except owlready2.OwlReadyInconsistentOntologyError:
            return False, set()
        ind = world.search_one(iri=str(YD["probe"]))
        return True, {str(c.iri).split("#")[-1] for c in ind.INDIRECT_is_a if getattr(c, "iri", None)}


def probe(values) -> rdflib.Graph:
    g = rdflib.Graph()
    p = YD["probe"]
    g.add((p, RDF.type, YD.Probe))
    for (pos, neg), v in zip(FEATURES, values):
        g.add((p, RDF.type, pos if v else neg))
    return g


def describe(base: rdflib.Graph, values) -> str:
    return "，".join(str(base.value(pos if v else neg, RDFS.label)) for (pos, neg), v in zip(FEATURES, values))


def check(commit: str) -> dict:
    base = rdflib.Graph().parse(HERE / "rules/openloop-features.ttl")
    rules = rdflib.Graph().parse(HERE / f"rules/openloop-{commit}.ttl")
    # 原句核对
    quotes = []
    for r in sorted(set(rules.subjects(YD.docPath, None))):
        text = doc_at(commit, str(rules.value(r, YD.docPath)))
        for q in rules.objects(r, YD.quote):
            quotes.append({"rule": str(rules.value(r, RDFS.label)), "quote": str(q), "found": str(q) in text})
    load = rule_graph(rules, [YD.LoadRule])
    verdict = rule_graph(rules, [YD.OpenLoopRule])
    rows = []
    for values in itertools.product([True, False], repeat=len(FEATURES)):
        p = probe(values)
        row = {"probe": describe(base, values)}
        ok, _ = consistent(base + p)
        if not ok:
            row["result"] = "推不出的组合"
            rows.append(row)
            continue
        ok, types = consistent(base + load + p)
        if "RejectedAtLoad" in types:
            row["result"] = "加载时整份拒绝"
            rows.append(row)
            continue
        ok, types = consistent(base + load + verdict + p)
        if not ok:
            row["result"] = "违例"
            row["why"] = "判开环的规则给这份定义相反的判定"
            # 找出各自给什么：一条规则一条规则单独放
            each = {}
            for r in rules.subjects(RDF.type, YD.OpenLoopRule):
                one = rdflib.Graph().parse(data=PREFIXES + str(rules.value(r, YD.axiomTurtle)), format="turtle")
                _, t = consistent(base + load + one + p)
                each[str(rules.value(r, RDFS.label))] = ("标开环" if "OpenLoopMarked" in t else
                                                          "不标开环" if "NotOpenLoopMarked" in t else "没说")
            row["each"] = each
        else:
            row["result"] = ("标开环" if "OpenLoopMarked" in types else
                             "不标开环" if "NotOpenLoopMarked" in types else "不知道")
        rows.append(row)
    return {"commit": commit, "quotes": quotes, "probes": rows}


def main(argv):
    out = [check(c) for c in argv]
    (HERE / "reports/openloop.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in out:
        print(c["commit"], "原句都在" if all(q["found"] for q in c["quotes"]) else "有原句对不上")
        for r in c["probes"]:
            print("  ", r["result"], "|", r["probe"], "|", r.get("each", ""))


if __name__ == "__main__":
    main(sys.argv[1:] or ["5159317", "eb8429e"])
