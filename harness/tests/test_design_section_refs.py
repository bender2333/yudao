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
# 原型（含 v8 这类简称）、需求记录与别的目录下的文档、ADR、调研、归档、路线图、规则文件、
# 运行配置、总图、构建约定、设计说明规范、RFC 与原型源码。这一条与转换脚本的排除规则一致；
# 脚本是 scripts/convert_design_section_refs.py。
#
# 三种写法都要认（工单 #1411 审查第 4 条）：只写「第 N 节」、「第 3-5 节」这类范围写法、
# 「第 3、4 节」这类连写。「原型」的豁免看文件开头：开头声明了照原型的设计做的客户端文件才算，
# 正文里提一次原型不整文件豁免（同一个判定在转换脚本的 proto_file）。
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

# 这两个文件是这条规则的工具：正文里要写出这个写法本身（正则、示例、自检用例），
# 扫它们没有意义。列在这里只是跳过这两个文件，不放过仓库里别的任何文件。
SKIP_FILES = (
    "scripts/convert_design_section_refs.py",
    "harness/tests/test_design_section_refs.py",
    "evals/context/rule-set.json",
)

# 节号的写法：「第」+ 编号 + 「节」，编号可以带小数点，也可以连写几个（「第 3、4 节」），
# 也可以是范围（「第 3-5 节」「第 7.1 至 7.3 节」）；「第 3 步」「第 2 项」不算
SECTION = re.compile(
    r"第\s*\d+(?:\.\d+)*(?:\s*[、，和与]\s*\d+(?:\.\d+)*)*\s*节"
    r"|第\s*\d+(?:\.\d+)*\s*[至到~～-]\s*\d+(?:\.\d+)*\s*节"
)

# 节号前面写着这些词，是别的文档的引用（工单 #1411「不在本单」一段）
OTHER_DOC = re.compile(
    r"原型[^。；，）)第与\n]{0,40}|需求记录|ADR[- ]?\d|调研|归档|路线图|规则文件|运行配置|"
    r"总图|构建约定|设计说明规范|可观测性设计|Loop System|RFC\s*\d+|[\w-]+\.(?:js|ts|tsx|jsx|html)|"
    r"D\d{2}|(?<![\w.])v\d+(?![\w.])|docs/(?!design/)[\w./-]*\.md"
)

# 文件开头声明了照原型的设计做：注释里的无主节号指的是原型（不在本单）
PROTO = re.compile(r"(?:原型[^。；\n]{0,60}?|(?<![\w.])v\d+[^。；\n]{0,40}?)第\s*(\d+(?:\.\d+)*)\s*节")

# 「只改」之外、原样保留节号的那几处（工单 #1411 的「自定的边界」，与转换脚本的 KEEP_AS_IS 一致）
KEEP_AS_IS: tuple[tuple[str, str], ...] = (
    ("client/tests/unit/model-logic.test.js", "选用的状态按设计说明第 9.5 节的用词"),
    ("harness/definitions/routings.json", "三部门的循环结构第 2 节"),
    ("evals/baseline/compute.py", "program-roadmap.md)第 6.1 节"),
    # 失败信息与报告里的文字（用户能看到的文字常量，不是注释）：只改的清单没有包含它们
    ("evals/runner/yudao_report.py", "判定按 D38 的 N-G1（评测场景设计第 6.3 节）"),
    ("evals/runner/yudao_report.py", "建档与事项是两个 run：下面这些数值不计入上面的指标汇总，也不进均值与噪声（第 5.2 节）"),
    ("harness/tests/kernel/test_only_grows.py", "先把设计说明第 7 节的表与内核事件模块一起改"),
    ("harness/tests/kernel/test_only_grows.py", "如果是有意改，先在设计说明第 3.1 节写明"),
    ("harness/tests/kernel/test_only_grows.py", "如果确实要停用一个原因，先在设计说明第 3.1 节写明"),
    ("harness/tests/kernel/test_only_grows.py", "先在恢复契约第 4 节写明"),
    ("harness/tests/test_thin_driver_names.py", "形态与核验角色设计说明第 4.1 节，工单 #1404"),
    ("harness/tests/test_thin_driver_names.py", "这些种类应当从定义取（骨架与应用设计说明第 6 节）"),
    ("scripts/ci_layers.py", "（测试分层设计说明第 10 节第 5 条）；改名的用例显示为一删一增"),
    ("evals/runner/compare_sides.py", "Yudao 对 OpenCode 的对照（评测场景设计第 6.3 节）"),
    ("evals/runner/run_eval.py", "上下文窗口；模型列表没有报告这个模型时用它（第 3 节「模型的容量」）"),
    ("evals/runner/run_yudao_eval.py", "上下文窗口；模型列表没有报告这个模型时用它（第 3 节「模型的容量」）"),
    ("client/tests/unit/rules-view.test.ts", "origin: \"规则登记第 8 节表格\""),
    ("harness/app/project_and_work_item_commands.py", "建档之前的事项（3.8 第 2 节）"),
    ("harness/app/project_commands.py", "3.8"),
    ("harness/projects.py", "3.8"),
    ("evals/runner/yudao_report.py", "高于」看质检这一段"),
)

# 注释里把原型的设计说明写成「设计说明第 N 节」的那几行：按写的工单核过，依据是原型的设计
# （与转换脚本的 PROTO_AS_IS 一致）
PROTO_AS_IS: tuple[tuple[str, str], ...] = (
    ("client/src/renderer/src/pixel/floor/render.ts", "原型 v10 floor.js 的绘制部分"),
    ("client/src/renderer/src/views/project/floor-screen.tsx", "回放到过去的时间点时不显示决定请求"),
    ("client/src/renderer/src/views/project/floor-screen.tsx", "回到那个位置的概览回放"),
    ("client/tests/e2e/shell.spec.ts", "连接断开时窗口整体变灰"),
)

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
                if path.relative_to(ROOT).as_posix() in SKIP_FILES:
                    continue
                yield path


def header_of(text: str) -> str:
    """文件开头第一段注释或文档字符串（与转换脚本的 header_block 同一口径）。"""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    block: list[str] = []
    while i < len(lines) and len(block) <= 80:
        stripped = lines[i].strip()
        if not stripped:
            if block:
                break
            i += 1
            continue
        if stripped.startswith(("#", "//", "*", "/*", "*/", "--", '"""', "'''")) or stripped.startswith(('"', "'")):
            block.append(lines[i])
        else:
            break
        i += 1
    return "\n".join(block)


def declares_prototype(rel: str, header: str) -> bool:
    """这个文件开头声明了照原型的设计做：客户端文件里的无主节号指的是原型。"""
    if not rel.startswith("client/"):
        return False
    for match in PROTO.finditer(header):
        head = match.group(0).rsplit("第", 1)[0]
        if "与设计说明" in head or "及设计说明" in head:
            # 「原型 v10 floor.js 的绘制部分与设计说明第 5.2 节」：这一处指的是设计说明本身
            continue
        return True
    return False


def allowed(rel: str, line: str) -> bool:
    """这一行按对照表原样保留（「只改」之外，或指的是原型的设计）。"""
    return any(rel == path and snippet in line for path, snippet in KEEP_AS_IS + PROTO_AS_IS)


def scan(rel: str, text: str) -> list[str]:
    """一份文件里按节号引用设计说明的地方：行号与那一行。"""
    proto = declares_prototype(rel, header_of(text))
    found: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if allowed(rel, line):
            continue
        for match in SECTION.finditer(line):
            before = line[max(0, match.start() - WINDOW) : match.start()]
            if OTHER_DOC.search(before):
                continue
            if proto:
                continue
            found.append(f"{rel}:{number}: {line.strip()}")
            break
    return found


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
        found.extend(scan(path.relative_to(ROOT).as_posix(), text))
    return found


def test_design_docs_are_referenced_by_title_not_by_section_number():
    global FOUND
    if FOUND is None:
        FOUND = offenders()
    assert not FOUND, "按节号引用设计说明的地方（改成 docs/design/<文件>.md「小节标题」）：\n" + "\n".join(FOUND)


# 下面三条是工单 #1411 审查第 4 条点出的三个口子，各用一段文字说明它现在报得出/报不出。

def test_a_range_of_sections_is_still_reported():
    """「第 3-5 节」这类范围写法与连写一样算引用。"""
    assert scan("harness/example.py", "# 覆盖 docs/design/local-tools.md 的本地行为（第 3-5 节）。\n")
    assert scan("harness/example.py", "# 按设计说明第 7.1 至 7.3 节实现。\n")
    assert scan("harness/example.py", "# 按设计说明第 3、4 节实现。\n")


def test_a_requirement_record_is_not_a_design_doc():
    """需求记录、路线图这些别的目录下的文档按路径写明时不算设计说明。"""
    assert not scan("harness/example.py", "# 覆盖 docs/requirements/startup-provider-reload.md 第 3-5 节的本地行为。\n")
    assert not scan("harness/example.py", "\"供对照使用（[总体路线图](../program-roadmap.md)第 6.1 节）。\"\n")


def test_the_prototype_exemption_follows_the_file_header_not_one_mention():
    """原型豁免只看文件开头：正文里提一次原型，后面的无主节号仍然要报。"""
    body_only = "// 页面路径的写法\nconst a = 1;\n// 原型 v8 设计说明第 3.3 节：首页 #/home\n// 另一处按设计说明第 7 节实现\n"
    assert scan("client/src/example.ts", body_only), "正文里提一次原型不该整文件豁免"

    header_declares = "// 页面路径（原型 v8 设计说明第 3.3 节）\n// 回放位置写在 ?at= 中（设计说明第 3.3 节）\n"
    assert not scan("client/src/example.ts", header_declares)

    assert scan("harness/example.py", "// 原型 v8 设计说明第 3.3 节\n// 按设计说明第 7 节实现\n"), "没有开头声明的不豁免"
