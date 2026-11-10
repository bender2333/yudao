"""从模型里的对象生问题：先看对象之间该有什么联系，再去文档找结论。

用法：python3 qgen.py            列出候选题（json），按先后排
问法（固定几种）：必有、至多、对称、粒度、跟着走、继承、有界。
这里只机械地找出「值得问的组合」：已有关系只覆盖一部分实例的（必有）、同类之间的关系（对称）、
一种关系两头挂了不同的类（粒度）、属于某类以后那一类的关系（继承）。说成项目里的话、划掉说不通的，交给人或大模型。
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

HERE = Path(__file__).resolve().parent
CORE = ["部件", "成果种类", "缝", "角色", "职能", "事项的来源", "目标函数", "上限", "形态", "环", "轮转方式", "层",
        "核验声明", "询问", "结束方式", "外环的状态", "证据来源（内聚的依据）", "停止原因清单", "循环层"]
SKIP = {OWL.differentFrom, RDF.type, RDFS.label, RDFS.comment}


def load() -> rdflib.Graph:
    g = rdflib.Graph()
    for f in sorted(glob.glob(str(HERE / "batches/*.ttl")) + glob.glob(str(HERE / "onto/*.ttl"))):
        g.parse(f)
    return g


def candidates(g: rdflib.Graph) -> list[dict]:
    lab = lambda x: str(g.value(x, RDFS.label) or str(x).split("#")[-1])  # noqa: E731
    cls = {lab(c): c for c in set(g.subjects(RDF.type, OWL.Class))}
    inst = {k: set(g.subjects(RDF.type, cls[k])) for k in CORE if k in cls}
    kinds = defaultdict(set)
    for k, ss in inst.items():
        for s in ss:
            kinds[s].add(k)
    rel = defaultdict(set)      # (A, p, B) -> 有这条关系的 A 实例
    for s, p, o in g:
        if p in SKIP or s not in kinds or o not in kinds:
            continue
        for a in kinds[s]:
            for b in kinds[o]:
                rel[(a, lab(p), b)].add(s)
    out = []
    for (a, p, b), have in sorted(rel.items()):
        miss = sorted(lab(x) for x in inst[a] - have)
        if miss:
            out.append({"kind": "必有", "a": a, "p": p, "b": b, "have": len(have), "of": len(inst[a]),
                        "missing": miss, "ask": f"每个{a}都必有「{p}」某个{b}吗？"})
        if a == b:
            out.append({"kind": "对称", "a": a, "p": p, "b": b, "ask": f"「{p}」是双向的吗？"})
    by_p = defaultdict(set)
    for a, p, b in rel:
        by_p[p].add((a, b))
    for p, ends in by_p.items():
        if len({b for _, b in ends}) > 1 or len({a for a, _ in ends}) > 1:
            out.append({"kind": "粒度", "p": p, "ends": sorted(ends), "ask": f"「{p}」该挂在哪一层？"})
    # 继承：角色属于职能；职能有的关系，角色也有吗
    for (a, p, b) in list(rel):
        if p == "属于" and b in inst:
            for (a2, p2, b2) in rel:
                if a2 == b and p2 != "属于":
                    out.append({"kind": "继承", "a": a, "via": b, "p": p2, "b": b2,
                                "ask": f"{a}属于{b}，{b}「{p2}」{b2}，{a}也「{p2}」吗？"})
    order = {"必有": 0, "对称": 1, "粒度": 2, "继承": 3}
    return sorted(out, key=lambda x: order[x["kind"]])


if __name__ == "__main__":
    rows = candidates(load())
    json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
    print(f"\n# {len(rows)} 道候选", file=sys.stderr)
