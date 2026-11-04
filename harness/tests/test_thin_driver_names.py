# 薄驱动与内核不含部门与成果的名称（骨架与应用设计说明第 6 节，工单 #863；总图第二节三环的「薄驱动」，
# 第四节「定义」的缝）。
#
# 薄驱动只连接：它问路由实现这一轮该谁开始、问边界能不能开始、把结果交给写入口。部门的标识与成果的种类
# 一律从定义取，不写在薄驱动的代码与说明里——写回代码以后换一份定义也不生效，薄驱动就又开始认应用的词。
#
# 工单 #1456 把成果种类的检索扩到内核清单里 kind 为 module 的文件与五个契约模块：内核只认「某种成果的某一版
# 及其依据」，按定义里的提案合同核对；PRD、交付、质检结论这些成果种类是定义里单独的一项（outcome_kinds.json），
# 由路由按名称引用。内核模块与契约模块里出现成果种类，说明又按成果种类写了判断。部门名同样不在内核与契约模块里
# （事实与裁决、循环两层不认识部门），旧定义的三部门默认值例外，写在下面的固定名单里。
#
# 这一项在源码里按整词检索命中即失败；命中时逐条写出是哪份文件、哪一行、命中了哪个名称。
# 比较按整词：`product_spec` 命中 `projection.product_spec` 与 `"product_spec"`，不命中 `product_spec_hash`
# 这类以它开头的另一个名字（下划线是词内字符），也不命中大写的运行状态名 `PRODUCT_SPEC`。
#
# 读仓库里的静态文件，不开数据库、不用子进程、不用网络，属于单元层。
# 守 R1（测试分层设计说明第 13 节）：第三环的不变式——内核只认通用的成果，薄驱动只连接，都不含应用的名称。

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

# 固定名单（工单 #1456）：可以留在内核模块里的名称，键是（文件, 名称），值是这一条的理由。
# 只收两种：旧定义文件的默认解释（字段只增，旧文件新版本能读），以及与成果种类同名但指别的东西的取值。
# 每一条都写了理由；理由空了、或者这一条已经不再命中时用例失败——名单不能留下一笔查不到来源的例外。
ALLOWED: dict[tuple[str, str], str] = {
    ("harness/definitions/__init__.py", "structure"):
        "rules.json 的 kind 取值：规则走候选与批准的那种改动方式，与结构说明同名但不是它",
    ("harness/definitions/__init__.py", "delivery_spec"):
        "旧定义没有写核验声明时按三部门解释（默认质检核验工程的交付）：字段只增，旧文件新版本能读",
    ("harness/definitions/__init__.py", "engineering"):
        "同上：旧定义的默认核验声明里被核验的角色，只对没有写声明的旧文件生效",
    ("harness/definitions/__init__.py", "quality"):
        "同上：旧定义的默认核验声明里的核验角色，只对没有写声明的旧文件生效",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _definition(path: Path) -> dict:
    return json.loads(_read(path))


def department_names() -> list[str]:
    # 组织定义里的部门标识：薄驱动、内核与契约模块都不带这些名称，部门由定义给出
    return [item["id"] for item in _definition(ORGANIZATION)["departments"]]


def outcome_kinds() -> list[str]:
    # 成果种类：定义里单独的一项（outcome_kinds.json，工单 #1456），路由按名称引用它的一组。
    # 内核与契约模块里不出现这些名称：加一种成果种类只写定义，不改内核
    return [item["id"] for item in _definition(OUTCOME_KINDS)["kinds"]]


def kernel_modules() -> list[str]:
    # 内核清单里 kind 为 module 的文件，加上五个契约模块
    manifest = _definition(MANIFEST)
    return [entry["path"] for entry in manifest["paths"] if entry["kind"] == "module"] + list(CONTRACT_MODULES)


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


def offenders(names: list[str], files: list[str] | None = None) -> list[str]:
    """这些名称在这些文件里出现、又不在固定名单里的，逐条写出来。"""
    reported: list[str] = []
    for file in files if files is not None else kernel_modules():
        for hit in hits(_read(REPO_ROOT / file), names, file=file):
            if (file, str(hit["name"])) in ALLOWED:
                continue
            reported.append(describe(hit))
    return reported


def test_the_names_the_thin_driver_must_not_know_are_not_empty():
    # 检索本身要能失败：定义里确实有部门与成果种类，名称清单不是空的
    assert department_names(), "组织定义里没有部门"
    assert outcome_kinds(), "定义里没有成果种类"
    assert len(kernel_modules()) >= len(CONTRACT_MODULES) + 1, "内核清单里没有 kind 为 module 的文件"


def test_the_thin_driver_names_no_department_from_the_definitions():
    offenders_in_driver = hits(_read(REPO_ROOT / THIN_DRIVER), department_names(), file=THIN_DRIVER)
    assert offenders_in_driver == [], (
        "薄驱动里出现了组织定义的部门标识，这些标识应当从定义取（骨架与应用设计说明第 6 节）：\n"
        + "\n".join(describe(hit) for hit in offenders_in_driver)
    )


def test_the_thin_driver_names_no_outcome_kind_from_the_definition():
    offenders_in_driver = hits(_read(REPO_ROOT / THIN_DRIVER), outcome_kinds(), file=THIN_DRIVER)
    assert offenders_in_driver == [], (
        "薄驱动里出现了成果种类，这些种类应当从定义取（骨架与应用设计说明第 6 节）：\n"
        + "\n".join(describe(hit) for hit in offenders_in_driver)
    )


def test_the_kernel_and_the_contract_modules_name_no_outcome_kind():
    found = offenders(outcome_kinds())
    assert found == [], (
        "内核或契约模块里出现了成果种类：内核按定义里的提案合同核对，不按成果种类写判断（工单 #1456）。\n"
        "确实要留下的写进本用例的固定名单 ALLOWED，并写一句理由：\n" + "\n".join(found)
    )


def test_the_kernel_and_the_contract_modules_name_no_department():
    found = offenders(department_names())
    assert found == [], (
        "内核或契约模块里出现了部门名：事实与裁决、循环两层不认识部门（总图第二节四层）。\n"
        "旧定义的三部门默认值写进固定名单并写明理由：\n" + "\n".join(found)
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


def test_an_outcome_kind_written_into_a_temporary_text_fails_with_file_line_and_name():
    # 故意写回一个成果种类时失败，失败说明写出文件、行与名称（工单 #1456）：用例用一段临时文本演示
    probe = "# 内核模块\nARTIFACT = \"product_spec\"\n"
    found = [describe(hit) for hit in hits(probe, outcome_kinds(), file="harness/adjudication.py")]
    assert len(found) == 1, found
    assert found[0].startswith("harness/adjudication.py:2:")
    assert "product_spec" in found[0]
