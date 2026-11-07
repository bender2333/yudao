"""第 3 批：发布带的形态的定义文件 → batches/batch3-definitions.ttl。

定义文件是结构化的 JSON，这一批不用模型抽取，由这个脚本按固定的对应关系转写，所以也不做两次抽取对照；
转写对不对，由 mutate.py 的第 3 批埋错与本脚本末尾的计数核对来查。
用法：python3 defs.py [提交]（默认 origin/main）。只读仓库。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import rdflib
from rdflib import RDF, RDFS, Literal

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
YD = rdflib.Namespace("https://yudao.dev/onto#")

# 形态的名字（runtime.py 的 FORM_REGISTRY）→ 定义目录 → 前两批里的个体
FORMS = {
    "default": ("harness/definitions/", "form-default"),
    "single_role_direct": ("harness/definitions/forms/single_role_direct/", "form-min"),
    "several_roles_direct": ("harness/definitions/forms/several_roles_direct/", "form-several"),
}
# 每份形态里的部门 → 前两批里的承担者
ACTORS = {
    "form-default": {"product": "dept-product", "engineering": "dept-engineering", "quality": "dept-quality"},
    "form-min": {"engineering": "role-min"},
    "form-several": {"product": "role-sev-product", "engineering": "role-sev-engineering"},
}
# 成果种类 → 前两批里的个体；没列的新建
KINDS = {
    # delivery 与 defect_record 不是 outcome_kinds.json 里的成果种类，是成果驱动路由自己认得的名字
    # （definitions/__init__.py 的 watched_output_issues 注释）；user_input 是事项的来源，产品关注它，总图叫「意图」
    "form-default": {"delivery_spec": "ok-delivery", "delivery": "ok-delivery", "product_spec": "ok-prd",
                     "guidance": "ok-guidance", "defect_record": "ok-defect", "user_input": "ok-intent"},
    "form-min": {"completion": "ok-min-completion", "guidance": "ok-guidance"},
    "form-several": {"completion": "ok-sev-completion", "guidance": "ok-guidance"},
}
ROTATION = {"watched_outputs": "rm-by-outcome", "direct": "rm-direct"}
SOURCES = {"user_input": "src-user-input", "onboarding": "src-onboarding"}
# 前两批已有、名字对得上的核验声明
DECLS = {("form-default", "quality", "engineering"): "decl-default-quality"}


def show(commit: str, path: str):
    out = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{path}"], capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 else None


def convert(commit: str) -> tuple[rdflib.Graph, dict]:
    g = rdflib.Graph()
    g.bind("yd", YD)
    count = {"forms": 0, "decls": 0, "produces": 0, "receives": 0, "watches": 0, "complete": 0}
    for name, (folder, form) in FORMS.items():
        org = show(commit, folder + "organization.json")
        routes = show(commit, folder + "routings.json")
        kinds = show(commit, folder + "outcome_kinds.json")
        work = show(commit, folder + "work_items.json")
        tools = show(commit, folder + "tools.json") or show(commit, "harness/definitions/tools.json")
        F = YD[form]
        count["forms"] += 1
        g.add((F, YD.definedBy, Literal(folder + "organization.json")))
        g.add((F, YD.batch, Literal(3)))
        actors = ACTORS[form]
        kindmap = dict(KINDS[form])
        for k in kinds["kinds"]:
            iri = kindmap.setdefault(k["id"], f"ok-def-{form[5:]}-{k['id'].replace('_', '-')}")
            K = YD[iri]
            if (K, RDF.type, YD.OutcomeKind) not in g:
                g.add((K, RDF.type, YD.OutcomeKind))
            if iri.startswith("ok-def-"):
                g.add((K, RDFS.label, Literal(f"{k['label']}（{name}）", lang="zh")))
            g.add((K, YD.inForm, F))
            g.add((K, YD.docRef, Literal(folder + "outcome_kinds.json")))
        route = next(r for r in routes["routings"] if r["id"] == org["routing"])
        g.add((F, YD.rotation, YD[ROTATION[route["id"]]]))
        if route.get("final_outcome"):
            g.add((F, YD.finalOutcome, YD[kindmap[route["final_outcome"]]]))
        for src, dep in org["sources"].items():
            g.add((YD[actors[dep]], YD.receives, YD[SOURCES[src]]))
            count["receives"] += 1
        tl = tools.get("tools", tools)
        tl = tl.items() if isinstance(tl, dict) else [(t["id"], t) for t in tl]
        proposal = {k: v.get("proposal") for k, v in tl if v.get("kind") == "host" and v.get("proposal")}
        granted: dict[str, set] = {}
        for kind in work["kinds"].values():
            for dep, w in kind.get("departments", {}).items():
                granted.setdefault(dep, set()).update(w.get("tools", []))
        for dep, names in granted.items():
            A = YD[actors[dep]]
            for tool in sorted(names):
                if tool in proposal and proposal[tool] in kindmap:
                    g.add((A, YD.produces, YD[kindmap[proposal[tool]]]))
                    count["produces"] += 1
            if route["id"] == "direct" and "submit_completion" in names:
                g.add((F, YD.canSubmitCompletion, A))
                count["complete"] += 1
        for d in org["departments"]:
            A = YD[actors[d["id"]]]
            g.add((A, YD.docRef, Literal(folder + "organization.json")))
            for w in d.get("watched", []):
                if w in kindmap:
                    g.add((A, YD.watches, YD[kindmap[w]]))
                    count["watches"] += 1
            for field in ("target", "evidence", "work"):
                if d.get(field):
                    raise SystemExit(f"{form} 的 {d['id']} 写了 {field}，转写还没处理，先补对应关系")
        for v in (org.get("verification") or {}).get("verifiers", []):
            for target in v["verifies"]:
                iri = DECLS.get((form, v["role"], target["role"]), f"decl-def-{form[5:]}-{v['role']}-{target['role']}")
                D = YD[iri]
                g.add((D, RDF.type, YD.VerificationDecl))
                g.add((D, YD.verifier, YD[actors[v["role"]]]))
                g.add((D, YD.verified, YD[actors[target["role"]]]))
                g.add((D, YD.inForm, F))
                for o in target["outcomes"]:
                    g.add((D, YD.forOutcome, YD[kindmap[o]]))
                g.add((D, YD.docRef, Literal(folder + "organization.json")))
                count["decls"] += 1
            scope = (org["verification"].get("write_scopes") or {}).get(v["role"])
            if scope and scope.get("paths"):
                # eb8429e 的 4.1 第 1 条说定义不另选位置；这份定义写了位置，记下，第 4 批对代码时看加载拒不拒绝
                g.add((F, YD.notModeled, Literal(
                    f"{v['role']} 的检查材料写入范围在定义里写了位置 {scope['paths']}", lang="zh")))
    return g, count


def main(argv):
    commit = argv[0] if argv else "origin/main"
    g, count = convert(commit)
    head = (f"# 第 3 批：发布带的三份形态的定义文件，由 defs.py 从 {commit} 转写，不手改。\n"
            "# 形态目录、部门与成果种类到前两批个体的对应写在 defs.py 开头。\n")
    out = HERE / "batches/batch3-definitions.ttl"
    out.write_text(head + g.serialize(format="turtle"), encoding="utf-8")
    print(commit, count)


if __name__ == "__main__":
    main(sys.argv[1:])
