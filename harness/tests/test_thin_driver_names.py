# 上面两层与薄驱动不含部门与成果的名称（骨架与应用设计说明「薄驱动」，工单 #863；总图第二节三环的「薄驱动」与
# 「四层」；第四节「定义」的缝；对照表「最小投影」「每道缝的守卫」的「四层」一行，工单 #1404）。
#
# 事实与裁决、循环两层只认识事项、事件、某种成果的某一版及其依据、提案、回执，以及「一轮工作」；部门与角色
# 是定义里填的内容，一律从事项所用的那份定义取，不写在这两层的代码与说明里——写回代码以后换一份改了名的
# 定义也不生效，这两层就又开始认应用的词。薄驱动只连接：它问路由实现这一轮该谁开始、问边界能不能开始、
# 把结果交给写入口，部门的标识与成果的种类也一律从定义取。
#
# 检索的文件清单从两处合起来取：内核清单里 kind 为 module 的文件，加上写在下面 FIXED_NAMES 里的固定名单
# （五个契约模块、薄驱动、运行层、执行与装配的几个文件、路由实现），就是对照表「四层」一行列的全部文件，
# 工单 #1404 把部门名的检索从薄驱动扩到了这些文件；命中的三种名字逐条写出文件、行与名称。
#
# 成果种类的检索（工单 #1456）：内核只认「某种成果的某一版及其依据」，按定义里的提案合同核对；PRD、交付、
# 质检结论这些成果种类是定义里单独的一项（outcome_kinds.json），由路由按名称引用。内核模块与契约模块里出现
# 成果种类，说明又按成果种类写了判断。检索的是路由认得的那几种成果；骨架自己产生的那两种（skeleton 里的
# 有效合同与代码树快照）内核本来就要按名字用，不在检索范围；minimal_projection.py 的 SNAPSHOT_KIND 就是后者。
#
# 比较按整词：`product_spec` 命中 `projection.product_spec` 与 `"product_spec"`，不命中 `product_spec_hash`
# 这类以它开头的另一个名字（下划线是词内字符），也不命中大写的运行状态名 `PRODUCT_SPEC`。
#
# 允许留下名称的两处，各自写明理由；两处各管一种名称，不互相借用：
# - EXEMPT_BLOCKS：旧定义兜底 `LEGACY_VERIFICATION` 的三处部门名。它是不写核验声明时的解释，不是按部门名
#   分支：旧定义没有核验声明，读它的那一份就只能按默认的三部门解释，否则旧数据读不回来（总图第四节「定义」
#   缝的守卫 `test_definitions.py`）。只遮这一处区块，遮完还核对该区块里恰好是这三个名称、没有被扩大；
#   这一处例外只给部门名的检索用，成果种类的检索照样查区块里（下面的用例守着）。
# - ALLOWED：与成果种类同名但指别的东西的取值，逐条写理由；理由空了、或者这一条已经不再命中时用例失败，
#   固定名单不能留下一笔查不到来源的例外。
#
# 读仓库里的静态文件，不开数据库、不用子进程、不用网络，属于单元层。
#
# 守 R1（测试分层设计说明「测试按三环留」）：第三环的不变式——内核只认通用的成果，薄驱动只连接，都不含应用的名称；
# 上两层同样只连接，不含应用的名称。

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIN_DRIVER = "harness/orchestrator.py"
ORGANIZATION = REPO_ROOT / "harness" / "definitions" / "organization.json"
OUTCOME_KINDS = REPO_ROOT / "harness" / "definitions" / "outcome_kinds.json"
MANIFEST = REPO_ROOT / "harness" / "definitions" / "kernel-manifest.json"

# 契约圈的五个模块：三道槽位契约、收紧检查契约与契约版本。它们与内核模块同一条规矩：
# 里面不写部门名与成果种类（工单 #1456）
CONTRACT_MODULES = (
    "harness/assembly_contract.py",
    "harness/execution_contract.py",
    "harness/routing_contract.py",
    "harness/tightening_contract.py",
    "harness/contract_versions.py",
)

# 写在测试里的固定名单（对照表 docs/design/architecture/name-map.md「每道缝的守卫」「四层」一行）：内核清单里没有的其余文件——薄驱动、运行层、执行与装配的
# 几个文件，加上路由实现 `watched_outputs.py`、`tightening.py`。清单里的模块由 MANIFEST 补齐；两处合起来
# 才是这一行列的全部文件
FIXED_NAMES = (
    "harness/contract_versions.py",
    "harness/execution_contract.py",
    "harness/assembly_contract.py",
    "harness/tightening_contract.py",
    "harness/routing_contract.py",
    "harness/orchestrator.py",
    "harness/runtime.py",
    "harness/engine.py",
    "harness/assembly.py",
    "harness/context.py",
    "harness/watched_outputs.py",
    "harness/tightening.py",
)

# 允许出现部门名的区块：旧定义兜底的核验关系与写入范围。它是「不写声明时的解释」，不是按部门名分支：
# 旧定义没有核验声明，读它的那一份就只能按默认的三部门解释，否则旧数据读不回来（总图第四节「定义」缝的
# 守卫 `test_definitions.py`）。区块之外、或者区块里多出别的部门名，守卫照样失败
EXEMPT_BLOCKS = {"harness/definitions/__init__.py": "LEGACY_VERIFICATION = VerificationDeclaration("}

# 固定名单（工单 #1456）：可以留在内核模块里的名称，键是（文件, 名称），值是这一条的理由。
# 只收与成果种类同名但指别的东西的取值。每一条都写了理由；理由空了、或者这一条已经不再命中时用例失败——
# 名单不能留下一笔查不到来源的例外
ALLOWED: dict[tuple[str, str], str] = {
    ("harness/definitions/__init__.py", "structure"):
        "rules.json 的 kind 取值：规则走候选与批准的那种改动方式，与结构说明同名但不是它",
    ("harness/definitions/__init__.py", "delivery_spec"):
        "旧定义没有写核验声明时按三部门解释（默认质检核验工程的交付）：字段只增，旧文件新版本能读",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _definition(path: Path) -> dict:
    return json.loads(_read(path))


def department_names() -> list[str]:
    # 组织定义里的部门标识：上两层、薄驱动与契约模块都不带这些名称，部门由定义给出
    return [item["id"] for item in _definition(ORGANIZATION)["departments"]]


def outcome_kinds() -> list[str]:
    # 成果种类：定义里单独的一项（outcome_kinds.json，工单 #1456），路由按名称引用它的一组。
    # 内核与契约模块里不出现这些名称：加一种成果种类只写定义，不改内核
    return [item["id"] for item in _definition(OUTCOME_KINDS)["kinds"]]


def kernel_modules() -> list[str]:
    # 内核清单里 kind 为 module 的文件，加上五个契约模块
    manifest = _definition(MANIFEST)
    return [entry["path"] for entry in manifest["paths"] if entry["kind"] == "module"] + list(CONTRACT_MODULES)


def guarded_files() -> list[str]:
    # 上面两层的全部文件：内核清单里 kind 为 module 的文件，加上固定名单；按路径去重、保持顺序
    listed = [entry["path"] for entry in _definition(MANIFEST)["paths"] if entry["kind"] == "module"]
    files: list[str] = []
    for name in (*listed, *FIXED_NAMES):
        if name not in files:
            files.append(name)
    return files


def _block(source: str, start: str) -> tuple[int, int] | None:
    # 允许的区块：start 那一行到它后面第一个顶格写的 `)`，两头都算在区块里。
    # 开头那一行或结束那一行找不到时是 None：找不到结束行时不许把文件余下的部分整段遮掉
    lines = source.splitlines()
    first = next((index for index, line in enumerate(lines) if line.startswith(start)), None)
    if first is None:
        return None
    last = next((index for index in range(first + 1, len(lines)) if lines[index].rstrip() == ")"), None)
    return None if last is None else (first, last)


def exempted(source: str, start: str) -> str:
    # 把允许的区块遮掉：行数保持不变，区块以外的命中照样按原行号报
    lines = source.splitlines()
    bounds = _block(source, start)
    if bounds is None:
        return source
    first, last = bounds
    return "\n".join([*lines[:first], *("" for _ in range(first, last + 1)), *lines[last + 1:]])


def _pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")


def hits(source: str, names: list[str], *, file: str) -> list[dict[str, object]]:
    # 命中：名称在源码里作为一个整词出现（标识符、字符串或说明的一部分）
    found: list[dict[str, object]] = []
    for number, line in enumerate(source.splitlines(), start=1):
        for name in names:
            if _pattern(name).search(line):
                found.append({"file": file, "line": number, "name": name, "text": line.strip()})
    return found


def describe(hit: dict[str, object]) -> str:
    # 一条命中写成一行：文件、行号、名称与那一行原文
    return f"{hit['file']}:{hit['line']}: {hit['name']} — {hit['text']}"


def reported(names: list[str], source: str, *, file: str, exempt: bool = False) -> list[str]:
    """一份源码里出现、又不在固定名单里的名称，逐条写出来。

    exempt 只给部门名用：旧定义区块那处例外是部门名的例外，成果种类的检索不走它（工单 #1456 的守卫不因为
    部门名的例外变松）。
    """
    block = EXEMPT_BLOCKS.get(file) if exempt else None
    return [describe(hit) for hit in hits(exempted(source, block) if block else source, names, file=file)
            if (file, str(hit["name"])) not in ALLOWED]


def offenders(names: list[str], files: list[str] | None = None, *, exempt: bool = False) -> list[str]:
    """这些名称在这些文件里出现、又不在两处允许名单里的，逐条写出来。"""
    found: list[str] = []
    for file in files if files is not None else kernel_modules():
        found.extend(reported(names, _read(REPO_ROOT / file), file=file, exempt=exempt))
    return found


def test_the_names_the_thin_driver_must_not_know_are_not_empty():
    # 检索本身要能失败：定义里确实有部门与成果种类，名称清单不是空的
    assert department_names(), "组织定义里没有部门"
    assert outcome_kinds(), "定义里没有成果种类"
    assert len(kernel_modules()) >= len(CONTRACT_MODULES) + 1, "内核清单里没有 kind 为 module 的文件"


def test_the_guard_reads_every_file_of_the_two_upper_layers():
    # 文件清单从内核清单与固定名单合起来取，去重、都在，且一张都不少（少了就有一个文件不再被检索）
    files = guarded_files()
    assert len(files) == len(set(files)), "文件清单里有重复的路径"
    missing = [name for name in files if not (REPO_ROOT / name).is_file()]
    assert missing == [], "文件清单里有不存在的文件：" + "、".join(missing)
    listed = {entry["path"] for entry in _definition(MANIFEST)["paths"] if entry["kind"] == "module"}
    assert listed <= set(files), "内核清单里 kind 为 module 的文件没有全部检索"
    assert set(FIXED_NAMES) <= set(files)
    # 对照表四层一行点到名的文件逐个核对：少了哪一个（不再被检索）都失败
    for name in ("harness/contract_versions.py", "harness/execution_contract.py", "harness/assembly_contract.py",
                 "harness/tightening_contract.py", "harness/routing_contract.py", "harness/orchestrator.py",
                 "harness/runtime.py", "harness/engine.py", "harness/assembly.py", "harness/context.py",
                 "harness/watched_outputs.py", "harness/tightening.py"):
        assert name in files, f"{name} 不在检索的文件清单里"


def test_the_two_upper_layers_name_no_department_from_the_definitions():
    # exempt=True：部门名有一处区块例外（旧定义兜底），只在这一项里遮掉
    found = offenders(department_names(), guarded_files(), exempt=True)
    assert found == [], (
        "上面两层里出现了组织定义的部门标识，这些标识应当从事项所用的那份定义取"
        "（形态与核验角色设计说明第 4.1 节，工单 #1404）。确实要留下的写进固定名单并写一句理由：\n"
        + "\n".join(found))


def test_the_thin_driver_names_no_outcome_kind_from_the_definition():
    found = hits(_read(REPO_ROOT / THIN_DRIVER), outcome_kinds(), file=THIN_DRIVER)
    assert found == [], (
        "薄驱动里出现了成果种类，这些种类应当从定义取（骨架与应用设计说明第 6 节）：\n"
        + "\n".join(describe(hit) for hit in found)
    )


def test_the_kernel_and_the_contract_modules_name_no_outcome_kind():
    found = offenders(outcome_kinds())
    assert found == [], (
        "内核或契约模块里出现了成果种类：内核按定义里的提案合同核对，不按成果种类写判断（工单 #1456）。\n"
        "确实要留下的写进本用例的固定名单 ALLOWED，并写一句理由：\n" + "\n".join(found)
    )


def test_every_name_in_the_fixed_list_has_a_reason_and_is_still_there():
    # 固定名单不留没有理由的例外，也不留已经查不到的一笔
    missing = [f"{file}: {name}" for (file, name), reason in ALLOWED.items() if not reason.strip()]
    assert missing == [], "固定名单里的这几条没有写理由：\n" + "\n".join(missing)
    present = {(str(hit["file"]), str(hit["name"])) for file in kernel_modules()
               for name in {name for (_file, name) in ALLOWED}
               for hit in hits(_read(REPO_ROOT / file), [name], file=file)}
    stale = [f"{file}: {name}" for (file, name) in ALLOWED if (file, name) not in present]
    assert stale == [], "固定名单里的这几条已经不再命中，删掉它们：\n" + "\n".join(stale)


def test_a_department_name_written_back_fails_with_the_file_the_line_and_the_name():
    # 验收第 1 条后半：故意在一个文件里写回 "quality" 时守卫失败，失败说明写出文件、行与名称。
    # 用临时文本演示，不改产品文件
    found = hits('def start(department):\n    return department == "quality"\n',
                 department_names(), file="harness/watched_outputs.py")
    assert [describe(hit) for hit in found] == [
        'harness/watched_outputs.py:2: quality — return department == "quality"']


def test_the_exempted_block_explains_the_three_departments_of_the_old_definition_only():
    # 允许的区块没有被扩大：它只解释旧定义（没有写核验声明）的核验角色「质检核验工程的交付」与它的写入范围。
    # 区块里的名称不是这三个、或者区块不在那一处，守卫的放行就没有依据了
    file = "harness/definitions/__init__.py"
    source = _read(REPO_ROOT / file)
    bounds = _block(source, EXEMPT_BLOCKS[file])
    assert bounds is not None, "允许的区块没有找到，守卫的豁免失去了依据"
    lines = source.splitlines()
    found = hits("\n".join(lines[bounds[0]:bounds[1] + 1]), department_names(), file=file)
    names = sorted(str(hit["name"]) for hit in found)
    assert names == ["engineering", "quality", "quality"]


def test_an_outcome_kind_inside_the_exempted_block_is_still_reported():
    # 区块例外只给部门名：旧定义区块里写回一个成果种类，成果种类的守卫照样报出来（遮掉区块的只是部门名那一项，
    # 否则这个区块对成果种类整段失明，比工单 #1456 的守卫更松）
    file = "harness/definitions/__init__.py"
    source = _read(REPO_ROOT / file)
    bounds = _block(source, EXEMPT_BLOCKS[file])
    assert bounds is not None, "允许的区块没有找到，这条核对失去了依据"
    lines = source.splitlines()
    probe = "\n".join([*lines[:bounds[1]], "# probe: qa_review", *lines[bounds[1]:]])
    assert reported(["qa_review"], probe, file=file) == [
        f"{file}:{bounds[1] + 1}: qa_review — # probe: qa_review"]
    assert hits(exempted(probe, EXEMPT_BLOCKS[file]), ["qa_review"], file=file) == []


def test_an_outcome_kind_written_into_a_temporary_text_fails_with_file_line_and_name():
    # 故意写回一个成果种类时失败，失败说明写出文件、行与名称（工单 #1456）：用例用一段临时文本演示
    probe = "# 内核模块\nARTIFACT = \"product_spec\"\n"
    found = [describe(hit) for hit in hits(probe, outcome_kinds(), file="harness/adjudication.py")]
    assert len(found) == 1, found
    assert found[0].startswith("harness/adjudication.py:2:")
    assert "product_spec" in found[0]
