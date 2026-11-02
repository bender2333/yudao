import json
import posixpath
import re
from pathlib import Path

from .index import load_index

ASSETS = Path(__file__).parent / "assets"
OUT = Path(".tmp") / "doc-index" / "graph.html"
TOP_DIRS = ("docs", ".claude", "harness", "client", "evals", "tools", ".github")


def dir_of(path):
    parts = path.split("/")
    if len(parts) == 1:
        return "(根目录)"
    if parts[0] in TOP_DIRS and len(parts) > 2:
        return parts[0] + "/" + parts[1]
    return parts[0]


def graph_data(root):
    idx = load_index(root)
    if not idx:
        raise SystemExit("还没有索引，先运行 build")
    nodes = []
    seen = set()
    for path in sorted(idx):
        for n in idx[path]["nodes"]:
            nodes.append(
                {
                    "id": n["id"],
                    "file": path,
                    "kind": n["kind"],
                    "parent": n.get("parent", ""),
                    "label": posixpath.basename(path) if n["kind"] == "file" else n["title"][:24],
                    "dir": dir_of(path),
                }
            )
            seen.add(n["id"])
    edges = []
    for path in sorted(idx):
        for e in idx[path]["edges"]:
            if e["dst"] not in seen:  # 索引范围之外的文件（代码、配置）
                seen.add(e["dst"])
                nodes.append(
                    {
                        "id": e["dst"],
                        "file": e["dst"],
                        "kind": "file",
                        "parent": "",
                        "label": posixpath.basename(e["dst"]),
                        "dir": dir_of(e["dst"]),
                        "external": True,
                    }
                )
            edges.append([e["src"], e["dst"], e["kind"]])
    dirs = sorted({n["dir"] for n in nodes})
    return {"nodes": nodes, "edges": edges, "dirs": dirs}


def view(root):
    data = graph_data(root)
    page = (ASSETS / "graph.html").read_text(encoding="utf-8")
    lib = (ASSETS / "cytoscape.min.js").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    parts = {"DATA": payload, "LIB": lib}
    page = re.sub(r"__(DATA|LIB)__", lambda m: parts[m.group(1)], page)
    out = Path(root) / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    return out, data
