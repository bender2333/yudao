import difflib
import json
from pathlib import Path

from .scan import git_tracked, is_scaffold, parse_file, read_text, scan_repo

DATA = Path(__file__).resolve().parent.parent / "data"
INDEX_DIR = ".doc-index"
SCHEMA = 1


def index_root(root):
    return Path(root) / INDEX_DIR


def index_file(root, path):
    return index_root(root) / "files" / (path + ".json")


def dump_lines(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render(data):
    """一个节点或一条边占一行，改动在 diff 里一眼能看出。"""
    lines = ["{", f'"schema":{SCHEMA},', f'"path":{dump_lines(data["path"])},', f'"hash":{dump_lines(data["hash"])},']
    lines.append('"nodes":[')
    lines.append(",\n".join(dump_lines(n) for n in data["nodes"]))
    lines.append("],")
    lines.append('"edges":[')
    lines.append(",\n".join(dump_lines(e) for e in data["edges"]))
    lines.append("]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def load_index(root):
    out = {}
    base = index_root(root) / "files"
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*.json")):
        data = json.loads(p.read_bytes().decode("utf-8"))
        out[data["path"]] = data
    return out


def load_confirmed(root):
    p = index_root(root) / "confirmed.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_bytes().decode("utf-8").split("\n") if l.strip()]


def confirmed_keys(root):
    return {(c["src"], c["dst"], c["up"]) for c in load_confirmed(root)}


def build_file_index(model, path, old, confirmed):
    f = model.files[path]
    old_nodes = {n["id"]: n["hash"] for n in old["nodes"]} if old else {}
    old_edges = {(e["src"], e["dst"], e["kind"]): e for e in old["edges"]} if old else {}
    nodes = [
        {k: v for k, v in {"id": n.id, "kind": n.kind, "title": n.title, "parent": n.parent, "hash": n.hash, "anchor": n.anchor}.items() if v}
        for n in f.nodes
    ]
    grouped = {}
    for e in model.edges:
        if model.nodes[e.src].file != path:
            continue
        grouped.setdefault((e.src, e.dst, e.kind), set()).add(e.raw)
    edges = []
    for key in sorted(grouped):
        src, dst, kind = key
        up = model.hash_of(dst)
        prev = old_edges.get(key)
        if prev is None or old_nodes.get(src) != model.nodes[src].hash or (src, dst, up) in confirmed:
            seen = up  # 新边记基线；下游改过或已确认，也认可当前的上游
        else:
            seen = prev["seen"]
        edges.append({"src": src, "dst": dst, "kind": kind, "raws": sorted(grouped[key]), "seen": seen})
    return {"path": path, "hash": f.hash, "nodes": nodes, "edges": edges}


def build(root):
    model = scan_repo(root)
    old = load_index(root)
    confirmed = confirmed_keys(root)
    written = removed = edges = 0
    for path in sorted(model.files):
        data = build_file_index(model, path, old.get(path), confirmed)
        edges += len(data["edges"])
        text = render(data)
        p = index_file(root, path)
        if not p.is_file() or p.read_bytes().decode("utf-8") != text:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            written += 1
    for path in old:
        if path not in model.files:
            index_file(root, path).unlink()
            removed += 1
    # 清掉空目录
    base = index_root(root) / "files"
    if base.is_dir():
        for d in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(d.iterdir()):
                d.rmdir()
    return {"files": len(model.files), "nodes": len(model.nodes), "edges": edges, "written": written, "removed": removed}


def status(root):
    model = scan_repo(root)
    old = load_index(root)
    old_nodes = {n["id"]: n for d in old.values() for n in d["nodes"]}
    out = []
    for nid, n in sorted(model.nodes.items()):
        if nid not in old_nodes:
            out.append(("新增", nid))
        elif old_nodes[nid]["hash"] != n.hash:
            out.append(("改动", nid))
    for nid in sorted(old_nodes):
        if nid not in model.nodes:
            out.append(("删除", nid))
    # 小节有变化时，文件节点本身的变化不再单列
    changed_files = {nid.split("#", 1)[0] for _, nid in out if "#" in nid}
    return [(k, nid) for k, nid in out if "#" in nid or nid not in changed_files]


def all_ids(root, idx=None):
    idx = idx if idx is not None else load_index(root)
    return {n["id"] for d in idx.values() for n in d["nodes"]}


def in_target(spec_id, nid):
    return nid == spec_id or nid.startswith(spec_id + " > ")


def resolve_spec(spec, ids, tracked=None):
    """把命令行写的文件或小节解析成节点或文件路径；解析不了就报错。"""
    if spec in ids:
        return spec
    if tracked is not None and spec in tracked:
        return spec
    hits = sorted(i for i in ids if i.startswith(spec))
    if len(hits) == 1:
        return hits[0]
    if hits:
        shown = "\n  ".join(hits[:15])
        raise SystemExit(f"目标 {spec!r} 有多个候选，请写完整：\n  {shown}")
    contains = sorted(i for i in ids if spec in i)
    near = contains or difflib.get_close_matches(spec, sorted(ids), n=10, cutoff=0.4)
    shown = "\n  ".join(near[:15])
    how = "包含这个写法的节点" if contains else "名字相近的节点"
    raise SystemExit(
        f"找不到 {spec!r}。节点名是 路径#标题 > 子标题（表格行是 路径#标题 > 表1 > 首列）；"
        f"用 nodes <关键词> 按关键词列出节点。{how}：\n  {shown}"
    )


def list_nodes(root, keyword):
    return sorted(i for i in all_ids(root) if keyword in i)


def target_match(spec_id, dst):
    """文件路径包含它里面的所有小节；小节包含它的子小节与表格行。"""
    if "#" not in spec_id:
        return dst == spec_id or dst.startswith(spec_id + "#")
    return in_target(spec_id, dst)


def line_numbers(root, cache, src_file, src_id, raws, kind=""):
    if src_file not in cache:
        text = read_text(Path(root) / src_file)
        cache[src_file] = (parse_file(src_file, text, is_scaffold(src_file)), text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    scan, lines = cache[src_file]
    node = next((n for n in scan.nodes if n.id == src_id), None)
    found = set()
    for raw in raws:
        hits = []
        if node is not None:
            hits = [
                i
                for i in range(node.start, min(node.end, len(lines)) + 1)
                if raw in lines[i - 1] and (kind != "map-position" or lines[i - 1].startswith("总图位置："))
            ]
        found.update(hits)
    return sorted(found)


def who(root, spec):
    idx = load_index(root)
    ids = all_ids(root, idx)
    tracked = set(git_tracked(root))
    target = resolve_spec(spec, ids, tracked)
    cache = {}
    rows = []
    for path, d in idx.items():
        for e in d["edges"]:
            if target_match(target, e["dst"]) and not target_match(target, e["src"]):
                lines = line_numbers(root, cache, path, e["src"], e["raws"], e["kind"])
                rows.append((path, lines, e))
    rows.sort(key=lambda r: (r[0], r[1], r[2]["dst"]))
    return target, rows


def is_record_doc(path):
    cfg = json.loads((DATA / "record-docs.json").read_bytes().decode("utf-8"))
    return path in cfg["files"] or path.startswith(tuple(cfg["prefixes"]))


def counts_for_pending(src_file, dst):
    """待核对的范围：上下游都不是记录文档；只有指向小节、表格行、总图的节或缝的引用参与，
    指向整份文件的引用只查文件在不在（死引用检查），不参与。"""
    return "#" in dst and not is_record_doc(src_file) and not is_record_doc(dst.split("#", 1)[0])


def pending(root, model=None):
    """上游变了而下游没变、也没确认的边，范围见 counts_for_pending。"""
    model = model or scan_repo(root)
    idx = load_index(root)
    confirmed = confirmed_keys(root)
    out = []
    for path, d in sorted(idx.items()):
        old_nodes = {n["id"]: n["hash"] for n in d["nodes"]}
        for e in d["edges"]:
            if not counts_for_pending(path, e["dst"]):
                continue
            src = model.nodes.get(e["src"])
            if src is None or src.hash != old_nodes[e["src"]]:
                continue  # 下游改过，算处理过
            up = model.hash_of(e["dst"])
            if up != e["seen"] and (e["src"], e["dst"], up) not in confirmed:
                out.append((path, e, up))
    return model, out


def confirm(root, down_spec, up_spec=None):
    model, items = pending(root)
    ids = all_ids(root)
    down = resolve_spec(down_spec, ids)
    up = resolve_spec(up_spec, ids, model.tracked_set) if up_spec else None
    todo = [
        (e, h)
        for _, e, h in items
        if target_match(down, e["src"]) and (up is None or target_match(up, e["dst"]))
    ]
    p = index_root(root) / "confirmed.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fh:
        for e, h in todo:
            fh.write(dump_lines({"src": e["src"], "dst": e["dst"], "down": model.nodes[e["src"]].hash, "up": h}) + "\n")
    return todo
