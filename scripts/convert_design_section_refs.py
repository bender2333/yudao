"""把代码与测试里按节号引用设计说明的地方改成「文档路径 + 小节标题」（工单 #1411）。

用法：
    uv run python scripts/convert_design_section_refs.py --report .tmp/report.tsv   # 只报告，不改文件
    uv run python scripts/convert_design_section_refs.py --apply                    # 改文件
    uv run python scripts/convert_design_section_refs.py --apply --cache .tmp/cache.json

换算办法见工单 #1411 正文的四步：

1. 定是哪份设计说明。注释里写了名字的按名字（旧叫法见 DOC_ALIASES），写了 `docs/design/`
   路径的按路径；只写「设计说明」或「第 N 节」的，按同一行、同一段注释、文件开头的说明推，
   再按同文件已经定下来的设计说明、同一节号在别的说明里是否存在来核对。
2. 定是哪一节。`git blame` 找到写这条注释的提交，读那个提交里的那份设计说明，第 N 节当时的
   标题就是要写的标题，再对到现在 main 上的名字（改过名的按 `docs/CHANGELOG.md` 的「旧标题 → 新标题」）。
   「第 N 节第 M 项」这类按序号指一项的，写成小节标题加那一项的名字。
3. 指向已经删去的小节的（DELETED 里逐条写明），去掉这一部分引用，注释的其余部分照旧。
4. 写法：`docs/design/<文件>.md「小节标题」`；同一段注释已经写明是哪份设计说明时只写「小节标题」。
   不写节号与行号。

再跑一次没有改动：改完的地方不再有「第 N 节」，剩下的都是写明了是别的文档的引用（原型、
需求记录、ADR、调研、归档、路线图、规则文件与运行配置），脚本跳过这些。

评价材料（`evals/scenarios/` 下的 checks、reference 与 materials）不在扫描范围：它们按摘要
校验，改一个字的注释也让那次评测运行作废，改 checks 还要用户事前批准（SKIP_PREFIXES）。

推不出是哪份设计说明、需要人定的，写进 MAPPING（按文件或「文件:行」）；这些条目在交付说明的
「自定的边界」里逐条说明。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 守卫扫的目录（工单 #1411 验收：harness/、client/src、client/tests、evals/、scripts/、.github/workflows/）
SCOPES = ("harness/", "client/src/", "client/tests/", "evals/", "scripts/", ".github/workflows/")

# 评价材料（场景的 checks、reference 与 materials）按摘要校验：改一个字的注释也让那次评测运行作废，
# 改 checks 还要用户事前批准。工单 #1411 的清单里有两处在这下面，脚本跳过它们（交付说明的
# 「自定的边界」写明）；守卫同样不扫这里。
SKIP_PREFIXES = ("evals/scenarios/",)

DESIGN_DIR = "docs/design"

# 设计说明的名字（注释里的写法）→ 文件。长的写在前面，先匹配长的。
DOC_ALIASES: dict[str, str] = {
    "应用层与接口层设计说明": "app-and-interface.md",
    "应用层与接口层设计": "app-and-interface.md",
    "应用层与接口层": "app-and-interface.md",
    "接口与应用层设计说明": "app-and-interface.md",
    "接口与应用层": "app-and-interface.md",
    "接口设计说明": "app-and-interface.md",
    "骨架与应用设计说明": "skeleton-and-application.md",
    "骨架与应用": "skeleton-and-application.md",
    "可信内核设计说明": "trusted-kernel.md",
    "受控内核设计说明": "trusted-kernel.md",
    "受控内核": "trusted-kernel.md",
    "可信内核": "trusted-kernel.md",
    "发布检查设计说明": "trusted-kernel.md",
    "模型管理设计说明": "model-management.md",
    "模型管理": "model-management.md",
    "网络取回与 MCP 工具设计说明": "network-and-mcp.md",
    "网络取回与 MCP 设计说明": "network-and-mcp.md",
    "网络取回与 MCP": "network-and-mcp.md",
    "网络与 MCP 设计说明": "network-and-mcp.md",
    "网络与 MCP": "network-and-mcp.md",
    "浏览器与 computer use 设计说明": "browser-and-computer-use.md",
    "浏览器与 computer use": "browser-and-computer-use.md",
    "浏览器说明": "browser-and-computer-use.md",
    "浏览器设计": "browser-and-computer-use.md",
    "验证的独立性设计说明": "independent-verification.md",
    "验证的独立性": "independent-verification.md",
    "独立性说明": "independent-verification.md",
    "检验的有效性设计说明": "independent-verification.md",
    "检验的有效性": "independent-verification.md",
    "画面与播放设计说明": "visualization.md",
    "画面与播放": "visualization.md",
    "评测场景设计说明": "evaluation-scenarios.md",
    "评测场景设计": "evaluation-scenarios.md",
    "评测场景": "evaluation-scenarios.md",
    "形态与核验角色设计说明": "forms-and-verifier-role.md",
    "形态与核验角色": "forms-and-verifier-role.md",
    "部门指导设计说明": "department-guidance.md",
    "部门指导的处理设计": "department-guidance.md",
    "部门指导": "department-guidance.md",
    "测试分层设计说明": "test-pyramid.md",
    "测试分层设计": "test-pyramid.md",
    "测试分层": "test-pyramid.md",
    "网页界面的提供与发布设计说明": "web-interface-and-release.md",
    "网页界面的提供与发布": "web-interface-and-release.md",
    "网页界面设计说明": "web-interface-and-release.md",
    "项目的组织设计说明": "project-organization.md",
    "项目的组织": "project-organization.md",
    "语义系统设计说明": "semantic-system.md",
    "语义系统": "semantic-system.md",
    "接入已有项目设计说明": "existing-project-onboarding.md",
    "接入已有项目": "existing-project-onboarding.md",
    "循环与收敛设计说明": "loops-and-convergence.md",
    "循环与收敛": "loops-and-convergence.md",
    "执行环境服务设计说明": "execution-environment.md",
    "执行环境服务": "execution-environment.md",
    "本地通用工具设计说明": "local-tools.md",
    "本地工具设计说明": "local-tools.md",
    "本地通用工具": "local-tools.md",
    "本地工具": "local-tools.md",
    "项目的起始文件夹设计说明": "project-initial-files.md",
    "项目的起始文件夹": "project-initial-files.md",
    "规则登记与参数设计说明": "rules-and-parameters.md",
    "规则登记与参数": "rules-and-parameters.md",
    "规则登记设计说明": "rules-and-parameters.md",
    "规则登记": "rules-and-parameters.md",
    "部门内多角色设计说明": "department-roles.md",
    "部门内多角色": "department-roles.md",
    "外包角色设计说明": "outsourced-roles.md",
    "外包角色": "outsourced-roles.md",
    "内核的代码质量检查设计说明": "kernel-quality-gate.md",
    "内核的代码质量检查": "kernel-quality-gate.md",
    "恢复契约与故障矩阵设计说明": "recovery-contract-and-fault-matrix.md",
    "恢复契约与故障矩阵": "recovery-contract-and-fault-matrix.md",
    "恢复契约": "recovery-contract-and-fault-matrix.md",
    "上下文装配设计说明": "context-assembly.md",
    "上下文装配": "context-assembly.md",
    "三部门的循环结构": "department-loop.md",
    "循环结构设计说明": "department-loop.md",
    "循环结构": "department-loop.md",
    "总体架构设计说明": "architecture/overall-architecture.md",
    "总体架构": "architecture/overall-architecture.md",
    "总图的词与代码名的对照": "architecture/name-map.md",
}

# 注释里写明了是别的文档、不在本单：紧挨着节号出现这些写法时不当设计说明引用处理。
# 工单 #1411：引用原型、需求记录、ADR、调研、归档文档、路线图、规则文件与运行配置的节号不在本单。
EXCLUDED_TOKENS: tuple[str, ...] = (
    r"原型[^。；，）)第与]{0,40}",
    r"RFC\s*\d+",
    r"(?<![\w.])v\d+(?![\w.])",
    r"[\w-]+\.(?:js|ts|tsx|jsx|html)",
    r"需求记录",
    r"D\d{2}",
    r"ADR[- ]?\d*",
    r"BUILD\.md",
    r"调研",
    r"归档",
    r"可观测性设计",
    r"路线图[^。；\n]{0,80}",
    r"规则文件",
    r"设计说明规范",
    r"运行配置",
    r"总图",
    r"Loop System",
    r"架构 [A-Z]\d",
    r"构建约定",
)

# 同一份文件里，原型的设计说明按节号引用了哪些节：注释里只写「第 N 节」而 N 是其中之一时，
# 指的是原型的设计，不换算（客户端页面文件常见：文件开头「原型 v8 设计说明第 3.3 节」，
# 下面只写「第 3.3 节」）。
PROTO_RE = re.compile(r"(?:原型[^。；\n]{0,60}?|(?<![\w.])v\d+[^。；\n]{0,40}?)第\s*(\d+(?:\.\d+)*)\s*节")

# 对照表：名字、同一行、同一段注释、文件开头都推不出来的，按文件（或「文件:行」）指到设计说明。
MAPPING: dict[str, str] = {
    "harness/api/app.py": "app-and-interface.md",
    "harness/app/application.py": "app-and-interface.md",
    "harness/app/project_commands.py": "app-and-interface.md",
    "harness/app/read_models.py": "app-and-interface.md",
    "harness/app/project_queries.py:1566": "model-management.md",
    "harness/providers/responses.py": "model-management.md",
    "harness/tests/test_responses.py": "model-management.md",
    "evals/": "evaluation-scenarios.md",
    "harness/definitions/rules.json:220": "department-roles.md",
    "harness/definitions/rules.json:572": "department-roles.md",
    ".github/workflows/ci.yml": "browser-and-computer-use.md",
    "harness/submissions.py": "skeleton-and-application.md",
    "harness/tightening.py": "skeleton-and-application.md",
    "client/src/renderer/src/pixel/registry.ts": "visualization.md",
    # 画布与翻译层的文件只讲画面这一份说明（个别页面文件仍按名字与文字定）
    "client/src/renderer/src/pixel/": "visualization.md",
    "client/src/renderer/src/translate/": "visualization.md",
    "client/src/renderer/src/shell/": "web-interface-and-release.md",
    # 守三环的用例：这一处指测试分层「测试按三环留」
    "client/tests/unit/check-methods.test.ts:6": "test-pyramid.md",
    "client/tests/unit/snapshot-view.test.ts:55": "test-pyramid.md",
    "client/tests/unit/translate-coverage.test.ts:6": "test-pyramid.md",
}

# 整份改写、节号对不上的，按内容对上现在的小节（工单 #1411 的「自定的边界」）。
TITLE_OVERRIDES: dict[str, str] = {
    "harness/definitions/rules.json:220": "审查者的上下文",
    "harness/definitions/rules.json:572": "角色清单",
}

# 已经删去的小节：指向它的那一部分引用去掉，注释的其余部分照旧。
# （工单 #1411 正文第 3 步点名的四处，加上清理时删去的两处。）
DELETED: set[tuple[str, str]] = {
    ("skeleton-and-application.md", "从现有代码过去的路径"),
    ("skeleton-and-application.md", "从现有代码过去的路径（工单）"),
    ("app-and-interface.md", "Web 控制台的删除"),
    ("app-and-interface.md", "Web 控制台的去留"),
    ("execution-environment.md", "现在的代码"),
    ("evaluation-scenarios.md", "实施顺序"),
    ("test-pyramid.md", "引入顺序"),
}

# CHANGELOG 里没有记、但当时与现在的标题能一一对上的。
EXTRA_RENAMES: dict[str, str] = {
    "第二种路由：骨架要满足的条件": "其他路由：骨架要满足的条件",
    "客户端的同步规则": "页面的同步规则",
}

MULTI_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)((?:\s*[、，和与]\s*\d+(?:\.\d+)*)+)\s*节")
RANGE_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)\s*[至到~～-]\s*(\d+(?:\.\d+)*)\s*节")
ITEM_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)\s*节\s*第\s*(\d+)\s*[项条]")
SECTION_RE = re.compile(r"第\s*(\d+(?:\.\d+)*)\s*节")
HEADING_RE = re.compile(r"^(#{2,6})\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$")
ITEM_LINE_RE = re.compile(r"^\s{0,3}(\d+)[.、)]\s+(.+?)\s*$")
QUOTE_RE = re.compile(r"「([^」]{1,60})」")
DOC_PATH_RE = re.compile(r"docs/design/((?:[\w-]+/)*[\w-]+\.md)")
SLICE_RE = re.compile(r"\s*S\d[a-z]?")

COMMENT_STARTS = ("#", "//", "*", "/*", "*/", "--", '"""', "'''")
TAIL_OK = re.compile(r"(设计说明|设计|文档|说明)?[\s）)。，、：:；;]*")
NAME_SUFFIX = re.compile(r"(设计说明|设计|文档|说明)$")
GAP_OK = re.compile(r"(?:[\s）)、，,（(：:；;的]|设计说明|设计|文档|说明)*")
BLAME_LINE_RE = re.compile(r"^([0-9a-f]{40}) \d+ \d+")

# 以下几类推断要在注释里补上文档路径；名字写在同一段注释里的只写「小节标题」。


def run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 失败：{out.stderr[:400]}")
    return out.stdout


# ---------------------------------------------------------------- 设计说明与历史版本


@lru_cache(maxsize=None)
def doc_headings(text: str) -> tuple[tuple[str, str], ...]:
    """解析一份设计说明的编号小节：((编号, 标题), ...)。"""
    return tuple((m.group(2), m.group(3).strip()) for m in map(HEADING_RE.match, text.splitlines()) if m)


@lru_cache(maxsize=None)
def current_doc(doc: str) -> str:
    return (ROOT / DESIGN_DIR / doc).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def now_headings(doc: str) -> dict[str, str]:
    return dict(doc_headings(current_doc(doc)))


@lru_cache(maxsize=None)
def all_docs() -> tuple[str, ...]:
    return tuple(sorted(set(DOC_ALIASES.values())))


_CACHE: dict[str, str | None] = {}
_CACHE_PATH: Path | None = None


def load_cache(path: str | None) -> None:
    global _CACHE_PATH
    if not path:
        return
    _CACHE_PATH = Path(path)
    if _CACHE_PATH.exists():
        _CACHE.update(json.loads(_CACHE_PATH.read_text(encoding="utf-8")))


def save_cache() -> None:
    if _CACHE_PATH:
        _CACHE_PATH.write_text(json.dumps(_CACHE), encoding="utf-8")


@lru_cache(maxsize=None)
def doc_at(commit: str, doc: str) -> str | None:
    key = f"{commit}:{doc}"
    if key in _CACHE:
        return _CACHE[key]
    try:
        text = run(["git", "show", f"{commit}:{DESIGN_DIR}/{doc}"])
    except RuntimeError:
        text = None
    _CACHE[key] = text
    return text


@lru_cache(maxsize=None)
def blame_commits(path: str) -> tuple[str, ...]:
    out = run(["git", "blame", "--line-porcelain", "--", path])
    return tuple(m.group(1) for m in map(BLAME_LINE_RE.match, out.splitlines()) if m)


@lru_cache(maxsize=None)
def file_lines(path: str) -> tuple[str, ...]:
    return tuple((ROOT / path).read_text(encoding="utf-8").splitlines())


@lru_cache(maxsize=None)
def renames() -> dict[str, set[str]]:
    """docs/CHANGELOG.md 里的「旧标题 → 新标题」。"""
    text = (ROOT / "docs/CHANGELOG.md").read_text(encoding="utf-8")
    table: dict[str, set[str]] = defaultdict(set)
    for old, new in re.findall(r"「([^」\n]{1,60})」\s*→\s*「([^」\n]{1,60})」", text):
        old = re.sub(r"^\d+(?:\.\d+)*\s*", "", old).strip()
        new = re.sub(r"^\d+(?:\.\d+)*\s*", "", new).strip()
        table[old].add(new)
    return dict(table)


def header_block(lines: tuple[str, ...]) -> str:
    """文件开头的说明：第一段连续的注释或模块文档字符串。"""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    block: list[str] = []
    while i < len(lines) and len(block) <= 80:
        t = lines[i].strip()
        if not t:
            if block:
                break
            i += 1
            continue
        if t.startswith(COMMENT_STARTS) or t.startswith('"') or t.startswith("'"):
            block.append(lines[i])
        else:
            break
        i += 1
    return "\n".join(block)


def block_above(lines: tuple[str, ...], line: int, limit: int = 5) -> str:
    """同一段注释里紧挨在这个引用上面的几行。"""
    out: list[str] = []
    i = line - 2
    while i >= 0 and len(out) < limit:
        t = lines[i].strip()
        if not t:
            break
        if not t.startswith(COMMENT_STARTS) and not t.startswith('"'):
            break
        out.append(lines[i])
        i -= 1
    return "\n".join(reversed(out))


def mentions(text: str) -> list[tuple[int, int, str]]:
    """一段文字里出现的设计说明：(起点, 终点, 文件)，按名字长度从长到短匹配，去掉被包含的。"""
    hits: list[tuple[int, int, str]] = []
    for alias, doc in sorted(DOC_ALIASES.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(re.escape(alias), text):
            hits.append((m.start(), m.end(), doc))
    for m in DOC_PATH_RE.finditer(text):
        if m.group(1) in all_docs():
            hits.append((m.start(), m.end(), m.group(1)))
    # 注释里也有只写文件名的（文件名 + 节号）
    for m in re.finditer(r"([\w-]+)\.md", text):
        if f"{m.group(1)}.md" in all_docs():
            hits.append((m.start(), m.end(), f"{m.group(1)}.md"))
    # 去掉被更长的名字包住的（「网络与 MCP」包在「网络取回与 MCP」里）
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    kept: list[tuple[int, int, str]] = []
    for h in hits:
        if kept and h[0] < kept[-1][1]:
            continue
        kept.append(h)
    return kept


def nearest_before(text: str, pos: int, hits: list[tuple[int, int, str]]) -> str | None:
    """紧挨在 pos 前面的那个名字（中间只有标点）：名字写在同一行的写法。"""
    for start, end, doc in reversed(hits):
        if end <= pos and GAP_OK.fullmatch(text[end:pos]):
            return doc
    return None


def excluded_before(text: str, pos: int) -> str | None:
    """紧挨在节号前面的「原型 v8」「ADR-0007」这类词。"""
    for pat in EXCLUDED_TOKENS:
        for m in re.finditer(pat, text):
            if m.end() <= pos and GAP_OK.fullmatch(text[m.end() : pos]):
                return m.group(0)
    return None


# ---------------------------------------------------------------- 换算


@dataclass
class Ref:
    file: str
    line: int
    start: int
    end: int
    sec: str
    secs: tuple[str, ...] = ()
    items: tuple[int, ...] = ()
    doc: str | None = None
    how: str = ""
    title: str | None = None
    status: str = "未定"
    score: float = 0.0
    quote: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def dropped(self) -> bool:
        return self.status.startswith("去掉")


@dataclass
class Group:
    """一段被替换的文字：一个或几个连写的节号。"""

    file: str
    line: int
    start: int
    end: int
    refs: list[Ref] = field(default_factory=list)

    def render(self) -> str | None:
        names = [r.title for r in self.refs if r.title]
        if not names:
            if any(r.dropped for r in self.refs) or all(r.doc is None for r in self.refs):
                return "" if any(r.dropped for r in self.refs) else None
            return None
        return "、".join(names)


@lru_cache(maxsize=None)
def prototype_sections(path: str) -> frozenset[str]:
    """这份文件里原型的设计说明按节号引用的节。"""
    text = (ROOT / path).read_text(encoding="utf-8")
    out = set()
    for m in PROTO_RE.finditer(text):
        head = m.group(0).rsplit("第", 1)[0]
        if "与设计说明" in head or "及设计说明" in head:
            # 「原型 v10 floor.js 与设计说明第 5.2 节」：这一处指的是设计说明本身
            continue
        out.add(m.group(1))
    return frozenset(out)


def mapping_doc(path: str, line: int | None = None) -> str | None:
    """对照表：先按「文件:行」，再按文件，最后按目录。"""
    if line is not None and f"{path}:{line}" in MAPPING:
        return MAPPING[f"{path}:{line}"]
    if path in MAPPING:
        return MAPPING[path]
    for key, doc in MAPPING.items():
        if key.endswith("/") and path.startswith(key):
            return doc
    return None


def in_scope(path: str) -> bool:
    if path.startswith(SKIP_PREFIXES):
        return False
    return any(path.startswith(s) for s in SCOPES)


def collect(files: list[str]) -> tuple[list[Group], dict[str, str]]:
    groups: list[Group] = []
    texts: dict[str, str] = {}
    for path in files:
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        texts[path] = text
        for i, line in enumerate(text.splitlines(), start=1):
            taken: list[tuple[int, int]] = []
            for m in MULTI_RE.finditer(line):
                secs = (m.group(1),) + tuple(re.findall(r"\d+(?:\.\d+)*", m.group(2)))
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), s, secs) for s in secs]))
                taken.append((m.start(), m.end()))
            for m in RANGE_RE.finditer(line):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                lo, hi = m.group(1), m.group(2)
                secs = (lo, hi) if "." in lo or "." in hi else tuple(str(x) for x in range(int(lo), int(hi) + 1))
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), s, secs) for s in secs]))
                taken.append((m.start(), m.end()))
            for m in ITEM_RE.finditer(line):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), m.group(1), (), (int(m.group(2)),))]))
                taken.append((m.start(), m.end()))
            for m in SECTION_RE.finditer(line):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                groups.append(Group(path, i, m.start(), m.end(), [Ref(path, i, m.start(), m.end(), m.group(1))]))
    return groups, texts


def commit_of(ref: Ref) -> str | None:
    commits = blame_commits(ref.file)
    return commits[ref.line - 1] if ref.line - 1 < len(commits) else None


def renamed(doc: str, old: str) -> str | None:
    """旧标题对到现在 main 上的名字。"""
    now = set(now_headings(doc).values())
    if old in now:
        return old
    cands = {t for t in renames().get(old, set()) if t in now}
    if not cands and EXTRA_RENAMES.get(old) in now:
        cands = {EXTRA_RENAMES[old]}
    return cands.pop() if len(cands) == 1 else None


def title_for(ref: Ref, doc: str) -> tuple[str | None, str]:
    """这一处指向 doc 的哪一节，写成「标题」或「标题」中「项名」；连带状态一起给出。

    先按编号找小节；编号形如「N.M」而 N.M 不是小节时，按第 N 节的第 M 项找（注释里
    带小数点的编号有时指的是「第 N 节的第 M 项」）。
    """

    commit = commit_of(ref)
    hist = doc_at(commit, doc) if commit else None
    if hist is None:
        now = now_headings(doc)
        if ref.sec in now:
            return render_ref(ref, doc, now[ref.sec], hist), "ok"
        return None, f"没有第 {ref.sec} 节"
    headings = dict(doc_headings(hist))
    old = headings.get(ref.sec)
    if old is not None:
        if (doc, old) in DELETED:
            return None, f"去掉（{old} 已删去）"
        title = renamed(doc, old)
        if title:
            return render_ref(ref, doc, title, hist), "ok"
        return None, f"旧标题「{old}」对不到现在的小节"
    base, _dot, last = ref.sec.rpartition(".")
    if base and last.isdigit() and base in headings:
        items = item_texts(hist, base)
        index = int(last)
        if 1 <= index <= len(items):
            name = items[index - 1][1]
            home = item_home(doc, name)
            if home:
                return "「" + home + "」中「" + name + "」", "ok"
            return None, f"第 {base} 节的第 {index} 项「{name}」现在不在说明里"
    return None, f"当时那份说明没有第 {ref.sec} 节"


def item_home(doc: str, name: str) -> str | None:
    """一项现在在哪一节里。"""
    for num, title in now_headings(doc).items():
        if any(item == name for _, item in item_texts(current_doc(doc), num)):
            return title
    return None


def render_ref(ref: Ref, doc: str, title: str, hist: str | None) -> str:
    """一节一处的写法：小节标题；带项号或后面已有引号的，保留那一项的名字。"""
    if ref.items and hist is not None:
        old_items = dict(item_texts(hist, ref.sec))
        names = []
        for n in ref.items:
            name = old_items.get(str(n))
            if not name or item_home(doc, name) is None:
                names = []
                break
            names.append(name)
        if names:
            return "「" + title + "」中" + "".join("「" + name + "」" for name in names)
    quote = quote_after(ref)
    if quote:
        if quote == title or quote in title:
            ref.end = max(ref.end, quote_end(ref))
        elif quote in body_by_title(doc, title):
            ref.end = max(ref.end, quote_end(ref))
            return "「" + title + "」中「" + quote + "」"
    return "「" + title + "」"


def item_names(ref: Ref, doc: str) -> list[str] | None:
    """第 N 节第 M 项：那一项当时的名字，且现在还在同一节里。"""
    if not ref.items:
        return None
    commit = commit_of(ref)
    hist = doc_at(commit, doc) if commit else None
    if hist is None:
        return None
    old_items = dict(item_texts(hist, ref.sec))
    now_items = {name for _, name in item_texts(current_doc(doc), current_num(doc, ref.title or ""))}
    names = []
    for n in ref.items:
        name = old_items.get(str(n))
        if not name or name not in now_items:
            return None
        names.append(name)
    return names


def current_num(doc: str, title: str) -> str:
    for num, t in now_headings(doc).items():
        if t == title.strip("「」"):
            return num
    return ""


def item_texts(doc_text: str, sec: str) -> list[tuple[str, str]]:
    """某节下面的有序列表项：((编号, 名字), ...)。"""
    lines = doc_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group(2) == sec:
            start = i + 1
            break
    if start is None:
        return []
    items = []
    for line in lines[start:]:
        if HEADING_RE.match(line):
            break
        m = ITEM_LINE_RE.match(line)
        if m:
            items.append((m.group(1), item_name(m.group(2))))
    return items


def item_name(text: str) -> str:
    t = re.sub(r"^\*\*(.+?)\*\*\s*", r"\1", text.strip())
    t = re.split(r"[。：:（(]\s*", t, maxsplit=1)[0]
    return t.strip("* 「」")[:40]


@lru_cache(maxsize=None)
def body_by_title(doc: str, title: str) -> str:
    """一份设计说明里某一节的正文（到下一节为止），用来与注释的文字比对。"""
    lines = current_doc(doc).splitlines()
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group(3).strip().strip("「」") == title.strip("「」"):
            out = [line]
            for later in lines[i + 1 :]:
                if HEADING_RE.match(later):
                    break
                out.append(later)
            return "\n".join(out)[:8000]
    return ""


def bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(len(text) - 1) if text[i].strip() and text[i + 1].strip()}


@lru_cache(maxsize=None)
def bigram_df() -> dict[str, int]:
    """每个字符二元组出现在多少节的正文里（越少越有区分度）。"""
    df: Counter[str] = Counter()
    for doc in all_docs():
        for title in now_headings(doc).values():
            df.update(bigrams(body_by_title(doc, title)))
    return dict(df)


def similarity(text: str, doc: str, title: str) -> float:
    """注释的文字覆盖那一节正文的程度：按二元组在全部小节里的常见程度加权。"""
    a = bigrams(text)
    if not a:
        return 0.0
    body = bigrams(body_by_title(doc, title))
    if not body:
        return 0.0
    df = bigram_df()
    n = len(df) + 1
    weight = {b: math.log(n / (1 + df.get(b, 0))) for b in a}
    total = sum(weight.values())
    return sum(weight[b] for b in a & body) / total if total else 0.0


def line_text(ref: Ref) -> str:
    return file_lines(ref.file)[ref.line - 1]


def comment_text(ref: Ref) -> str:
    """这一行与同一段注释的上面几行，用来与设计说明比文字。"""
    return block_above(file_lines(ref.file), ref.line) + "\n" + line_text(ref)


def quote_after(ref: Ref) -> str:
    line = line_text(ref)
    m = QUOTE_RE.search(line, ref.end)
    if not m or m.start() - ref.end > 4:
        return ""
    return m.group(1)


def quote_end(ref: Ref) -> int:
    line = line_text(ref)
    m = QUOTE_RE.search(line, ref.end)
    return m.end() if m and m.start() - ref.end <= 4 else ref.end


def consider(ref: Ref, doc: str, how: str) -> bool:
    """按一份候选设计说明换算这一处；成功就记下。"""
    title, status = title_for(ref, doc)
    if title is None:
        ref.status = status
        return False
    ref.doc, ref.how, ref.title, ref.status = doc, how, title, "ok"
    return True


def score_of(ref: Ref, doc: str) -> float:
    """这一处注释与那份说明的那一节有多相符（用于在几个候选里挑一个）。"""
    title, status = title_for(ref, doc)
    if title is None:
        return -1.0
    section = title.split("」")[0].lstrip("「")
    text = comment_text(ref)
    quote = quote_after(ref)
    score = similarity(text, doc, section)
    # 小节的标题里有一两个词就写在注释里（「规则清单」对「装配规则」）
    title_grams = bigrams(section)
    if title_grams:
        score += 0.22 * len(title_grams & bigrams(text)) / len(title_grams)
    if quote and (quote in title or quote in body_by_title(doc, section)):
        score += 0.35
    return round(score, 3)


def rank(ref: Ref, docs: list[str]) -> list[tuple[float, str, str]]:
    """候选设计说明按与注释文字的相符程度排序：((得分, 文件, 写好的标题), ...)。"""
    scored = []
    for doc in dict.fromkeys(docs):
        title, status = title_for(ref, doc)
        if title is None:
            continue
        scored.append((score_of(ref, doc), doc, title))
    return sorted(scored, reverse=True)


def resolve(groups: list[Group], texts: dict[str, str]) -> None:
    refs = [r for g in groups for r in g.refs]
    file_doc: dict[str, Counter[str]] = {}
    for path in {r.file for r in refs}:
        counter: Counter[str] = Counter()
        for _start, _end, doc in mentions(texts[path]):
            counter[doc] += 1
        file_doc[path] = counter

    # 第一轮：名字写在同一行（确定）、同一段注释、文件开头（可能是别的说明）
    for ref in refs:
        line = line_text(ref)
        if excluded_before(line, ref.start):
            ref.status, ref.how = "排除（别的文档）", "排除"
            continue
        doc = nearest_before(line, ref.start, mentions(line))
        if doc:
            # 名字就写在这一处：这一份说明里没有这一节就是这一节删了，不再猜别的说明
            if not consider(ref, doc, "同行名字"):
                ref.doc = doc
            continue
        if ref.sec in prototype_sections(ref.file):
            # 同一份文件里原型的设计说明按这个节号引用过，这一处指的是原型
            ref.status, ref.how = "排除（原型）", "排除"
            continue
        above = block_above(file_lines(ref.file), ref.line)
        doc = nearest_before(above + "\n", len(above), mentions(above)) if above else None
        if doc:
            consider(ref, doc, "同段注释")
            continue
        header = header_block(file_lines(ref.file))
        if header and mentions(header):
            consider(ref, mentions(header)[-1][2], "文件头")

    # 一个引用里连写的几个节号用同一份设计说明
    for g in groups:
        head = next((r for r in g.refs if r.doc), None)
        if head is None:
            continue
        for r in g.refs:
            if r.doc is None and not r.status.startswith("排除"):
                if not consider(r, head.doc, "同行名字"):
                    r.doc = head.doc

    # 第二轮：对照表里人定的那一份
    for ref in refs:
        if ref.ok or ref.dropped or ref.status.startswith("排除"):
            continue
        doc = mapping_doc(ref.file, ref.line)
        if doc:
            consider(ref, doc, "对照表")

    # 第三轮：按注释文字与各说明的小节正文比对；同一份文件里已经定下来的说明、文件开头写明的
    # 那一份、文件里提到过的说明，都是候选上的少许加分
    header_doc = {}
    for path in {r.file for r in refs}:
        header = header_block(file_lines(path))
        found = {doc for _s, _e, doc in mentions(header)}
        header_doc[path] = found.pop() if len(found) == 1 else None
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for ref in refs:
        if ref.doc and not ref.status.startswith("排除"):
            votes[ref.file][ref.doc] += 1
    for ref in refs:
        if ref.ok or ref.dropped or ref.status.startswith("排除"):
            continue
        total = sum(file_doc[ref.file].values()) or 1
        prior = {doc: 0.06 * count / total for doc, count in file_doc[ref.file].items()}
        counted = sum(votes[ref.file].values()) or 1
        for doc, count in votes[ref.file].items():
            prior[doc] = prior.get(doc, 0.0) + 0.16 * count / counted
        if header_doc.get(ref.file):
            prior[header_doc[ref.file]] = prior.get(header_doc[ref.file], 0.0) + 0.12
        ranked = [
            (round(score_of(ref, doc) + prior.get(doc, 0.0), 3), doc, title)
            for doc in all_docs()
            for title, status in [title_for(ref, doc)]
            if title is not None
        ]
        ranked.sort(reverse=True)
        if not ranked:
            ref.status = "未定：没有一份说明有这个节号"
            continue
        best = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        if (best[0] >= 0.30 and best[0] >= 1.10 * second) or best[0] >= 0.45:
            ref.doc, ref.how, ref.title, ref.status, ref.score = best[1], "推断", best[2], "ok", best[0]
        else:
            ref.doc, ref.score = best[1], best[0]
            ref.status = "未定：两种读法都可能"

    # 第五轮：同一份文件（或同一个目录）里定下来的多数；都推不出来时退回文字最相符的一份。
    # 这几类的把握低于上面几轮，报告里单独标出来，交付说明的「自定的边界」逐条写明。
    for ref in refs:
        if ref.ok or ref.dropped or ref.status.startswith("排除"):
            continue
        counted = sum(votes[ref.file].values()) or 0
        if counted:
            for doc, _count in votes[ref.file].most_common(3):
                if consider(ref, doc, "同文件的多数"):
                    break
        if ref.ok:
            continue
        directory = str(Path(ref.file).parent.as_posix()) + "/"
        tally: Counter[str] = Counter()
        for path, counter in votes.items():
            if str(Path(path).parent.as_posix()) + "/" == directory:
                tally.update(counter)
        for doc, _count in tally.most_common(3):
            if consider(ref, doc, "同目录的多数"):
                break
    for ref in refs:
        if ref.ok or ref.dropped or ref.status.startswith("排除"):
            continue
        for _score, doc, _title in (
            sorted(
                (
                    (score_of(ref, doc), doc, title)
                    for doc in all_docs()
                    for title, status in [title_for(ref, doc)]
                    if title is not None
                ),
                reverse=True,
            )[:3]
        ):
            if consider(ref, doc, "文字最相符"):
                ref.score = score_of(ref, doc)
                break
    for ref in refs:
        if ref.ok or ref.dropped or ref.status.startswith("排除"):
            continue
        counted = sum(votes[ref.file].values()) or 0
        if not counted:
            continue
        doc, count = votes[ref.file].most_common(1)[0]
        if count / counted < 0.6:
            continue
        if consider(ref, doc, "同文件的多数"):
            ref.score = score_of(ref, doc)

    # 「文件:行」的对照表最后覆盖一次：人定的优先
    for ref in refs:
        key = f"{ref.file}:{ref.line}"
        if key not in MAPPING:
            continue
        doc = MAPPING[key]
        if TITLE_OVERRIDES.get(key):
            ref.doc, ref.how, ref.status = doc, "对照表", "ok"
            ref.title = "「" + TITLE_OVERRIDES[key] + "」"
            continue
        consider(ref, doc, "对照表")

# ---------------------------------------------------------------- 写回


def apply_groups(groups: list[Group], texts: dict[str, str]) -> tuple[list[str], int]:
    changed_files: list[str] = []
    changed_refs = 0
    by_file: dict[str, list[Group]] = defaultdict(list)
    for g in groups:
        by_file[g.file].append(g)
    for path, gs in sorted(by_file.items()):
        text = texts[path]
        lines = text.splitlines(keepends=True)
        by_line: dict[int, list[Group]] = defaultdict(list)
        for g in gs:
            by_line[g.line].append(g)
        touched = 0
        for lineno, line_groups in by_line.items():
            line = lines[lineno - 1]
            for g in sorted(line_groups, key=lambda x: x.start, reverse=True):
                new = g.render()
                if new is None:
                    continue
                doc = next((r.doc for r in g.refs if r.doc), None)
                context = line + "\n" + block_above(file_lines(path), lineno)
                named = bool(doc) and doc in {d for _s, _e, d in mentions(context)}
                start, end = g.start, max([g.end] + [r.end for r in g.refs])
                if any(r.dropped for r in g.refs):
                    slice_match = SLICE_RE.match(line, end)
                    if slice_match:
                        end = slice_match.end()
                if new == "":
                    _, start, end = drop_span(line, start, end)
                    line = line[:start] + line[end:]
                else:
                    if not named:
                        if doc:
                            new = f"{DESIGN_DIR}/{doc}" + new
                            suffix = NAME_SUFFIX.search(line[:start])
                            if suffix:
                                start = suffix.start()
                                while start > 0 and line[start - 1] in " \t":
                                    start -= 1
                            elif start > 0 and line[start - 1] == "的":
                                start -= 1
                            if start > 0 and re.match(r"[\w\u4e00-\u9fff]", line[start - 1]):
                                new = " " + new
                    line = line[:start] + new + line[end:]
                touched += 1
            lines[lineno - 1] = line
        new_text = "".join(lines)
        if new_text != text:
            (ROOT / path).write_text(new_text, encoding="utf-8")
            changed_files.append(path)
            changed_refs += touched
    return changed_files, changed_refs


def drop_span(line: str, start: int, end: int) -> tuple[str, int, int]:
    """删掉一处引用以后，连带去掉空掉的括注与多余的标点。"""
    left, right = line[:start], line[end:]
    openers = {"（": "）", "(": ")"}
    if left and left[-1] in openers and right.startswith(openers[left[-1]]):
        start -= 1
        end += 1
        left, right = line[:start], line[end:]
    if left.endswith(("、", "，", ",")) and right.startswith(("、", "，", ",", "）", ")")):
        start -= 1
    while start > 0 and line[start - 1] in " \t":
        start -= 1
    return line, start, end


# ---------------------------------------------------------------- 主流程


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", help="把换算结果写到这个 TSV，不改文件")
    ap.add_argument("--apply", action="store_true", help="改文件")
    ap.add_argument("--only", help="只处理这些文件（逗号分隔）")
    ap.add_argument("--cache", help="历史版本设计说明的缓存（只在开发脚本时用）")
    args = ap.parse_args(argv)

    load_cache(args.cache)
    files = [f for f in run(["git", "ls-files"]).splitlines() if f and in_scope(f)]
    if args.only:
        keep = set(args.only.split(","))
        files = [f for f in files if f in keep]
    groups, texts = collect(files)
    resolve(groups, texts)

    if args.report:
        rows = ["\t".join(("file", "line", "start", "end", "sec", "doc", "how", "title", "status", "score"))]
        for g in groups:
            for r in g.refs:
                rows.append(
                    "\t".join(
                        (r.file, str(r.line), str(g.start), str(g.end), r.sec, r.doc or "", r.how, r.title or "", r.status, f"{r.score:.3f}")
                    )
                )
        Path(args.report).write_text("\n".join(rows), encoding="utf-8")

    if args.apply:
        changed_files, changed_refs = apply_groups(groups, texts)
        print(f"改了 {len(changed_files)} 个文件、{changed_refs} 处")

    refs = [r for g in groups for r in g.refs]
    ok = sum(1 for r in refs if r.ok)
    excluded = sum(1 for r in refs if r.status.startswith("排除"))
    dropped = sum(1 for r in refs if r.dropped)
    undecided = len(refs) - ok - excluded - dropped
    print(f"处数 {len(refs)}，可换算 {ok}，去掉（小节已删）{dropped}，排除（别的文档）{excluded}，未定 {undecided}")
    save_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
