"""该做什么了：对一个 main 提交从头算一遍，把结果归成四类，按先后给建议。

用法：python3 next.py [提交]（默认 origin/main；先自己 git fetch origin main）
写 reports/next/<提交>.md 与 .json，并把 .md 打印出来。

只报告，不改模型：现有脚本复制到临时目录里跑，文档与代码都按给定的提交用 git show 读，
不切分支，不碰工作区里检出的文件，也不覆盖 reports/ 里各轮留下的记录。
同一个提交、同一份模型，算出来就是同一份，不靠上一次的结果。
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

import rdflib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quotecheck import DOCS  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
YD = rdflib.Namespace("https://yudao.dev/onto#")
RDFS = rdflib.RDFS
# 模型最后一次逐句对齐的提交，与开环规则抽自哪个提交；增量更新做好以前手改
ALIGNED = json.loads((HERE / "aligned.json").read_text(encoding="utf-8"))
# 已写成修复工单草稿的发现（reports/fix-tickets-draft.md）
TICKETS = {("layer-name", "harness/definitions/__init__.py"): "工单草稿一",
           ("openloop", ""): "工单草稿二"}
CODE_TEXT = {"layer-name": "内核模块的判断里出现职能名或成果种类名（形态与核验角色 验收第 3 条）"}
SCOPE = "范围（A）：骨架、定义、裁决、路由、循环、组织、缝与环；产品怎么做、页面怎么画不在模型里"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def norm(t: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"[*`#>|\-]", "", t)
    return re.sub(r"\s+", "", t)


def run_tools(commit: str, work: Path) -> Path:
    """现有脚本在临时副本里按顺序跑；返回副本里的 reports 目录。"""
    tools = work / "onto"
    shutil.copytree(HERE, tools, ignore=shutil.ignore_patterns("__pycache__", "next"))
    env = {**os.environ, "YUDAO_REPO": str(REPO), "YUDAO_COMMIT": commit}
    steps = [["quotecheck.py", commit], ["defs.py", commit], ["run.py"], ["crosscheck.py"],
             ["codecheck.py", commit], ["openloop.py", f"{commit}@{ALIGNED['rules']}"]]
    for step in steps:
        out = subprocess.run([sys.executable, *step], cwd=tools, env=env, capture_output=True, text=True)
        if out.returncode != 0:
            raise SystemExit(f"{step[0]} 失败：\n{out.stderr[-2000:]}")
    return tools


def model_graph(tools: Path) -> rdflib.Graph:
    g = rdflib.Graph()
    for f in sorted((tools / "batches").glob("*.ttl")):
        if f.name != "batch2-contested.ttl":
            g.parse(f)
    return g


def source(g: rdflib.Graph, focus: str) -> list[str]:
    """一个个体在模型里的出处：原句与它挂的文档节号。"""
    n = YD[focus]
    refs = [str(x) for x in g.objects(n, YD.docRef)] + [f"总图 {x}" for x in g.objects(n, YD.archRef)]
    quotes = [str(x) for x in g.objects(n, YD.quote)]
    lines = [f"「{q}」" for q in quotes[:2]]
    if refs:
        lines.append(" · ".join(dict.fromkeys(refs)))
    return lines


def cited_sections(g: rdflib.Graph) -> dict[str, set[str]]:
    """模型挂过的节：docRef 里写的设计说明与节号（「4.9」「第 1 节」）。总图整份都在范围里，不分节。"""
    out: dict[str, set[str]] = {}
    for ref in {str(o) for o in g.objects(None, YD.docRef)}:
        for part in ref.split("；"):
            for name, path in DOCS.items():
                if part.strip().startswith(name):
                    rest = part.strip()[len(name):]
                    nums = re.findall(r"(\d+(?:\.\d+)*)", rest)
                    out.setdefault(path, set()).update(nums or ["*"])
    return out


def section_no(head: str) -> str:
    m = re.match(r"(\d+(?:\.\d+)*)", head)
    return m.group(1) if m else ""


def unextracted(commit: str, quotes: list[str], docs: list[str], cited: dict[str, set[str]]) -> list[dict]:
    """模型对齐以后，模型读的文档里新加的行，哪一行都没被模型的原句引用。原句核对查不出这一种。
    按所在的节分两种：模型挂过的节（in_cited，多半要重抽）与模型没挂过的节（多半在范围外，只提一句）。"""
    qn = [norm(q) for q in quotes]
    rows = []
    for path in docs:
        diff = git("diff", "-U0", ALIGNED["commit"], commit, "--", path)
        text = git("show", f"{commit}:{path}").splitlines() if diff else []
        line_no = 0
        for line in diff.splitlines():
            m = re.match(r"@@ -\S+ \+(\d+)", line)
            if m:
                line_no = int(m.group(1)) - 1
                continue
            if not line.startswith("+") or line.startswith("+++"):
                continue
            line_no += 1
            t = norm(line[1:])
            if len(t) < 8 or any(q in t or t in q for q in qn):
                continue
            heads = [h.lstrip("# ").strip() for h in reversed(text[:line_no]) if h.startswith("#")]
            head = heads[0] if heads else ""
            # 只看最近的标题：没编号的小标题（例如 4.14 下的「项目页上的内容在哪里看」）不算挂过的节
            num = section_no(head)
            secs = cited.get(path, set())
            in_cited = path.endswith(".html") or "*" in secs or any(num == c or num.startswith(c + ".") for c in secs)
            rows.append({"doc": path, "line": line_no, "section": head, "number": num, "in_cited": in_cited,
                         "text": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", line[1:]))).strip()})
    return rows


def collect(commit: str, tools: Path) -> dict:
    rep = tools / "reports"
    load = lambda name: json.loads((rep / name).read_text(encoding="utf-8"))  # noqa: E731
    g = model_graph(tools)
    quote_rows = load("quotecheck.json")[commit]
    results, cross, code = load("results.json"), load("crosscheck.json"), load("codecheck.json")[commit]
    openloop = load("openloop.json")[0]
    docs = sorted({d for r in quote_rows for d in r["doc"].split("、")})
    found = {"一": [], "二": [], "三": [], "四": []}

    # 模型跟不跟得上
    # found：True 原句在；"拼接" 是「……」两边分开核对都在；False 对不上
    stale = [r for r in quote_rows if r["found"] is False]
    spliced = [r for r in quote_rows if r["found"] == "拼接"]
    new_lines = unextracted(commit, [r["quote"] for r in quote_rows], docs, cited_sections(g))

    # 第 0 至 3 批的检查：同一条在几批里重复出现，只记一次，记最后一批的
    seen = OrderedDict()
    for n, b in sorted(results["batches"].items(), key=lambda kv: int(kv[0])):
        for s in b["shacl"]:
            seen[(s["result"], s["check"], s["focus"])] = {**s, "batch": int(n)}
        if not b["consistent"]:
            found["一"].append({"title": f"第 {n} 批推理不一致", "where": b["unsat"] or [b["error"]], "kind": "不一致"})
    for s in seen.values():
        item = {"title": f"{s['label']}：{s['message']}", "where": source(g, s["focus"]),
                "check": s["check"], "batch": s["batch"]}
        {"违例": found["一"], "确实缺": found["二"]}.get(s["result"], found["四"]).append(item)

    # 设计对定义文件
    for r in cross:
        item = {"title": f"{r['form']}：{r['subject']} {r['property']} {r['object']}（{r['why']}）",
                "where": [], "check": "crosscheck"}
        if r["result"] == "违例":
            found["一"].append(item)
        elif r["result"] == "确实缺":
            found["二"].append(item)
        elif r["why"] == "定义文件有，设计没写":
            found["三"].append({**item, "kind": "现状有、设计没写"})
        else:
            found["四"].append(item)

    # 代码
    for r in code:
        ticket = TICKETS.get((r["check"], r["focus"]))
        item = {"title": f"{r['focus']}：{CODE_TEXT.get(r['check'], r['check'])}", "where": r["detail"][:4], "check": r["check"],
                "ticket": ticket}
        if r["result"] == "违例":
            found["一"].append(item)
        elif r["result"] == "确实缺":
            found["二"].append(item)
        else:
            found["四"].append({**item, "title": f"{r['focus']}：总图的词在 name-map 里没有对应的代码"})

    # 开环：几条判法对同一份定义给相反判定
    bad = [p for p in openloop["probes"] if p["result"] == "违例"]
    if bad:
        rules = {k for p in bad for k in p["each"]}
        where = [f"「{q['quote']}」 · {q['rule']}" for q in openloop["quotes"] if q["rule"] in rules]
        found["一"].append({"title": f"判开环的几条规则对同一份定义给相反的判定（{len(bad)} 种组合）",
                            "where": where + ["代码：orchestrator.py 按最后采纳的成果判，direct.py 按交完成的角色判"],
                            "check": "openloop", "ticket": TICKETS[("openloop", "")]})

    # 推出的空位：最后一批还空着的，和已经由设计填上的推理链
    last = results["batches"][str(max(int(k) for k in results["batches"]))]
    for s in last["slots"]:
        found["三"].append({"title": f"{s['path']}（深度 {s['depth']}）", "where": [s["basis"]],
                            "kind": "推出的空位"})
    filled = [t for t in results["tracking"] if t.get("filled_by")]

    # 四类里没写成工单的违例、确实缺，各给一条建议
    advice = []
    inside = [u for u in new_lines if u["in_cited"]]
    if stale or inside:
        secs = "、".join(dict.fromkeys(f"{Path(u['doc']).stem} {u['number'] or u['section']}" for u in inside))
        advice.append(f"先把模型跟上：{len(stale)} 句原句对不上；模型挂过的节里新加了 {len(inside)} 行（{secs}），"
                      "要重抽；下面的结论只到模型对齐的那一版")
    for it in found["一"]:
        advice.append(f"先定：{it['title']}" + (f"（{it['ticket']}已写好，等你开）" if it.get("ticket") else
                                              "（几句说法冲突，先定以哪一句为准）"))
    for it in found["二"]:
        advice.append(f"补上：{it['title']}")
    slots = [x for x in found["三"] if x["kind"] == "推出的空位"]
    for it in slots:
        advice.append(f"想清楚：{it['title']}")
    gap = [x for x in found["三"] if x["kind"] == "现状有、设计没写"]
    if gap:
        advice.append(f"设计说明补写：定义文件里有、设计没写的 {len(gap)} 处，挑会被别人依赖的先写")
    newer = subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", ALIGNED["commit"], commit]).returncode == 0
    return {"commit": commit, "newer": newer, "date": git("show", "-s", "--format=%cs", commit).strip(),
            "aligned": ALIGNED, "quotes": len(quote_rows), "stale": stale, "spliced": len(spliced),
            "unextracted": new_lines, "docs": docs, "found": found, "filled": filled, "advice": advice}


def render(r: dict) -> str:
    f = r["found"]
    out = [f"# 该做什么了 · main {r['commit']}（{r['date']}）", ""]
    inside = [u for u in r["unextracted"] if u["in_cited"]]
    outside = [u for u in r["unextracted"] if not u["in_cited"]]
    ok = "跟得上" if not r["stale"] and not inside else "没跟上"
    out.append(f"模型最后对齐 {r['aligned']['commit']}，对这个提交{ok}：原句 {r['quotes']} 句，"
               f"对不上 {len(r['stale'])} 句（另有 {r['spliced']} 句是拼接，分开核对都在）；"
               f"对齐以后新加、模型还没抽的：模型挂过的节里 {len(inside)} 行，模型没挂过的节里 {len(outside)} 行"
               f"（多半在范围外，例如页面怎么画）。")
    if not r["newer"]:
        out.append(f"注意：这个提交不在 {r['aligned']['commit']} 之后，「新加」的行其实是之后删掉或改掉的，只作参考。")
    out.append(f"覆盖：{SCOPE}。模型读的文档：{'、'.join(r['docs'])}。没列的文档模型不知道，这里不说它们没问题。")
    for s in r["stale"][:5]:
        out.append(f"- 对不上：{s['subject']} 「{s['quote'][:60]}」 · {s['doc']}")
    by_doc = OrderedDict()
    for u in inside:
        by_doc.setdefault((u["doc"], u["section"]), []).append(u)
    for (doc, sec), rows in list(by_doc.items())[:6]:
        out.append(f"- 没抽：{doc}「{sec}」{len(rows)} 行，例如第 {rows[0]['line']} 行「{rows[0]['text'][:70]}」")
    if outside:
        secs = "、".join(dict.fromkeys(f"「{u['section']}」" for u in outside))
        out.append(f"- 模型没挂过的节里新加的（只提一句）：{Path(outside[0]['doc']).name} 等，{secs}")
    if len(by_doc) > 6:
        out.append(f"- 没抽：另有 {len(by_doc) - 6} 节")

    def block(title, items, limit=None):
        out.extend(["", f"## {title}（{len(items)}）"])
        for i, it in enumerate(items[:limit] if limit else items, 1):
            out.append(f"{i}. {it['title']}" + (f" · {it['ticket']}" if it.get("ticket") else ""))
            out.extend(f"   {w}" for w in it["where"])
        if limit and len(items) > limit:
            out.append(f"   另有 {len(items) - limit} 条，见 .json")

    block("一、内部不一致的设计（违例）", f["一"])
    block("二、设计了还没实现（确实缺）", f["二"])
    slots = [x for x in f["三"] if x["kind"] == "推出的空位"]
    gap = [x for x in f["三"] if x["kind"] == "现状有、设计没写"]
    block("三、照现状还要考虑的：推出的空位（推理，不是类比）", slots)
    if r["filled"]:
        out.append(f"   已由设计填上的推理链 {len(r['filled'])} 条，例如：{r['filled'][0]['path']} → {r['filled'][0]['filled_by']}")
    block("三、照现状还要考虑的：定义文件里有、设计没写（对照，不是推理）", gap, limit=5)
    groups = OrderedDict()
    for it in f["四"]:
        groups.setdefault(it["check"], []).append(it)
    out.extend(["", f"## 四、不知道（{len(f['四'])}）"])
    for check, items in groups.items():
        out.append(f"- {check}：{len(items)} 条，例如 {items[0]['title']}")
    out.extend(["", "## 建议（按先后）"])
    out.extend(f"{i}. {a}" for i, a in enumerate(r["advice"][:6], 1))
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> None:
    ref = argv[0] if argv else "origin/main"
    commit = git("rev-parse", "--short", ref).strip()
    with tempfile.TemporaryDirectory() as tmp:
        tools = run_tools(commit, Path(tmp))
        r = collect(commit, tools)
    outdir = HERE / "reports" / "next"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{commit}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    md = render(r)
    (outdir / f"{commit}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main(sys.argv[1:])
