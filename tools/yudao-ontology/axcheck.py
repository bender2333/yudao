"""公理草稿过符号层：每条单独加进第 0 批的副本里，看一致性、新推出的空位、SHACL 违例；
没推出空位的，再埋一个它该抓的错（删掉一个满足它的实例的那条关系），看它抓不抓得到。

用法：python3 axcheck.py questions/axioms-draft.ttl     结果写 questions/axcheck.json
草稿文件里每条是一个 yd:MustHaveAxiom（写法同 batches/batch0-axioms.ttl），可以带 yd:question 指回题号。
只在临时副本里跑，不动 batches/。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import rdflib
from rdflib import RDF, URIRef

HERE = Path(__file__).resolve().parent
YD = rdflib.Namespace("https://yudao.dev/onto#")
REPO = os.environ.get("YUDAO_REPO", str(HERE.parent.parent))


def run(root: Path) -> dict:
    p = subprocess.run([sys.executable, "run.py"], cwd=root, env={**os.environ, "YUDAO_REPO": REPO},
                       capture_output=True, text=True)
    if p.returncode:
        return {"error": p.stderr[-400:]}
    r = json.loads((root / "reports/results.json").read_text(encoding="utf-8"))
    return {k: {"consistent": v["consistent"], "slots": len(v["slots"]),
                "paths": sorted(x["path"] for x in v["slots"]),
                "shacl": len(v.get("shacl") or []) if not isinstance(v.get("shacl"), int) else v["shacl"],
                "unsat": [str(u) for u in (v.get("unsat") or [])], "error": v.get("error") or ""}
            for k, v in r["batches"].items()}


def axiom_block(draft: rdflib.Graph, ax) -> str:
    sub = rdflib.Graph()
    sub.namespace_manager.bind("yd", YD)
    for t in draft.triples((ax, None, None)):
        sub.add(t)
    return sub.serialize(format="turtle")


def instances(root: Path, cls, prop, inverse: bool):
    g = rdflib.Graph()
    for f in (root / "batches").glob("*.ttl"):
        g.parse(f)
    for f in (root / "onto").glob("*.ttl"):
        g.parse(f)
    out = []
    for s in g.subjects(RDF.type, cls):
        trip = list(g.triples((None, prop, s))) if inverse else list(g.triples((s, prop, None)))
        if trip:
            out.append(trip)
    return out


def main(path: str) -> None:
    draft = rdflib.Graph().parse(path)
    axioms = list(draft.subjects(RDF.type, YD.MustHaveAxiom))
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        shutil.copytree(HERE, base, ignore=shutil.ignore_patterns("__pycache__", "reports", "experiments", "extractions"))
        (base / "reports").mkdir()
        before = run(base)
        # 草稿里除公理以外的东西（新类、新属性）先一起放进去
        extra = rdflib.Graph()
        for t in draft:
            if t[0] not in axioms:
                extra.add(t)
        rows = []
        for ax in axioms:
            root = Path(tmp) / str(ax).split("#")[-1]
            shutil.copytree(base, root)
            b0 = root / "batches/batch0-axioms.ttl"
            b0.write_text(b0.read_text(encoding="utf-8") + "\n" + extra.serialize(format="turtle").split("\n\n", 1)[-1]
                          + "\n" + axiom_block(draft, ax), encoding="utf-8")
            after = run(root)
            row = {"axiom": str(ax).split("#")[-1], "label": str(draft.value(ax, rdflib.RDFS.label)),
                   "question": str(draft.value(ax, YD.question) or ""), "after": after}
            if "error" not in after:
                row["consistent"] = all(v["consistent"] for v in after.values())
                row["new_slots"] = {k: after[k]["slots"] - before[k]["slots"] for k in after if k in before}
                row["new_slot_paths"] = sorted({p for k in after if k in before
                                                for p in after[k]["paths"] if p not in before[k]["paths"]})
                row["new_shacl"] = {k: after[k]["shacl"] - before[k]["shacl"] for k in after if k in before}
                # 没推出空位：埋一个错，看抓不抓得到
                if row["consistent"] and not any(row["new_slots"].values()):
                    cls, prop = draft.value(ax, YD.onClass), draft.value(ax, YD.viaProperty)
                    inv = str(draft.value(ax, YD.viaInverse) or "").lower() == "true"
                    have = instances(root, cls, prop, inv)
                    if not have:
                        row["planted"] = "模型里没有满足它的实例，埋不了错"
                    else:
                        victim = have[0]
                        for f in (root / "batches").glob("*.ttl"):
                            g = rdflib.Graph().parse(f)
                            hit = [t for t in victim if t in g]
                            if hit:
                                for t in hit:
                                    g.remove(t)
                                g.serialize(f, format="turtle")
                        planted = run(root)
                        caught = "error" not in planted and any(planted[k]["slots"] > after[k]["slots"] for k in planted)
                        row["planted"] = {"removed": [[str(x).split("#")[-1] for x in t] for t in victim],
                                          "caught": caught}
            rows.append(row)
    out = HERE / "questions" / "axcheck.json"
    out.write_text(json.dumps({"before": before, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in rows:
        print(r["axiom"], r.get("consistent"), r.get("new_slots"), r.get("planted", ""))
        for p in r.get("new_slot_paths", []):
            print("   空位：", p)


if __name__ == "__main__":
    main(sys.argv[1])
