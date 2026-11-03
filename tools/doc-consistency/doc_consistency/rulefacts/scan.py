"""规则事实线第 2 步：粗筛与盘点。

在脚手架文件里找「像在复述规则」的句子，分三类，数出迁移量与噪音率。只读、不改任何文档、不调用 LLM。
词表：键取自 canon.json 的六张正本表、标签快照与脚手架文件所有表格的首列；角色取自 roles.json（复用 canon.role_aliases）；
动作词与句式动词在 data/rulefacts-scan.json。

粗筛：一句话里同时有键、角色、动作词，就是候选。
三类（按顺序判，规则写在 classify）：
  1. 已是引用：句子里有指向正本文件的链接、`路径`「小节」、或「见 X」（X 是正本文件名），并且没有「由」「只由」「不」「为准」「理由」这些陈述规则的词。
  2. 能改成句式：匹配五种句式之一的粗形状（正则）：只由…；由…加/写/改…；角色…不加/改/写…；（不）是…的理由；以…为准。可同时像几种。
  3. 不是规则事实：命中了词表，但不合上面两类（流程叙述、例子、命令行、格式说明）。
"""

import json
import random
import re
from dataclasses import dataclass, field

from ..scaffold import file_of, labels_file, load_json
from ..scan import MD, is_scaffold, scan_repo
from .canon import role_aliases, row_cells

SAMPLE_SEED = 20261103
CLS = ("已是引用", "能改成句式", "不是规则事实")
SHAPES = ("只由谁", "由谁", "谁不", "是不是理由", "以谁为准")  # 与第 3.2 节五种句式对应（引用不在这里）

CUT = re.compile(r"[。；！？]|<br\s*/?>")
SENT = re.compile(r"[。！？]|<br\s*/?>")
LIST_MARK = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")
FENCE = re.compile(r"^\s*(```|~~~)")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
LEAD_COLON = ("：", ":")
STATEMENT = ("由", "不", "为准", "理由")  # 在陈述规则的词：有了就不算「已是引用」


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


def bounded(words):
    """词的正则：纯 ASCII 的词两边不能紧挨字母数字，免得 stage 命中 backstage。中文词直接子串。"""
    parts = []
    for w in sorted(set(words), key=lambda x: (-len(x), x)):
        e = re.escape(w)
        if re.fullmatch(r"[\x21-\x7e]+", w):
            e = rf"(?<![A-Za-z0-9_-]){e}(?![A-Za-z0-9_-])"
        parts.append(e)
    return re.compile("|".join(parts)) if parts else None


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
    rx_narrow: object = None
    rx_wide: object = None
    rx_role: object = None
    rx_action: object = None
    rx_shape: dict = field(default_factory=dict)


def load_vocab(root, model):
    cfg = load_json("canon.json")
    sc = load_json("rulefacts-scan.json")
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
    )
    v.rx_narrow, v.rx_wide = bounded(narrow), bounded(wide)
    v.rx_role = bounded(v.roles)
    v.rx_action = bounded(v.actions)
    verbs = lambda ws: "|".join(re.escape(w) for w in sorted(ws, key=lambda x: -len(x)))
    role_rx = "|".join(re.escape(r) for r in sorted(v.roles, key=lambda x: -len(x)))
    v.rx_shape = {
        "只由谁": re.compile(r"只由"),
        "由谁": re.compile(rf"(?<![理自经缘事来只])由(?!于)[^，。；：]{{0,60}}?(?:{verbs(sc['shapes']['由谁'])})"),
        "谁不": re.compile(rf"(?:{role_rx})[^，。；：]{{0,12}}?不(?:{verbs(sc['shapes']['谁不'])})"),
        "是不是理由": re.compile(r"是[^，。；]{1,30}的理由"),
        "以谁为准": re.compile(r"以[^，。；]{1,30}为准|为准"),
    }
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


def classify(v, text):
    """三类分法。返回 (类别, 句式列表)。"""
    shapes = [name for name, rx in v.rx_shape.items() if rx.search(clean(text))]
    refers = False
    for names in v.canon_files.values():
        if any(n in text for n in names[:2]):  # 路径或文件名：链接、反引号路径、「小节」都带着它
            refers = True
        if names[2] and re.search(rf"见\s*[`\[「]?{re.escape(names[2])}", text):  # 见 + 文件的标题
            refers = True
    if refers and not any(w in clean(text) for w in STATEMENT):
        return CLS[0], []
    if shapes:
        return CLS[1], shapes
    return CLS[2], []


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
    hits, n_sent = [], 0
    consumed = set()

    def make(text, line, ctx="", **kw):
        nk, wk, roles, acts = match(v, text, ctx)
        if not ((nk or wk) and roles and acts):
            return None
        cls, shapes = classify(v, text)
        h = Hit(scan.path, line, text, cls=cls, shapes=shapes, narrow=bool(nk), keys=nk + wk, roles=roles, actions=acts, **kw)
        own = match(v, text)
        h.inherited = not ((own[0] or own[1]) and own[2])
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
                    h = make(seg, i + 1, ctx if ci else "", table=True)
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
                    whole = seg + "：" + "；".join(t for _, t in items) if items else seg
                    h = make(seg, i + 1, code=in_code)
                    if h is None and items:
                        h = make(whole, i + 1, code=in_code, group=True)
                        if h:
                            h.text = seg
                    if h is None:
                        # 引导句本身就是「（不）是…的理由」「以…为准」的形状：词表之外补进来，单独记数
                        shapes = [n for n in ("是不是理由", "以谁为准") if v.rx_shape[n].search(seg)]
                        if shapes:
                            h = Hit(scan.path, i + 1, seg, code=in_code, shape_lead=True)
                    if h:
                        h.items = items
                        h.cls, h.shapes = classify(v, whole)
                        hits.append(h)
                        consumed.update(rows)
                    continue
                h = make(seg, i + 1, code=in_code)
                if h:
                    inline = seg.find("：")
                    if 0 <= inline < len(seg) - 1 and ci < len(clauses) - 1:
                        # 句中的冒号引出「；」分开的几项：同一句里后面的分句是它的条目
                        rest = clauses[ci + 1 :]
                        h.items = [(i + 1, t) for t in rest]
                        h.cls, h.shapes = classify(v, seg + "；" + "；".join(rest))
                        skip.update(range(ci + 1, len(clauses)))
                    hits.append(h)
        i += 1
    return hits, n_sent


def scan_all(root):
    model = scan_repo(root)
    v = load_vocab(root, model)
    hits, files, total = [], {}, 0
    for path in sorted(model.files):
        if not (is_scaffold(path) and path.endswith(".md")):
            continue
        h, n = scan_file(v, model.files[path])
        files[path] = (n, h)
        hits += h
        total += n
    return v, hits, files, total


# ---------- 输出 ----------


def tag(h):
    t = f"{h.cls}/{'、'.join(h.shapes) or '-'}，{'窄' if h.narrow else '宽'}"
    return t + ("，代码块" if h.code else "") + ("，形状补入" if h.shape_lead else "") + ("，表格" if h.table else "")


def fmt_hit(h):
    out = [f"{h.file}:{h.line}  [{tag(h)}]  {h.text}"]
    out += [f"    {ln}: {t}" for ln, t in h.items]
    return out


def counts(hits):
    return {c: sum(1 for h in hits if h.cls == c) for c in CLS}


def format_scan(root, sample=None):
    v, hits, files, total = scan_all(root)
    n = len(hits)
    c = counts(hits)
    narrow = [h for h in hits if h.narrow]
    rows = [h for h in hits if h.table]
    out = [
        f"规则事实线·粗筛：{len(files)} 个脚手架文件，{total} 个句子（表格一格一句）；候选 {n} 条",
        f"三类：已是引用 {c[CLS[0]]}，能改成句式 {c[CLS[1]]}，不是规则事实 {c[CLS[2]]}",
        f"窄口径命中 {len(narrow)}（其中表格格子 {sum(1 for h in narrow if h.table)}），宽口径命中 {n}（含窄口径，其中表格格子 {len(rows)}，涉及 {len({(h.file, h.line) for h in rows})} 行）",
        f"其中：代码块里 {sum(1 for h in hits if h.code)}，靠引导句加条目合起来才命中 {sum(1 for h in hits if h.group)}，引导句只靠句式形状补入（没有键、角色或动作词）{sum(1 for h in hits if h.shape_lead)}，表格格子靠所在行首列补上键或角色 {sum(1 for h in hits if h.inherited)}",
        f"词表：窄口径键 {len(v.narrow_keys)} 个（标签快照与证据前缀），其余键 {len(v.wide_keys)} 个，角色与别名 {len(v.roles)} 个，动作词 {len(v.actions)} 个"
        + ("；没有标签快照（.doc-index/labels.json），标签来源已跳过" if v.no_labels else ""),
        "",
        "文件\t总数\t引用\t句式\t非规则\t窄\t宽(含窄)",
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
