"""跟版本走：模型里每一句原句，到给定的提交里逐句核对还在不在。

用法：python3 quotecheck.py <提交>...（默认 HEAD），结果写 reports/quotecheck.json。
第 1 批的原句对总图 docs/architecture.html 的正文（去掉标签）；第 2 批按 docRef 里的设计说明名字找文件。
比较前去掉 Markdown 的强调与代码记号、合并空白；原句里的「……」是省略，两边分别核对。
只读仓库。
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
from pathlib import Path

import rdflib

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
YD = rdflib.Namespace("https://yudao.dev/onto#")
DOCS = {"形态与核验角色设计说明": "docs/design/forms-and-verifier-role.md",
        "部门内多角色设计说明": "docs/design/department-roles.md",
        "骨架与应用设计说明": "docs/design/skeleton-and-application.md",
        "验证的独立性设计说明": "docs/design/independent-verification.md"}
FILES = ["batch1-overview.ttl", "batch2-design.ttl", "batch2-eb8429e.ttl"]


def show(commit, path):
    out = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{path}"], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def norm(t: str) -> str:
    t = re.sub(r"[*`]", "", t)
    return re.sub(r"\s+", "", t)


def html_text(src: str) -> str:
    src = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", src, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", src))


def docs_for(refs, file):
    """docRef 里点到的所有设计说明（一条 docRef 可以用「；」列几份）；batch2-eb8429e 都出自形态与核验角色设计说明。"""
    if file.startswith("batch1"):
        return ["docs/architecture.html"]
    out = [path for r in refs for part in str(r).split("；") for name, path in DOCS.items() if part.strip().startswith(name)]
    if file == "batch2-eb8429e.ttl" and not any(str(r).startswith("验证的独立性") for r in refs):
        out = [DOCS["形态与核验角色设计说明"]]
    return list(dict.fromkeys(out))


def check(commit):
    texts = {}
    rows = []
    for f in FILES:
        g = rdflib.Graph().parse(HERE / "batches" / f)
        for s, q in sorted(g.subject_objects(YD.quote), key=str):
            refs = list(g.objects(s, YD.docRef))
            paths = docs_for(refs, f)
            if not paths:
                rows.append({"file": f, "subject": str(s).split("#")[-1], "quote": str(q), "doc": None, "found": None})
                continue
            for path in paths:
                if path not in texts:
                    raw = show(commit, path)
                    texts[path] = norm(html_text(raw) if path.endswith(".html") else raw)
            text = "".join(texts[p] for p in paths)

            def has(sep):
                return all(norm(x) in text for x in str(q).split(sep) if norm(x))
            # 「……」是省略；「；」在第 1 批里是抽取时把总图上相邻两处拼成一句，分开都在算拼接
            found = True if has("……") else ("拼接" if all(norm(x) in text for part in str(q).split("……")
                                                         for x in part.split("；") if norm(x)) else False)
            rows.append({"file": f, "subject": str(s).split("#")[-1], "quote": str(q), "doc": "、".join(paths), "found": found})
    return rows


def main(argv):
    res = {c: check(c) for c in (argv or ["HEAD"])}
    (HERE / "reports/quotecheck.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for c, rows in res.items():
        miss = [r for r in rows if r["found"] is False or r["found"] == "拼接"]
        nodoc = [r for r in rows if r["found"] is None]
        print(c, len(rows), "句；对不上", len(miss), "；没找到出处", len(nodoc))
        for r in miss + nodoc:
            print("  ", r["found"], r["file"], r["subject"], r["doc"], "|", r["quote"][:90])


if __name__ == "__main__":
    main(sys.argv[1:])
