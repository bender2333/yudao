"""工单 #1404：三个部门都改名的定义经项目设置换上，路由照常跑完、事件序列除名字外与默认相同。

前面几张把部门名从上面两层（事实与裁决、循环）拿掉了：写入范围与检查材料按声明（#1390）、路由与查询按定义
（#1391）、装配按定义（#1401）、形态随事项冻结（#1392）、项目的形态能改能改回（#1402）。这一条用例走一遍
整件事：从产品定义复制一份、把三个部门都改成别的名字（不手写一整份），用 `organization.adopt` 把它换到项目上，
跑同一个脚本化事项（收输入的部门交 PRD、交要求的部门交交付、核验角色先独立判断再放行），与默认定义下的同一个
事项比事件序列，除部门名以外相同；结束时放行的是改名后的核验角色。

层：集成层（完整的三部门循环：真实事件库与工作区、假模型按部门给出回答，两条事项各跑完一次）。
守 R3（路线图阶段二写明的「形态随事项冻结、核验角色是角色的性质」：换一份改了名的定义，路由照常跑完，
事件序列除名字以外不变）与 R2（形态经项目设置的命令换上、查询报得出来：形态名与它的组织版本）。

先后由事件决定，不用时长赌（测试分层设计说明第 10 节第 7 条）：两个事项一个跑完再跑另一个，脚本按部门给出。
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.contracts import Accepted
from harness.app.form_commands import OrganizationAdopt
from harness.app.form_queries import ProjectOrganization
from harness.definitions import DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, Definitions, load_definitions
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec
from harness.runtime import LoopSystem
from harness.tests.event_sequence import normalized_run
from harness.tests.helpers import quality_turns
from harness.tightening import WATCHED_OUTPUTS

GOAL = "做一个可以长期演进的逐行文本处理工具。"

# 发布带里的第二份形态：从产品定义复制、三个部门都改名的定义（工单 #1404）
RENAMED_FORM = "three_departments_renamed"
RENAMED = {"product": "spec_owner", "engineering": "builder", "quality": "inspector"}

# 两边比较时的占位：部门按它在定义里的次序编号，名字不同、位置相同的部门落到同一个占位上
DEPARTMENT_PLACEHOLDER = "<department#{}>"


# ---------------------------------------------------------------------------
# 三个部门都改名的定义：从产品定义复制，不手写一整份


def _renamed(value: Any, old: str, new: str) -> Any:
    # 定义文件里表示部门的那个字符串全部换掉，其余内容照旧；规则登记的条目名按部门分段，一起换
    if isinstance(value, dict):
        return {_renamed_key(key, old, new): _renamed(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item, old, new) for item in value]
    return new if value == old else value


def _renamed_key(key: Any, old: str, new: str) -> Any:
    if not isinstance(key, str):
        return key
    return ".".join(new if part == old else part for part in key.split("."))


def renamed_definitions(tmp_path: Path) -> Definitions:
    """产品定义的一份副本：三个部门的编号换成 RENAMED 里的名字，其余内容（含中文名）照旧。"""
    directory = tmp_path / "renamed" / "definitions"
    directory.mkdir(parents=True)
    for path in DEFINITIONS_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        for old, new in RENAMED.items():
            content = _renamed(content, old, new)
        (directory / path.name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


# ---------------------------------------------------------------------------
# 同一个脚本化事项：两个事项的回答内容相同，只有部门的名字不同


def script(names: tuple[str, str, str] = tuple(RENAMED.values())) -> dict[str, list[Any]]:
    # 收输入的部门交 PRD、交要求的部门交交付、核验角色先独立判断再放行（与默认三部门同一个事项）
    product, engineering, verifier = names
    return {
        product: [product_spec(goal=GOAL)],
        engineering: [delivery_turn(summary="补了用法一节")],
        verifier: quality_turns("release", "checks passed on the current snapshot"),
    }


def _run_item(tmp_path: Path, definitions: Definitions, form: str | None,
              names: tuple[str, str, str]) -> tuple[LoopSystem, str]:
    """开一个实例，按需把项目的形态换掉，跑完一个事项；返回实例与 run。"""
    forms = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), RENAMED_FORM: (definitions, WATCHED_OUTPUTS)}
    system = LoopSystem.for_testing(tmp_path / f"loop-{form or DEFAULT_FORM}",
                                    FakeAdapter(script(names)), forms=forms, resume_on_startup=False)
    application = Application(system)
    project_id = system.projects.register("同一个事项", GOAL)
    if form is not None:
        # 用项目设置里的形态换上它（工单 #1402 的命令），不直接写事件
        current = application.query("project.organization", ProjectOrganization(project_id=project_id)).data
        adopted = asyncio.run(application.command("organization.adopt", OrganizationAdopt(
            command_id=str(uuid.uuid4()), project_id=project_id, form=form, changes={}, reason="换成改了名的三部门",
            base_version=current.version), actor="user:local"))
        assert isinstance(adopted, Accepted), adopted
        current = application.query("project.organization", ProjectOrganization(project_id=project_id)).data
        assert (current.form, current.version) == (form, definitions.version)
        # 查询报出这一份形态的核验角色就是改名后的那个
        choice = next(item for item in current.forms if item.form == form)
        assert choice.verifier_roles == [RENAMED["quality"]]
    _, run_id = system.projects.start_work_item(project_id, "补用法一节")
    ended = system.run_until_stop(run_id)
    assert ended.status == "done", ended.error
    return system, run_id


# ---------------------------------------------------------------------------
# 比较：除部门名以外的部分相同


def _canonical_text(value: str, mapping: dict[str, str]) -> str:
    # 部门名按整词换：`spec_owner` 不命中 `product_spec` 这类更长的名字（下划线是词内字符）
    for name, placeholder in mapping.items():
        value = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", placeholder, value)
    return value


def _canonical(value: Any, mapping: dict[str, str]) -> Any:
    # 定义里跟着部门改的部分，两边都换成同一个占位（也就是这份 run 自己的两个版本号）
    if isinstance(value, dict):
        return {_canonical_text(key, mapping): _canonical(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item, mapping) for item in value]
    if isinstance(value, str):
        return _canonical_text(value, mapping)
    return value


def _versions(system: LoopSystem, run_id: str) -> dict[str, str]:
    created = next(event.payload for event in system.store.list_events(run_id)
                   if event.type == EventType.RUN_CREATED)
    return {"definitions_version": created["definitions_version"],
            "parameters_version": created["parameters_version"]}


def comparable(system: LoopSystem, run_id: str, names: tuple[str, str, str]) -> Any:
    """这次 run 的完整事件序列与投影，部门名换成占位；这份定义自己的两个版本号写成与默认那一边相同的占位。"""
    mapping = {name: DEPARTMENT_PLACEHOLDER.format(index) for index, name in enumerate(names)}
    versions = _versions(system, run_id)
    mapping[versions["definitions_version"]] = "<definitions>"
    mapping[versions["parameters_version"]] = "<parameters>"
    return _canonical(normalized_run(system, run_id), mapping)


# ---------------------------------------------------------------------------


def test_the_same_item_under_the_renamed_definition_runs_to_the_same_event_sequence(tmp_path):
    # 验收第 2 条：三个部门都改名、经项目设置换上以后，同一个脚本化事项照常跑完，事件序列除部门名以外与
    # 默认定义相同；结束时放行的是改名后的核验角色
    default_names = ("product", "engineering", "quality")
    default_system, default_run = _run_item(tmp_path, DEFINITIONS, None, default_names)
    renamed = renamed_definitions(tmp_path)
    assert renamed.departments == tuple(RENAMED.values())
    renamed_system, renamed_run = _run_item(tmp_path, renamed, RENAMED_FORM, tuple(RENAMED.values()))

    # 两条事项都以放行结束；放行的是核验角色：默认是质检，改名以后是改名后的那个
    assert default_system.project(default_run).stop_reason == "released"
    assert renamed_system.project(renamed_run).stop_reason == "released"
    released_by = {event.department for event in renamed_system.store.list_events(renamed_run)
                   if event.type == EventType.QA_SUBMITTED}
    assert released_by == {RENAMED["quality"]}

    # 事件序列与投影除部门名以外相同：这里比的是整份规整以后的事件序列与投影
    assert comparable(renamed_system, renamed_run, tuple(RENAMED.values())) == \
        comparable(default_system, default_run, default_names)
    default_system.close()
    renamed_system.close()
