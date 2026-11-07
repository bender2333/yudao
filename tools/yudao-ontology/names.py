"""正名表：CONTEXT.md 的词条与 _Avoid_，加 name-map 第一列。只读文档，不改。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def canonical_names(root: Path = ROOT):
    ctx = (root / "CONTEXT.md").read_text(encoding="utf-8")
    terms = set(re.findall(r"^\*\*(.+?)\*\*:", ctx, re.M))
    avoid = {}
    for m in re.finditer(r"^\*\*(.+?)\*\*:[\s\S]*?^_Avoid_:\s*(.+)$", ctx, re.M):
        for w in re.split(r"[,，、]\s*", m.group(2)):
            w = re.sub(r"[（(].*?[）)]", "", w).strip()
            if w:
                avoid.setdefault(w, m.group(1))
    nm = (root / "docs/design/architecture/name-map.md").read_text(encoding="utf-8")
    for line in nm.splitlines():
        if line.startswith("| ") and not line.startswith("| ---") and not line.startswith("| 总图"):
            first = line.split("|")[1].strip()
            for w in re.split(r"[、，,]\s*", first):
                if w:
                    terms.add(w)
    return terms, avoid
