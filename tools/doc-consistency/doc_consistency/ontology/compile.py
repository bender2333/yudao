"""把规则事实线的两份词表编译成本体事实（方案第 10.1 节接法第 3 条）。

`canon.json` 的写法在本体里是什么（方案第 10.1 节的对照表）：
表的 node 是种类；首列每一行是这个种类的实例；列的 fact 是关系，many 是单值或多值，
vocab 是关系终点的种类；roles.json 的别名、顶层「载体别名」是别名；groups 是实例的集合。
这些概念都住在「脚手架」这一层（方案第 10.1 节接法第 5 条）。

第 1 节「事实放在哪」一行的表级别名和「位置」一格要分开看（方案第 10.1 节「重新建模」）：
是载体的（工单正文、子工单、总图……）不是这一行的另一个名字，而是这一行关于的东西，编成 about；
「位置」一格里的反引号路径是这一行放在仓库的哪里，编成 located_in；
不是载体的表级别名（缝的已定未定、推送、合并……）才是别名。

canon.json 没有、本体的规则要用的声明，放在 data/ontology/overlay.json，不改 canon.json。
"""

from dataclasses import dataclass, field

from ..rulefacts.canon import carrier_map, read_tables
from ..rulefacts.patterns import carrier_aliases
from ..scaffold import load_json, sym
from ..scan import scan_repo

SCAFFOLD = "scaffold"
ROLE = "角色"
CARRIER = "载体"
PATH = "路径"
PHRASE = "短语"  # 没有词表的列：一格按顿号、分号切开，每个短语原样当一个值


@dataclass
class Facts:
    symbols: set = field(default_factory=set)
    kinds: dict = field(default_factory=dict)  # 种类 -> 层
    rels: list = field(default_factory=list)  # (关系, 起点, 终点, 单多值, 出处)


def compile_facts(canon_cfg, roles_cfg, table_keys, overlay=None, prevails=(), located=None):
    """纯函数。
    table_keys：表 -> 首列的键；prevails：(优先的载体, 其次的载体)；
    located：表 -> {「位置」一格里的载体名: 那一行的键}；overlay：data/ontology/overlay.json 的内容。"""
    overlay = overlay or {"tables": {}, "relations": []}
    located = located or {}
    f = Facts()
    carriers = set(canon_cfg.get("vocab", {}).get(CARRIER, []))

    def kind(k, src):
        f.kinds.setdefault(k, SCAFFOLD)
        f.symbols.add(sym("kind", k, SCAFFOLD))
        f.symbols.add(sym("kind_from", k, src))

    def inst(name, k):
        f.symbols.add(sym("instance_of", name, k))

    def rel(name, dom, rng, card, src):
        f.rels.append((name, dom, rng, card, src))
        f.symbols.add(sym("rel", name, dom, rng, card, src))

    kind(ROLE, "roles.json")
    kind(PHRASE, "canon.json")
    for r, c in roles_cfg["roles"].items():
        inst(r, ROLE)
        for a in c.get("aliases", []):
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
        extra = overlay["tables"].get(tid, {})
        node = spec.get("node") or ""
        if extra.get("node"):
            f.symbols.add(sym("overlay_node", tid, extra["node"]))
            if node:
                f.symbols.add(sym("canon_node", tid, node))
            else:
                node = extra["node"]
        if node:
            kind(node, tid)
            for k in table_keys.get(tid, []):
                inst(k, node)
        for row, aliases in spec.get("aliases", {}).items():
            for a in aliases:
                if a in carriers:
                    f.symbols.add(sym("about", row, a, "aliases"))
                else:
                    f.symbols.add(sym("alias", a, row, tid))
        for c_name, row in located.get(tid, {}).items():
            if c_name in carriers:
                f.symbols.add(sym("about", row, c_name, "位置"))
            else:  # carrier_aliases 只给载体名和反引号路径，不是载体的就是路径
                inst(c_name, PATH)
                f.symbols.add(sym("located_in", row, c_name))
        for col, c in spec["columns"].items():
            name = c["fact"]
            if c.get("prevail"):
                between = extra.get("between", "")
                if between:
                    f.symbols.add(sym("overlay_between", tid, between))
                rel(name, between, between or CARRIER, "multi", tid)
            else:
                v = c.get("vocab")
                rng = ROLE if v == ROLE else (v or PHRASE)
                rel(name, node, rng, "multi" if c.get("many") else "single", tid)
            f.symbols.add(sym("rel_column", name, tid, col))
    for k in overlay.get("kinds", []):
        kind(k["name"], "overlay.json")
    for r in overlay.get("relations", []):
        rel(r["name"], r["from"], r["to"], r["card"], "overlay.json")
    for win, lose in prevails:
        f.symbols.add(sym("prevails", win, lose))
    return f


def compile_repo(root):
    """读真仓库：只读 canon.json、roles.json、overlay.json 与正本表格，不改任何文件。"""
    cfg = load_json("canon.json")
    model = scan_repo(root)
    _, _, _, _, keys, prevails = read_tables(model, cfg)
    carriers = carrier_map(cfg)
    located = {tid: carrier_aliases(model, tid, spec, carriers) for tid, spec in cfg["tables"].items()}
    return compile_facts(
        cfg,
        load_json("roles.json"),
        keys,
        load_json("ontology/overlay.json"),
        [(p.winner, p.loser) for p in prevails],
        located,
    )
