"""工单 #1509：路由与会话按事项冻结的定义——路由实例按形态各一份，建会话收事项的部门清单。

前面几张把部门名从上面几层拿掉了：#1391 的路由与查询按定义、#1401 的装配按定义、#1392 的形态随事项冻结、
#1402 的形态能改能回。这一条补上 #1404 交回时查出的另一半：写入口与装配已经按事项冻结的那份定义，
路由与会话还按进程加载的那一份，三个部门都改名的那份形态采用以后第一次开工就是 `KeyError: 'product'`。

做法：#1509 的工单写明的第二条，路由契约加一个可选的注入方法（照 `use_facts` 的样子），组装处给每份形态
一份路由实例、接上它自己那份定义；没有注入的实例照旧读进程加载的那份（所以测试里的第二种路由不用改）；
建会话收事项那份形态的部门清单。

层：集成层（两个事项各跑完一次完整的三部门循环，第二个跨一次进程重启）。同一文件里也有不需要完整循环的
用例（路由实例、注入的可选性、会话的部门清单、默认收件人），按分层设计说明第 2 节「一个文件中的测试用到
不同层级的资源时，整个文件登记为其中最高的一层」一起登记为集成层。

守 R3（路线图阶段二写明的「形态随事项冻结」：同一个实例里两份形态各自按自己冻结的那份定义取值）；
R2 的两条也守：路由契约只增（旧的实现照旧被接受、不被调用）与建会话的部门清单来自定义。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from harness import proposals, routing_contract
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.contracts import Accepted
from harness.app.form_commands import OrganizationAdopt
from harness.app.form_queries import ProjectOrganization
from harness.definitions import DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.environment import Workspaces
from harness.models import RunProjection, SessionRecord
from harness.proposals import ask_turn, delivery_turn, product_spec
from harness.runtime import LoopSystem, load_forms
from harness.sessions import SessionFactory
from harness.tests.helpers import quality_turns
from harness.tightening import WATCHED_OUTPUTS
from harness.watched_outputs import ROUTING, waiting_departments

GOAL = "做一个可以长期演进的逐行文本处理工具。"

# 发布带里的第二份形态：从产品定义复制、三个部门都改名的定义（与 #1404 的改名对照同一份做法）
RENAMED_FORM = "three_departments_renamed"
RENAMED = {"product": "spec_owner", "engineering": "builder", "quality": "inspector"}
RENAMED_NAMES = tuple(RENAMED.values())
DEFAULT_NAMES = tuple(RENAMED.keys())


# ---------------------------------------------------------------------------
# 三个部门都改名的定义：从产品定义复制，不手写一整份
# ---------------------------------------------------------------------------


def _renamed(value: Any) -> Any:
    # 定义文件里表示部门的那个字符串全部换掉，其余内容照旧；规则登记的条目名按部门分段，一起换
    if isinstance(value, dict):
        return {_renamed_key(key): _renamed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item) for item in value]
    return RENAMED.get(value, value) if isinstance(value, str) else value


def _renamed_key(key: Any) -> Any:
    if not isinstance(key, str):
        return key
    return ".".join(RENAMED.get(part, part) for part in key.split("."))


def renamed_definitions(tmp_path: Path):
    """产品定义的一份副本：三个部门的编号换成 RENAMED 里的名字，其余内容（含中文名）照旧。"""
    directory = tmp_path / "renamed" / "definitions"
    directory.mkdir(parents=True, exist_ok=True)
    for path in DEFINITIONS_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        content = _renamed(content)
        (directory / path.name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _forms(renamed: Any) -> dict[str, tuple[Any, Any]]:
    # 实例同时加载的两份形态：默认的三部门与三个部门都改名的那一份
    return {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), RENAMED_FORM: (renamed, WATCHED_OUTPUTS)}


class _Store:
    # 组装处手里的事件库：这里只核对路由的接法，路由不读事件（成果驱动只读投影）
    def list_events(self, run_id: str) -> list[Any]:
        return []


def _new_input_view() -> RunProjection:
    # 一条还没有任何部门处理过的新输入：收输入的部门是唯一有新的工作的那一个
    view = RunProjection(run_id="run", task="build a CLI")
    view.input_version = 1
    return view


# ---------------------------------------------------------------------------
# 路由实例按形态各一份，接上自己那份定义
# ---------------------------------------------------------------------------


def test_each_form_gets_its_own_routing_instance_bound_to_its_own_definitions(tmp_path):
    # 验收第 1 条的装载那一半：同一个实例加载两份形态时，每份得到自己的一份路由实例（不共用），
    # 各按自己那份定义里的部门清单取值；登记表里那一份没有被改动，仍读进程加载的定义
    renamed = renamed_definitions(tmp_path)
    forms = load_forms(_forms(renamed), _Store())
    default_routing = forms[DEFAULT_FORM].routing
    renamed_routing = forms[RENAMED_FORM].routing
    assert default_routing is not renamed_routing

    view = _new_input_view()
    assert (default_routing.ready_departments(view, waiting=set(DEFAULT_NAMES)),
            default_routing.next_department(view, waiting=set(DEFAULT_NAMES))) == (["product"], "product")
    assert (renamed_routing.ready_departments(view, waiting=set(RENAMED_NAMES)),
            renamed_routing.next_department(view, waiting=set(RENAMED_NAMES))) == (["spec_owner"], "spec_owner")
    # 一份形态的部门清单不会盖掉另一份：先后问两个实例，答案各自不变
    assert default_routing.next_department(view, waiting=set(DEFAULT_NAMES)) == "product"
    assert renamed_routing.next_department(view, waiting=set(RENAMED_NAMES)) == "spec_owner"

    # 没有注入的那一份（登记表里的那个实例）仍读进程加载的定义：注入的副本不改登记表
    assert routing_contract.select(DEFINITIONS.routing) is ROUTING
    assert ROUTING.next_department(view, waiting=set(DEFAULT_NAMES)) == "product"

    # 在等待的部门也按这一份定义的部门清单算（改名的部门不会被漏掉）
    assert waiting_departments({}, renamed) == set(RENAMED_NAMES)
    assert waiting_departments({"builder": "active"}, renamed) == set(RENAMED_NAMES) - {"builder"}


def test_a_routing_that_declares_the_injection_gets_its_own_instance_and_the_others_are_left_alone(tmp_path,
                                                                                                  monkeypatch):
    # R2：契约的注入是可选的（照 use_facts 的样子只增）。声明了 use_definitions 的实现每次选择得到一份新的、
    # 接上这一次定义的实例（一份形态一份，不共用）；交出空表示就地注入。没有声明的实现（测试里的第二种路由）
    # 照旧交出登记的那一个，也不会被调用
    monkeypatch.setattr(routing_contract, "_REGISTRY", dict(routing_contract._REGISTRY))

    class _WithDefinitions:
        NAME = "with_definitions"
        CONTRACT_VERSION = routing_contract.CURRENT_VERSION

        def __init__(self, definitions: Any = None) -> None:
            self.definitions = definitions

        def check_definition(self, definitions: Any) -> None:
            return None

        def use_definitions(self, definitions: Any) -> "_WithDefinitions":
            return _WithDefinitions(definitions)

    class _InPlace:
        NAME = "in_place"
        CONTRACT_VERSION = routing_contract.CURRENT_VERSION

        def __init__(self) -> None:
            self.definitions: Any = None

        def check_definition(self, definitions: Any) -> None:
            return None

        def use_definitions(self, definitions: Any) -> None:
            self.definitions = definitions

    class _WithoutDefinitions:
        NAME = "without_definitions"
        CONTRACT_VERSION = routing_contract.CURRENT_VERSION

        def check_definition(self, definitions: Any) -> None:
            return None

    renamed = renamed_definitions(tmp_path)
    template = _WithDefinitions()
    routing_contract.register(template)
    # 两次选择各拿一份新实例、各接上这一次交进来的定义：模板本身没有被改动
    first = routing_contract.select("with_definitions", DEFINITIONS)
    second = routing_contract.select("with_definitions", renamed)
    assert first is not template and second is not template and first is not second
    assert (first.definitions, second.definitions) == (DEFINITIONS, renamed)
    assert template.definitions is None
    # 就地注入的实现交出空：照旧用登记的那一个，注入照常发生
    in_place = _InPlace()
    routing_contract.register(in_place)
    assert routing_contract.select("in_place", DEFINITIONS) is in_place
    assert in_place.definitions is DEFINITIONS

    other = _WithoutDefinitions()
    routing_contract.register(other)
    assert routing_contract.select("without_definitions", DEFINITIONS) is other
    assert routing_contract.select("without_definitions") is other
    assert not hasattr(other, "use_definitions")


def test_a_routing_that_declares_the_injection_but_is_not_callable_is_rejected(tmp_path, monkeypatch):
    # R2：注入是契约上的可选方法，声明了却不是可调用的，在开始一轮工作之前失败、写明是哪一种路由
    monkeypatch.setattr(routing_contract, "_REGISTRY", dict(routing_contract._REGISTRY))

    class _Broken:
        NAME = "broken_injection"
        CONTRACT_VERSION = routing_contract.CURRENT_VERSION
        use_definitions = "not a method"

        def check_definition(self, definitions: Any) -> None:
            return None

    routing_contract.register(_Broken())
    with pytest.raises(routing_contract.UnavailableRouting) as raised:
        routing_contract.select("broken_injection", DEFINITIONS)
    assert "use_definitions" in str(raised.value) and "broken_injection" in str(raised.value)


def test_sessions_are_created_for_the_departments_of_the_item_form():
    # 验收第 1 条的会话那一半：建会话收事项那份形态的部门清单；不给时按进程加载的定义（直接建 run 的调用）
    factory = SessionFactory()
    sessions = factory.create_run_sessions("run-1", departments=RENAMED_NAMES)
    assert tuple(sessions) == RENAMED_NAMES
    assert factory.get("run-1", "inspector").department == "inspector"
    assert tuple(factory.create_run_sessions("run-2")) == DEFINITIONS.departments


def test_sessions_are_rebuilt_from_the_projection_of_a_renamed_item(tmp_path):
    # 环境层问会话时会话表里还没有这个部门：按投影里的部门补建，不按进程加载的定义建那三个会话
    view = RunProjection(run_id="run-1")
    view.sessions = {"spec_owner": SessionRecord(session_id="ses_spec", department="spec_owner", status="idle")}
    factory = SessionFactory()
    workspaces = Workspaces(tmp_path / "runs", view=lambda run_id: view, writes=None, artifacts=None,
                            sessions=factory)
    assert workspaces.session_of("run-1", "spec_owner")[0] == "ses_spec"
    assert factory.get("run-1", "spec_owner").session_id == "ses_spec"
    with pytest.raises(KeyError):
        factory.get("run-1", "product")


def test_the_default_ask_recipient_follows_the_proposal_contract():
    # 顺手去掉的第二处写死的部门名（工单 #1509）：默认收件人按提案合同取，默认定义下是能交 PRD 的产品；
    # 给了收件人时照旧用给的那一个
    assert json.loads(ask_turn().output[0]["arguments"])["recipient"] == "product"
    assert json.loads(ask_turn("engineering").output[0]["arguments"])["recipient"] == "engineering"


def test_the_default_ask_recipient_says_so_when_no_department_can_submit_a_product_spec(monkeypatch):
    # 定义里没有能交 PRD 的部门时，默认收件人给不出来的原因写清楚，不悄悄退回某个部门名
    class _NoProduct:
        departments = ("only",)

        def proposal_contract(self, department: str, kind: str) -> dict[str, Any]:
            return {"kinds": {}}

    monkeypatch.setattr(proposals, "DEFINITIONS", _NoProduct())
    with pytest.raises(ValueError, match="product_spec"):
        ask_turn()


# ---------------------------------------------------------------------------
# 同一个实例里两个事项，各按自己冻结的那份定义跑完
# ---------------------------------------------------------------------------


def _adopt(application: Application, project_id: str, form: str) -> None:
    # 用项目设置里的形态换上它（#1402 的命令），不直接写事件
    current = application.query("project.organization", ProjectOrganization(project_id=project_id)).data
    adopted = asyncio.run(application.command("organization.adopt", OrganizationAdopt(
        command_id=str(uuid.uuid4()), project_id=project_id, form=form, changes={},
        reason="换成改了名的三部门", base_version=current.version), actor="user:local"))
    assert isinstance(adopted, Accepted), adopted


def _script(names: tuple[str, str, str]) -> dict[str, list[Any]]:
    # 收输入的部门交 PRD、交要求的部门交交付、核验角色先独立判断再放行：两个事项的脚本内容相同，只有名字不同。
    # 核验角色的脚本项按它的实际轮数给足（每一轮预测性探索、独立判断与结论各是一次模型调用）
    product, engineering, verifier = names
    return {
        product: [product_spec(goal=GOAL)],
        engineering: [delivery_turn(summary="补了用法一节")],
        verifier: quality_turns("release", "checks passed on the current snapshot", times=40),
    }


def _authors(system: LoopSystem, run_id: str) -> set[str]:
    return {event.department for event in system.store.list_events(run_id) if event.department}


def test_two_items_in_one_instance_each_run_by_their_own_frozen_definition(tmp_path):
    # 验收第 1 条：同一个实例里，第一个事项用默认形态，第二个用三个部门都改名的形态；两个都开工、
    # 一轮一轮转下去，都以放行结束，各自的部门按自己冻结的那份定义取值
    renamed = renamed_definitions(tmp_path)
    script = {**_script(DEFAULT_NAMES), **_script(RENAMED_NAMES)}
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter(script), forms=_forms(renamed),
                                    resume_on_startup=False)
    application = Application(system)
    try:
        project_id = system.projects.register("两份形态", GOAL)
        _, default_run = system.projects.start_work_item(project_id, "补用法一节")
        default_ended = system.run_until_stop(default_run)
        assert (default_ended.status, default_ended.stop_reason) == ("done", "released"), default_ended.error
        assert system.orchestrator.recorded_form(default_run) == DEFAULT_FORM

        _adopt(application, project_id, RENAMED_FORM)
        _, renamed_run = system.projects.start_work_item(project_id, "再补一节")
        renamed_ended = system.run_until_stop(renamed_run)
        assert (renamed_ended.status, renamed_ended.stop_reason) == ("done", "released"), renamed_ended.error
        assert system.orchestrator.recorded_form(renamed_run) == RENAMED_FORM
        # 部门按各自冻结的那份定义取值：默认那一份只出现它自己的三个部门，改名那一份只出现改名后的三个
        default_authors, renamed_authors = _authors(system, default_run), _authors(system, renamed_run)
    finally:
        application.close()
        system.close()

    assert default_authors == set(DEFAULT_NAMES)
    assert renamed_authors == set(RENAMED_NAMES)


# ---------------------------------------------------------------------------
# 进程重启以后继续的事项，路由仍按它冻结的那份定义
# ---------------------------------------------------------------------------


def test_an_item_continued_after_a_restart_still_routes_by_its_frozen_definition(tmp_path):
    # 验收第 2 条：改名形态的事项只跑了一轮就关掉进程；用同一个数据目录重开以后继续跑完，
    # 路由仍按这个事项冻结的那份定义（接着开工的是改名后的部门，不是进程加载的那三个部门）
    renamed = renamed_definitions(tmp_path)
    data_dir = tmp_path / "loop"
    system = LoopSystem.for_testing(data_dir, FakeAdapter(_script(RENAMED_NAMES)), forms=_forms(renamed),
                                    resume_on_startup=False)
    application = Application(system)
    try:
        project_id = system.projects.register("重启后继续", GOAL)
        _adopt(application, project_id, RENAMED_FORM)
        _, run_id = system.projects.start_work_item(project_id, "补用法一节")
        # 只跑第一轮（收输入的部门交 PRD）：进程在这一轮之后中断
        after_first = system.activate_once(run_id)
        assert after_first.status == "running"
        assert _authors(system, run_id) == {"spec_owner"}
    finally:
        application.close()
        system.close()

    reopened = LoopSystem.for_testing(data_dir, FakeAdapter(_script(RENAMED_NAMES)), forms=_forms(renamed),
                                      resume_on_startup=False)
    try:
        ended = reopened.run_until_stop(run_id)
        assert (ended.status, ended.stop_reason) == ("done", "released"), ended.error
        resumed = {event.department for event in reopened.store.list_events(run_id) if event.department}
    finally:
        reopened.close()

    # 重启以后的轮次也按改名后的部门开工：整条事项的部门只有改名后的三个
    assert resumed == set(RENAMED_NAMES)
