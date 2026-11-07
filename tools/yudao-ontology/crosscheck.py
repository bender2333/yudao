"""第 3 批的第二个检查：设计说的与定义文件写的逐条对照。

run.py 把各批合成一张图推理，设计里写过的三元组会把定义文件漏掉的同一条盖住，所以合图查不出「定义漏了设计写的」。
这里把设计（第 1、2 批）与定义（第 3 批）分成两张图，只对已经有定义文件的形态，按几种关系逐条比：
  设计有、定义没有 → 确实缺（设计承诺过、已建出来的东西里没有，指导下一步开发）
  定义有、设计没写 → 不知道
  只能有一个值的关系（轮转方式、最后采纳的成果）两边不同 → 违例
用法：python3 crosscheck.py；mutate.py 用 compare(design, definitions)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import rdflib
from rdflib import RDFS

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import defs  # noqa: E402
import run  # noqa: E402

YD = run.YD
FORM_PROPS = [YD.rotation, YD.finalOutcome, YD.canSubmitCompletion]
FUNCTIONAL = {YD.rotation, YD.finalOutcome}
ACTOR_PROPS = [YD.receives, YD.produces, YD.watches]
DECL_PROPS = [YD.verifier, YD.verified, YD.forOutcome]


def design_graph() -> rdflib.Graph:
    return run.load([HERE / "onto/core.ttl"] + [HERE / f for b in (1, 2) for f in run.BATCHES[b]])


def definitions_graph(assumptions: bool = True) -> rdflib.Graph:
    files = [HERE / "batches/batch3-definitions.ttl"]
    if assumptions:
        files.append(HERE / "batches/batch3-assumptions.ttl")
    return run.load(files)


def facts(g: rdflib.Graph, form) -> set:
    out = set()
    for p in FORM_PROPS:
        out |= {(form, p, o) for o in g.objects(form, p)}
    for a in defs.ACTORS[str(form).split("#")[-1]].values():
        A = YD[a]
        for p in ACTOR_PROPS:
            for o in g.objects(A, p):
                out.add((A, p, o))
                # 假定：一类成果算进它所属的那种（缺陷记录 ⊂ 质检结论）。交得出那种，就交得出这一类
                if p == YD.produces:
                    out |= {(A, p, s) for s in g.subjects(YD.subKindOf, o)}
    for d in g.subjects(YD.inForm, form):
        if (d, rdflib.RDF.type, YD.VerificationDecl) in g:
            for p in DECL_PROPS:
                out |= {(("decl", g.value(d, YD.verifier), g.value(d, YD.verified)), p, o) for o in g.objects(d, p)}
    return out


def compare(design: rdflib.Graph, definitions: rdflib.Graph) -> list[dict]:
    both = design + definitions
    rows = []
    for form in sorted(set(definitions.subjects(YD.definedBy, None))):
        d, x = facts(design, form), facts(definitions, form)
        for s, p, o in sorted(d - x, key=str):
            if p in FUNCTIONAL and any(s2 == s and p2 == p for s2, p2, _ in x):
                continue
            rows.append(row("确实缺", "设计写了，定义文件里没有", both, form, s, p, o))
        for s, p, o in sorted(x - d, key=str):
            if p in FUNCTIONAL and any(s2 == s and p2 == p for s2, p2, _ in d):
                other = next(o2 for s2, p2, o2 in d if s2 == s and p2 == p)
                rows.append(row("违例", f"设计写的是「{run.label(both, other)}」，定义文件写的是另一个", both, form, s, p, o))
            else:
                rows.append(row("不知道", "定义文件有，设计没写", both, form, s, p, o))
    return rows


def name(g, s):
    if isinstance(s, tuple):
        return f"{run.label(g, s[1])}核验{run.label(g, s[2])}的声明"
    return run.label(g, s)


def row(result, why, g, form, s, p, o):
    return {"result": result, "why": why, "form": run.label(g, form), "subject": name(g, s),
            "property": run.label(g, p), "object": run.label(g, o)}


def main():
    rows = compare(design_graph(), definitions_graph())
    (HERE / "reports/crosscheck.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(r["result"], "|", r["form"], "|", r["subject"], r["property"], r["object"], "|", r["why"])


if __name__ == "__main__":
    main()
