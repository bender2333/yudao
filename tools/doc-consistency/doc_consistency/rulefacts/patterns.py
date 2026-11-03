"""规则事实线第 3 步：句式解析。

把脚手架文件里正本表格以外的句子，用 Lark 文法（grammar.lark）读成原子：
  由谁          says(节点,键,事实,主语)
  只由谁        says 加 only(节点,键,事实,主语)
  谁不          says_not(节点,键,事实,主语)
  清单一员      member / not_member(节点,键,条目)
  以谁为准      prevails(节点,载体A,载体B)         A 优先
  在场可否      may(节点,角色,事,在场或不在场,可以或不可以)
  交给          handoff(节点,卡在项,角色)
  穷尽清单      only_members(节点,键,条目) 每条目一条，加 closed(节点,键)

词汇封闭：终结符从词表生成后接在文法后面（角色与别名、合称来自 roles.json；键来自 canon.json 九张表的首列，
第 1 节表另把「位置」一格里的载体名和反引号路径当那一行的键的别名；载体与机器来自 canon.json 的 vocab；动作词来自 rulefacts-scan.json；
动词到事实名的映射等在 rulefacts-patterns.json）。合称先展开再出原子；括号里的话与「领取时」「之前」这类限定
剥掉当附注，不进原子；没有主语的句子不解析、不猜。Python 只负责词表、规范化、把语法树翻成原子；比对在 rules/rulefacts/compare.lp。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from lark import Lark, Token, Tree
from lark.exceptions import LarkError

from ..scaffold import load_json
from .canon import BACKTICK, PAREN, role_aliases, row_cells, split_top
from .scan import LIST_MARK, SENT, bounded_src

GRAMMAR = Path(__file__).with_name("grammar.lark")
SHAPES = ("由谁", "只由谁", "谁不", "清单一员", "以谁为准", "在场可否", "交给", "穷尽清单")
SHAPE_OF = {
    "by_who": "由谁",
    "only_who": "只由谁",
    "who_not": "谁不",
    "who_not_bare": "谁不",
    "member": "清单一员",
    "not_member": "清单一员",
    "lead_member": "清单一员",
    "lead_not_member": "清单一员",
    "prevails": "以谁为准",
    "prevails_elided": "以谁为准",
    "may": "在场可否",
    "handoff": "交给",
    "closed_inline": "穷尽清单",
    "closed_count": "穷尽清单",
}
CJK = "⺀-鿿　-〿＀-￯"
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
COMMA = re.compile("，|,")
HALF2FULL = {",": "，", ";": "；", ":": "："}
ITEM_SPLIT = re.compile("；|;")


def nz(s):
    """规范化：汉字旁边的空白去掉，汉字后面的半角 , ; : 换成全角。词表和句子用同一个，两边才对得上。"""
    s = re.sub(rf"\s+(?=[{CJK}])|(?<=[{CJK}])\s+", "", s)
    return re.sub(rf"(?<=[{CJK}])([,;:])", lambda m: HALF2FULL[m.group(1)], s)


@dataclass
class Vocab:
    roles: dict  # 说法 -> [角色]，合称已展开
    machines: dict  # 说法 -> 机器
    keys: dict  # 说法 -> 键
    list_keys: dict  # 说法 -> 键（keys 加「交回」这类别名）
    carriers: dict  # 说法 -> 载体
    stuck: dict  # 说法 -> 第 7 节的卡在项
    events: dict  # 说法 -> 权限表的事
    verbs: dict  # 说法 -> [事实名]
    acts: set
    presence: dict
    mayv: dict
    hand: list
    adverbs: list
    key_facts: dict  # 键 -> {正本里有的事实名}
    hands_on: list
    quals: list
    qual_rx: list
    carrier_surfaces: set  # 是载体的键说法（第 1 节「位置」一格里的载体名）
    parser: object = None
    any_rx: object = None
    subj_rx: object = None
    grammar: str = ""


def head_parts(key):
    """表首列里一项的各种说法：去掉括号的全文、冒号前的头、头里顿号分开的各段。"""
    base = PAREN.sub("", key).strip()
    head = re.split("[：:]", base, maxsplit=1)[0].strip()
    parts = [p.strip() for p in head.split("、") if len(p.strip()) >= 2]
    return [base, head, *parts]


def carrier_aliases(model, tid, spec, carriers):
    """第 1 节表「位置」一格里的载体名和反引号路径 -> 这一行的键。
    例：「总图 `docs/architecture.html`、画面总图」里的「总图」和 docs/architecture.html；「`harness/`、`client/`」里的 harness/。"""
    col = spec.get("carrier_column")
    if not col:
        return {}
    file = tid.split("#", 1)[0]
    rows = sorted(
        (n for n in model.nodes.values() if n.kind == "row" and n.file == file and n.id.startswith(tid + " > ")),
        key=lambda n: n.start,
    )
    if not rows:
        return {}
    lines = model.files[file].text.split("\n")
    header = row_cells(lines[rows[0].start - 3])
    if col not in header:
        raise SystemExit(f"data/canon.json：{tid} 没有「{col}」这一列（载体别名从这里读）")
    out = {}
    for n in rows:
        vals = row_cells(lines[n.start - 1])
        cell = vals[header.index(col)] if header.index(col) < len(vals) else ""
        for path in BACKTICK.findall(PAREN.sub("", cell)):  # 括号里的路径只是顺带提到，不算
            out.setdefault(path.strip(), n.title)
        for piece in re.split(r"、|；|;|<br\s*/?>", cell):
            p = PAREN.sub("", LINK.sub(r"\1", piece)).replace("`", "").strip()
            first = p.split()[0] if p.split() else ""
            for cand in (p, first):
                if cand in carriers and cand not in out:
                    out[cand] = n.title
    return out


def alt(words):
    """正则备选，长的在前（词法每个位置只取第一个对上的）。空表用一个不会出现的字符。"""
    ws = sorted({w for w in words if w}, key=lambda w: (-len(w), w))
    if not ws:
        return r"\x00"
    return "|".join(re.escape(w).replace("/", r"\/") for w in ws)


def terminals(v):
    t = lambda name, words: f"{name}: /{alt(words)}/"
    return "\n".join(
        [
            t("ROLE", v.roles),
            t("MACHINE", v.machines),
            t("KEY", v.keys),
            t("LISTKEY", v.list_keys),
            t("STUCK", v.stuck),
            t("EVENT", v.events),
            t("CARRIER", v.carriers),
            t("_ADV", v.adverbs),
            t("VERB", v.verbs),
            t("ACT", v.acts),
            t("PRES", v.presence),
            t("MAYV", v.mayv),
            t("HAND", v.hand),
        ]
    )


def build_vocab(model, cfg, cells, keys):
    """词表。cells 是 canon.read_tables 读出的事实，keys 是各表首列的键（表 -> [键]）。"""
    pat = load_json("rulefacts-patterns.json")
    sc = load_json("rulefacts-scan.json")
    aliases, _ = role_aliases()
    roles = {nz(a): list(r) for a, r in aliases.items()}
    machines = {nz(m): m for m in cfg["vocab"].get("机器", [])}
    carrier_list = cfg["vocab"]["载体"]
    carriers = {nz(c): c for c in carrier_list}
    carriers.update({nz(a): t for a, t in cfg.get("载体别名", {}).items()})  # 「其他需求记录」读成「需求记录」
    verbs = {nz(k): list(f) for k, f in pat["动词"].items() if not k.startswith("_")}
    # 谁不 的无宾语写法（审查者不推送）只认这几个动作，且必须是粗筛的动作词；其余动词都要带键（架构师循环不改总图），
    # 免得「子架构师与架构师循环不建」这种宾语在前一个分句里的句子被读成没有宾语的原子
    acts = {nz(w) for w in pat["无宾语的动作"] if w in sc["actions"]}
    special = {f: name for f, name in pat["键的词表"].items() if not f.startswith("_")}
    suffixes = pat["卡在项的后缀"]
    key_facts = {}
    for c in cells:
        key_facts.setdefault(c.key, set()).add(c.fact)

    keyd, stuck, events, carrier_keys = {}, {}, {}, {}
    for tid, spec in cfg["tables"].items():
        if any(c.get("prevail") for c in spec["columns"].values()):
            continue  # 「以谁为准」表的首列是两个载体，不是键
        facts = {c["fact"] for c in spec["columns"].values()}
        kind = next((special[f] for f in sorted(facts) if f in special), None)
        for k in keys.get(tid, []):
            if kind == "卡在项":
                for part in head_parts(k)[2:] or head_parts(k)[1:2]:
                    for suf in ["", *suffixes]:
                        stuck.setdefault(nz(part + suf), k)
                stuck.setdefault(nz(head_parts(k)[0]), k)
            elif kind == "事":
                for s in head_parts(k):
                    events.setdefault(nz(s), k)
            elif spec.get("key_vocab") != "角色":
                keyd.setdefault(nz(k), k)
                if "：" in k:  # 「意图：目的、判据…」写成「意图」
                    keyd.setdefault(nz(head_parts(k)[1]), k)
        for k, names in spec.get("aliases", {}).items():  # canon.json 登记的别名（表级 aliases：行的键 -> 说法）
            for a in names:
                keyd.setdefault(nz(a), k)
        for c, k in carrier_aliases(model, tid, spec, set(carrier_list)).items():
            keyd.setdefault(nz(c), k)
            carrier_keys[nz(c)] = k
    list_keys = dict(keyd)
    for a, k in pat["清单的键别名"].items():
        if not a.startswith("_"):
            list_keys.setdefault(nz(a), k)

    quals = sorted({nz(q) for q in [*cfg.get("qualifiers", []), *pat["限定"]]}, key=lambda q: (-len(q), q))
    v = Vocab(
        roles=roles,
        machines=machines,
        keys=keyd,
        list_keys=list_keys,
        carriers=carriers,
        stuck=stuck,
        events=events,
        verbs=verbs,
        acts=acts,
        presence={nz(k): s for k, s in pat["在场词"].items()},
        mayv={nz(k): s for k, s in pat["可否词"].items()},
        hand=[nz(h) for h in pat["交给的动词"]],
        adverbs=[nz(a) for a in pat["副词"]],
        key_facts=key_facts,
        hands_on=list(pat["用户只定与确认"]["hands_on"]),
        quals=quals,
        qual_rx=[re.compile(nz(r)) for r in pat["限定正则"]],
        carrier_surfaces=set(carrier_keys),
    )
    v.grammar = GRAMMAR.read_text(encoding="utf-8") + "\n" + terminals(v)
    v.parser = Lark(v.grammar, parser="earley", lexer="dynamic", start="start", ambiguity="resolve")
    heads = [*roles, *machines, *keyd, *list_keys, *carriers, *stuck, *events]
    v.any_rx = re.compile(bounded_src(heads) + "|只有|这些|以下")
    v.subj_rx = re.compile(bounded_src([*roles, *machines]))
    return v


# ---------- 句子 ----------


@dataclass
class Group:
    """一个解析成功的句子（分句）。"""

    node: str  # 单元的 id，同一单元里第二个分句起带 .2 .3
    unit: str
    file: str
    line: int
    shape: str
    atoms: list  # (谓词, 参数…)，不含节点
    text: str  # 原句
    piece: str  # 实际解析的那一段（规范化以后）
    notes: list = field(default_factory=list)
    carrier: str = ""  # 主语是载体时的载体名（接「，与…不一致时以…为准」用）


class Reject(Exception):
    pass


def unit_text(u):
    """单元要解析的全文：引导句或句中冒号带的条目接在后面。"""
    if not u.items:
        return u.text
    base, sep = u.text.rstrip(), "；"
    if base.endswith(("：", ":")):
        base, sep = base.rstrip("：:"), "："
    items = []
    for _, t in u.items:
        t = SENT.split(LIST_MARK.sub("", t, 1))[0].strip()  # 条目所在行里后面另起的句子不算
        if t:
            items.append(t)
    return base + sep + "；".join(items)


def markup_clean(raw):
    t = LINK.sub(r"\1", raw).replace("`", "").replace("**", "")
    return re.sub("[「」『』“”]", "", t).strip()


def strip_parens(text):
    notes = []
    while True:
        m = PAREN.search(text)
        if not m:
            break
        inner = m.group(0)[1:-1].strip()
        if inner:
            notes.append(inner)
        text = text[: m.start()] + text[m.end() :]
    return text, notes


def strip_quals(v, text):
    notes = []
    for rx in v.qual_rx:  # 先剥带「在」的整段（在合并之前），再剥词表里的
        for m in rx.finditer(text):
            notes.append(m.group(0))
        text = rx.sub("", text)
    for q in v.quals:
        if q in text:
            notes.append(q)
            text = text.replace(q, "")
    return text, notes


def pick_fact(v, key, verb):
    cands = v.verbs[verb]
    have = v.key_facts.get(key, set())
    return next((f for f in cands if f in have), cands[0])


def expand(v, subjs):
    out = []
    for tok in subjs.children:
        s = str(tok)
        for r in v.roles.get(s) or [v.machines[s]]:
            if r not in out:
                out.append(r)
    return out


def key_of(v, kp):
    """「键」或「载体的键」（harness/ 的代码与测试）-> 键。「的」两边必须是同一行的键，否则不读。"""
    ks = {v.keys[str(t)] for t in kp.children}
    if len(ks) != 1:
        raise Reject
    return ks.pop()


def clean_item(v, text):
    t = text.strip().strip("。.")
    if len(t) < 2 or v.subj_rx.search(t) or re.match("下面这些|以下|这些", t):
        raise Reject  # 带主语的句子不是清单条目；代词不是
    return t


def build(v, tree):
    """语法树 -> (句式, 原子, 主语载体, 省略的以谁为准)。"""
    node = tree.children[-1]
    name, ch = str(node.data), node.children
    shape = SHAPE_OF[name]
    atoms, carrier, elided = [], "", None
    if name in ("by_who", "only_who"):
        keys, subj, verb = ch
        for kp in keys.children:
            k = key_of(v, kp)
            f = pick_fact(v, k, str(verb))
            for r in expand(v, subj):
                atoms.append(("says", k, f, r))
                if name == "only_who":
                    atoms.append(("only", k, f, r))
        if len(keys.children) == 1 and len(keys.children[0].children) == 1 and str(keys.children[0].children[0]) in v.carrier_surfaces:
            carrier = str(keys.children[0].children[0])
    elif name == "who_not":
        subj, verb, kp = ch
        k = key_of(v, kp)
        f = pick_fact(v, k, str(verb))
        atoms = [("says_not", k, f, r) for r in expand(v, subj)]
    elif name == "who_not_bare":
        subj, act = ch
        atoms = [("says_not", str(act), "做", r) for r in expand(v, subj)]
    elif name in ("member", "not_member"):
        item, lk = ch
        atoms = [(name, v.list_keys[str(lk)], clean_item(v, str(item)))]
    elif name in ("lead_member", "lead_not_member"):
        _, lk, items = ch
        k = v.list_keys[str(lk)]
        atoms = [(name[5:], k, clean_item(v, str(i))) for i in items.children]
    elif name == "prevails":
        a, b, w = (v.carriers[str(ch[i])] for i in (0, 1, 3))
        if w not in (a, b):
            raise Reject
        atoms = [("prevails", w, b if w == a else a)]
    elif name == "prevails_elided":
        other, w = (v.carriers[str(ch[i])] for i in (0, 2))
        elided = (w, other)
    elif name == "may":
        pres, subj, mayv, ev = ch
        atoms = [("may", r, v.events[str(ev)], v.presence[str(pres)], v.mayv[str(mayv)]) for r in expand(v, subj)]
    elif name == "handoff":
        stuck, _, subj = ch
        atoms = [("handoff", v.stuck[str(stuck)], r) for r in expand(v, subj)]
    elif name == "closed_inline":
        items, lk = ch
        k = v.list_keys[str(lk)]
        atoms = [("only_members", k, clean_item(v, str(i))) for i in items.children] + [("closed", k)]
    elif name == "closed_count":
        lk = next(c for c in ch if isinstance(c, Token) and c.type == "LISTKEY")
        items = ch[-1]
        k = v.list_keys[str(lk)]
        atoms = [("only_members", k, clean_item(v, str(i))) for i in items.children] + [("closed", k)]
    else:  # pragma: no cover
        raise Reject
    return shape, atoms, carrier, elided


def parse_body(v, body):
    """规范化以后的一段话 -> 解析结果，解析不了返回 None。"""
    body = body.strip()
    if not body or not v.any_rx.search(body):
        return None
    try:
        tree = v.parser.parse(body)
        return build(v, tree)
    except (LarkError, Reject):
        return None


def parse_piece(v, piece):
    """一段话：先原样，不行再把限定剥掉。返回 (结果, 附注) 或 None。括号里的话任何时候都先剥成附注。"""
    body, notes = strip_parens(piece)
    body = nz(body).strip().rstrip("。.！!？?；;")
    r = parse_body(v, body)
    if r:
        return r, notes
    body2, qn = strip_quals(v, body)
    if body2 != body:
        r = parse_body(v, body2)
        if r:
            return r, notes + qn
    return None


def parse_unit(v, u):
    """一个单元 -> [Group]。先整句，不行再按顶层的逗号切成分句各自解析（分句也要自己有主语）。"""
    full = unit_text(u)
    text = markup_clean(full)
    out = []

    def add(res, notes, piece):
        shape, atoms, carrier, _ = res
        node = u.id if not out else f"{u.id}.{len(out) + 1}"
        out.append(Group(node, u.id, u.file, u.line, shape, atoms, full, nz(piece), notes, carrier))

    got = parse_piece(v, text)
    if got and not got[0][3]:
        add(got[0], got[1], text)
        return out
    pieces = split_top(text, COMMA)
    if len(pieces) <= 1:
        return out
    prev_carrier = ""
    for piece in pieces:
        got = parse_piece(v, piece)
        if not got:
            prev_carrier = ""
            continue
        (shape, atoms, carrier, elided), notes = got
        if elided:
            # 「总图只由总架构师改，与设计说明不一致时以设计说明为准」：前一个分句的主语是载体，才知道谁和谁比
            if not prev_carrier or prev_carrier not in v.carriers:
                continue
            subject = v.carriers[prev_carrier]
            w, other = elided
            if w not in (subject, other):
                continue
            res = (shape, [("prevails", w, other if w == subject else subject)], "", None)
            add(res, notes, piece)
            prev_carrier = ""
            continue
        add((shape, atoms, carrier, None), notes, piece)
        prev_carrier = carrier
    return out


def parse_units(v, units):
    """所有单元 -> {单元 id: [Group]}，没解析成功的单元不在里面。"""
    out = {}
    for u in units:
        gs = parse_unit(v, u)
        if gs:
            out[u.id] = gs
    return out
