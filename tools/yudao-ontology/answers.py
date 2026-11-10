"""题目的答案：核原句、存基线、以后对出挪丢或改了意思的规矩。

用法：
  python3 answers.py verify questions/answers-raw.json <提交>      核每条证据的原句：逐字在那份文件里吗、那份文件算不算证据
  python3 answers.py baseline questions/answers-raw.json <提交>    核完存成 questions/baseline.json（只留对得上的证据）
  python3 answers.py recheck <新提交>                              拿基线对新提交：每条证据还在原处、挪到别的文件、换了说法，还是没了

基线是「这道题现在靠哪几句话回答」。第四节移出这类大挪动以后，recheck 列出：
- 挪走：同一句在别的文件里（原样或相似度够），出处要改，意思没变；
- 改写：原文件里有一句很像的，要人判意思变没变；
- 没了：哪里都找不到，这道题的结论失去了依据，要重新取证。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("YUDAO_REPO", str(HERE.parent.parent))
import changes  # noqa: E402
import quotecheck  # noqa: E402

EVIDENCE = ("docs/architecture.html", "CONTEXT.md", "docs/design/", "docs/requirements/", "harness/", "rules/")
HISTORY = tuple(changes.HISTORY)
BASE = HERE / "questions" / "baseline.json"


def is_evidence(path: str) -> bool:
    return path.startswith(EVIDENCE) and not path.startswith(HISTORY)


def text_of(commit: str, path: str) -> tuple[str, str, list[int]]:
    return changes.doc_text(commit, [path])


def found(commit: str, path: str, quote: str, cache: dict) -> bool:
    if path not in cache:
        cache[path] = text_of(commit, path)
    return changes._found(quote, cache[path][1])


def verify(rows: list[dict], commit: str) -> list[dict]:
    cache: dict = {}
    for r in rows:
        for kind in ("evidence", "code_evidence"):
            for e in r.get(kind, []):
                e["is_evidence"] = is_evidence(e["path"])
                e["found"] = bool(e.get("quote")) and found(commit, e["path"], e["quote"], cache)
    return rows


def where_now(commit: str, path: str, quote: str, cache: dict) -> dict:
    if found(commit, path, quote, cache):
        return {"state": "在"}
    raw, text, keep = cache[path]
    score, sent = changes.nearest(quote, raw, text, keep, [])
    # 别的文件：只看证据文件，先找原样，再找最像
    best = None
    files = changes.git("ls-tree", "-r", "--name-only", commit, "--", *[p.rstrip("/") for p in EVIDENCE]).splitlines()
    probe = max((quotecheck.norm(x) for x in quote.split("……")), key=len)[:16]
    for p in files:
        if p == path or not is_evidence(p) or not p.endswith((".md", ".html", ".json", ".py")):
            continue
        t = text_of(commit, p)
        if probe in t[1] and changes._found(quote, t[1]):
            return {"state": "挪走", "to": p, "exact": True}
    if score < changes.REWORD:
        changed = changes.git("diff", "--name-only", BASELINE_COMMIT, commit, "--", "docs", "CONTEXT.md").splitlines()
        for p in changed:
            if p == path or not is_evidence(p):
                continue
            raw2, t2, k2 = text_of(commit, p)
            s2, sent2 = changes.nearest(quote, raw2, t2, k2, [])
            if s2 >= changes.REWORD and (best is None or s2 > best["score"]):
                best = {"state": "挪走", "to": p, "exact": False, "score": round(s2, 2), "candidate": sent2}
        if best:
            return best
        return {"state": "没了", "score": round(score, 2)}
    return {"state": "改写", "score": round(score, 2), "candidate": sent}


BASELINE_COMMIT = ""


def recheck(commit: str) -> dict:
    global BASELINE_COMMIT
    base = json.loads(BASE.read_text(encoding="utf-8"))
    BASELINE_COMMIT = base["commit"]
    cache: dict = {}
    out = []
    for r in base["answers"]:
        for e in r["evidence"] + r.get("code_evidence", []):
            w = where_now(commit, e["path"], e["quote"], cache)
            if w["state"] != "在":
                out.append({"id": r["id"], "verdict": r["verdict"], "path": e["path"], "quote": e["quote"], **w})
    lost = sorted({x["id"] for x in out if x["state"] == "没了"})
    return {"from": base["commit"], "to": commit, "changed": out, "questions_without_evidence": lost}


def render(rc: dict) -> str:
    if not rc["changed"]:
        return f"题目基线（{rc['from']}）的证据在 {rc['to']} 上都还在原处。"
    lines = [f"题目基线（{rc['from']} → {rc['to']}）：{len(rc['changed'])} 条证据不在原处。"]
    for x in rc["changed"]:
        if x["state"] == "挪走":
            how = "原样" if x.get("exact") else f"换了说法，相似 {x['score']}，「{x['candidate'][:50]}」"
            lines.append(f"- {x['id']} 挪走：「{x['quote'][:50]}」从 {x['path']} 到 {x['to']}（{how}）")
        elif x["state"] == "改写":
            lines.append(f"- {x['id']} 改写（相似 {x['score']}，要人判意思变没变）：「{x['quote'][:50]}」→「{x['candidate'][:50]}」")
        else:
            lines.append(f"- {x['id']} 没了：「{x['quote'][:50]}」（{x['path']}，哪里都找不到）")
    if rc["questions_without_evidence"]:
        lines.append("失去全部或部分依据、要重新取证的题：" + "、".join(rc["questions_without_evidence"]))
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    cmd = argv[0]
    if cmd in ("verify", "baseline"):
        rows = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        commit = changes.git("rev-parse", "--short", argv[2]).strip()
        rows = verify(rows, commit)
        bad = [(r["id"], e["path"], e["quote"][:40], e["is_evidence"]) for r in rows
               for e in r.get("evidence", []) + r.get("code_evidence", []) if not (e["found"] and e["is_evidence"])]
        total = sum(len(r.get("evidence", [])) + len(r.get("code_evidence", [])) for r in rows)
        print(f"{commit}：{len(rows)} 道题，证据 {total} 条，对不上或不算证据 {len(bad)} 条")
        for b in bad:
            print("  ", *b)
        if cmd == "baseline":
            keep = []
            for r in rows:
                r = dict(r)
                for kind in ("evidence", "code_evidence"):
                    r[kind] = [e for e in r.get(kind, []) if e["found"] and e["is_evidence"]]
                keep.append(r)
            BASE.write_text(json.dumps({"commit": commit, "answers": keep}, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
            print("基线写到", BASE.relative_to(HERE))
    elif cmd == "recheck":
        commit = changes.git("rev-parse", "--short", argv[1]).strip()
        rc = recheck(commit)
        print(json.dumps(rc, ensure_ascii=False, indent=1))
        print(render(rc))


if __name__ == "__main__":
    main(sys.argv[1:])
