"""规则事实线第 6 步：基线。

存量里「像在说规则但解析不了」、又不是规则事实的提醒，记在 .doc-index/rulefacts/baseline.jsonl：
每条一行 {"file", "hash", "head"}，hash 是句子（引导句带的条目接在后面）规范化以后的 sha256 前 16 位，head 是句子前 60 字。
只追加：已有的行不动，新的接在末尾；句子改过 hash 就变了，不在基线里，会重新报。rules check 默认只报不在基线里的提醒。
"""

import hashlib
import json
import re
from pathlib import Path

from .patterns import nz
from .scan import LIST_MARK

PATH = Path(".doc-index") / "rulefacts" / "baseline.jsonl"
HEAD = 60


def sentence(h):
    """提醒的句子：引导句加它带的条目，去掉列表记号，规范化空白。"""
    parts = [h.text] + [LIST_MARK.sub("", t, count=1) for _, t in h.items]
    return re.sub(r"\s+", " ", nz(" ".join(parts))).strip()


def key(h):
    return (h.file, hashlib.sha256(sentence(h).encode("utf-8")).hexdigest()[:16])


def load(root):
    """{(文件, hash): 记录}，文件不在就是空的；有坏行直接报错，不猜。"""
    p = Path(root) / PATH
    if not p.is_file():
        return {}
    out = {}
    for n, line in enumerate(p.read_bytes().decode("utf-8").split("\n"), 1):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            out[(r["file"], r["hash"])] = r
        except (ValueError, KeyError) as e:
            raise SystemExit(f"{PATH.as_posix()}:{n} 不是一条基线记录：{e}")
    return out


def update(root, hits):
    """把不在基线里的提醒追加进去。返回输出行。"""
    base = load(root)
    now = {key(h) for h in hits}
    new = []
    for h in hits:
        k = key(h)
        if k not in base and k not in {key(x) for x in new}:
            new.append(h)
    if new:
        p = Path(root) / PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="\n") as f:
            for h in new:
                f.write(json.dumps({"file": h.file, "hash": key(h)[1], "head": h.text[:HEAD]}, ensure_ascii=False) + "\n")
    stale = sum(1 for k in base if k not in now)
    return [
        f"基线已更新：原有 {len(base)} 条，新增 {len(new)} 条，共 {len(base) + len(new)} 条，写在 {PATH.as_posix()}",
        f"其中 {stale} 条已不在现有提醒里（句子改过或已经解析成功；基线只追加，仍保留）",
    ]
