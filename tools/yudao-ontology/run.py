"""Yudao 本体第一步：按批加载、推理、推空位、跑 SHACL、出报告。

用法：python3 run.py [--upto N] [--depth D] [--out reports/]
只读仓库里的文档与本目录的 Turtle；不改任何文档与代码。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import rdflib
from rdflib import OWL, RDF, RDFS, BNode, Literal, URIRef
from rdflib.collection import Collection

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from names import canonical_names  # noqa: E402

YD = rdflib.Namespace("https://yudao.dev/onto#")
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")

BATCHES: dict[int, list[str]] = {
    0: ["onto/core.ttl", "batches/batch0-axioms.ttl"],
    1: ["batches/batch1-overview.ttl", "batches/batch1-scope.ttl"],
    2: ["batches/batch2-design.ttl", "batches/batch2-scope.ttl", "batches/batch2-eb8429e.ttl"],
    3: ["batches/batch3-definitions.ttl", "batches/batch3-scope.ttl"],
}
ASSUMPTION_FILES: dict[int, list[str]] = {1: ["batches/batch1-assumptions.ttl"], 2: ["batches/batch2-assumptions.ttl"], 3: ["batches/batch3-assumptions.ttl"]}


def files_upto(n: int, assumptions: bool = True) -> list[Path]:
    out = []
    for b in sorted(BATCHES):
        if b > n:
            break
        out += [HERE / f for f in BATCHES[b]]
        if assumptions:
            out += [HERE / f for f in ASSUMPTION_FILES.get(b, [])]
    return out


def load(paths, replace: dict[str, Path] | None = None) -> rdflib.Graph:
    g = rdflib.Graph()
    g.bind("yd", YD)
    for p in paths:
        p = Path(p)
        if replace and p.name in replace:
            p = replace[p.name]
        if p.exists():
            g.parse(p)
    return g


# ---------------------------------------------------------------- 公理
@dataclass
class Axiom:
    iri: URIRef
    label: str
    on: URIRef
    prop: URIRef
    inverse: bool
    filler: URIRef
    basis: str


def axioms(g: rdflib.Graph) -> list[Axiom]:
    out = []
    for a in sorted(g.subjects(RDF.type, YD.MustHaveAxiom)):
        inv = g.value(a, YD.viaInverse)
        out.append(Axiom(a, str(g.value(a, RDFS.label)), g.value(a, YD.onClass), g.value(a, YD.viaProperty),
                         bool(inv and inv.toPython()), g.value(a, YD.filler), str(g.value(a, YD.basis))))
    return out


def compile_axioms(g: rdflib.Graph) -> None:
    """每条必有公理编成 onClass ⊑ ∃p.filler（inverse 时 ∃p⁻.filler）。"""
    for ax in axioms(g):
        r = BNode()
        g.add((r, RDF.type, OWL.Restriction))
        if ax.inverse:
            ip = BNode()
            g.add((ip, OWL.inverseOf, ax.prop))
            g.add((r, OWL.onProperty, ip))
        else:
            g.add((r, OWL.onProperty, ax.prop))
        g.add((r, OWL.someValuesFrom, ax.filler))
        g.add((ax.on, RDFS.subClassOf, r))


# ---------------------------------------------------------------- 推理
@dataclass
class Reasoned:
    consistent: bool
    types: dict[URIRef, set[URIRef]] = field(default_factory=dict)
    unsat: list[str] = field(default_factory=list)
    error: str = ""


def reason(g: rdflib.Graph) -> Reasoned:
    import owlready2
    owlready2.JAVA_EXE = "java"
    g = rdflib.Graph() + g
    classes = set(g.subjects(RDF.type, OWL.Class))
    for s, _, c in list(g.triples((None, RDF.type, None))):
        if c in classes and isinstance(s, URIRef):
            g.add((s, RDF.type, OWL.NamedIndividual))
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "m.owl")
        g.serialize(path, format="xml")
        world = owlready2.World()
        onto = world.get_ontology("file://" + path).load()
        try:
            with onto:
                owlready2.sync_reasoner_hermit(world, infer_property_values=False, debug=0)
        except owlready2.OwlReadyInconsistentOntologyError as e:
            return Reasoned(False, error=str(e)[:300])
        types: dict[URIRef, set[URIRef]] = {}
        for ind in world.individuals():
            ts = set()
            for c in ind.INDIRECT_is_a:
                if isinstance(c, owlready2.ThingClass) and c.iri:
                    ts.add(URIRef(c.iri))
            types[URIRef(ind.iri)] = ts
        unsat = [c.iri for c in world.inconsistent_classes()]
        return Reasoned(True, types, unsat)


# ---------------------------------------------------------------- 空位
@dataclass
class Slot:
    iri: URIRef
    depth: int
    parent: URIRef
    axiom: Axiom
    root: URIRef
    path: tuple  # (root, ax1, ax2, ...)


def label(g, n) -> str:
    v = g.value(n, RDFS.label)
    return str(v) if v is not None else str(n).split("#")[-1]


def named_fillers(g: rdflib.Graph, types, node, ax: Axiom, slots: set) -> list:
    cands = g.subjects(ax.prop, node) if ax.inverse else g.objects(node, ax.prop)
    return [c for c in cands if c not in slots and ax.filler in types.get(c, set())]


def slot_loop(base: rdflib.Graph, depth: int):
    g = rdflib.Graph() + base
    axs = axioms(g)
    r = reason(g)
    if not r.consistent:
        return g, [], r
    slots: list[Slot] = []
    slot_iris: set = set()
    by_iri: dict = {}
    frontier = [n for n in r.types if n not in slot_iris]
    for d in range(1, depth + 1):
        new = []
        for x in frontier:
            ts = r.types.get(x, set())
            for ax in axs:
                if ax.on not in ts:
                    continue
                if named_fillers(g, r.types, x, ax, set()):
                    continue
                parent = by_iri.get(x)
                root = parent.root if parent else x
                path = (parent.path if parent else (x,)) + (ax.iri,)
                s = URIRef(f"{YD}slot-{len(slots) + 1}")
                g.add((s, RDF.type, YD.Slot))
                g.add((s, RDF.type, ax.filler))
                g.add((s, RDFS.label, Literal(f"空位：{ax.label}")))
                g.add((s, ax.prop, x) if ax.inverse else (x, ax.prop, s))
                slot = Slot(s, d, x, ax, root, path)
                slots.append(slot)
                slot_iris.add(s)
                by_iri[s] = slot
                new.append(s)
        if not new:
            break
        r = reason(g)
        if not r.consistent:
            break
        frontier = new
    return g, slots, r


def walk(g, types, path, axmap):
    """在一份图上沿空位的路径走：每一步有名字对上就往下，对不上就停。"""
    node = path[0]
    chain = []
    for i, axi in enumerate(path[1:]):
        f = named_fillers(g, types, node, axmap[axi], set())
        if not f:
            return False, chain
        node = sorted(f)[0]
        chain.append(node)
    return True, chain


# ---------------------------------------------------------------- SHACL
P = "PREFIX yd: <https://yudao.dev/onto#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"


def in_scope(cls):
    return f"FILTER EXISTS {{ ?sc a yd:CommittedScope ; yd:covers {cls} . }}"


def out_scope(cls):
    return f"FILTER NOT EXISTS {{ ?sc a yd:CommittedScope ; yd:covers {cls} . }}"


def checks(terms, avoid):
    avoid_vals = ", ".join(f'"{w}"' for w in sorted(avoid))
    term_vals = ", ".join(f'"{w}"' for w in sorted(terms))
    return [
        # id, 说明, target, kind, pre, cond, scope class
        ("seam-sides", "每道缝写明两侧", "yd:Seam", "absence", "",
         "$this yd:side ?s1, ?s2 . FILTER(?s1 != ?s2)", "yd:Seam"),
        ("seam-status", "每道缝写明已定或未定", "yd:Seam", "absence", "", "$this yd:status ?st .", "yd:Seam"),
        ("seam-unsettled", "这道缝标为未定（写法规范第 5 条：未定就是不知道）", "yd:Seam", "unknown",
         "$this yd:status yd:status-unsettled .", "", None),
        ("watched-produced", "被关注的成果有人产出", "yd:OutcomeKind", "absence",
         "?w yd:watches $this .", "?a yd:produces $this .", "yd:OutcomeKind"),
        ("source-received", "每种事项的来源有人接", "yd:Source", "absence", "", "?a yd:receives $this .", "yd:Source"),
        ("released-has-decl", "以放行结束的成果有核验声明", "yd:ReleasedOutcomeKind", "absence", "",
         "?d yd:forOutcome $this .", "yd:VerificationDecl"),
        ("direct-can-complete", "直做形态有角色能交完成", "yd:Form", "absence", "$this yd:rotation yd:rm-direct .",
         "$this yd:canSubmitCompletion ?r .", "yd:Form"),
        ("decl-verified-produces", "被核验者就是产出被核验成果的一方", "yd:VerificationDecl", "violation",
         "$this yd:verified ?v ; yd:forOutcome ?o . ?p yd:produces ?o . FILTER NOT EXISTS { ?v yd:produces ?o }", "", None),
        ("planned", "文档写的是「以后」（写法规范第 5 条）", "yd:Department", "unknown",
         "$this yd:planned true .", "", None),
        ("planned-source", "文档写的是「以后」（写法规范第 5 条）", "yd:Source", "unknown",
         "$this yd:planned true .", "", None),
        ("verify-acyclic", "谁能拒绝谁无环", "yd:Actor", "violation",
         "$this (^yd:verifier/yd:verified)+ $this .", "", None),
        ("checkdef-per-item", "每个事项具体查什么来自检查材料，设计说明没写", "yd:CheckDefinition", "unknown",
         "$this yd:perItemFrom ?m .", "", None),
        ("halfopen-written-release", "按半开环的假定，这份核验的结论只靠读、没有主机回执，不该写成放行（假定与设计的写法冲突）",
         "yd:HalfOpenDecl", "violation",
         "$this yd:forOutcome ?o . ?o yd:completion yd:completion-release . FILTER NOT EXISTS { $this yd:hasIndependentEvidence ?e }", "", None),
        ("halfopen-depends", "这份核验有两种结论：有主机回执的算已核验，只靠读的按半开环的假定不该写成放行（这一次靠哪种，设计里看不出）",
         "yd:HalfOpenDecl", "unknown",
         "$this yd:forOutcome ?o ; yd:hasIndependentEvidence ?e . ?o yd:completion yd:completion-release .", "", None),
        ("direct-verified-can-complete", "直做形态里被核验的角色交得出完成（形态与核验角色设计说明 4.3 第 5 条，eb8429e）", "yd:VerificationDecl", "violation",
         "$this yd:inForm ?f ; yd:verified ?v . ?f yd:rotation yd:rm-direct . FILTER NOT EXISTS { ?f yd:canSubmitCompletion ?v }", "", None),
        ("form-defined", "设计里有这份形态，发布的定义文件里没有", "yd:Form", "absence",
         "FILTER EXISTS { ?any yd:definedBy ?file }", "$this yd:definedBy ?f .", "yd:Form"),
        ("name-avoid", "用了词表里写明要避免的词", "yd:Concept", "violation",
         f"$this rdfs:label ?l . FILTER(STR(?l) IN ({avoid_vals}))", "", None),
        ("name-unknown", "词表与 name-map 里都没有这个词，正名对不上", "yd:Concept", "unknown",
         f"$this rdfs:label ?l . FILTER(STR(?l) NOT IN ({term_vals}))", "", None),
    ]


def shapes_graph(terms, avoid) -> rdflib.Graph:
    sg = rdflib.Graph()
    sg.bind("sh", SH)
    sg.bind("yd", YD)
    for cid, desc, target, kind, pre, cond, scope in checks(terms, avoid):
        variants = []
        if kind == "absence":
            body = f"{pre} FILTER NOT EXISTS {{ {cond} }} FILTER NOT EXISTS {{ $this yd:planned true }}"
            variants = [("missing", SH.Warning, f"{body} {in_scope(scope)}"),
                        ("unknown", SH.Info, f"{body} {out_scope(scope)}")]
        elif kind == "violation":
            variants = [("violation", SH.Violation, pre)]
        else:
            variants = [("unknown", SH.Info, pre)]
        for suffix, sev, where in variants:
            s = YD[f"shape-{cid}-{suffix}"]
            c = BNode()
            sg.add((s, RDF.type, SH.NodeShape))
            sg.add((s, SH.targetClass, URIRef(YD + target.split(":")[1])))
            sg.add((s, SH.severity, sev))
            sg.add((s, RDFS.label, Literal(desc, lang="zh")))
            sg.add((s, SH.sparql, c))
            sg.add((c, RDF.type, SH.SPARQLConstraint))
            sg.add((c, SH.message, Literal(desc, lang="zh")))
            sg.add((c, SH.select, Literal(P + f"SELECT $this WHERE {{ {where} }}")))
    return sg


SEV = {SH.Violation: "违例", SH.Warning: "确实缺", SH.Info: "不知道"}


def run_shacl(data: rdflib.Graph, shapes: rdflib.Graph):
    from pyshacl import validate
    _, rg, _ = validate(data, shacl_graph=shapes, inference="none", advanced=True, allow_warnings=True)
    out = []
    for r in rg.subjects(RDF.type, SH.ValidationResult):
        shape = rg.value(r, SH.sourceShape)
        out.append({
            "result": SEV[rg.value(r, SH.resultSeverity)],
            "check": str(shape).split("shape-")[-1].rsplit("-", 1)[0],
            "focus": str(rg.value(r, SH.focusNode)).split("#")[-1],
            "label": label(data, rg.value(r, SH.focusNode)),
            "message": str(rg.value(r, SH.resultMessage)),
        })
    return sorted(out, key=lambda x: (x["result"], x["check"], x["focus"]))


def materialize(g: rdflib.Graph, types) -> rdflib.Graph:
    m = rdflib.Graph() + g
    for n, ts in types.items():
        for t in ts:
            m.add((n, RDF.type, t))
    return m


# ---------------------------------------------------------------- 一批
@dataclass
class BatchResult:
    batch: int
    consistent: bool
    unsat: list
    classified: dict
    shacl: list
    slots: list
    error: str = ""


def run_batch(n: int, depth: int, replace=None, assumptions=True, extra=None) -> tuple[BatchResult, rdflib.Graph, Reasoned]:
    base = load(files_upto(n, assumptions), replace)
    if extra is not None:
        extra(base)
    compile_axioms(base)
    r0 = reason(base)
    if not r0.consistent:
        return BatchResult(n, False, [], {}, [], [], r0.error), base, r0
    terms, avoid = canonical_names()
    sh = run_shacl(materialize(base, r0.types), shapes_graph(terms, avoid))
    classified = {}
    for cls in (YD.VerifierRole, YD.VerifiedForm, YD.ReleasedOutcomeKind, YD.CollaboratingDepartment, YD.HalfOpenDecl):
        classified[label(base, cls)] = sorted(label(base, i) for i, ts in r0.types.items() if cls in ts)
    _, slots, rs = slot_loop(base, depth)
    return BatchResult(n, True, r0.unsat, classified, sh, slots, "" if rs.consistent else rs.error), base, r0


def slot_row(g, s: Slot):
    names = [label(g, s.path[0])] + [label(g, a) for a in s.path[1:]]
    return {"slot": str(s.iri).split("#")[-1], "depth": s.depth, "root": label(g, s.root),
            "path": " → ".join(names), "axiom": s.axiom.label, "basis": s.axiom.basis,
            "key": [str(x) for x in s.path]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", type=int, default=max(BATCHES))
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--out", default=str(HERE / "reports"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    terms, avoid = canonical_names()
    shapes_graph(terms, avoid).serialize(HERE / "onto/shapes.ttl", format="turtle")
    results = {}
    graphs = {}
    for n in range(0, a.upto + 1):
        br, g, r = run_batch(n, a.depth)
        graphs[n] = (g, r)
        results[n] = {
            "batch": n, "consistent": br.consistent, "unsat": br.unsat, "error": br.error,
            "classified": br.classified, "shacl": br.shacl,
            "slots": [slot_row(g, s) for s in br.slots],
        }
        print(f"batch {n}: consistent={br.consistent} unsat={len(br.unsat)} shacl={len(br.shacl)} slots={len(br.slots)}")
    # 空位追踪：每个空位在后面各批走一遍。后面一批里，以「填上了前面空位的那个有名字的节点」为根的空位，
    # 就是前面那个空位往下的一层，记在原来那一行，不另起一行。
    track = []
    alias = {}  # (批, 节点) -> 早先的路径前缀
    for n in sorted(results):
        g0, _ = graphs[n]
        for row in results[n]["slots"]:
            key = tuple(URIRef(k) for k in row["key"])
            pref = alias.get((n, key[0]))
            full = (pref + key[1:]) if pref else key
            if any(t["key"] == full for t in track):
                continue
            entry = {"born": n, "path": row["path"], "depth": len(full) - 1, "axiom": row["axiom"],
                     "filled_in": None, "filled_by": None, "partial": None, "key": full}
            if pref:
                entry["path"] = " → ".join([label(g0, full[0])] + [label(g0, a) for a in full[1:]])
            for m in sorted(results):
                if m <= n:
                    continue
                gm, rm = graphs[m]
                if not rm.consistent:
                    continue
                axmap = {ax.iri: ax for ax in axioms(gm)}
                ok, chain = walk(gm, rm.types, full, axmap)
                for i, c in enumerate(chain):
                    alias[(m, c)] = full[: i + 2]
                if ok:
                    entry["filled_in"] = m
                    entry["filled_by"] = " → ".join(label(gm, c) for c in chain)
                    break
                if chain:
                    entry["partial"] = {"batch": m, "upto": " → ".join(label(gm, c) for c in chain)}
            track.append(entry)
    for t in track:
        t["key"] = [str(x) for x in t["key"]]
    (out / "results.json").write_text(json.dumps({"batches": results, "tracking": track}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"tracking rows: {len(track)}")


if __name__ == "__main__":
    main()
