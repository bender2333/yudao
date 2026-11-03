"""规则事实线的一页图：角色 × 规则矩阵 + 规则图。从 canon 读出的事实生成，不手画。"""

import json
import re
from pathlib import Path

from . import canon as rf

ASSETS = Path(__file__).resolve().parent.parent / "assets"
OUT = Path(".tmp") / "doc-index" / "rulefacts.html"


def page_data(root):
    c = rf.read_canon(root)
    named = set(c.named)
    unreach = {(r, t) for r, t in c.unreachable}
    dup_keys = {(k, f) for k, f, _, _ in c.dup}

    # 矩阵：一行一条（表, 键, 事实），值是展开后的全部值；角色事实才有格子标记
    matrix, order = [], {}
    for x in c.cells:
        k = (x.table, x.key, x.fact)
        if k not in order:
            spec = c.tables[x.table]
            is_role = any(v["fact"] == x.fact and v.get("vocab") == "角色" for v in spec["columns"].values())
            order[k] = {
                "table": x.table,
                "tableName": rf.short(x.table),
                "file": x.file,
                "key": x.key,
                "fact": x.fact,
                "values": [],
                "src": f"{x.file}:{x.line}",
                "isRole": is_role,
                "open": any(v["fact"] == x.fact and v.get("open") for v in spec["columns"].values()),
                "keyRole": spec.get("key_vocab") == "角色",
                "dup": (x.key, x.fact) in dup_keys,
            }
            matrix.append(order[k])
        order[k]["values"].append(x.value)
    for row in matrix:
        marks = {}
        if row["isRole"] or row["keyRole"]:
            # 值是角色的事实：被点名的是值里的角色；键是角色的表（角色表）：被点名的是键
            named_here = row["values"] if row["isRole"] else [row["key"]]
            for r in c.roles:
                if r not in named_here:
                    continue
                if (r, row["table"]) in unreach:
                    marks[r] = "miss"  # 被点名，读不到正本所在的文件
                elif r in c.agent_roles:
                    marks[r] = "read"
                else:
                    marks[r] = "na"  # 用户不是 agent，没有阅读范围
        row["marks"] = marks

    # 规则图：只画表里有的边
    nodes, by_id, edges = [], {}, []

    def node(kind, label):
        nid = f"{kind}:{label}"
        if nid not in by_id:
            by_id[nid] = {"id": nid, "kind": kind, "label": label, "facts": []}
            nodes.append(by_id[nid])
        return by_id[nid]

    for r in c.roles:
        node("角色", r)
    kind_of_table = {tid: spec["node"] for tid, spec in c.tables.items() if "node" in spec}
    for tid, kind in kind_of_table.items():
        for k in c.keys[tid]:
            node(kind, k)
    for x in c.cells:
        if x.table not in kind_of_table:  # 没有声明图节点的表（权限表）只进矩阵
            continue
        src = f"{x.file}:{x.line}"
        key_node = by_id.get(f"{kind_of_table[x.table]}:{x.key}") or next((n for n in nodes if n["label"] == x.key), None)
        if key_node is None:  # 键在别的表里才是节点（例如 needs-triage 的理由写在第 7 节）
            key_node = node(kind_of_table[x.table], x.key)
        key_node["facts"].append({"text": f"{x.key} {x.fact} {x.value}", "src": src})
        if x.edge:
            role_node = by_id[f"角色:{x.value}"]
            if role_node is not key_node:
                role_node["facts"].append({"text": f"{x.key} {x.fact} {x.value}", "src": src})
            a, b = (role_node, key_node) if x.edge == "角色→键" else (key_node, role_node)
            edges.append({"source": a["id"], "target": b["id"], "fact": x.fact, "src": src})
    kinds = ["角色"] + [k for k in dict.fromkeys(kind_of_table.values()) if k != "角色"]

    return {
        "roles": [{"name": r, "agent": r in c.agent_roles} for r in c.roles],
        "matrix": matrix,
        "graph": {"nodes": nodes, "edges": edges, "kinds": kinds},
        "notes": [{"table": rf.short(x.table), "key": x.key, "fact": x.fact, "text": x.text, "src": f"{x.file}:{x.line}"} for x in c.notes],
        "unparsed": [{"table": rf.short(x.table), "key": x.key, "column": x.column, "text": x.text, "src": f"{x.file}:{x.line}"} for x in c.unparsed],
        "dups": [
            {
                "key": k,
                "fact": f,
                "sides": [
                    {
                        "table": rf.short(t),
                        "src": ",".join(sorted({f"{x.file}:{x.line}" for x in c.cells if (x.table, x.key, x.fact) == (t, k, f)})),
                        "values": [x.value for x in c.cells if (x.table, x.key, x.fact) == (t, k, f)],
                        "only": [v for kk, ff, v, tt in c.only_in if (kk, ff, tt) == (k, f, t)],
                    }
                    for t in (t1, t2)
                ],
            }
            for k, f, t1, t2 in c.dup
        ],
        "unreachable": [{"role": r, "table": rf.short(t), "file": t.split("#", 1)[0]} for r, t in c.unreachable],
        "stat": {
            "facts": len(c.cells),
            "notes": len(c.notes),
            "unparsed": len(c.unparsed),
            "dup": len(c.dup),
            "unreachable": len(c.unreachable),
        },
    }


def view(root):
    data = page_data(root)
    page = (ASSETS / "rulefacts.html").read_text(encoding="utf-8")
    lib = (ASSETS / "cytoscape.min.js").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    parts = {"DATA": payload, "LIB": lib}
    page = re.sub(r"__(DATA|LIB)__", lambda m: parts[m.group(1)], page)
    out = Path(root) / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    return out, data
