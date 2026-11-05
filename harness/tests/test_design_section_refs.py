# 代码与测试引用设计说明时写文档路径与小节标题，不写节号（工单 #1411；
# docs/agents/design-spec.md「反向引用」：工单、代码注释、规则文件与规则登记引用设计说明，
# 写「文档路径 + 小节标题」，不写节号和行号）：设计说明删节或插节以后节号前移，按节号的
# 引用就指错了；按标题的不受影响。规则文件里的这类引用已经改好，这里守代码与测试。
#
# 守 R2（测试分层设计说明「测试按三环留」的「只能向后兼容的一环：合同」）：引用与设计说明的
# 现在的小节标题一致，改说明以后按名字还能找到；同时属于「只核对已删除的东西不出现」的
# 防回退护栏（同一节「一个测试凭什么留」的特别规则）。
#
# 扫描的目录与工单的验收一致：harness/、client/src、client/tests、evals/、scripts/、
# .github/workflows/。评价材料（evals/scenarios/ 下的 checks、reference 与 materials）不在扫描
# 范围：它们按摘要校验，改一个字的注释也让那次评测运行作废。写明是别的文档的节号不算：
# 原型（含 v8 这类简称）、需求记录、ADR、调研、归档、路线图、规则文件、运行配置、总图、
# 构建约定、设计说明规范、RFC 与原型源码。这一条与转换脚本的排除规则一致；脚本是
# scripts/convert_design_section_refs.py。
#
# 读仓库里的静态文件，不开数据库、不用子进程、不用网络，属于单元层。

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SCOPES = ("harness", "client/src", "client/tests", "evals", "scripts", ".github/workflows")

SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
    ".md",
    ".css",
    ".html",
}

SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".venv"}

# 评价材料（场景的 checks、reference 与 materials）按摘要校验，改注释也让评测运行作废，
# 与转换脚本跳过同一批路径（工单 #1411 的「自定的边界」）
SKIP_PREFIXES = ("evals/scenarios/",)

# 节号的写法：「第」+ 编号 + 「节」，编号可以带小数点，也可以连写几个；「第 3 步」「第 2 项」不算
SECTION = re.compile(r"第\s*\d+(?:\.\d+)*(?:\s*[、，和与]\s*\d+(?:\.\d+)*)*\s*节")

# 节号前面写着这些词，是别的文档的引用（工单 #1411「不在本单」一段）
OTHER_DOC = re.compile(
    r"原型[^。；，）)第与\n]{0,40}|需求记录|ADR[- ]?\d|调研|归档|路线图|规则文件|运行配置|"
    r"总图|构建约定|设计说明规范|可观测性设计|Loop System|RFC\s*\d+|[\w-]+\.(?:js|ts|tsx|jsx|html)|"
    r"D\d{2}|(?<![\w.])v\d+(?![\w.])"
)

# 同一份文件里原型的设计说明按节号引用过的节：注释里只写节号而节号是其中之一时，指的是原型
PROTO = re.compile(r"(?:原型[^。；\n]{0,60}?|(?<![\w.])v\d+[^。；\n]{0,40}?)第\s*(\d+(?:\.\d+)*)\s*节")

# 判断「前面是不是写了别的文档」时，往回看这么多字
WINDOW = 60

# 每行都有「第」的文件不用再去解码，先按字节判断（扫描量大，这一步省一半时间）
MARK = "第".encode()

FOUND: list[str] | None = None


def text_files():
    for scope in SCOPES:
        base = ROOT / scope
        for root, dirs, names in os.walk(base):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            for name in names:
                path = Path(root) / name
                if path.suffix not in SUFFIXES:
                    continue
                if path.relative_to(ROOT).as_posix().startswith(SKIP_PREFIXES):
                    continue
                yield path


def offenders() -> list[str]:
    """按节号引用设计说明的地方：文件、行与那一行。"""
    found: list[str] = []
    for path in text_files():
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if MARK not in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(ROOT).as_posix()
        proto = set()
        for hit in PROTO.finditer(text):
            head = hit.group(0).rsplit("第", 1)[0]
            if "与设计说明" in head or "及设计说明" in head:
                continue
            proto.add(hit.group(1))
        for number, line in enumerate(text.splitlines(), start=1):
            for match in SECTION.finditer(line):
                before = line[max(0, match.start() - WINDOW) : match.start()]
                if OTHER_DOC.search(before):
                    continue
                numbers = re.findall(r"\d+(?:\.\d+)*", match.group(0))
                if numbers and all(value in proto for value in numbers):
                    continue
                found.append(f"{rel}:{number}: {line.strip()}")
    return found


def test_design_docs_are_referenced_by_title_not_by_section_number():
    global FOUND
    if FOUND is None:
        FOUND = offenders()
    assert not FOUND, "按节号引用设计说明的地方（改成 docs/design/<文件>.md「小节标题」）：\n" + "\n".join(FOUND)
