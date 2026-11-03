"""规则事实线第 1 步：把正本表格读成事实，交给 clingo 比对。

Python 只负责读表、喂事实、取结论；比较在 rules/rulefacts/canon.lp。不读 .doc-index/，不用标签快照。
"""

import re
from dataclasses import dataclass, field

from markdown_it.rules_block.table import escapedSplit

from ..scaffold import file_of, load_json, pick, scaffold_facts, solve, sym
from ..scan import scan_repo

PAREN = re.compile(r"[（(][^）)]*[）)]")
BACKTICK = re.compile(r"`([^`]+)`")
BR = r"<br\s*/?>"
# 角色格：或、顿号、与、分号、逗号分开多个值；清单格（没有词表）只认顿号与分号
SEP_ROLE = re.compile(rf"或|、|与|；|;|，|,|{BR}")
SEP_LIST = re.compile(rf"、|；|;|{BR}")


@dataclass
class Cell:
    table: str
    key: str
    fact: str
    value: str
    file: str
    line: int
    edge: str = ""


@dataclass
class Note:
    table: str
    key: str
    fact: str
    text: str
    file: str
    line: int


@dataclass
class Unparsed:
    table: str
    key: str
    column: str
    text: str
    file: str
    line: int


@dataclass
class Canon:
    tables: dict  # 表 -> 配置，按 canon.json 的顺序
    cells: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    unparsed: list = field(default_factory=list)
    keys: dict = field(default_factory=dict)  # 表 -> 首列的键，按文档顺序
    canon: list = field(default_factory=list)  # (键, 事实, 值)，去重后
    dup: list = field(default_factory=list)  # (键, 事实, 表1, 表2)
    only_in: list = field(default_factory=list)  # (键, 事实, 值, 表)
    named: list = field(default_factory=list)  # (表, 角色)
    unreachable: list = field(default_factory=list)  # (角色, 表)
    roles: list = field(default_factory=list)  # 角色表里的全部角色，含不读文件的用户
    agent_roles: set = field(default_factory=set)
    syms: set = field(default_factory=set)  # 喂给 clingo 的事实，第 3 步比对时接着用


def short(table_id):
    """表的短名：去掉文件名和文档标题，只留「4. 状态与标签 > 表1」。"""
    parts = table_id.split("#", 1)[-1].split(" > ")
    return " > ".join(parts[1:]) if len(parts) > 2 else " > ".join(parts)


def role_aliases():
    """别名与合称 -> 展开后的角色。合称的成员必须是 roles.json 里的角色。"""
    cfg = load_json("roles.json")
    out = {}
    for r, c in cfg["roles"].items():
        for a in [r, *c.get("aliases", [])]:
            out[a] = [r]
    for g, members in cfg.get("groups", {}).items():
        bad = [m for m in members if m not in cfg["roles"]]
        if bad:
            raise SystemExit(f"data/roles.json：合称「{g}」里有不是角色的成员 {bad}")
        out[g] = list(members)
    return out, list(cfg["roles"])


def split_top(text, sep):
    """按分隔符切，括号里的不切。"""
    depth, depths = 0, []
    for ch in text:
        if ch in "（(":
            depth += 1
        depths.append(depth)
        if ch in "）)":
            depth = max(0, depth - 1)
    out, last = [], 0
    for m in sep.finditer(text):
        if depths[m.start()] == 0:
            out.append(text[last : m.start()])
            last = m.end()
    out.append(text[last:])
    return [x.strip() for x in out if x.strip()]


def row_cells(line):
    cols = escapedSplit(line.strip())
    if cols and cols[0] == "":
        cols = cols[1:]
    if cols and cols[-1] == "":
        cols = cols[:-1]
    return [c.strip() for c in cols]


def read_token(token, aliases, quals):
    """一个值。返回 (展开后的值列表或 None, 有没有剥掉括号或限定)。None 表示读不出。"""
    body = PAREN.sub("", token).strip()
    trimmed = body != token.strip()
    if not body:
        return [], True  # 只有一句括号里的话
    if aliases is None:
        return [body], trimmed
    body = body.strip("`")
    done = False
    while not done:
        done = True
        for q in quals:
            if body != q and body.startswith(q):
                body, trimmed, done = body[len(q) :].strip(), True, False
                break
            if body != q and body.endswith(q):
                body, trimmed, done = body[: -len(q)].strip(), True, False
                break
    return (aliases[body], trimmed) if body in aliases else (None, trimmed)


def read_closed(token, vocab):
    """写成名字的词表（可以、不可以）：第一个「，」前面必须是词表里的值，后面的话是附注。读不出返回 None。"""
    body = PAREN.sub("", token).strip()
    head, sep, rest = body.partition("，")
    head = head.strip().strip("`")
    if head not in vocab:
        return None, False
    return [head], bool(sep and rest.strip()) or body != token.strip()


def read_tables(model, cfg):
    aliases, _ = role_aliases()
    quals = sorted(cfg.get("qualifiers", []), key=len, reverse=True)
    cells, notes, unparsed, table_keys = [], [], [], {}
    seen = set()  # 同一格里两个合称展开出同一个角色，只记一次
    for tid, spec in cfg["tables"].items():
        file = file_of(tid)
        rows = sorted(
            (n for n in model.nodes.values() if n.kind == "row" and n.file == file and n.id.startswith(tid + " > ")),
            key=lambda n: n.start,
        )
        if not rows:
            raise SystemExit(f"data/canon.json：找不到表 {tid}（用 nodes 命令查节点名）")
        if rows[0].table != spec["key"]:
            raise SystemExit(f"data/canon.json：{tid} 的首列是「{rows[0].table}」，不是「{spec['key']}」")
        table_keys[tid] = list(dict.fromkeys(n.title for n in rows))
        lines = model.files[file].text.split("\n")
        header = row_cells(lines[rows[0].start - 3])
        for col in spec["columns"]:
            if col not in header:
                raise SystemExit(f"data/canon.json：{tid} 没有「{col}」这一列（表头：{header}）")
        for n in rows:
            vals = row_cells(lines[n.start - 1])
            cell_of = lambda col: vals[header.index(col)] if header.index(col) < len(vals) else ""
            for col, c in spec["columns"].items():
                text = cell_of(col)
                row_keys = [n.title]
                if "key_from" in c:
                    kf = c["key_from"]
                    row_keys = [t for t in BACKTICK.findall(cell_of(kf["column"])) if t in kf["tags"]]
                if "after" in c:
                    if c["after"] not in text:
                        continue
                    text = text.split(c["after"], 1)[1]
                is_role = c.get("vocab") == "角色"
                closed = cfg.get("vocab", {}).get(c.get("vocab"))  # 写成名字的词表；没有则是自由短语（角色除外）
                sep = SEP_ROLE if is_role else SEP_LIST
                tokens = split_top(text, sep) if c.get("many", True) else [text.strip()]
                for key in row_keys:
                    for tok in tokens:
                        if not tok:
                            continue
                        if closed:
                            got, trimmed = read_closed(tok, closed)
                        else:
                            got, trimmed = read_token(tok, aliases if is_role else None, quals)
                        if got is None:
                            unparsed.append(Unparsed(tid, key, col, tok, file, n.start))
                            continue
                        if trimmed:
                            notes.append(Note(tid, key, c["fact"], tok, file, n.start))
                        for v in got:
                            if (tid, key, c["fact"], v) not in seen:
                                seen.add((tid, key, c["fact"], v))
                                cells.append(Cell(tid, key, c["fact"], v, file, n.start, c.get("edge", "")))
    return cells, notes, unparsed, table_keys


def read_canon(root, model=None):
    model = model or scan_repo(root)
    cfg = load_json("canon.json")
    cells, notes, unparsed, keys = read_tables(model, cfg)
    # 阅读范围的事实照图谱线现成的；标签快照这条线用不到，传空集
    facts = scaffold_facts(model, set(), root)
    syms = set(facts.symbols)
    for tid, spec in cfg["tables"].items():
        syms.add(sym("canon_table", tid))
        syms.add(sym("in_file", tid, file_of(tid)))
        if spec.get("key_vocab") == "角色":
            syms.add(sym("key_role", tid))
        for c in spec["columns"].values():
            if c.get("vocab") == "角色":
                syms.add(sym("role_fact", tid, c["fact"]))
    for c in cells:
        syms.add(sym("cell", c.table, c.key, c.fact, c.value))
    atoms = solve(syms, ["scope.lp", "rulefacts/canon.lp"])
    _, all_roles = role_aliases()
    return Canon(
        tables=cfg["tables"],
        cells=cells,
        notes=notes,
        unparsed=unparsed,
        keys=keys,
        canon=pick(atoms, "canon"),
        dup=pick(atoms, "dup_canon"),
        only_in=pick(atoms, "only_in"),
        named=pick(atoms, "named"),
        unreachable=pick(atoms, "unreachable"),
        roles=all_roles,
        agent_roles={r for r, _ in facts.roles},
        syms=syms,
    )


def format_canon(c):
    out = []
    n_cells = len(c.cells)
    out.append(
        f"规则事实线：读出事实 {n_cells} 条（去重后 {len(c.canon)} 条），附注 {len(c.notes)} 条，读不出 {len(c.unparsed)} 条，"
        f"一条事实两处正本 {len(c.dup)} 条，读不到正本 {len(c.unreachable)} 条"
    )
    for tid, spec in c.tables.items():
        mine = [x for x in c.cells if x.table == tid]
        opened = "、".join(f"列「{col}」词表「{v['vocab']}」未封闭" for col, v in spec["columns"].items() if v.get("open"))
        out.append(f"== {tid}（键列「{spec['key'] or '（空）'}」，{len(mine)} 条{'；' + opened if opened else ''}） ==")
        for x in mine:
            out.append(f"{x.key} / {x.fact} / {x.value}    {x.file}:{x.line}")
    out.append(f"== 附注：{len(c.notes)} 条（括号里的话与限定，不进事实） ==")
    for x in c.notes:
        out.append(f"{x.file}:{x.line}  {x.key} / {x.fact}：{x.text}")
    out.append(f"== 读不出：{len(c.unparsed)} 条（不在词表里，原样报出，不猜） ==")
    for x in c.unparsed:
        out.append(f"{x.file}:{x.line}  {x.key} / 列「{x.column}」：{x.text}")
    return out + format_dup(c) + format_unreachable(c)


def format_dup(c):
    out = [f"== 一条事实两处正本：{len(c.dup)} 条 =="]
    for k, f, t1, t2 in c.dup:
        out.append(f"{k} / {f}")
        for t in (t1, t2):
            mine = [x for x in c.cells if x.table == t and x.key == k and x.fact == f]
            where = ",".join(sorted({f"{x.file}:{x.line}" for x in mine}))
            out.append(f"  {where}  {short(t)}：{'、'.join(x.value for x in mine)}")
        for t in (t1, t2):
            only = [v for kk, ff, v, tt in c.only_in if (kk, ff, tt) == (k, f, t)]
            out.append(f"  只在 {short(t)} 有：{'、'.join(only) if only else '（无）'}")
    return out


def format_unreachable(c):
    out = [f"== 读不到正本：{len(c.unreachable)} 条（正本点名的角色，必读范围里没有正本所在的文件） =="]
    for r, t in c.unreachable:
        out.append(f"{r}  读不到  {file_of(t)}  （{short(t)}）")
    return out
