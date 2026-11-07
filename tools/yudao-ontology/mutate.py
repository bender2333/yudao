"""检验模型本身之一：在副本上埋错，看检查能不能查出、落在哪一栏。

不动 batches/ 里的原文件：每种改法在内存里改一份图再跑同一套推理与 SHACL。
「改一个名字」模拟的是文档副本里换了一个词、重新抽取以后标签变了。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

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
    ("source-unreceived", 2, "来源没人接", "删掉「工程架构师接上一层交来的任务」这一条",
     lambda g: g.remove((YD["role-eng-architect"], YD.receives, YD["src-subtask"])), ("确实缺", "source-received")),
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


def main():
    rows = []
    base = {}
    for b in (1, 2):
        br, g, _ = run.run_batch(b, 3)
        base[b] = outcome(br, g)
        assert base[b]["kind"] == "一致", f"原样的第 {b} 批不一致"
        bad = [h for h in base[b]["shacl"] if h.startswith(("违例", "确实缺"))]
        rows.append({"id": f"control-b{b}", "batch": b, "name": "不改（对照）", "how": "原样跑一次",
                     "expected": "没有违例、没有确实缺", "got": "；".join(bad) or "没有违例、没有确实缺", "detected": not bad})
    for mid, b, name, how, fn, exp in MUTATIONS:
        br, g, _ = run.run_batch(b, 3, extra=fn)
        res = outcome(br, g)
        new = ([res["detail"]] if res["kind"] == "不一致" else
               sorted(set(res["shacl"]) - set(base[b]["shacl"])) + ["空位：" + s for s in sorted(set(res["slots"]) - set(base[b]["slots"]))])
        ok = judged(exp, res, base[b])
        rows.append({"id": mid, "batch": b, "name": name, "how": how, "expected": "：".join(x for x in exp if x),
                     "got": res["kind"] + ("；" + "；".join(new[:4]) if new else ""), "detected": ok})
        print(("OK  " if ok else "MISS"), b, name, "|", rows[-1]["got"][:150])
    (HERE / "reports/mutations.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
