"""规则事实线第 2 步：粗筛与盘点。

在脚手架文件里找「像在复述规则」的句子，分三类，数出迁移量与噪音率。只读、不改任何文档、不调用 LLM。
词表：键取自 canon.json 的九张正本表、标签快照与脚手架文件所有表格的首列；角色取自 roles.json（复用 canon.role_aliases）；
动作词与句式动词在 data/rulefacts-scan.json。

粗筛：一句话里同时有键、角色、动作词，就是候选。
第 3 步补了两条：主语是机器（CI、脚本、钩子）的句子算候选；匹配八种句式粗形状的句子直接算候选，不再要求同时有键、角色与动作词。
三类（按顺序判，规则写在 finish）：
  1. 解析成功：patterns.py 用真正的文法（grammar.lark）解析成功。陈述加指路的句子也按解析走。
  2. 已是引用：纯指路的句子：句子里有指向正本文件的链接、`路径`「小节」、或「见 X」（X 是正本文件名），并且没有「由」「不」「为准」「理由」这些陈述规则的词，而且解析不了。
  3. 不是规则事实：命中了词表，但既没解析成功也不是纯指路（流程叙述、例子、命令行、格式说明，也有还没写成句式的规则事实）。
"""

import json
import random
import re
from dataclasses import dataclass, field

from ..scaffold import file_of, labels_file, load_json
from ..scan import MD, is_scaffold, scan_repo
from .canon import role_aliases, row_cells

SAMPLE_SEED = 20261103
CLS = ("已是引用", "解析成功", "不是规则事实")

CUT = re.compile(r"[。；！？]|<br\s*/?>")
SENT = re.compile(r"[。！？]|<br\s*/?>")
LIST_MARK = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
FENCE = re.compile(r"^\s*(```|~~~)")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
LEAD_COLON = ("：", ":")
STATEMENT = ("由", "不", "为准", "理由")  # 在陈述规则的词：有了就不算「已是引用」


@dataclass
class Unit:
    """一个要解析的句子（分句）。不论是不是候选，脚手架文件里正本表格行以外的每个分句都有一个。"""

    file: str
    line: int
    idx: int  # 同一行里第几个
    text: str
    items: list = field(default_factory=list)  # 引导句或句中冒号带的 (行号, 原文)
    table: bool = False
    code: bool = False

    @property
    def id(self):
        return f"{self.file}:{self.line}#{self.idx}"


@dataclass
class Hit:
    file: str
    line: int
    text: str
    items: list = field(default_factory=list)  # 引导句带的 (行号, 原文)
    cls: str = ""
    shapes: list = field(default_factory=list)
    narrow: bool = False
    code: bool = False
    table: bool = False
    group: bool = False  # 靠引导句加它下面的条目合起来才命中
    shape_lead: bool = False  # 引导句自己没有键、角色、动作词，但本身是「是…的理由」「以…为准」的形状
    inherited: bool = False  # 表格格子靠所在行首列补上了键或角色
    keys: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    by_shape: bool = False  # 没有键、角色或动作词，靠句式形状补入
    by_machine: bool = False  # 主语是机器（CI、脚本、钩子）
    unit: object = None
    groups: list = field(default_factory=list)  # 解析成功的结果（patterns.Group）


def bounded_src(words):
    """词的正则源码：纯 ASCII 的词两边不能紧挨字母数字，免得 stage 命中 backstage。中文词直接子串。"""
    parts = []
    for w in sorted(set(words), key=lambda x: (-len(x), x)):
        e = re.escape(w)
        if re.fullmatch(r"[\x21-\x7e]+", w):
            e = rf"(?<![A-Za-z0-9_-]){e}(?![A-Za-z0-9_-])"
        parts.append(e)
    return "|".join(parts)


def bounded(words):
    src = bounded_src(words)
    return re.compile(src) if src else None


def find_all(rx, text):
    return sorted({m.group(0) for m in rx.finditer(text)}) if rx else []


@dataclass
class Vocab:
    narrow_keys: set
    wide_keys: set
    roles: set
    role_names: set
    actions: set
    ignore: list
    canon_tables: list  # 正本表格的 tid
    canon_files: dict  # 正本文件 -> 能指到它的写法
    no_labels: bool
    shapes: dict
    machines: set = field(default_factory=set)
    rx_narrow: object = None
    rx_wide: object = None
    rx_role: object = None
    rx_action: object = None
    rx_machine: object = None
    rx_shape: dict = field(default_factory=dict)
    rx_machine_subject: object = None


def load_vocab(root, model):
    cfg = load_json("canon.json")
    sc = load_json("rulefacts-scan.json")
    pat = load_json("rulefacts-patterns.json")
    machines = set(cfg.get("vocab", {}).get("机器", []))
    aliases, _ = role_aliases()
    role_names = set(aliases)
    labels, no_labels = set(), False
    p = labels_file(root)
    if p.is_file():
        labels = set(json.loads(p.read_bytes().decode("utf-8"))["labels"])
    else:
        no_labels = True
    narrow = set(labels)
    wide = set()
    canon_files = {}
    for tid, spec in cfg["tables"].items():
        keys = {n.title for n in model.nodes.values() if n.kind == "row" and n.id.startswith(tid + " > ")}
        (narrow if spec.get("node") == "证据前缀" else wide).update(keys)
        f = file_of(tid)
        h1 = next((n.title for n in model.files[f].nodes if n.kind == "section" and n.parent == f), "") if f in model.files else ""
        base = f.rsplit("/", 1)[-1]
        canon_files[f] = (f, base, h1)
    # 脚手架文件所有表格的首列（canon 之外的表格，也包括正本表格自己的键）
    for n in model.nodes.values():
        if n.kind == "row" and is_scaffold(n.file):
            wide.add(n.title)
    wide -= {"(空)", ""}
    if not sc.get("role_as_key", True):
        narrow -= role_names
        wide -= role_names
    narrow = {k for k in narrow if len(k) >= 2}
    wide = {k for k in wide if len(k) >= 2} - narrow
    v = Vocab(
        narrow_keys=narrow,
        wide_keys=wide,
        roles=role_names,
        role_names=role_names,
        actions=set(sc["actions"]),
        ignore=sorted(sc["action_ignore"], key=len, reverse=True),
        canon_tables=list(cfg["tables"]),
        canon_files=canon_files,
        no_labels=no_labels,
        shapes=sc["shapes"],
        machines=machines,
    )
    v.rx_narrow, v.rx_wide = bounded(narrow), bounded(wide)
    v.rx_role = bounded(v.roles)
    v.rx_action = bounded(v.actions)
    v.rx_machine = bounded(machines)
    verbs = lambda ws: "|".join(re.escape(w) for w in sorted(set(ws), key=lambda x: (-len(x), x)))
    # 句式动词：粗筛里写的，加上第 3 步句式里的动词（rulefacts-patterns.json）
    by_verbs = list(sc["shapes"]["由谁"]) + [w for w in pat["动词"] if not w.startswith("_")]
    role_rx = "|".join(re.escape(r) for r in sorted(v.roles | machines, key=lambda x: (-len(x), x)))
    # 八种句式的粗形状（引用不算）。窄口径、宽口径与动作词都不要求，形状对上就是候选
    v.rx_shape = {
        "只由谁": re.compile(r"只由"),
        "由谁": re.compile(rf"(?<![理自经缘事来只])由(?!于)[^，。；：]{{0,60}}?(?:{verbs(by_verbs)})"),
        "谁不": re.compile(rf"(?:{role_rx})[^，。；：]{{0,12}}?不(?:{verbs(sc['shapes']['谁不'])})"),
        "清单一员": re.compile(r"是[^，。；]{1,30}的理由"),
        "以谁为准": re.compile(r"以[^，。；]{1,30}为准|为准"),
        "在场可否": re.compile(r"在场[^，。；]{0,30}?(?:可以|不能)"),
        "交给": re.compile(rf"(?:{verbs(pat['交给的动词'])})(?:{role_rx})"),
        "穷尽清单": re.compile(r"只有[^，。；]{0,40}?(?:是[^，。；]{1,30}的理由|情形|情况|种)"),
    }
    # 主语是机器：「由 CI …做」或分句一开头就是机器，后面跟着动词
    if machines:
        v.rx_machine_subject = re.compile(
            rf"(?:由|^)\s*(?:{bounded_src(machines)})[^，。；：]{{0,24}}?(?:{verbs(set(by_verbs) | set(sc['actions']))})"
        )
    return v


def clean(text):
    """匹配用的文本：链接只留显示文字。"""
    return LINK_TARGET.sub("]", text)


def match(v, text, ctx=""):
    """返回 (窄命中的键, 宽命中的键, 角色, 动作词)。ctx 是表格行首列，补充键与角色。"""
    t = clean(text)
    both = t + "\n" + ctx
    mask = t
    for ig in v.ignore:
        mask = mask.replace(ig, "")
    return (
        find_all(v.rx_narrow, both),
        find_all(v.rx_wide, both),
        find_all(v.rx_role, both),
        find_all(v.rx_action, mask),
    )


def is_pointer(v, text):
    """纯指路：句子里有指向正本文件的链接、反引号路径加「小节」、或「见」加正本文件的标题，并且没有陈述规则的词。"""
    refers = False
    for names in v.canon_files.values():
        if any(n in text for n in names[:2]):  # 路径或文件名：链接、反引号路径、「小节」都带着它
            refers = True
        if names[2] and re.search(rf"见\s*[`\[「]?{re.escape(names[2])}", text):  # 见 + 文件的标题
            refers = True
    return refers and not any(w in clean(text) for w in STATEMENT)


def finish(v, h):
    """三类分法，按顺序判：解析成功；纯指路（解析不了的才算）；其余。"""
    if h.groups:
        h.cls, h.shapes = CLS[1], list(dict.fromkeys(g.shape for g in h.groups))
    elif is_pointer(v, h.text):
        h.cls, h.shapes = CLS[0], []
    else:
        h.cls, h.shapes = CLS[2], []


# ---------- 切分 ----------


def line_kinds(tokens, lines):
    """每行的种类：skip（标题、表头、分隔线、代码围栏线）、code、row（表格正文行）；没有的是正文。"""
    kinds = {}
    for t in tokens:
        if not t.map:
            continue
        s, e = t.map
        if t.type == "fence":
            closed = lines[e - 1].strip().startswith(("```", "~~~")) and e - 1 > s
            kinds[s] = "skip"
            if closed:
                kinds[e - 1] = "skip"
            for i in range(s + 1, e - 1 if closed else e):
                kinds[i] = "code"
        elif t.type == "code_block":
            for i in range(s, e):
                kinds[i] = "code"
        elif t.type in ("heading_open", "hr", "html_block"):
            for i in range(s, e):
                kinds[i] = "skip"
        elif t.type == "table_open":
            kinds[s] = kinds[s + 1] = "skip"
            for i in range(s + 2, e):
                kinds[i] = "row"
    return kinds


def segments(text):
    return [s.strip() for s in CUT.split(text) if s.strip()]


def sentences(text):
    """先按「。！？」与 <br> 切成句，每句再按「；」切成分句。返回 [[分句, ...], ...]。"""
    out = []
    for sent in SENT.split(text):
        clauses = [c.strip() for c in sent.split("；") if c.strip()]
        if clauses:
            out.append(clauses)
    return out


def lead_extent(lines, kinds, i, base, is_item):
    """引导句在第 i 行（0 起）行尾：它后面紧跟的列表项与续行，到空行、标题、表格、代码块、同级下一项为止。返回行号列表。"""
    out, j = [], i + 1
    while j < len(lines):
        raw = lines[j]
        if not raw.strip():
            k = j
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k >= len(lines) or kinds.get(k) in ("skip", "code", "row"):
                break
            m = LIST_MARK.match(lines[k])
            indent = len(lines[k]) - len(lines[k].lstrip())
            ok = (m and (indent > base if is_item else indent >= base)) or (not m and indent > base)
            if not ok:
                break
            j = k
            raw = lines[j]
        if kinds.get(j) in ("skip", "code", "row"):
            break
        m = LIST_MARK.match(raw)
        indent = len(raw) - len(raw.lstrip())
        if m and (indent <= base if is_item else indent < base):
            break  # 同级或更外层的下一项
        out.append(j)
        j += 1
    return out


def scan_file(v, scan):
    lines = scan.text.split("\n")
    tokens = MD.parse(scan.text)
    kinds = line_kinds(tokens, lines)
    # 正本表格的行不扫（是正本，不是复述）
    canon_rows = {n.start - 1 for n in scan.nodes if n.kind == "row" and any(n.id.startswith(t + " > ") for t in v.canon_tables)}
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            start = end + 1  # YAML 头跳过
    hits, n_sent, units = [], 0, []
    consumed = set()
    per_line = {}

    def new_unit(text, line, **kw):
        k = per_line[line] = per_line.get(line, 0) + 1
        u = Unit(scan.path, line, k, text, **kw)
        units.append(u)
        return u

    def make(u, ctx="", text=None, shape_ok=True, **kw):
        """候选：键、角色、动作词齐了；或者（shape_ok）主语是机器、句式形状对上。"""
        t = u.text if text is None else text
        nk, wk, roles, acts = match(v, t, ctx)
        base = bool((nk or wk) and roles and acts)
        by_machine = by_shape = False
        if not base:
            if not shape_ok:
                return None
            c = clean(t)
            by_machine = bool(v.rx_machine_subject and v.rx_machine_subject.search(c))
            by_shape = not by_machine and any(rx.search(c) for rx in v.rx_shape.values())
            if not (by_machine or by_shape):
                return None
        h = Hit(scan.path, u.line, u.text, narrow=bool(nk), keys=nk + wk, roles=roles, actions=acts, by_machine=by_machine, by_shape=by_shape, unit=u, **kw)
        own = match(v, t)
        h.inherited = base and not ((own[0] or own[1]) and own[2])
        return h

    i = start
    while i < len(lines):
        raw = lines[i]
        kind = kinds.get(i)
        if not raw.strip() or kind == "skip" or i in consumed or i in canon_rows:
            i += 1
            continue
        if kind == "row":
            cells = row_cells(raw)
            ctx = cells[0] if cells else ""
            for ci, cell in enumerate(cells):
                for seg in segments(cell):
                    n_sent += 1
                    u = new_unit(seg, i + 1, table=True)
                    h = make(u, ctx if ci else "", table=True)
                    if h:
                        hits.append(h)
            i += 1
            continue
        m = LIST_MARK.match(raw)
        body = raw[m.end() :] if m else raw.lstrip()
        body = re.sub(r"^>\s*", "", body)
        indent = len(m.group(1)) if m else len(raw) - len(raw.lstrip())
        sents = sentences(body)
        n_sent += sum(len(x) for x in sents)
        in_code = kind == "code"
        for si, clauses in enumerate(sents):
            skip = set()
            for ci, seg in enumerate(clauses):
                if ci in skip:
                    continue
                last = si == len(sents) - 1 and ci == len(clauses) - 1
                if last and not in_code and body.rstrip().endswith(LEAD_COLON):
                    # 引导句：它下面紧跟的列表项与续行一起算
                    rows = lead_extent(lines, kinds, i, indent, bool(m))
                    items = [(j + 1, lines[j].strip()) for j in rows]
                    u = new_unit(seg, i + 1, items=items, code=in_code)
                    whole = seg + "：" + "；".join(t for _, t in items) if items else seg
                    h = make(u, shape_ok=False, code=in_code)
                    if h is None and items:
                        h = make(u, text=whole, shape_ok=False, code=in_code, group=True)
                    if h is None:
                        # 引导句本身就是「（不）是…的理由」「以…为准」的形状：词表之外补进来，单独记数
                        if any(v.rx_shape[n].search(seg) for n in ("清单一员", "以谁为准", "穷尽清单")):
                            h = Hit(scan.path, i + 1, seg, code=in_code, shape_lead=True, unit=u)
                    if h:
                        h.items = items
                        hits.append(h)
                        consumed.update(rows)
                    continue
                u = new_unit(seg, i + 1, code=in_code)
                inline = seg.find("：")
                rest = clauses[ci + 1 :] if 0 <= inline < len(seg) - 1 and ci < len(clauses) - 1 else []
                u.items = [(i + 1, t) for t in rest]  # 句中的冒号引出「；」分开的几项：同一句里后面的分句是它的条目
                h = make(u, code=in_code)
                if h:
                    if rest:
                        h.items = u.items
                        skip.update(range(ci + 1, len(clauses)))
                    hits.append(h)
        i += 1
    return hits, n_sent, units


class Scanned:
    """scan_all 的结果。"""

    def __init__(self, v, hits, files, total, units, pv, groups):
        self.v, self.hits, self.files, self.total, self.units, self.pv, self.groups = v, hits, files, total, units, pv, groups


def scan_all(root, model=None, parse=True):
    """扫出候选，并（parse）用真正的文法解析每个分句。parse=False 只为测词表，三类分法不可用。"""
    model = model or scan_repo(root)
    v = load_vocab(root, model)
    hits, files, total, units = [], {}, 0, []
    for path in sorted(model.files):
        if not (is_scaffold(path) and path.endswith(".md")):
            continue
        h, n, u = scan_file(v, model.files[path])
        files[path] = (n, h)
        hits += h
        units += u
        total += n
    pv, groups = None, {}
    if parse:
        from . import patterns  # 晚一点导入：patterns 不依赖本模块
        from .canon import read_tables

        cfg = load_json("canon.json")
        cells, _, _, _, keys, _ = read_tables(model, cfg)
        pv = patterns.build_vocab(model, cfg, cells, keys)
        groups = patterns.parse_units(pv, units)
    for h in hits:
        h.groups = groups.get(h.unit.id, []) if h.unit else []
        finish(v, h)
    return Scanned(v, hits, files, total, units, pv, groups)


# ---------- 输出 ----------


def tag(h):
    t = f"{h.cls}/{'、'.join(h.shapes) or '-'}，{'窄' if h.narrow else '宽'}"
    return (
        t
        + ("，代码块" if h.code else "")
        + ("，形状补入" if h.shape_lead else "")
        + ("，机器主语补入" if h.by_machine else "")
        + ("，句式形状补入" if h.by_shape else "")
        + ("，表格" if h.table else "")
    )


def fmt_hit(h):
    out = [f"{h.file}:{h.line}  [{tag(h)}]  {h.text}"]
    out += [f"    {ln}: {t}" for ln, t in h.items]
    return out


def counts(hits):
    return {c: sum(1 for h in hits if h.cls == c) for c in CLS}


def format_scan(root, sample=None):
    sc = scan_all(root)
    v, hits, files, total = sc.v, sc.hits, sc.files, sc.total
    n = len(hits)
    c = counts(hits)
    narrow = [h for h in hits if h.narrow]
    rows = [h for h in hits if h.table]
    parsed = [u for u in sc.units if sc.groups.get(u.id)]
    hit_units = {h.unit.id for h in hits if h.unit}
    out = [
        f"规则事实线·粗筛：{len(files)} 个脚手架文件，{total} 个句子（表格一格一句）；候选 {n} 条",
        f"三类：已是引用 {c[CLS[0]]}，解析成功 {c[CLS[1]]}，不是规则事实 {c[CLS[2]]}",
        f"窄口径命中 {len(narrow)}（其中表格格子 {sum(1 for h in narrow if h.table)}），宽口径命中 {n}（含窄口径，其中表格格子 {len(rows)}，涉及 {len({(h.file, h.line) for h in rows})} 行）",
        f"其中：代码块里 {sum(1 for h in hits if h.code)}，靠引导句加条目合起来才命中 {sum(1 for h in hits if h.group)}，引导句只靠句式形状补入（没有键、角色或动作词）{sum(1 for h in hits if h.shape_lead)}，表格格子靠所在行首列补上键或角色 {sum(1 for h in hits if h.inherited)}",
        f"第 3 步补入：机器主语 {sum(1 for h in hits if h.by_machine)}，句式形状（没有键、角色或动作词）{sum(1 for h in hits if h.by_shape)}；文法解析成功共 {len(parsed)} 个分句，其中不是候选的 {sum(1 for u in parsed if u.id not in hit_units)} 个",
        f"词表：窄口径键 {len(v.narrow_keys)} 个（标签快照与证据前缀），其余键 {len(v.wide_keys)} 个，角色与别名 {len(v.roles)} 个，动作词 {len(v.actions)} 个"
        + ("；没有标签快照（.doc-index/labels.json），标签来源已跳过" if v.no_labels else ""),
        "",
        "文件\t总数\t引用\t解析\t非规则\t窄\t宽(含窄)",
    ]
    for p, (_, hs) in files.items():
        if hs:
            k = counts(hs)
            out.append(f"{p}\t{len(hs)}\t{k[CLS[0]]}\t{k[CLS[1]]}\t{k[CLS[2]]}\t{sum(1 for h in hs if h.narrow)}\t{len(hs)}")
    out.append("")
    shown = hits
    if sample is not None:
        shown = random.Random(SAMPLE_SEED).sample(hits, min(sample, n))
        order = {id(h): i for i, h in enumerate(hits)}
        shown.sort(key=lambda h: order[id(h)])
        out.append(f"== 抽样 {len(shown)} 条（共 {n} 条，固定种子 {SAMPLE_SEED}） ==")
    else:
        out.append("== 候选 ==")
    for h in shown:
        out += fmt_hit(h)
    return out
