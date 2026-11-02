import hashlib
import posixpath
import re
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

# 不进索引的位置
EXCLUDE_PREFIXES = ("docs/archive/", "agents_jour/", ".claude/worktrees/")
ARCH_FILE = "docs/architecture.html"
PREAMBLE = "(开头)"
SECTION_NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}

# 反引号里出现这些扩展名才当作文件路径
PATH_EXTENSIONS = {
    "md", "html", "py", "json", "jsonl", "yml", "yaml", "mjs", "js", "ts", "tsx",
    "ps1", "sh", "toml", "txt", "lp", "css", "svg", "png", "lock", "cfg", "ini",
}
PATH_CHARS = re.compile(r"^[\w.\-/@一-鿿]+$")
LINE_SUFFIX = re.compile(r"(::[\w\[\]\-.]+|:\d+(-\d+)?)$")

MD = MarkdownIt("commonmark").enable("table")


def normalize_text(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text(path):
    text = Path(path).read_bytes().decode("utf-8")
    return text[1:] if text.startswith("﻿") else text


def digest(text):
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def git_tracked(root):
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return sorted(p for p in out.split("\0") if p)


def in_scope(path):
    if not path.endswith((".md", ".html")):
        return False
    if path.startswith(EXCLUDE_PREFIXES):
        return False
    if path.startswith("docs/prototypes/") and path.endswith(".html"):
        return False
    return True


def is_scaffold(path):
    return (
        path in ("CLAUDE.md", "AGENTS.md")
        or path.startswith("docs/agents/")
        or path.startswith(".claude/skills/")
    )


@dataclass
class Node:
    id: str
    file: str
    kind: str  # file | section | row | seam
    title: str
    parent: str
    start: int  # 1 起，含
    end: int
    hash: str = ""
    anchor: str = ""
    table: str = ""  # 表格行所在表的首列表头


@dataclass
class Ref:
    src: str
    kind: str  # link | href | code-path | section-ref | map-position
    raw: str
    line: int
    target: str  # 路径，原样（未解析）
    anchor: str = ""
    section: str = ""
    strict: bool = False  # 带扩展名和斜杠的路径：找不到就是死引用


@dataclass
class Code:
    src: str
    line: int
    content: str


@dataclass
class FileScan:
    path: str
    text: str
    hash: str
    nodes: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    codes: list = field(default_factory=list)


def github_slug(title):
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def inline_text(token):
    parts = []
    for c in token.children or []:
        if c.type in ("text", "code_inline"):
            parts.append(c.content)
    return "".join(parts).strip()


def path_token(content):
    """反引号里的内容像文件路径时返回 (路径, 锚点, 是否严格)，否则返回 None。"""
    t = content.strip()
    if not t or t.startswith(("/", "~", "-", "http:", "https:")):
        return None
    anchor = ""
    if "#" in t:
        t, anchor = t.split("#", 1)
    t = LINE_SUFFIX.sub("", t)
    if not t or not PATH_CHARS.match(t) or ".." in t.replace("../", ""):
        return None
    ext = t.rsplit(".", 1)[-1] if "." in posixpath.basename(t) else ""
    has_ext = ext in PATH_EXTENSIONS
    if not has_ext and "/" not in t:
        return None
    strict = has_ext and "/" in t
    return t, anchor, strict


def link_target(href):
    href = unquote(href.strip())
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", href) or href.startswith("//"):
        return None
    path, _, anchor = href.partition("#")
    path = path.split("?", 1)[0]
    return path, anchor


def locate_line(lines, start, end, needle, cursor):
    """在 [start,end) 行里从 cursor 起找 needle，找不到返回 cursor。"""
    if needle:
        for i in range(max(cursor, start), min(end, len(lines))):
            if needle in lines[i]:
                return i
    return max(cursor, start)


def parse_markdown(path, text, with_rows):
    text = normalize_text(text)
    lines = text.split("\n")
    tokens = MD.parse(text)
    scan = FileScan(path=path, text=text, hash=digest(text))
    scan.nodes.append(Node(path, path, "file", path, "", 1, len(lines), scan.hash))

    # 小节
    heads = []
    for i, t in enumerate(tokens):
        if t.type == "heading_open":
            heads.append((t.map[0], int(t.tag[1]), inline_text(tokens[i + 1])))
    used = {path}
    sections = []  # (start0, end0, node)
    stack = []
    first = heads[0][0] if heads else len(lines)
    if any(l.strip() for l in lines[:first]):
        n = Node(f"{path}#{PREAMBLE}", path, "section", PREAMBLE, path, 1, first)
        sections.append([0, first, n])
        used.add(n.id)
    for k, (start, level, title) in enumerate(heads):
        while stack and stack[-1][0] >= level:
            stack.pop()
        base = f"{path}#" + " > ".join([s[1] for s in stack] + [title])
        nid, n_dup = base, 2
        while nid in used:
            nid, n_dup = f"{base} ({n_dup})", n_dup + 1
        used.add(nid)
        parent = path if not stack else stack[-1][2]
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        n = Node(nid, path, "section", title, parent, start + 1, end)
        sections.append([start, end, n])
        stack.append((level, title, nid))

    def section_at(line0):
        for s, e, n in sections:
            if s <= line0 < e:
                return n
        return None

    # 表格行
    row_lines = set()
    rows = []  # (line0 起, 止, node)
    if with_rows:
        table_no = {}
        in_body = False
        cur_table = None
        for i, t in enumerate(tokens):
            if t.type == "table_open":
                sec = section_at(t.map[0])
                table_no[sec.id] = table_no.get(sec.id, 0) + 1
                cur_table = (sec, table_no[sec.id], inline_text(tokens[i + 4]))
            elif t.type == "tbody_open":
                in_body = True
            elif t.type == "tbody_close":
                in_body = False
            elif t.type == "tr_open" and in_body:
                sec, no, header = cur_table
                title = inline_text(tokens[i + 2]) or "(空)"
                base = f"{sec.id} > 表{no} > {title}"
                nid, n_dup = base, 2
                while nid in used:
                    nid, n_dup = f"{base} ({n_dup})", n_dup + 1
                used.add(nid)
                n = Node(nid, path, "row", title, sec.id, t.map[0] + 1, t.map[1], table=header)
                rows.append((t.map[0], t.map[1], n))
                row_lines.update(range(t.map[0], t.map[1]))
                scan.nodes.append(n)

    def node_at(line0):
        for s, e, n in rows:
            if s <= line0 < e:
                return n
        n = section_at(line0)
        return n if n else scan.nodes[0]

    for s, e, n in sections:
        scan.nodes.append(n)
        own = [lines[i] for i in range(s, e) if i not in row_lines]
        n.hash = digest("\n".join(own))
    for s, e, n in rows:
        n.hash = digest("\n".join(lines[s:e]))
    scan.nodes[1:] = sorted(scan.nodes[1:], key=lambda n: (n.start, n.kind == "row"))

    # 引用与反引号
    for t in tokens:
        if t.type != "inline" or not t.map:
            continue
        start, end = t.map
        cursor = start
        kids = t.children or []
        in_link = 0
        for j, c in enumerate(kids):
            nxt = kids[j + 1] if j + 1 < len(kids) else None
            hint = ""
            if nxt is not None and nxt.type == "text" and nxt.content.startswith("「") and "」" in nxt.content:
                hint = nxt.content[1 : nxt.content.find("」")]
            if c.type == "link_open":
                in_link += 1
                href = c.attrGet("href") or ""
                tgt = link_target(href)
                line0 = locate_line(lines, start, end, unquote(href), cursor)
                cursor = line0
                if tgt is None:
                    continue
                # 链接后面紧跟「小节」时，小节跟在 link_close 之后
                after = kids[j + 1 :]
                hint = ""
                depth = 1
                for k2, c2 in enumerate(after):
                    if c2.type == "link_open":
                        depth += 1
                    elif c2.type == "link_close":
                        depth -= 1
                        if depth == 0:
                            nt = after[k2 + 1] if k2 + 1 < len(after) else None
                            if nt is not None and nt.type == "text" and nt.content.startswith("「") and "」" in nt.content:
                                hint = nt.content[1 : nt.content.find("」")]
                            break
                p, anchor = tgt
                src = node_at(line0).id
                scan.refs.append(Ref(src, "link", unquote(href), line0 + 1, p, anchor, hint, strict=bool(p)))
            elif c.type == "link_close":
                in_link -= 1
            elif c.type == "code_inline":
                line0 = locate_line(lines, start, end, c.content, cursor)
                cursor = line0
                src = node_at(line0).id
                scan.codes.append(Code(src, line0 + 1, c.content))
                if in_link:
                    continue
                pt = path_token(c.content)
                if pt:
                    p, anchor, strict = pt
                    kind = "section-ref" if hint else "code-path"
                    scan.refs.append(Ref(src, kind, c.content, line0 + 1, p, anchor, hint, strict))

    # 总图位置行
    for i, l in enumerate(lines):
        if l.startswith("总图位置："):
            body = l[len("总图位置：") :].split("依据：", 1)[0]
            src = node_at(i).id
            seen = set()
            current = None
            literal = ""
            quoted = False

            def emit(sec, hint, raw):
                key = (sec, hint)
                if key not in seen:
                    seen.add(key)
                    scan.refs.append(Ref(src, "map-position", raw, i + 1, ARCH_FILE, f"s{sec}", hint))

            for m in re.finditer(r"第\s*([一二三四五六])\s*节|「([^」]+)」|全部六节", body):
                if m.group(1):
                    if current is not None and not quoted:
                        emit(current, "", literal)
                    current, literal, quoted = SECTION_NUMBERS[m.group(1)], m.group(0), False
                elif m.group(2):
                    if current is not None:
                        emit(current, m.group(2), m.group(0))
                        quoted = True
                elif "](" not in body:
                    scan.refs.append(Ref(src, "map-position", "全部六节", i + 1, ARCH_FILE))
            if current is not None and not quoted:
                emit(current, "", literal)
    return scan


class _HtmlScanner(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.items = []  # dict：kind,title,anchor,start,end,parent(索引)
        self.section = None
        self.seam = None
        self.seam_depth = 0
        self.h2 = False
        self.small = False
        self.bold = False
        self.span = False
        self.raw_refs = []  # (item 或 None, href, line)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        if tag == "section" and a.get("id"):
            self.section = {"kind": "section", "anchor": a["id"], "title": "", "start": line, "end": line, "parent": None}
            self.items.append(self.section)
        elif tag == "div" and self.section is not None:
            if self.seam is not None:
                self.seam_depth += 1
            elif "seam" in (a.get("class") or "").split():
                self.seam = {"kind": "seam", "anchor": "", "title": "", "start": line, "end": line, "parent": self.section}
                self.seam_depth = 1
                self.items.append(self.seam)
        elif tag == "h2" and self.section is not None and not self.section["title"]:
            self.h2 = True
        elif tag == "small":
            self.small = True
        elif tag == "b" and self.seam is not None and not self.seam["title"]:
            self.bold = True
        elif tag == "span":
            self.span = True
        elif tag == "a" and a.get("href"):
            self.raw_refs.append((self.seam or self.section, a["href"], line))

    def handle_endtag(self, tag):
        line = self.getpos()[0]
        if tag == "section" and self.section is not None:
            self.section["end"] = line
            self.section = None
        elif tag == "div" and self.seam is not None:
            self.seam_depth -= 1
            if self.seam_depth == 0:
                self.seam["end"] = line
                self.seam = None
        elif tag == "h2":
            self.h2 = False
        elif tag == "small":
            self.small = False
        elif tag == "b":
            self.bold = False
        elif tag == "span":
            self.span = False

    def handle_data(self, data):
        if self.h2 and not self.small:
            self.section["title"] += data
        elif self.bold and not self.span:
            self.seam["title"] += data


def parse_html(path, text):
    text = normalize_text(text)
    lines = text.split("\n")
    scan = FileScan(path=path, text=text, hash=digest(text))
    scan.nodes.append(Node(path, path, "file", path, "", 1, len(lines), scan.hash))
    p = _HtmlScanner(path)
    p.feed(text)
    p.close()
    ids = {}
    for item in p.items:
        if item["kind"] == "section":
            nid = f"{path}#{item['anchor']}"
            parent = path
            title = item["title"].strip() or item["anchor"]
        else:
            parent_node = ids[id(item["parent"])]
            nid = f"{parent_node.id} > {item['title'].strip()}"
            parent = parent_node.id
            title = item["title"].strip()
        n = Node(nid, path, item["kind"], title, parent, item["start"], item["end"], anchor=item["anchor"])
        ids[id(item)] = n
        scan.nodes.append(n)
    seam_lines = {}
    for item in p.items:
        if item["kind"] == "seam":
            seam_lines.setdefault(id(item["parent"]), set()).update(range(item["start"], item["end"] + 1))
    for item in p.items:
        n = ids[id(item)]
        skip = seam_lines.get(id(item), set())
        own = [lines[i - 1] for i in range(n.start, n.end + 1) if i not in skip and i <= len(lines)]
        n.hash = digest("\n".join(own))
    for owner, href, line in p.raw_refs:
        tgt = link_target(href)
        if tgt is None:
            continue
        src = ids[id(owner)].id if owner is not None else path
        scan.refs.append(Ref(src, "href", href, line, tgt[0], tgt[1], "", strict=bool(tgt[0])))
    return scan


def parse_file(path, text, with_rows):
    if path.endswith(".html"):
        return parse_html(path, text)
    return parse_markdown(path, text, with_rows)


def find_node(scan_nodes, ref):
    """按锚点与小节名在目标文件的节点里找；找不到返回 None。"""
    by_anchor = [n for n in scan_nodes if n.anchor and n.anchor == ref.anchor] if ref.anchor else []
    base = by_anchor[0] if by_anchor else None
    if ref.anchor and base is None:
        slug = [n for n in scan_nodes if n.kind == "section" and github_slug(n.title) == ref.anchor.lower()]
        base = slug[0] if slug else None
    if ref.section:
        pool = [n for n in scan_nodes if n.kind in ("section", "seam")]
        if base is not None and ref.kind == "map-position":
            pool = [n for n in pool if n.parent == base.id] + [base]
        for test in (
            lambda t: t == ref.section,
            lambda t: t.startswith(ref.section),
            lambda t: ref.section in t,
        ):
            hit = [n for n in pool if test(n.title)]
            if hit:
                return hit[0]
    return base


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    raw: str
    line: int


class Model:
    def __init__(self, root, tracked, files):
        self.root = Path(root)
        self.tracked = tracked
        self.tracked_set = set(tracked)
        self.dirs = {posixpath.dirname(p) for p in tracked}
        for d in list(self.dirs):
            while d:
                d = posixpath.dirname(d)
                self.dirs.add(d)
        self.files = files  # path -> FileScan
        self.nodes = {}
        for f in files.values():
            for n in f.nodes:
                self.nodes[n.id] = n
        self._file_hash = {}
        self.edges = []
        self.refs_all = []  # (Ref, 来源文件, 状态 file|dir|missing, 目标文件)
        for f in files.values():
            for ref in f.refs:
                self._resolve(f, ref)

    def candidates(self, from_file, target):
        """相对当前文件、相对所在技能目录、相对仓库根，三处依次找。"""
        cands = []
        if target:
            cands.append(posixpath.normpath(posixpath.join(posixpath.dirname(from_file), target)))
            parts = from_file.split("/")
            if from_file.startswith(".claude/skills/") and len(parts) > 3:
                cands.append(posixpath.normpath(posixpath.join("/".join(parts[:3]), target)))
            cands.append(posixpath.normpath(target))
        return [c for c in cands if not c.startswith("..") and c != "."]

    def resolve_path(self, from_file, target):
        for c in self.candidates(from_file, target):
            if c in self.tracked_set:
                return "file", c
            if c.rstrip("/") in self.dirs:
                return "dir", c.rstrip("/")
        return "missing", None

    def _resolve(self, f, ref):
        if not ref.target:  # 同文件锚点
            file = f.path
            kind = "file"
        else:
            kind, file = self.resolve_path(f.path, ref.target)
        self.refs_all.append((ref, f.path, kind, file))
        if kind in ("dir", "missing"):
            return
        dst = file
        if file in self.files and (ref.anchor or ref.section):
            n = find_node(self.files[file].nodes, ref)
            if n is not None:
                dst = n.id
        if dst == ref.src or (dst == f.path and file == f.path):
            return
        self.edges.append(Edge(ref.src, dst, ref.kind, ref.raw, ref.line))

    def hash_of(self, dst):
        if dst in self.nodes:
            return self.nodes[dst].hash
        if dst not in self._file_hash:
            p = self.root / dst
            # 索引范围之外的文件（代码、配置、图片）按字节算，行尾统一
            data = p.read_bytes().replace(b"\r\n", b"\n") if p.is_file() else None
            self._file_hash[dst] = hashlib.sha256(data).hexdigest()[:16] if data is not None else None
        return self._file_hash[dst]


def scan_repo(root):
    root = Path(root)
    tracked = git_tracked(root)
    files = {}
    for p in tracked:
        if in_scope(p) and (root / p).is_file():
            files[p] = parse_file(p, read_text(root / p), is_scaffold(p))
    return Model(root, tracked, files)
