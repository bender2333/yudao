# 薄驱动不含部门与成果的名称（骨架与应用设计说明第 6 节，工单 #863；总图第二节三环的「薄驱动」）。
#
# 薄驱动只连接：它问路由实现这一轮该谁开始、问边界能不能开始、把结果交给写入口。部门的标识与成果的种类
# 一律从定义取，不写在薄驱动的代码与说明里——写回代码以后换一份定义也不生效，薄驱动就又开始认应用的词。
# 这一项在薄驱动的源码里检索组织定义里的部门标识与路由自己那份定义里的成果种类，命中即失败；命中时
# 失败说明逐条给出是哪一行、命中了哪个名称，以及这些名称现在应该从哪份定义取。
#
# 比较按整词：`product_spec` 命中 `projection.product_spec` 与 `"product_spec"`，不命中 `product_spec_hash`
# 这类以它开头的另一个名字（下划线是词内字符），也不命中大写的运行状态名 `PRODUCT_SPEC`。
#
# 读仓库里的静态文件，不开数据库、不用子进程、不用网络，属于单元层。
# 守 R1（测试分层设计说明第 13 节）：第三环的不变式——薄驱动只连接，不含应用的名称。

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIN_DRIVER = REPO_ROOT / "harness" / "orchestrator.py"
ORGANIZATION = REPO_ROOT / "harness" / "definitions" / "organization.json"
ROUTINGS = REPO_ROOT / "harness" / "definitions" / "routings.json"


def _definition(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def department_names() -> list[str]:
    # 组织定义里的部门标识：薄驱动不带这些名称，部门由定义给出
    return [item["id"] for item in _definition(ORGANIZATION)["departments"]]


def outcome_kinds() -> list[str]:
    # 成果种类：路由自己那份定义里的 outcome_kinds（第二版路由契约，#861）
    kinds: list[str] = []
    for routing in _definition(ROUTINGS)["routings"]:
        for kind in routing["outcome_kinds"]:
            if kind not in kinds:
                kinds.append(kind)
    return kinds


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


def test_the_names_the_thin_driver_must_not_know_are_not_empty():
    # 检索本身要能失败：定义里确实有部门与成果种类，名称清单不是空的
    assert department_names(), "组织定义里没有部门"
    assert outcome_kinds(), "路由自己的定义里没有成果种类"


def test_the_thin_driver_names_no_department_from_the_definitions():
    offenders = hits(THIN_DRIVER.read_text(encoding="utf-8"), department_names())
    assert offenders == [], (
        "薄驱动里出现了组织定义的部门标识，这些标识应当从定义取（骨架与应用设计说明第 6 节）：\n"
        + "\n".join(offenders)
    )


def test_the_thin_driver_names_no_outcome_kind_from_the_routing_definition():
    offenders = hits(THIN_DRIVER.read_text(encoding="utf-8"), outcome_kinds())
    assert offenders == [], (
        "薄驱动里出现了成果种类，这些种类应当从定义取（骨架与应用设计说明第 6 节）：\n"
        + "\n".join(offenders)
    )
