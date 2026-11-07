"""两次（或三次）独立抽取的对照：按中文标签对齐，只列对不上的。

用法：python3 compare.py 参照.ttl 抽取A.ttl 抽取B.ttl [--out 报告.json]
标识（IRI）各抽各的，所以按 rdfs:label 对齐；标签里括号中的补充说明另算一种宽松匹配。
"""
from __future__ import annotations

import argparse
import json
import re
from itertools import combinations
from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, URIRef

YD = "https://yudao.dev/onto#"
SKIP = {"archRef", "quote", "docRef", "batch", "planned"}


def norm(s: str, loose: bool) -> str:
    s = s.strip().replace(" ", "")
    if loose:
        s = re.sub(r"[（(].*?[）)]", "", s)
    return s


def facts(path: Path, loose: bool):
    g = rdflib.Graph()
    g.parse(path)

    def lab(n):
        if isinstance(n, rdflib.Literal):
            return str(n.toPython()).lower()
        v = g.value(n, RDFS.label)
        if v is None:
            return str(n).split("#")[-1]  # 共用的个体（如 yd:completion-release）按标识
        return norm(str(v), loose)

    types, rels = set(), set()
    for s, p, o in g:
        if not str(s).startswith(YD) or str(s).split("#")[-1].startswith("slot-"):
            continue
        if p == RDF.type and str(o).startswith(YD):
            types.add((str(o).split("#")[-1], lab(s)))
        elif str(p).startswith(YD) and str(p).split("#")[-1] not in SKIP:
            rels.add((lab(s), str(p).split("#")[-1], lab(o)))
    return types, rels


def compare(paths: dict[str, Path], loose: bool):
    data = {k: facts(p, loose) for k, p in paths.items()}
    out = {"loose": loose, "counts": {k: {"types": len(t), "relations": len(r)} for k, (t, r) in data.items()}, "pairs": {}}
    for a, b in combinations(paths, 2):
        ta, ra = data[a]
        tb, rb = data[b]
        both = (ta & tb) | (ra & rb)
        union = (ta | tb) | (ra | rb)
        out["pairs"][f"{a}~{b}"] = {
            "agree": len(both), "union": len(union),
            "agreement": round(len(both) / len(union), 3) if union else 1.0,
            f"only_{a}": sorted(map(list, (ta - tb) | (ra - rb))),
            f"only_{b}": sorted(map(list, (tb - ta) | (rb - ra))),
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--names", default="参照,A,B")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    names = a.names.split(",")
    paths = {n: Path(f) for n, f in zip(names, a.files)}
    res = {"strict": compare(paths, False), "loose": compare(paths, True)}
    for mode, r in res.items():
        print(mode, r["counts"], {k: (v["agree"], v["union"], v["agreement"]) for k, v in r["pairs"].items()})
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
