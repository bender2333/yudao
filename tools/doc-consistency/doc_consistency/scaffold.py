import json
import re
import subprocess
from pathlib import Path

import clingo
from clingo import Function, Number, String

from .index import index_root, pending, resolve_spec
from .scan import is_scaffold, scan_repo

TOOL = Path(__file__).resolve().parent.parent
RULES = TOOL / "rules"
DATA = TOOL / "data"

SLASH = re.compile(r"^/([a-z][a-z0-9-]*)$")
NAME = re.compile(r"^[a-z][a-z0-9-]*$")
HYPHEN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$")
LABEL_FLAG = re.compile(r"--(?:add-label|remove-label|label)[ =]\"?([a-z][\w:-]*)")
# 引用所在的子句里有这些词，算必读：读、遵守、以谁为准、谁是正本，或「按[链接]」直接要求照着做
DIRECTIVE = re.compile(r"读|遵守|遵循|为准|正本|按\s*[\[`]")
SKILL_FILE = re.compile(r"^\.claude/skills/([^/]+)/SKILL\.md$")


def load_json(name):
    return json.loads((DATA / name).read_bytes().decode("utf-8"))


def labels_file(root):
    return index_root(root) / "labels.json"


def refresh(root):
    out = subprocess.run(
        ["gh", "label", "list", "--limit", "500", "--json", "name"], cwd=root, capture_output=True, check=True
    ).stdout
    names = sorted(x["name"] for x in json.loads(out.decode("utf-8")))
    p = labels_file(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = '{\n"source":"gh label list",\n"labels":[\n' + ",\n".join(json.dumps(n, ensure_ascii=False) for n in names) + "\n]\n}\n"
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return names


def load_labels(root):
    p = labels_file(root)
    if not p.is_file():
        raise SystemExit("缺少 .doc-index/labels.json：先运行 refresh（需要已登录的 gh）")
    return set(json.loads(p.read_bytes().decode("utf-8"))["labels"])


def sym(name, *args):
    return Function(name, [String(a) if isinstance(a, str) else Number(a) for a in args])


def ignored_paths(root, paths):
    """gitignore 管着的路径（运行产物、临时目录）不算死引用。"""
    if not paths:
        return set()
    r = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=root,
        input=("\0".join(sorted(paths)) + "\0").encode("utf-8"),
        capture_output=True,
    )
    if r.returncode not in (0, 1):
        raise SystemExit(f"git check-ignore 出错：{r.stderr.decode('utf-8', 'replace')}")
    return {p for p in r.stdout.decode("utf-8").split("\0") if p}


def roles_config(model):
    cfg = load_json("roles.json")
    wf = model.files.get(cfg["workflow"])
    if wf is None:
        raise SystemExit(f"找不到工作流文件 {cfg['workflow']}")
    in_table = [n.title for n in wf.nodes if n.kind == "row" and n.table == "角色"]
    if not in_table:
        raise SystemExit(f"{cfg['workflow']} 里没有表头为「角色」的表")
    missing = [r for r in in_table if r not in cfg["roles"]]
    extra = [r for r in cfg["roles"] if r not in in_table]
    if missing or extra:
        raise SystemExit(f"data/roles.json 和 {cfg['workflow']} 的角色表对不上：表里有而数据文件没有 {missing}；数据文件有而表里没有 {extra}")
    return [(r, cfg["roles"][r]) for r in in_table if cfg["roles"][r].get("agent", True)]


def clause_of(line, raw):
    """引用所在的子句：两侧到最近的逗号、分号、句号或表格竖线。"""
    p = line.find(raw)
    if p < 0:
        return line
    seps = ["，", "；", ",", ";", "。", "|"]
    a = max([line.rfind(s, 0, p) for s in seps] + [-1]) + 1
    ends = [e for e in (line.find(s, p + len(raw)) for s in seps) if e >= 0]
    return line[a : min(ends) if ends else len(line)]


def strip_refs(text):
    text = re.sub(r"`[^`]*`", "", text)
    return re.sub(r"\]\([^)]*\)", "]", text)


class Facts:
    def __init__(self):
        self.symbols = set()
        self.mention_lines = {}  # (节点, 实体) -> 行号
        self.roles = []
        self.sizes = {}

    def add(self, name, *args):
        self.symbols.add(sym(name, *args))


def scaffold_facts(model, labels, root):
    ext = load_json("known-external.json")
    ext_skills = set(ext["builtin_skills"]) | set(ext["user_skills"])
    kinds = ext["table_headers"]
    skills = {m.group(1) for p in model.tracked if (m := SKILL_FILE.match(p))}
    f = Facts()
    for s in skills:
        f.add("skill", s)
    for s in ext_skills:
        f.add("external_skill", s)
    for x in labels:
        f.add("label", x)

    for file in model.files.values():
        if not is_scaffold(file.path):
            continue
        f.add("scaffold", file.path)
        m = SKILL_FILE.match(file.path)
        if m:
            f.add("defines", file.path, "skill:" + m.group(1))
        lines = file.text.split("\n")
        for n in file.nodes:
            if n.kind == "row":
                if n.title in labels:
                    f.add("defines", n.id, "label:" + n.title)
                if n.title in skills:
                    f.add("defines", n.id, "skill:" + n.title)
                kind = kinds.get(n.table)
                if kind == "label":
                    f.add("label_ref", n.id, n.title, n.start)
                elif kind == "skill":
                    f.add("skill_ref", n.id, n.title, n.start)
        for c in file.codes:
            tok, line = c.content.strip(), lines[c.line - 1]
            m = SLASH.match(tok)
            if m:
                f.add("skill_ref", c.src, m.group(1), c.line)
                f.add("mention", c.src, "skill:" + m.group(1))
                f.mention_lines.setdefault((c.src, "skill:" + m.group(1)), set()).add(c.line)
            elif NAME.match(tok):
                if tok in skills:
                    f.add("mention", c.src, "skill:" + tok)
                    f.mention_lines.setdefault((c.src, "skill:" + tok), set()).add(c.line)
                if tok in labels:
                    f.add("mention", c.src, "label:" + tok)
                    f.mention_lines.setdefault((c.src, "label:" + tok), set()).add(c.line)
                if any(k in line for k in (f"`{tok}`技能", f"`{tok}` 技能", f"技能`{tok}`", f"技能 `{tok}`")):
                    f.add("skill_ref", c.src, tok, c.line)
                if "标签" in line and HYPHEN.match(tok) and tok not in skills and tok not in ext_skills:
                    f.add("label_ref", c.src, tok, c.line)
            for lm in LABEL_FLAG.finditer(tok):
                f.add("label_ref", c.src, lm.group(1), c.line)

    # 路径：三处位置依次找，找不到再看是不是 gitignore 管着的位置
    cand_of = {}
    for ref, src_file, status, dst in model.refs_all:
        if is_scaffold(src_file) and ref.strict and status == "missing":
            cand_of[(ref.src, ref.raw)] = model.candidates(src_file, ref.target)
    ignored = ignored_paths(root, {c for cs in cand_of.values() for c in cs})
    ignored |= set(ext["conventional_paths"]["paths"])
    for ref, src_file, status, dst in model.refs_all:
        if not (is_scaffold(src_file) and ref.strict):
            continue
        f.add("path_ref", ref.src, ref.raw, ref.line)
        if status != "missing" or any(c in ignored for c in cand_of[(ref.src, ref.raw)]):
            f.add("path_alive", ref.src, ref.raw)

    # 阅读范围
    roles = roles_config(model)
    f.roles = roles
    texts = {p: file.text.split("\n") for p, file in model.files.items()}
    all_aliases = {r: cfg["aliases"] for r, cfg in roles}
    sizes = f.sizes

    def size(path):
        if path not in sizes:
            if path in model.files:
                sizes[path] = len(model.files[path].text)
            else:
                try:
                    sizes[path] = len((root / path).read_bytes().decode("utf-8").replace("\r\n", "\n"))
                except UnicodeDecodeError:
                    sizes[path] = 0  # 图片等二进制文件不是要读的文字
        return sizes[path]

    for r, cfg in roles:
        f.add("role", r)
        entries = list(cfg["rule_files"]) + [f".claude/skills/{s}/SKILL.md" for s in cfg["skills"]]
        for e in entries:
            if e not in model.tracked_set:
                raise SystemExit(f"data/roles.json：{r} 的入口 {e} 不存在")
            f.add("entry", r, e)
            f.add("size", e, size(e))
    any_refs, must_refs = set(), set()
    for ref, src_file, status, dst in model.refs_all:
        if not is_scaffold(src_file) or status != "file" or dst == src_file or ref.kind not in ("link", "code-path", "section-ref", "href"):
            continue
        any_refs.add((src_file, dst))
        line = texts[src_file][ref.line - 1]
        clause = clause_of(line, ref.raw)
        by_section = " > 先读" in ref.src
        if not (by_section or DIRECTIVE.search(clause)):
            continue
        own_clause = strip_refs(clause)
        for r, cfg in roles:
            mine = any(a in own_clause for a in all_aliases[r])
            others = any(a in own_clause for o, al in all_aliases.items() if o != r for a in al)
            if others and not mine and not by_section:
                continue
            must_refs.add((r, src_file, dst))
    for a, b in sorted(any_refs):
        f.add("any_ref", a, b)
        f.add("size", b, size(b))
    for r, a, b in sorted(must_refs):
        f.add("must_ref", r, a, b)
        f.add("size", b, size(b))
    for p in model.files:
        if is_scaffold(p):
            f.add("size", p, size(p))
    return f


def solve(symbols, rule_files):
    ctl = clingo.Control(["1", "--warn=none"])
    for r in rule_files:
        ctl.load(str(RULES / r))
    with ctl.backend() as b:
        for s in symbols:
            b.add_rule([b.add_atom(s)])
    ctl.ground([("base", [])])
    models = []
    res = ctl.solve(on_model=lambda m: models.append(sorted(m.symbols(shown=True), key=str)))
    if not res.satisfiable or len(models) != 1:
        raise SystemExit("clingo 没有给出唯一的结果：规则有错")
    return models[0]


def pick(atoms, name):
    out = []
    for a in atoms:
        if a.name == name:
            out.append(tuple(x.string if x.type == clingo.SymbolType.String else (x.number if x.type == clingo.SymbolType.Number else str(x)) for x in a.arguments))
    return sorted(out)


def file_of(node):
    return node.split("#", 1)[0]


def check(root):
    model = scan_repo(root)
    labels = load_labels(root)
    facts = scaffold_facts(model, labels, root)
    atoms = solve(facts.symbols, ["deadrefs.lp"])
    lines = []
    dead = []
    for n, s, l in pick(atoms, "dead_skill"):
        dead.append((file_of(n), l, f"技能 `{s}` 不存在（不是 .claude/skills 里的技能，也不在内置与用户级技能名单里）", n))
    for n, x, l in pick(atoms, "dead_label"):
        dead.append((file_of(n), l, f"标签 `{x}` 不在 GitHub 标签里", n))
    for n, p, l in pick(atoms, "dead_path"):
        dead.append((file_of(n), l, f"路径 `{p}` 找不到（相对当前文件、所在技能目录、仓库根都没有）", n))
    dead = sorted(set(dead))
    lines.append(f"== 死引用：{len(dead)} 条 ==")
    for path, l, msg, n in dead:
        lines.append(f"{path}:{l}  {msg}")
    _, pend = pending(root, scope=is_scaffold, model=model)
    lines.append(f"== 待核对（下游在脚手架文件里，上游变了）：{len(pend)} 条 ==")
    for path, e, up in pend:
        lines.append(f"{path}  {e['src']}  引用的 {e['dst']} 变了  （改下游，或 confirm {e['src']!r} 记确认）")
    total = len(dead) + len(pend)
    lines.append(f"== 提醒共 {total} 条（只提醒，不拦提交） ==")
    return lines, total


def scope(root):
    model = scan_repo(root)
    facts = scaffold_facts(model, load_labels(root), root)
    atoms = solve(facts.symbols, ["scope.lp"])
    out = []
    reads, reach = {}, {}
    for r, f in pick(atoms, "reads"):
        reads.setdefault(r, set()).add(f)
    for r, f in pick(atoms, "reach"):
        reach.setdefault(r, set()).add(f)
    cr = dict(pick(atoms, "chars_read"))
    ch = dict(pick(atoms, "chars_reach"))
    for r, _ in facts.roles:
        out.append((r, sorted(reads.get(r, ())), sorted(reach.get(r, ()) - reads.get(r, set())), cr.get(r, 0), ch.get(r, 0)))
    return model, facts, out


def impact(root, spec):
    model = scan_repo(root)
    labels = load_labels(root)
    facts = scaffold_facts(model, labels, root)
    ids = set(model.nodes)
    target = resolve_spec(spec, ids, model.tracked_set)
    syms = set(facts.symbols)
    syms.add(sym("target", target))
    for n in model.nodes.values():
        syms.add(sym("node_file", n.id, n.file))
        if n.parent:
            syms.add(sym("parent", n.id, n.parent))
    for e in model.edges:
        syms.add(sym("edge", e.src, e.dst, e.kind))
    atoms = solve(syms, ["scope.lp", "impact.lp"])
    hits = {}
    for n, why, x in pick(atoms, "hit"):
        hits.setdefault(n, []).append((why, x))
    must = {}
    for r, n in pick(atoms, "seen_must"):
        must.setdefault(r, []).append(n)
    link = {}
    for r, n in pick(atoms, "seen_link"):
        link.setdefault(r, []).append(n)
    unseen = [a[0] for a in pick(atoms, "unseen")]
    return model, facts, target, hits, must, link, unseen


def hit_lines(model, facts, node, hits):
    lines = set()
    for why, x in hits:
        if why == "ref":
            lines.update(e.line for e in model.edges if e.src == node and e.dst == x)
        else:
            lines.update(facts.mention_lines.get((node, x), ()))
    return sorted(lines)
