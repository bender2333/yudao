# 上面两层不含部门的名称（骨架与应用设计说明第 6 节，工单 #863；总图第二节三环的「薄驱动」与「四层」；
# 对照表第 4 节「每道缝的守卫」的「四层」一行，工单 #1404）。
#
# 事实与裁决、循环两层只认识事项、事件、某种成果的某一版及其依据、提案、回执，以及「一轮工作」；部门与角色
# 是定义里填的内容，一律从事项所用的那份定义取，不写在这两层的代码与说明里——写回代码以后换一份改了名的
# 定义也不生效，这两层就又开始认应用的词。薄驱动只连接：它问路由实现这一轮该谁开始、问边界能不能开始、
# 把结果交给写入口。
#
# 检索的文件清单从两处合起来取：内核清单里 kind 为 module 的文件，加上写在下面 FIXED_NAMES 里的固定名单
# （五个契约模块、薄驱动、运行层、执行与装配的几个文件、路由实现），就是对照表「四层」一行列的全部文件。
# 命中即失败，失败说明逐条给出文件、行与命中的名称。成果种类只在薄驱动里检索：扩到内核模块由工单 #1456 做。
#
# 唯一留在代码里的部门名是 `definitions/__init__.py` 的 `LEGACY_VERIFICATION`：旧定义没有写核验声明时按三部门
# 解释（总图第四节「定义」缝的守卫），它是一段数据，不是按名字分支。守卫把这一段遮掉再检索，理由记在这里；
# 另有一项核对这一段没有被扩大。
#
# 比较按整词：`product_spec` 命中 `projection.product_spec` 与 `"product_spec"`，不命中 `product_spec_hash`
# 这类以它开头的另一个名字（下划线是词内字符），也不命中大写的运行状态名 `PRODUCT_SPEC`。
#
# 读仓库里的静态文件，不开数据库、不用子进程、不用网络，属于单元层。
# 守 R1（测试分层设计说明第 13 节）：第三环的不变式——上两层只连接，不含应用的名称。

import json
import re
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "harness" / "definitions" / "kernel-manifest.json"
ORGANIZATION = REPO_ROOT / "harness" / "definitions" / "organization.json"
ROUTINGS = REPO_ROOT / "harness" / "definitions" / "routings.json"
THIN_DRIVER = REPO_ROOT / "harness" / "orchestrator.py"

# 写在测试里的固定名单（对照表第 4 节「四层」一行）：内核清单里没有的其余文件——五个契约模块、薄驱动、
# 运行层、执行与装配的几个文件，加上路由实现 `watched_outputs.py`、`tightening.py`。清单里的模块由上面的
# MANIFEST 补齐；两处合起来才是这一行列的全部文件
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


def _definition(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def department_names() -> list[str]:
    # 组织定义里的部门标识：上两层不带这些名称，部门由定义给出
    return [item["id"] for item in _definition(ORGANIZATION)["departments"]]


def outcome_kinds() -> list[str]:
    # 成果种类：路由自己那份定义里的 outcome_kinds（第二版路由契约，#861）
    kinds: list[str] = []
    for routing in _definition(ROUTINGS)["routings"]:
        for kind in routing["outcome_kinds"]:
            if kind not in kinds:
                kinds.append(kind)
    return kinds


def guarded_files() -> list[Path]:
    # 上面两层的全部文件：内核清单里 kind 为 module 的文件，加上固定名单；按路径去重、保持顺序
    listed = [REPO_ROOT / entry["path"] for entry in _definition(MANIFEST)["paths"]
              if entry["kind"] == "module"]
    files: list[Path] = []
    for path in (*listed, *(REPO_ROOT / name for name in FIXED_NAMES)):
        if path not in files:
            files.append(path)
    return files


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _block(source: str, start: str) -> tuple[int, int] | None:
    # 允许的区块：start 那一行到它后面第一个顶格写的 `)`，两头都算在区块里；找不到时是 None
    lines = source.splitlines()
    first = next((index for index, line in enumerate(lines) if line.startswith(start)), None)
    if first is None:
        return None
    last = next((index for index in range(first + 1, len(lines)) if lines[index].rstrip() == ")"), len(lines))
    return first, last


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


def hits(source: str, names: list[str]) -> list[str]:
    # 命中：名称在源码里作为一个整词出现（标识符、字符串或说明的一部分）
    found: list[str] = []
    for number, line in enumerate(source.splitlines(), start=1):
        for name in names:
            if _pattern(name).search(line):
                found.append(f"{number}: {name} — {line.strip()}")
    return found


def department_hits(files: Mapping[str, str]) -> list[str]:
    # 逐个文件检索部门标识，命中写成「文件:行: 名称 — 那一行」；文件写成相对仓库根的路径
    names = department_names()
    found: list[str] = []
    for relative, source in files.items():
        block = EXEMPT_BLOCKS.get(relative)
        for hit in hits(exempted(source, block) if block else source, names):
            found.append(f"{relative}:{hit}")
    return found


def guarded_sources() -> dict[str, str]:
    return {_relative(path): path.read_text(encoding="utf-8") for path in guarded_files()}


def test_the_names_the_two_upper_layers_must_not_know_are_not_empty():
    # 检索本身要能失败：定义里确实有部门与成果种类，名称清单不是空的
    assert department_names(), "组织定义里没有部门"
    assert outcome_kinds(), "路由自己的定义里没有成果种类"


def test_the_guard_reads_every_file_of_the_two_upper_layers():
    # 文件清单从内核清单与固定名单合起来取，去重、都在，且一张都不少（少了就有一个文件不再被检索）
    files = guarded_files()
    assert len(files) == len(set(files)), "文件清单里有重复的路径"
    missing = [path for path in files if not path.is_file()]
    assert missing == [], "文件清单里有不存在的文件：" + "、".join(str(path) for path in missing)
    listed = {REPO_ROOT / entry["path"] for entry in _definition(MANIFEST)["paths"]
              if entry["kind"] == "module"}
    assert listed <= set(files), "内核清单里 kind 为 module 的文件没有全部检索"
    assert {REPO_ROOT / name for name in FIXED_NAMES} <= set(files)
    # 对照表那几处点到名的文件都在清单里
    for name in ("harness/orchestrator.py", "harness/runtime.py", "harness/engine.py", "harness/assembly.py",
                 "harness/context.py", "harness/watched_outputs.py", "harness/tightening.py"):
        assert REPO_ROOT / name in files, f"{name} 不在检索的文件清单里"


def test_the_two_upper_layers_name_no_department_from_the_definitions():
    offenders = department_hits(guarded_sources())
    assert offenders == [], (
        "上面两层里出现了组织定义的部门标识，这些标识应当从事项所用的那份定义取"
        "（形态与核验角色设计说明第 4.1 节，工单 #1404）：\n" + "\n".join(offenders))


def test_the_thin_driver_names_no_outcome_kind_from_the_routing_definition():
    offenders = hits(THIN_DRIVER.read_text(encoding="utf-8"), outcome_kinds())
    assert offenders == [], (
        "薄驱动里出现了成果种类，这些种类应当从定义取（骨架与应用设计说明第 6 节）：\n"
        + "\n".join(offenders)
    )


def test_a_department_name_written_back_fails_with_the_file_the_line_and_the_name():
    # 验收第 1 条后半：故意在一个文件里写回 "quality" 时守卫失败，失败说明写出文件、行与名称。
    # 用临时文本演示，不改产品文件
    offenders = department_hits({"harness/watched_outputs.py": 'def start(department):\n'
                                                              '    return department == "quality"\n'})
    assert offenders == ['harness/watched_outputs.py:2: quality — return department == "quality"']


def test_the_exempted_block_explains_the_three_departments_of_the_old_definition_only():
    # 允许的区块没有被扩大：它只解释旧定义（没有写核验声明）的核验角色「质检核验工程的交付」与它的写入范围。
    # 区块里的名称不是这三个、或者区块不在那一处，守卫的放行就没有依据了
    relative = "harness/definitions/__init__.py"
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    bounds = _block(source, EXEMPT_BLOCKS[relative])
    assert bounds is not None, "允许的区块没有找到，守卫的豁免失去了依据"
    lines = source.splitlines()
    found = hits("\n".join(lines[bounds[0]:bounds[1] + 1]), department_names())
    names = sorted(hit.split(": ")[1].split(" — ")[0] for hit in found)
    assert names == ["engineering", "quality", "quality"]
