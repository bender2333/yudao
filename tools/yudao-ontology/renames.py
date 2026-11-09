"""改名从哪来：不靠人登记，从两个提交之间的改动推出来。

两种来源：
- 术语表（CONTEXT.md）的改动。词条换了名字、新词条的 _Avoid_ 里写着旧名字，算确定；
  旧词条名按确定的改名换完正好是一个新词条，也算确定（「部门默认」→「职能默认」）；
  改动里成对出现的「旧 → 新」，新的是一个词条、旧的在它的 _Avoid_ 里，也算确定（「模板」→「形态」）。
- 模型读的文档的 git 改动：删掉的行和加上的行按字配对，数每种「旧片段 → 新片段」出现几次。
  这些是候选，有杂音（例如「一个 → 独立」）。

用法：
- 接原句不用确认：候选换进旧原句以后新文档里真有这句，才算接上（changes.py 做），杂音接不上任何一句。
- 换模型里的标签、查哪里还用旧词，只用确定的和确认过的。确认过的存在 renames.json，是缓存，不是要谁维护的记录：
  python3 renames.py <旧提交> <新提交>            列候选，标出哪些确定、哪些要你点
  python3 renames.py confirm <旧词> <新词>        记一条确认（Bender 点了以后）
  python3 renames.py reject <旧词> <新词>         记一条不是改名
只读仓库。
"""
from __future__ import annotations

import collections
import datetime
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("YUDAO_REPO", HERE.parent.parent))
CACHE = HERE / "renames.json"
MIN_COUNT = 2   # 候选至少出现几次才列出；接原句时有自验证，列多一点也不会接错
MAX_LEN = 14    # 片段太长多半是整句改写，不算改名


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout


def glossary(commit: str) -> dict[str, list[str]]:
    """词条名 → _Avoid_ 里的词。"""
    text = git("show", f"{commit}:CONTEXT.md")
    out = {}
    for m in re.finditer(r"^\*\*(.+?)\*\*:([\s\S]*?)(?=^\*\*|\Z)", text, re.M):
        av = re.search(r"^_Avoid_:\s*(.+)$", m.group(2), re.M)
        out[m.group(1)] = ([re.sub(r"[（(].*?[）)]", "", w).strip() for w in re.split(r"[,，、]\s*", av.group(1))]
                           if av else [])
    return out


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", line)).strip()


def diff_pairs(old: str, new: str, paths: list[str]) -> collections.Counter:
    """删掉的行与加上的行在同一个改动块里按相似度配对，再按字比，数「旧片段 → 新片段」。"""
    pairs: collections.Counter = collections.Counter()
    for p in paths:
        d = git("diff", "-U0", "--no-color", old, new, "--", p)
        for hunk in re.split(r"^@@.*$", d, flags=re.M)[1:]:
            rem = [_clean(x[1:]) for x in hunk.splitlines() if x.startswith("-") and not x.startswith("---")]
            add = [_clean(x[1:]) for x in hunk.splitlines() if x.startswith("+") and not x.startswith("+++")]
            used = set()
            for r in rem:
                best = max(((difflib.SequenceMatcher(None, r, a).ratio(), i) for i, a in enumerate(add) if i not in used),
                           default=(0, None))
                if best[0] < 0.6:
                    continue
                used.add(best[1])
                sm = difflib.SequenceMatcher(None, r, add[best[1]], autojunk=False)
                for op, i1, i2, j1, j2 in sm.get_opcodes():
                    o, n = r[i1:i2].strip(), add[best[1]][j1:j2].strip()
                    if op == "replace" and o and n and len(o) <= MAX_LEN and len(n) <= MAX_LEN + 2:
                        pairs[(o, n)] += 1
    return pairs


def load_cache() -> dict:
    if CACHE.exists():
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        if "confirmed" in d:
            return d
    return {"about": "确认过的改名的缓存，由 renames.py confirm/reject 写；不是要谁维护的记录。",
            "confirmed": [], "rejected": []}


def infer(old: str, new: str, paths: list[str]) -> list[dict]:
    """两个提交之间的改名候选，确定的排前面。每条：from、to、count、why、status（确定 / 确认过 / 要确认 / 不是）。"""
    ga, gb = glossary(old), glossary(new)
    gone, born = set(ga) - set(gb), set(gb) - set(ga)
    sure: dict[tuple[str, str], str] = {}
    for n in born:
        for g in gone:
            if g in gb[n]:
                sure[(g, n)] = f"术语表：词条「{g}」改成「{n}」，「{n}」的 _Avoid_ 里有「{g}」"
    for (o, n) in list(sure):
        for g in gone:
            if o in g and g.replace(o, n) in born and (g, g.replace(o, n)) not in sure:
                sure[(g, g.replace(o, n))] = f"术语表：词条「{g}」按「{o} → {n}」换完正是新词条"
    pairs = diff_pairs(old, new, paths + ["CONTEXT.md"])
    for (o, n), c in pairs.items():
        if (o, n) not in sure and n in gb and o in gb[n]:
            sure[(o, n)] = f"术语表：「{o}」在词条「{n}」的 _Avoid_ 里，改动里出现 {c} 次"
    cache = load_cache()
    conf = {(r["from"], r["to"]) for r in cache["confirmed"]}
    rej = {(r["from"], r["to"]) for r in cache["rejected"]}
    rows = []
    for key in set(sure) | {k for k, c in pairs.items() if c >= MIN_COUNT}:
        status = ("不是" if key in rej else "确定" if key in sure else "确认过" if key in conf else "要确认")
        rows.append({"from": key[0], "to": key[1], "count": pairs.get(key, 0),
                     "why": sure.get(key, f"改动里出现 {pairs.get(key, 0)} 次"), "status": status})
    order = {"确定": 0, "确认过": 1, "要确认": 2, "不是": 3}
    return sorted(rows, key=lambda r: (order[r["status"]], -r["count"], r["from"]))


def accepted(rows: list[dict]) -> list[tuple[str, str]]:
    """标签与覆盖检查能用的：确定的与确认过的。长的先换，免得「部门」先吃掉「三部门」。"""
    return sorted({(r["from"], r["to"]) for r in rows if r["status"] in ("确定", "确认过")}, key=lambda x: -len(x[0]))


def _record(kind: str, o: str, n: str) -> None:
    cache = load_cache()
    cache[kind] = [r for r in cache[kind] if (r["from"], r["to"]) != (o, n)]
    cache[kind].append({"from": o, "to": n, "at": datetime.date.today().isoformat()})
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"记下：{o} → {n}（{'确认过' if kind == 'confirmed' else '不是改名'}）")


def main(argv: list[str]) -> None:
    if argv and argv[0] in ("confirm", "reject"):
        _record("confirmed" if argv[0] == "confirm" else "rejected", argv[1], argv[2])
        return
    sys.path.insert(0, str(HERE))
    from quotecheck import DOCS
    old, new = argv[0], argv[1] if len(argv) > 1 else "origin/main"
    paths = sorted(set(DOCS.values())) + ["docs/architecture.html"]
    for r in infer(old, new, paths):
        print(f"{r['status']:<4} {r['count']:4d}  {r['from']} → {r['to']}  · {r['why']}")


if __name__ == "__main__":
    main(sys.argv[1:])
