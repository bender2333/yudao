"""规则事实线第 3 步：复述和正本比，输出 rules check。

patterns.py 把句子读成原子，这里把原子和第 1 步读出的正本事实一起交给 clingo（rules/rulefacts/compare.lp），
取回矛盾，补上两边的出处（复述 文件:行、正本 文件:行）和差在哪。Python 不判断矛盾，只摆事实。
"""

import random
from dataclasses import dataclass, field

from ..scaffold import pick, solve, sym
from ..scan import scan_repo
from . import canon as rf
from . import scan as S
from .patterns import SHAPES

# 矛盾的八类（五类加三类），再加方案第 3.1 节的「用户亲手改建删写」
FIVE = (
    ("extra", "多说了正本没有的值"),
    ("only_wrong", "说「只由」，正本里还有别人"),
    ("denied", "说「不」，正本里有"),
    ("not_member_wrong", "说不是理由，正本里是"),
    ("precedence_cycle", "「以谁为准」方向相反或绕成一圈"),
)
THREE = (
    ("may_wrong", "在场可否与正本相反"),
    ("handoff_wrong", "交给的角色，正本里没有"),
    ("closed_missing", "穷尽清单：复述说只有这些，正本还有别的"),
    ("closed_extra", "穷尽清单：复述里有正本没有的"),
)
USER = (("user_hands_on", "用户亲手改建删写（用户只定与确认）"),)
KINDS = FIVE + THREE + USER
LABEL = dict(KINDS)
RULES = ["scope.lp", "rulefacts/canon.lp", "rulefacts/compare.lp"]
RESULTS = [k for k, _ in KINDS] + ["above"]


@dataclass
class Conflict:
    kind: str
    nodes: list  # 复述的句子节点，precedence_cycle 有几个
    rows: list  # 波及的正本行 [(键, 事实)]
    canon: list  # 正本 文件:行  键 / 事实：值
    why: str  # 差在哪
    key: tuple = ()  # 这条矛盾在规则结论里的原样参数，排序用


@dataclass
class Restate:
    """一处复述：某个句子说到某条正本事实。"""

    node: str
    key: str
    fact: str
    src: str
    text: str
    shape: str
    conflict: bool = False


@dataclass
class Check:
    canon: object
    sc: object
    groups: list
    by_node: dict
    conflicts: list = field(default_factory=list)
    restates: list = field(default_factory=list)
    edges: list = field(default_factory=list)  # 以谁为准的边 (节点, 优先, 其次)

    def count(self, kind):
        return sum(1 for c in self.conflicts if c.kind == kind)

    def unparsed(self):
        return [h for h in self.sc.hits if h.cls == S.CLS[2]]


def where(g):
    return f"{g.file}:{g.line}"


def atoms_syms(groups, hands_on):
    syms = set()
    for g in groups:
        for a in g.atoms:
            syms.add(sym(a[0], g.node, *a[1:]))
    for f in hands_on:
        syms.add(sym("hands_on", f))
    return syms


def row_of(atom):
    """原子说到的正本行 (键, 事实)；以谁为准不属于任何一行。"""
    p = atom[0]
    if p in ("says", "only", "says_not"):
        return atom[1], atom[2]
    if p in ("member", "not_member", "only_members", "closed"):
        return atom[1], "理由"
    if p == "may":
        return atom[2], "在场可否" if atom[3] == "在场" else "不在场可否"
    if p == "handoff":
        return atom[1], "交给"
    return None


def canon_lines(c, k, f):
    by = {}
    for x in c.cells:
        if x.key == k and x.fact == f:
            by.setdefault((x.file, x.line), []).append(x.value)
    return [f"{file}:{line}  {k} / {f}：{'、'.join(vals)}" for (file, line), vals in sorted(by.items())]


def canon_values(c, k, f):
    return list(dict.fromkeys(x.value for x in c.cells if x.key == k and x.fact == f))


def components(pairs):
    """成环的载体对 -> 连通的几组。"""
    comp = {}
    for a, b in pairs:
        ga, gb = comp.get(a, {a}), comp.get(b, {b})
        g = ga | gb
        for x in g:
            comp[x] = g
    return sorted({tuple(sorted(g)) for g in comp.values()})


def run(c, groups, hands_on):
    """正本事实 + 复述原子 -> clingo -> 矛盾。"""
    atoms = solve(set(c.syms) | atoms_syms(groups, hands_on), RULES)
    return {k: pick(atoms, k) for k in RESULTS}


def build_conflicts(c, groups, res):
    by_node = {g.node: g for g in groups}
    only_of = {}
    for g in groups:
        for a in g.atoms:
            if a[0] == "only":
                only_of.setdefault((g.node, a[1], a[2]), []).append(a[3])
    out = []

    def add(kind, nodes, rows, canon, why, key):
        out.append(Conflict(kind, nodes, rows, canon, why, key))

    for n, k, f, v in res["extra"]:
        vals = canon_values(c, k, f)
        if f == "理由" and any(a[0] == "member" and a[1:] == (k, v) for a in by_node[n].atoms):
            why = f"复述说「{v}」是 {k} 的理由，正本的理由里没有它（正本：{'、'.join(vals) or '无'}）"
        elif vals:
            why = f"复述说 {k} {f} {v}，正本里没有这个值（正本：{'、'.join(vals)}）"
        else:
            why = f"复述说 {k} {f} {v}，正本里 {k} 没有「{f}」这条事实"
        add("extra", [n], [(k, f)], canon_lines(c, k, f), why, (n, k, f, v))
    for n, k, f, v in res["only_wrong"]:
        said = "、".join(only_of.get((n, k, f), []))
        add("only_wrong", [n], [(k, f)], canon_lines(c, k, f), f"复述说只由 {said}，正本里还有 {v}", (n, k, f, v))
    for n, k, f, v in res["denied"]:
        add("denied", [n], [(k, f)], canon_lines(c, k, f), f"复述说 {v} 不「{f}」{k}，正本里 {v} 在 {k} 的「{f}」里", (n, k, f, v))
    for n, k, x in res["not_member_wrong"]:
        add("not_member_wrong", [n], [(k, "理由")], canon_lines(c, k, "理由"), f"复述说「{x}」不是 {k} 的理由，正本的理由里有它", (n, k, x))
    # 以谁为准：成环的一组载体，列出组内的每一句
    edges = [(g.node, a[1], a[2]) for g in groups for a in g.atoms if a[0] == "prevails"]
    for comp in components([(a, b) for a, b in res["precedence_cycle"]]):
        mine = [e for e in edges if e[1] in comp and e[2] in comp]
        why = "、".join(comp) + " 之间，" + "；".join(f"{w}优先于{o}（{where(by_node[n])}）" for n, w, o in mine) + "：方向相反或绕成一圈"
        add("precedence_cycle", [n for n, _, _ in mine], [], [], why, comp)
    for n, r, x, s, val in res["may_wrong"]:
        f = "在场可否" if s == "在场" else "不在场可否"
        normal = "、".join(canon_values(c, x, f))
        add("may_wrong", [n], [(x, f)], canon_lines(c, x, f), f"复述说用户{s}时 {r} {val}（{x.split('：')[0]}），正本说{normal}", (n, r, x, s, val))
    for n, k, r in res["handoff_wrong"]:
        vals = "、".join(canon_values(c, k, "交给"))
        add("handoff_wrong", [n], [(k, "交给")], canon_lines(c, k, "交给"), f"复述说「{k.split('、')[0]}」交给 {r}，正本交给的是 {vals}，没有 {r}", (n, k, r))
    # 穷尽清单：一句话对一个键报一条，漏的、多的合在一起列
    for kind in ("closed_missing", "closed_extra"):
        grouped = {}
        for n, k, v in res[kind]:
            grouped.setdefault((n, k), []).append(v)
        for (n, k), vs in sorted(grouped.items()):
            said = "、".join(a[2] for a in by_node[n].atoms if a[0] == "only_members" and a[1] == k)
            if kind == "closed_missing":
                why = f"复述说只有 {said}，漏了正本里的 {'、'.join(sorted(vs))}"
            else:
                why = f"复述的清单里有 {'、'.join(sorted(vs))}，正本的理由里没有（正本：{'、'.join(canon_values(c, k, '理由'))}）"
            add(kind, [n], [(k, "理由")], canon_lines(c, k, "理由"), why, (n, k, tuple(sorted(vs))))
    for n, k, f in res["user_hands_on"]:
        # 正本：第 1 节「谁定」里写用户的几行（用户只定与确认）
        lines = sorted({f"{x.file}:{x.line}  {x.key} / {x.fact}：用户" for x in c.cells if x.value == "用户" and x.fact == "由谁定"})
        add("user_hands_on", [n], [(k, f)], lines, f"复述把「{f}」{k} 归给用户；用户只定与确认，不亲手改、建、删、写，这样写会走样", (n, k, f))
    order = {k: i for i, (k, _) in enumerate(KINDS)}
    out.sort(key=lambda x: (order[x.kind], where(by_node[x.nodes[0]]) if x.nodes else "", x.key))
    return out


def check(root):
    model = scan_repo(root)
    sc = S.scan_all(root, model=model)
    c = rf.read_canon(root, model=model)
    groups = [g for u in sc.units for g in sc.groups.get(u.id, [])]
    hands_on = sc.pv.hands_on if sc.pv else []
    res = run(c, groups, hands_on)
    chk = Check(c, sc, groups, {g.node: g for g in groups})
    chk.conflicts = build_conflicts(c, groups, res)
    hit = {(n, k, f) for x in chk.conflicts for n in x.nodes for k, f in x.rows}
    seen = set()
    for g in groups:
        for a in g.atoms:
            r = row_of(a)
            if r and (g.node, *r) not in seen:
                seen.add((g.node, *r))
                chk.restates.append(Restate(g.node, r[0], r[1], where(g), g.text, g.shape, (g.node, *r) in hit))
    chk.edges = [(g.node, a[1], a[2]) for g in groups for a in g.atoms if a[0] == "prevails"]
    return chk


# ---------- 输出 ----------

SHOW_UNPARSED = 20
TIERS = ("A", "B", "C")


def in_tier(h, tier):
    """提醒的档（第 4 步分档，默认 A 即现在的做法）。
    A：全部候选；B：只留窄口径命中、句式形状补入（含引导句靠句式形状补入的）、机器主语三种来源；C：只留句式形状补入。"""
    shaped = h.by_shape or h.shape_lead
    if tier == "C":
        return shaped
    if tier == "B":
        return h.narrow or shaped or h.by_machine
    return True


def format_check(chk, show_all=False, tier="A", sample=None):
    """show_all：提醒全部列出（默认前 20 条）；tier：提醒只留这一档；sample：从这一档里按固定种子抽 N 条（顺序不变）。默认参数的输出与第 3 步一字不差。"""
    sc, c = chk.sc, chk.canon
    hits = sc.hits
    cnt = S.counts(hits)
    shapes = {s: 0 for s in SHAPES}
    for g in chk.groups:
        shapes[g.shape] += 1
    n_notes = sum(len(g.notes) for g in chk.groups)
    hit_units = {h.unit.id for h in hits if h.unit}
    out = [
        f"规则事实线·比对：{len(sc.files)} 个脚手架文件，{len(sc.units)} 个分句；候选 {len(hits)} 条；正本事实 {len(c.canon)} 条",
        f"解析成功 {len(chk.groups)} 句（{'，'.join(f'{k} {v}' for k, v in shapes.items())}）；附注 {n_notes} 条（括号里的话与限定，不进原子）；"
        f"其中候选里 {cnt[S.CLS[1]]} 条，不是候选的 {sum(1 for g in chk.groups if g.unit not in hit_units)} 句",
    ]
    five = "，".join(f"{LABEL[k]} {chk.count(k)}" for k, _ in FIVE)
    three = "，".join(f"{LABEL[k]} {chk.count(k)}" for k, _ in THREE)
    out.append(f"矛盾 {len(chk.conflicts)} 条。五类：{five}。三类：{three}。另：{USER[0][1]} {chk.count('user_hands_on')}")
    for kind, label in KINDS:
        mine = [x for x in chk.conflicts if x.kind == kind]
        out.append(f"== {label}：{len(mine)} 条 ==")
        for x in mine:
            for n in x.nodes:
                g = chk.by_node[n]
                out.append(f"复述 {where(g)}  {g.text}")
            for line in x.canon:
                out.append(f"  正本 {line}")
            if not x.canon:
                out.append("  正本 （没有对应的一行）")
            out.append(f"  差在哪：{x.why}")
    out += rf.format_unreachable(c)
    out += rf.format_dup(c)
    un_all = chk.unparsed()
    kept = [h for h in un_all if in_tier(h, tier)]
    un = kept
    if sample is not None:
        picked = random.Random(S.SAMPLE_SEED).sample(un, min(sample, len(un)))
        order = {id(h): i for i, h in enumerate(un)}
        un = sorted(picked, key=lambda h: order[id(h)])
    shown = un if (show_all or sample is not None) else un[:SHOW_UNPARSED]
    base = f"候选 {len(hits)} − 解析成功 {cnt[S.CLS[1]]} − 纯指路 {cnt[S.CLS[0]]}"
    if tier == "A" and sample is None:
        head = f"{len(un)} 条（{base}），" + ("全部列出" if show_all else f"前 {len(shown)} 条")
    else:
        head = f"档 {tier}：{len(kept)} 条（全部 {len(un_all)} 条里留下的；{base}），" + (
            f"固定种子（{S.SAMPLE_SEED}）抽 {len(shown)} 条" if sample is not None else "全部列出" if show_all else f"前 {len(shown)} 条"
        )
    out.append(f"== 像在说规则但解析不了：{head}；这是以后钩子的提醒 ==")
    for h in shown:
        out += S.fmt_hit(h)
    return out
