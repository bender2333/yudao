"""变动影响清单：模型对齐的提交到这次的提交之间改了什么、波及模型里哪些概念、哪里还没跟上。

记下来：模型读的文档每份加减几行；推出的改名（renames.py）；对不上的原句一句句归类：
  换词接上（候选换进去以后新文档里真有这句，不用确认）、改写（新文档里有一句很像，给出候选，人判意思变没变）、删掉。
覆盖检查：改写与删掉的原句 → 模型里引它的个体 → 这些个体还被哪些原句引、定义文件与代码生成的事实有没有变；
  确定的改名 → 全仓哪些文件还用旧词（记录类文件默认不查）。
再和对齐那一版的「该做什么了」输出比，四类结论里新冒出来的、消失的。

用法：python3 changes.py <对齐的提交> <这次的提交>（next.py 会调它）；写 reports/changes/<旧>..<新>.md 与 .json。
只读仓库，不改模型；接原句写回模型由 heal.py 做。
"""
from __future__ import annotations

import difflib
import itertools
import json
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict
from pathlib import Path

import rdflib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import quotecheck  # noqa: E402
import renames  # noqa: E402

REPO = Path(os.environ.get("YUDAO_REPO", HERE.parent.parent))
YD = rdflib.Namespace("https://yudao.dev/onto#")
RDFS = rdflib.RDFS
HAND = ["batch0-axioms.ttl", "batch1-overview.ttl", "batch1-assumptions.ttl", "batch1-scope.ttl",
        "batch2-design.ttl", "batch2-eb8429e.ttl", "batch2-assumptions.ttl", "batch2-scope.ttl",
        "batch2-contested.ttl", "batch3-assumptions.ttl", "batch3-scope.ttl"]
# 记录类文件写的是历史，旧说法留着是对的，覆盖检查不查。这是工具的设置，不是谁要记的东西
HISTORY = ["docs/adr/", "docs/archive/", "docs/prototypes/", "docs/decision.md", "docs/CHANGELOG.md",
           "claude_jour.md", "agents_jour/", ".doc-index/", "docs/evaluation/", "tools/yudao-ontology/"]
REWORD = 0.6  # 新文档里最像的一句和旧原句的相似度，到这个数算改写，不到算删掉


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout


def model_docs() -> list[str]:
    return ["docs/architecture.html"] + sorted(set(quotecheck.DOCS.values()))


def doc_text(commit: str, paths: list[str]) -> tuple[str, str, list[int]]:
    """原文（去标签）、去掉空白与强调记号的文本，和后者每个字在原文里的位置。"""
    raw = "\n".join(quotecheck.html_text(t) if p.endswith(".html") else t
                    for p in paths for t in [quotecheck.show(commit, p)])
    keep = [i for i, ch in enumerate(raw) if not (ch.isspace() or ch in "*`")]
    return raw, "".join(raw[i] for i in keep), keep


def _found(q: str, text: str) -> bool:
    return all(quotecheck.norm(x) in text for part in q.split("……") for x in part.split("；") if quotecheck.norm(x))


def heal_one(quote: str, text: str, cands: list[tuple[str, str]]):
    """试候选的组合（最多 4 个，同一个旧词只取一种换法），换完新文档里真有这句才算接上。"""
    rel = [c for c in cands if c[0] in quote]
    for k in range(1, min(4, len(rel)) + 1):
        for combo in itertools.combinations(rel, k):
            if len({c[0] for c in combo}) < k:
                continue
            q = quote
            for o, n in sorted(combo, key=lambda c: -len(c[0])):
                q = q.replace(o, n)
            if q != quote and _found(q, text):
                return q, list(combo)
    return None, []


def nearest(quote: str, raw: str, text: str, keep: list[int], cands: list[tuple[str, str]]):
    """新文档里和旧原句最像的一句：先按确定的改名换一遍再比；返回（相似度，原文里那一句）。"""
    q = quote.split("……")[0]
    for o, n in cands:
        q = q.replace(o, n)
    q = quotecheck.norm(q)
    if not q:
        return 0.0, ""
    best, at = 0.0, 0
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(q)
    for i in range(0, max(1, len(text) - len(q) // 2), 2):
        sm.set_seq1(text[i:i + len(q) + 8])
        if sm.real_quick_ratio() <= best or sm.quick_ratio() <= best:
            continue
        r = sm.ratio()
        if r > best:
            best, at = r, i
    if not keep or not best:
        return best, ""
    # 只取窗口里真对上的那一段：第一个与最后一个对上的块（至少两个字）
    sm.set_seq1(text[at:at + len(q) + 8])
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
    if not blocks:
        return best, ""
    s, e = keep[at + blocks[0].a], keep[min(at + blocks[-1].a + blocks[-1].size - 1, len(keep) - 1)]
    tail = e
    while tail < len(raw) - 1 and tail - e < 4 and raw[tail + 1] not in "。！？\n|":
        tail += 1
    if tail + 1 < len(raw) and raw[tail + 1] in "。！？":
        e = tail + 1
    return best, re.sub(r"\s+", " ", raw[s:e + 1]).strip(" |")


def hand_literals() -> list[tuple[str, str, str]]:
    """手写的几批里的标签、docRef（文件，谓词，文字）。"""
    out = []
    for f in HAND:
        p = HERE / "batches" / f
        if p.exists():
            for m in re.finditer(r'(rdfs:label|yd:docRef)\s+"((?:[^"\\]|\\.)*)"', p.read_text(encoding="utf-8")):
                out.append((f, m.group(1), m.group(2)))
    return out


def model_graph() -> rdflib.Graph:
    g = rdflib.Graph()
    for f in sorted((HERE / "batches").glob("*.ttl")):
        if f.name != "batch2-contested.ttl":
            g.parse(f)
    return g


def label(g: rdflib.Graph, n) -> str:
    return str(g.value(n, RDFS.label) or str(n).split("#")[-1])


def generated(commit: str) -> set[str]:
    """定义文件与代码生成的事实，按标签写成一行一句，方便两个提交比。"""
    import codecheck
    import defs
    out = set()
    for g in (defs.convert(commit)[0], codecheck.facts(commit)):
        for s, p, o in g:
            if p == RDFS.label:
                continue
            show = lambda x: label(g, x) if isinstance(x, rdflib.URIRef) else str(x)  # noqa: E731
            out.add(f"{show(s)} {str(p).split('#')[-1]} {show(o)}")
    return out


def coverage(commit: str, words: list[tuple[str, str]]) -> list[dict]:
    """确定的改名：全仓哪些文件还用旧词。记录类文件不查；术语表的 _Avoid_ 行、同一行里新旧都有的（在说这次改名）不算。"""
    rows = []
    for o, n in words:
        hits: dict[str, list[int]] = OrderedDict()
        for line in git("grep", "-n", "-F", o, commit, "--").splitlines():
            m = re.match(rf"{commit}:([^:]+):(\d+):(.*)$", line)
            if not m:
                continue
            path, no, txt = m.group(1).strip('"'), int(m.group(2)), m.group(3)
            if any(path.startswith(h) for h in HISTORY) or txt.lstrip().startswith("_Avoid_") or n in txt:
                continue
            hits.setdefault(path, []).append(no)
        area = Counter()
        for path, lines in hits.items():
            top = path.split("/")[0] if "/" in path else path
            if path.startswith("docs/"):
                top = "/".join(path.split("/")[:2]) if path.count("/") > 1 else path
            area[top] += len(lines)
        rows.append({"from": o, "to": n, "files": len(hits), "lines": sum(len(v) for v in hits.values()),
                     "areas": area.most_common(), "first": [(p, v[:3]) for p, v in list(hits.items())[:8]]})
    return rows


def impact(old: str, new: str) -> dict:
    docs = model_docs()
    num = [l.split("\t") for l in git("diff", "--numstat", old, new, "--", *docs, "CONTEXT.md").splitlines() if l]
    record = [{"doc": p, "added": int(a), "removed": int(r)} for a, r, p in num if a.isdigit()]
    cand_rows = renames.infer(old, new, docs)
    sure = renames.accepted(cand_rows)
    cands = [(r["from"], r["to"]) for r in cand_rows if r["status"] != "不是"]

    # 原句
    qrows = quotecheck.check(new)
    stale = [r for r in qrows if r["found"] is False]
    texts: dict[str, tuple] = {}
    healed, reworded, deleted, used = [], [], [], Counter()
    for r in stale:
        if r["doc"] not in texts:
            texts[r["doc"]] = doc_text(new, r["doc"].split("、"))
        raw, text, keep = texts[r["doc"]]
        q2, combo = heal_one(r["quote"], text, cands)
        if q2:
            healed.append({**r, "new": q2, "by": combo})
            used.update(combo)
            continue
        score, sent = nearest(r["quote"], raw, text, keep, sure + [k for k in used if k not in sure])
        (reworded if score >= REWORD else deleted).append({**r, "score": round(score, 2), "candidate": sent})

    # 候选里要点的只有模型用得上的：接上过原句的，或者手写的标签、docRef 里有旧词的
    lits = hand_literals()
    for row in cand_rows:
        key = (row["from"], row["to"])
        row["healed"] = used.get(key, 0)
        row["in_labels"] = sum(1 for _, _, t in lits if row["from"] in t)
        # 要点的只有模型用得上的：接上过原句（在模型的句子里证明过），或者正是某个个体的名字（标签就是它，或以它开头再带括号）
        named = any(t == row["from"] or t.startswith(row["from"] + "（") for _, p, t in lits if p == "rdfs:label")
        row["matters"] = bool(row["healed"]) or (named and row["count"] >= 3)
    chosen = {o for o, _ in sure}  # 同一个旧词已经确认了一种新说法，别的说法不再问
    ask = [r for r in cand_rows if r["status"] == "要确认" and r["matters"] and r["from"] not in chosen]
    labels = [(f, p, t) for f, p, t in lits if any(o in t for o, _ in sure)]

    # 概念：改写与删掉的原句挂在哪些个体上，它们还被哪些原句引、模型里有几条断言
    g = model_graph()
    by_quote = {r["quote"]: r for r in qrows}
    concepts = OrderedDict()
    for r in reworded + deleted:
        s = YD[r["subject"]]
        if r["subject"] in concepts:
            continue
        others = [str(q) for q in g.objects(s, YD.quote) if str(q) != r["quote"]]
        concepts[r["subject"]] = {
            "subject": r["subject"], "label": label(g, s),
            "triples": len(list(g.triples((s, None, None)))) + len(list(g.triples((None, None, s)))),
            "other_quotes": [{"quote": q[:60], "found": by_quote.get(q, {}).get("found")} for q in others]}

    # 定义文件与代码生成的事实
    ga, gb = generated(old), generated(new)
    gen = {"added": sorted(gb - ga), "removed": sorted(ga - gb)}

    # 四类结论和对齐那一版比
    prev = HERE / "reports" / "next" / f"{git('rev-parse', '--short', old).strip()}.json"
    diff4 = None
    if prev.exists():
        diff4 = {"prev": prev.name}
    return {"old": old, "new": new, "record": record, "candidates": cand_rows, "ask": ask,
            "quotes": len(qrows), "stale": len(stale), "healed": healed, "reworded": reworded, "deleted": deleted,
            "labels": [{"file": f, "pred": p, "text": t} for f, p, t in labels],
            "concepts": list(concepts.values()), "generated": gen,
            "coverage": coverage(new, [x for x in sure if len(x[0]) >= 2]), "diff4": diff4}


def compare_found(prev: dict, cur: dict) -> dict:
    """两份「该做什么了」的四类结论：按标题比，新冒出来的与消失的。"""
    out = {}
    for k in ("一", "二", "三", "四"):
        a = {x["title"] for x in prev["found"][k]}
        b = {x["title"] for x in cur["found"][k]}
        out[k] = {"new": sorted(b - a), "gone": sorted(a - b)}
    return out


def render(r: dict) -> str:
    out = [f"# 变动影响清单 · {r['old']} → {r['new']}", ""]
    add = sum(x["added"] for x in r["record"])
    rem = sum(x["removed"] for x in r["record"])
    out.append(f"## 记下来：改了什么")
    out.append(f"模型读的文档与术语表：{len(r['record'])} 份改过，加 {add} 行、删 {rem} 行。")
    out.extend(f"- {x['doc']}：+{x['added']} −{x['removed']}" for x in r["record"])
    sure = [c for c in r["candidates"] if c["status"] in ("确定", "确认过")]
    out.append("")
    out.append(f"推出的改名：确定或确认过 {len(sure)} 条，要你点的 {len(r['ask'])} 条"
               f"（候选一共 {len(r['candidates'])} 条，模型用不上的不用点）。")
    out.extend(f"- {c['status']}：{c['from']} → {c['to']}（{c['why']}；接上原句 {c['healed']} 条，手写标签与出处里有 {c['in_labels']} 处）"
               for c in sure + r["ask"])
    out.extend(["", "## 原句：哪些对不上了"])
    nq = lambda rows: len({x["quote"] for x in rows})  # noqa: E731
    out.append(f"原句 {r['quotes']} 条，对不上 {r['stale']} 条：换词接上 {len(r['healed'])} 条（不用确认），"
               f"改写 {len(r['reworded'])} 条（{nq(r['reworded'])} 句话，要人判意思变没变），"
               f"删掉 {len(r['deleted'])} 条（{nq(r['deleted'])} 句话）。")
    for kind, rows in (("改写", r["reworded"]), ("删掉", r["deleted"])):
        groups = OrderedDict()
        for x in rows:
            groups.setdefault(x["quote"], []).append(x)
        for q, xs in groups.items():
            who = "、".join(x["subject"] for x in xs)
            if kind == "改写":
                out.append(f"- 改写（相似 {xs[0]['score']}，{len(xs)} 个个体引它：{who}）：旧「{q[:80]}」")
                out.append(f"  新文档里最像的：「{xs[0]['candidate'][:100]}」")
            else:
                out.append(f"- 删掉（{len(xs)} 个个体引它：{who}）：「{q[:80]}」（最像的只有 {xs[0]['score']}）")
    if r["labels"]:
        out.append(f"手写的标签与出处里用旧词的 {len(r['labels'])} 处，按确定的改名换，不用人。")
    out.extend(["", "## 覆盖：波及哪些概念、哪里还没跟上"])
    for c in r["concepts"]:
        others = "；".join(f"「{o['quote']}」{'在' if o['found'] else '也对不上'}" for o in c["other_quotes"][:3]) or "没有别的原句"
        out.append(f"- {c['label']}（{c['subject']}）：模型里 {c['triples']} 条断言挂在它上面；别的原句：{others}")
    gen = r["generated"]
    out.append(f"- 定义文件与代码生成的事实：加 {len(gen['added'])} 条、少 {len(gen['removed'])} 条，重新生成，不用人"
               + (f"，例如「{(gen['added'] or gen['removed'])[0][:80]}」" if gen["added"] or gen["removed"] else ""))
    froms = [c["from"] for c in r["coverage"]]
    for c in r["coverage"]:
        if any(f != c["from"] and f in c["from"] for f in froms):
            continue  # 「项目部门设置」这类已经算在「部门」里
        if not c["lines"]:
            out.append(f"- 「{c['from']}」→「{c['to']}」：记录类文件以外，全仓都跟上了")
            continue
        areas = "、".join(f"{a} {n} 行" for a, n in c["areas"][:6])
        out.append(f"- 「{c['from']}」→「{c['to']}」：还有 {c['files']} 份文件 {c['lines']} 行用旧词：{areas}")
    if r.get("diff4"):
        d = r["diff4"]
        out.extend(["", f"## 四类结论和对齐那一版（{d['prev']}）比"])
        for k, v in d.get("by", {}).items():
            if v["new"] or v["gone"]:
                out.append(f"- {k}：新冒出 {len(v['new'])} 条，消失 {len(v['gone'])} 条"
                           + (f"，例如新的「{v['new'][0][:60]}」" if v["new"] else ""))
        if not any(v["new"] or v["gone"] for v in d.get("by", {}).values()):
            out.append("- 没有变化")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> None:
    old, new = argv[0], argv[1] if len(argv) > 1 else "origin/main"
    old, new = git("rev-parse", "--short", old).strip(), git("rev-parse", "--short", new).strip()
    r = impact(old, new)
    outdir = HERE / "reports" / "changes"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{old}..{new}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    md = render(r)
    (outdir / f"{old}..{new}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main(sys.argv[1:])
