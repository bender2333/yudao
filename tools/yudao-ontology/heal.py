"""把模型跟到新的提交：只动变了的那几处，三道检查过了才写回，全跟上了才挪对齐点。

用法：
  python3 heal.py <新提交>                 先在副本上试，报告会改什么、三道过没过，不写回
  python3 heal.py <新提交> --apply         三道都过才写回 batches/；什么都不剩才把 aligned.json 挪到新提交
  python3 heal.py <新提交> --accept 1 2    改写的第 1、2 句（按变动影响清单里的顺序）人判过意思没变，换成新文档里那一句

自动做的（不用人）：
- 换词接上的原句：候选换进旧原句以后，新文档里真有这句（changes.py 判的），把模型里的原句换成新的。
- 手写的标签与出处（docRef）：只按确定的与确认过的改名换（renames.py）。注释不动。
- 定义文件那一批重新生成（defs.py）。
不自动做的：改写的句子（要人判意思变没变，用 --accept）、删掉的句子与新加的段落（意思变了，要人或 agent 重抽）。
三道：原句核对（接上的不能还对不上）、HermiT 一致性（每一批）、埋错仍全查出（mutate.py）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import changes  # noqa: E402
import renames  # noqa: E402

REPO = Path(os.environ.get("YUDAO_REPO", HERE.parent.parent))


def lit(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def edit_batches(root: Path, r: dict, accept: list[int]) -> dict:
    """在 root/batches 里改：原句、标签、出处。返回每个文件改了几处。"""
    quote_map = {x["quote"]: x["new"] for x in r["healed"]}
    groups = OrderedDict()
    for x in r["reworded"]:
        groups.setdefault(x["quote"], x["candidate"])
    for i, (q, cand) in enumerate(groups.items(), 1):
        if i in accept and cand:
            quote_map[q] = cand
    sure = renames.accepted(r["candidates"])
    # 等你点的改名（例如「三部门」）里套着确定的改名（「部门」）时，这处先不换，免得换成「三职能」
    pending = [c["from"] for c in r["ask"]]
    count: dict[str, int] = {}

    def fix(m: re.Match) -> str:
        pred, ws, text = m.group(1), m.group(2), m.group(3).replace('\\"', '"').replace("\\\\", "\\")
        new = text
        if pred == "yd:quote":
            new = quote_map.get(text, text)
        elif not any(p in text and any(o in p and o != p for o, _ in sure) for p in pending):
            for o, n in sure:
                new = new.replace(o, n)
        if new != text:
            count[cur] = count.get(cur, 0) + 1
        return f'{pred}{ws}"{lit(new)}"'

    for f in changes.HAND:
        p = root / "batches" / f
        if not p.exists():
            continue
        cur = f
        src = p.read_text(encoding="utf-8")
        out = re.sub(r'(rdfs:label|yd:docRef|yd:quote)(\s+)"((?:[^"\\]|\\.)*)"',
                     fix, src)
        p.write_text(out, encoding="utf-8")
    return count


def gates(root: Path, new: str, must_find: set[str]) -> dict:
    env = {**os.environ, "YUDAO_REPO": str(REPO), "YUDAO_COMMIT": new}
    py = lambda *a: subprocess.run([sys.executable, *a], cwd=root, env=env, capture_output=True, text=True)  # noqa: E731
    out = {}
    d = py("defs.py", new)
    out["defs"] = d.returncode == 0
    q = py("quotecheck.py", new)
    rows = json.loads((root / "reports/quotecheck.json").read_text(encoding="utf-8"))[new]
    still = [x for x in rows if x["found"] is False and x["quote"] in must_find]
    out["quotes"] = {"ok": q.returncode == 0 and not still, "stale": sum(1 for x in rows if x["found"] is False),
                     "healed_but_stale": [x["quote"][:60] for x in still]}
    run = py("run.py")
    res = json.loads((root / "reports/results.json").read_text(encoding="utf-8")) if run.returncode == 0 else None
    out["consistent"] = {"ok": bool(res) and all(b["consistent"] for b in res["batches"].values()),
                         "error": run.stderr[-500:] if run.returncode else ""}
    mu = py("mutate.py")
    rows = json.loads((root / "reports/mutations.json").read_text(encoding="utf-8")) if mu.returncode == 0 else []
    muts = [x for x in rows if not x["id"].startswith("control")]
    out["mutations"] = {"ok": mu.returncode == 0 and muts and all(x["detected"] for x in rows),
                        "detected": sum(1 for x in muts if x["detected"]), "total": len(muts),
                        "missed": [x["name"] for x in rows if not x["detected"]], "error": mu.stderr[-500:] if mu.returncode else ""}
    out["ok"] = out["defs"] and out["quotes"]["ok"] and out["consistent"]["ok"] and out["mutations"]["ok"]
    return out


def main(argv: list[str]) -> None:
    new = changes.git("rev-parse", "--short", argv[0]).strip()
    apply = "--apply" in argv
    accept = [int(x) for x in argv[argv.index("--accept") + 1:] if x.isdigit()] if "--accept" in argv else []
    aligned = json.loads((HERE / "aligned.json").read_text(encoding="utf-8"))
    old = aligned["commit"]
    r = changes.impact(old, new)
    import next as nx
    g = changes.model_graph()
    docs = changes.model_docs()
    inside = [u for u in nx.unextracted(new, [x["quote"] for x in changes.quotecheck.check(new)], docs,
                                        nx.cited_sections(g), base=old) if u["in_cited"]]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "onto"
        shutil.copytree(HERE, root, ignore=shutil.ignore_patterns("__pycache__", "reports"))
        (root / "reports").mkdir()
        count = edit_batches(root, r, accept)
        cand = OrderedDict()
        for x in r["reworded"]:
            cand.setdefault(x["quote"], x["candidate"])
        groups = list(cand)
        must = {x["new"] for x in r["healed"]} | {cand[q] for i, q in enumerate(groups, 1) if i in accept}
        gate = gates(root, new, must)
        left_reword = [q for i, q in enumerate(groups, 1) if i not in accept]
        left_deleted = list(OrderedDict.fromkeys(x["quote"] for x in r["deleted"]))
        done = gate["ok"] and not left_reword and not left_deleted and not inside
        summary = {"old": old, "new": new, "edited": count, "healed": len(r["healed"]), "accepted": accept,
                   "left_reworded": len(left_reword), "left_deleted": len(left_deleted), "unextracted_inside": len(inside),
                   "gates": gate, "applied": False, "aligned_moved": False}
        if apply and gate["ok"]:
            for f in changes.HAND + ["batch3-definitions.ttl"]:
                if (root / "batches" / f).exists():
                    shutil.copy(root / "batches" / f, HERE / "batches" / f)
            summary["applied"] = True
            if done:
                aligned.update({"commit": new, "note": f"{old} 到 {new} 由 heal.py 跟上：换词接上 {len(r['healed'])} 条，"
                                f"人判过的改写 {len(accept)} 句；三道都过。"})
                (HERE / "aligned.json").write_text(json.dumps(aligned, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                summary["aligned_moved"] = True
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    lines = [f"模型 {old} → {new}：自动改了 {sum(count.values())} 处（" + "、".join(f"{k} {v}" for k, v in count.items()) + "）；",
             f"三道：原句核对{'过' if gate['quotes']['ok'] else '没过'}（还对不上 {gate['quotes']['stale']} 条），"
             f"一致性{'过' if gate['consistent']['ok'] else '没过'}，埋错 {gate['mutations']['detected']}/{gate['mutations']['total']}；",
             f"剩给人的：改写 {len(left_reword)} 句、删掉 {len(left_deleted)} 句、模型挂过的节里新加 {len(inside)} 行。",
             ("已写回 batches/。" if summary["applied"] else "没写回（试跑，或三道没过）。")
             + ("对齐点挪到 " + new + "。" if summary["aligned_moved"] else "对齐点没动。")]
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
