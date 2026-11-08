"""正名表：CONTEXT.md 的词条与 _Avoid_，加 name-map 第一列。只读文档，不改。"""
import os
import re
import subprocess
from pathlib import Path

# YUDAO_REPO 与 YUDAO_COMMIT：next.py 设上以后，按那个提交读，不读工作区里检出的版本
ROOT = Path(os.environ.get("YUDAO_REPO", Path(__file__).resolve().parents[2]))


def _read(root: Path, path: str) -> str:
    commit = os.environ.get("YUDAO_COMMIT")
    if commit:
        return subprocess.run(["git", "-C", str(root), "show", f"{commit}:{path}"],
                              capture_output=True, text=True, check=True).stdout
    return (root / path).read_text(encoding="utf-8")


def canonical_names(root: Path = ROOT):
    ctx = _read(root, "CONTEXT.md")
    terms = set(re.findall(r"^\*\*(.+?)\*\*:", ctx, re.M))
    avoid = {}
    for m in re.finditer(r"^\*\*(.+?)\*\*:[\s\S]*?^_Avoid_:\s*(.+)$", ctx, re.M):
        for w in re.split(r"[,，、]\s*", m.group(2)):
            w = re.sub(r"[（(].*?[）)]", "", w).strip()
            if w:
                avoid.setdefault(w, m.group(1))
    nm = _read(root, "docs/design/architecture/name-map.md")
    for line in nm.splitlines():
        if line.startswith("| ") and not line.startswith("| ---") and not line.startswith("| 总图"):
            first = line.split("|")[1].strip()
            for w in re.split(r"[、，,]\s*", first):
                if w:
                    terms.add(w)
    return terms, avoid
