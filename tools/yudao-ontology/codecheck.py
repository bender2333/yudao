"""第 4 批：代码。把某个提交里的代码事实转写成 Turtle，再用 SHACL 查三件事：

1. 分层：内核模块（kernel-manifest.json 里 kind 为 module 的文件）的判断里出现部门名或成果种类名，记违例。
   形态与核验角色设计说明验收第 3 条「事实与裁决、循环两层的代码里不出现部门名，也不出现 PRD、交付、质检结论这些成果种类的判断」。
   只看判断：比较（== != in）的操作数、Literal[...] 的取值（一个 Literal 里有两个以上才算）、模块顶层写死的集合。
   报错文字、文档字符串、注释不算。
2. name-map 落后于代码：name-map 里状态写「代码里还没有」的词，已经是定义文件里某一项的显示名（label），记违例。
3. 事项的来源：组织定义没有来源一项时记不知道（还没承诺）；有，就查每一种来源的部门在定义里。
4. 总图的词有没有对照：第 1 批里的概念（总图的词），name-map 里没有它这一行，记不知道（代码里有没有，这张表没说）。
   对照表少一行只能让结果退到不知道，不能变成确实缺：确实缺只给声明过的闭合范围。

用法：python3 codecheck.py <提交>...（默认 eb8429e），结果写 reports/codecheck.json；
batches/batch4-code.ttl 是 eb8429e 的转写，由本脚本生成，不手改。只读仓库。
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, BNode, Literal

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
YD = rdflib.Namespace("https://yudao.dev/onto#")
SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
DEFAULT = "eb8429e"


def git(*args) -> str:
    out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def show(commit, path):
    return git("show", f"{commit}:{path}")


def kernel_modules(commit) -> list[str]:
    m = json.loads(show(commit, "harness/definitions/kernel-manifest.json") or '{"paths": []}')
    return [p["path"] for p in m["paths"] if p.get("kind", "module") == "module" and p["path"].endswith(".py")]


def banned_names(commit) -> dict[str, str]:
    """部门名与成果种类名 → 它是什么。取这个提交的定义；那时还没有成果种类定义的，用 eb8429e 的（报告里写明）。"""
    out = {}
    org = json.loads(show(commit, "harness/definitions/organization.json") or "{}")
    for d in org.get("departments", []):
        out[d["id"]] = "部门名"
    kinds = show(commit, "harness/definitions/outcome_kinds.json") or show(DEFAULT, "harness/definitions/outcome_kinds.json")
    for k in json.loads(kinds)["kinds"]:
        out[k["id"]] = "成果种类名"
    return out


class Judgements(ast.NodeVisitor):
    """收集判断里用到的字符串：比较的操作数、Literal[...] 的取值、模块顶层写死的集合。"""

    def __init__(self):
        self.hits: list[tuple[int, str, str]] = []
        self.depth = 0

    def _strings(self, node, where):
        for n in ast.walk(node):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                self.hits.append((n.lineno, n.value, where))

    def visit_Compare(self, node):
        for n in [node.left, *node.comparators]:
            if isinstance(n, (ast.Constant, ast.Set, ast.Tuple, ast.List)):
                self._strings(n, "比较")
        self.generic_visit(node)

    def visit_Subscript(self, node):
        name = node.value.attr if isinstance(node.value, ast.Attribute) else getattr(node.value, "id", "")
        if name == "Literal":
            # 一个 Literal 里只撞上一个名字（例如规则种类 Literal["parameter", "structure"] 的 structure）多半是同名，
            # 列出两个以上的部门名或成果种类名才算写死了一张表；在 layer_uses 里按 where 收紧
            self._strings(node.slice, f"Literal@{node.lineno}")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_Assign(self, node):
        if self.depth == 0 and isinstance(node.value, (ast.Set, ast.Tuple, ast.List, ast.Dict, ast.Call)):
            target = node.targets[0]
            if isinstance(target, ast.Name):
                self._strings(node.value, f"顶层集合 {target.id}")
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if self.depth == 0 and node.value is not None and isinstance(node.value, (ast.Set, ast.Tuple, ast.List, ast.Dict, ast.Call)):
            target = node.target
            if isinstance(target, ast.Name):
                self._strings(node.value, f"顶层集合 {target.id}")
        self.generic_visit(node)


def layer_uses(source: str, banned: dict[str, str]) -> list[tuple[int, str, str, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    v = Judgements()
    v.visit(tree)
    seen = set()
    out = []
    lit = {}
    for line, s, where in v.hits:
        if where.startswith("Literal@") and s in banned:
            lit.setdefault(where, set()).add(s)
    for line, s, where in v.hits:
        if where.startswith("Literal@"):
            if len(lit.get(where, ())) < 2:
                continue
            where = "Literal"
        if s in banned and (line, s) not in seen:
            seen.add((line, s))
            out.append((line, s, banned[s], where))
    return sorted(out)


def labels_in_definitions(commit) -> dict[str, str]:
    out = {}
    files = [f for f in git("ls-tree", "-r", "--name-only", commit, "harness/definitions").split() if f.endswith(".json")]
    for f in files:
        try:
            data = json.loads(show(commit, f))
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if isinstance(x.get("label"), str):
                    out.setdefault(x["label"], f)
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return out


def name_map_rows(commit) -> list[tuple[str, str]]:
    text = show(commit, "docs/design/architecture/name-map.md")
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0] not in ("总图的词", "---") and not set(cells[0]) <= set("-: "):
            rows.append((cells[0], cells[-1]))
    return rows


def total_terms() -> list[str]:
    """第 1 批里的概念（c-* 个体）的标签，就是总图的词。"""
    sys.path.insert(0, str(HERE))
    import run
    g = run.load([HERE / "onto/core.ttl"] + [HERE / f for f in run.BATCHES[1]])
    return sorted({str(o) for s, o in g.subject_objects(RDFS.label) if str(s).split("#")[-1].startswith("c-")})


def facts(commit, override: dict[str, str] | None = None, drop_rows: set | None = None) -> rdflib.Graph:
    """override：路径 → 改过的源码（变异用）；drop_rows：从 name-map 里去掉的词（变异用）。"""
    g = rdflib.Graph()
    g.bind("yd", YD)
    banned = banned_names(commit)
    n = 0
    for path in kernel_modules(commit):
        src = (override or {}).get(path) or show(commit, path)
        M = YD["mod-" + re.sub(r"[^A-Za-z0-9]+", "-", path)]
        g.add((M, RDF.type, YD.KernelModule))
        g.add((M, RDFS.label, Literal(path)))
        for line, s, kind, where in layer_uses(src, banned):
            n += 1
            U = YD[f"use-{n}"]
            g.add((U, RDF.type, YD.NameUse))
            g.add((U, RDFS.label, Literal(f"{path}:{line} {where}里的「{s}」（{kind}）")))
            g.add((M, YD.judgesByName, U))
    labels = labels_in_definitions(commit)
    for i, (term, status) in enumerate(name_map_rows(commit)):
        if drop_rows and term in drop_rows:
            continue
        R = YD[f"nm-{i}"]
        g.add((R, RDF.type, YD.NameMapRow))
        g.add((R, RDFS.label, Literal(term)))
        g.add((R, YD.nmStatus, Literal(status)))
        bare = re.sub(r"[（(].*?[）)]", "", term).strip()
        for t in {term, bare}:
            if t in labels:
                g.add((R, YD.labelInDefinitions, Literal(f"{labels[t]}（label「{t}」）")))
    mapped = {re.sub(r"[（(].*?[）)]", "", t).strip() for t, _ in name_map_rows(commit)
              if not (drop_rows and t in drop_rows)} | {t for t, _ in name_map_rows(commit) if not (drop_rows and t in drop_rows)}
    for i, term in enumerate(total_terms()):
        T = YD[f"term-{i}"]
        g.add((T, RDF.type, YD.TotalTerm))
        g.add((T, RDFS.label, Literal(term)))
        if term in mapped:
            g.add((T, YD.mappedInNameMap, Literal(True)))
    org = json.loads(show(commit, "harness/definitions/organization.json") or "{}")
    O = YD["def-organization"]
    g.add((O, RDF.type, YD.OrganizationDefinition))
    g.add((O, RDFS.label, Literal("harness/definitions/organization.json")))
    members = {d["id"] for d in org.get("departments", [])}
    if "sources" in org:
        g.add((O, YD.declaresSources, Literal(True)))
        for src, dep in org["sources"].items():
            S = YD[f"defsrc-{src}"]
            g.add((S, RDF.type, YD.DefinitionSource))
            g.add((S, RDFS.label, Literal(src)))
            g.add((O, YD.hasSource, S))
            if dep in members:
                g.add((S, YD.receivedByMember, Literal(dep)))
    return g


P = "PREFIX yd: <https://yudao.dev/onto#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
CHECKS = [
    ("layer-name", "内核模块的判断里出现部门名或成果种类名（分层，验收第 3 条）", "yd:KernelModule", SH.Violation,
     "$this yd:judgesByName ?u ."),
    ("namemap-stale", "name-map 写「代码里还没有」，定义文件里已经有这一项", "yd:NameMapRow", SH.Violation,
     "$this yd:nmStatus ?s ; yd:labelInDefinitions ?f . FILTER(CONTAINS(STR(?s), \"还没有\"))"),
    ("sources-uncommitted", "组织定义还没有事项的来源一项（还没承诺，不算缺）", "yd:OrganizationDefinition", SH.Info,
     "FILTER NOT EXISTS { $this yd:declaresSources true }"),
    ("term-unmapped", "总图的这个词在 name-map 里没有一行，代码里有没有不知道", "yd:TotalTerm", SH.Info,
     "FILTER NOT EXISTS { $this yd:mappedInNameMap true }"),
    ("source-member", "定义里这种来源没有本定义里的部门接", "yd:DefinitionSource", SH.Warning,
     "FILTER NOT EXISTS { $this yd:receivedByMember ?d }"),
]
SEV = {SH.Violation: "违例", SH.Warning: "确实缺", SH.Info: "不知道"}


def shapes() -> rdflib.Graph:
    sg = rdflib.Graph()
    for cid, desc, target, sev, where in CHECKS:
        s, c = YD[f"shape-{cid}"], BNode()
        sg.add((s, RDF.type, SH.NodeShape))
        sg.add((s, SH.targetClass, YD[target.split(":")[1]]))
        sg.add((s, SH.severity, sev))
        sg.add((s, SH.sparql, c))
        sg.add((c, RDF.type, SH.SPARQLConstraint))
        sg.add((c, SH.message, Literal(desc, lang="zh")))
        sg.add((c, SH.select, Literal(P + f"SELECT $this WHERE {{ {where} }}")))
    return sg


def check(g: rdflib.Graph) -> list[dict]:
    from pyshacl import validate
    _, rg, _ = validate(g, shacl_graph=shapes(), inference="none", advanced=True, allow_warnings=True)
    out = []
    for r in rg.subjects(RDF.type, SH.ValidationResult):
        f = rg.value(r, SH.focusNode)
        cid = str(rg.value(r, SH.sourceShape)).split("shape-")[-1]
        detail = []
        if cid == "layer-name":
            detail = sorted(str(g.value(u, RDFS.label)) for u in g.objects(f, YD.judgesByName))
        elif cid == "namemap-stale":
            detail = [str(x) for x in g.objects(f, YD.labelInDefinitions)]
        out.append({"result": SEV[rg.value(r, SH.resultSeverity)], "check": cid,
                    "focus": str(g.value(f, RDFS.label)), "detail": detail})
    return sorted(out, key=lambda x: (x["check"], x["focus"]))


def main(argv):
    commits = argv or [DEFAULT]
    res = {}
    for c in commits:
        g = facts(c)
        if c == DEFAULT:
            (HERE / "batches/batch4-code.ttl").write_text(
                f"# 第 4 批：{DEFAULT} 的代码事实，由 codecheck.py 生成，不手改。\n" + g.serialize(format="turtle"), encoding="utf-8")
        res[c] = check(g)
        print(c, len(res[c]))
        for r in res[c]:
            print("  ", r["result"], r["check"], r["focus"], r["detail"][:6])
    (HERE / "reports/codecheck.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
