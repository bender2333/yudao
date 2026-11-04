"""把规则事实线的两份词表编译成本体事实（方案第 10.1 节接法第 3 条）。

`canon.json` 的写法在本体里是什么（方案第 10.1 节的对照表）：
表的 node 是种类；首列每一行是这个种类的实例；列的 fact 是关系，many 是单值或多值，
vocab 是关系终点的种类；表级 aliases、roles.json 的别名、顶层「载体别名」是别名；groups 是实例的集合。
这些概念都住在「脚手架」这一层（方案第 10.1 节接法第 5 条）。
"""

from dataclasses import dataclass, field

from ..rulefacts.canon import read_tables
from ..scaffold import load_json, sym
from ..scan import scan_repo

SCAFFOLD = "scaffold"
ROLE = "角色"
PHRASE = "短语"  # 没有词表的列：一格按顿号、分号切开，每个短语原样当一个值


@dataclass
class Facts:
    symbols: set = field(default_factory=set)
    kinds: dict = field(default_factory=dict)  # 种类 -> 层
    rels: list = field(default_factory=list)  # (关系, 起点, 终点, 单多值, 表)


def compile_facts(canon_cfg, roles_cfg, table_keys):
    """纯函数：canon.json、roles.json 的内容与每张表首列的键 -> 本体事实。"""
    f = Facts()

    def kind(k, src):
        f.kinds.setdefault(k, SCAFFOLD)
        f.symbols.add(sym("kind", k, SCAFFOLD))
        f.symbols.add(sym("kind_from", k, src))

    def inst(name, k):
        f.symbols.add(sym("instance_of", name, k))

    kind(ROLE, "roles.json")
    kind(PHRASE, "canon.json")
    for r in roles_cfg["roles"]:
        inst(r, ROLE)
        for a in roles_cfg["roles"][r].get("aliases", []):
            if a != r:
                f.symbols.add(sym("alias", a, r, "roles.json"))
    for g, members in roles_cfg.get("groups", {}).items():
        for m in members:
            f.symbols.add(sym("group", g, m))
    for vname, values in canon_cfg.get("vocab", {}).items():
        kind(vname, "canon.json vocab")
        for v in values:
            inst(v, vname)
    for a, target in canon_cfg.get("载体别名", {}).items():
        f.symbols.add(sym("alias", a, target, "canon.json 载体别名"))

    for tid, spec in canon_cfg["tables"].items():
        f.symbols.add(sym("table", tid))
        node = spec.get("node") or ""
        if node:
            kind(node, tid)
            for k in table_keys.get(tid, []):
                inst(k, node)
        for row, aliases in spec.get("aliases", {}).items():
            for a in aliases:
                f.symbols.add(sym("alias", a, row, tid))
        for col, c in spec["columns"].items():
            name = c["fact"]
            if c.get("prevail"):
                rng, card = "载体", "single"
            else:
                v = c.get("vocab")
                rng = ROLE if v == ROLE else (v or PHRASE)
                card = "multi" if c.get("many") else "single"
            f.rels.append((name, node, rng, card, tid))
            f.symbols.add(sym("rel", name, node, rng, card, tid))
            f.symbols.add(sym("rel_column", name, tid, col))
    return f


def compile_repo(root):
    """读真仓库：只读 canon.json、roles.json 与正本表格的首列，不改任何文件。"""
    cfg = load_json("canon.json")
    model = scan_repo(root)
    _, _, _, _, keys, _ = read_tables(model, cfg)
    return compile_facts(cfg, load_json("roles.json"), keys)
