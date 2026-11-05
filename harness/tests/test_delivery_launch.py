# 交付说明的启动方式 launch（浏览器与 computer use 设计说明第 3.3 节，工单 #148）。
#
# launch 是可选字段，需要试用的每个入口一项；五类不符合使交付被拒绝并返回字段级错误，
# 符合时接纳、delivery_accepted 带 launch；没有 launch 的旧交付照旧接纳。
# 跑产品与工程两轮工作、读事件，属于集成层。

from pathlib import Path

import pytest

from harness.definitions import DEFINITIONS
from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec
from harness.runtime import LoopSystem

WEB = {"name": "web", "kind": "web",
       "commands": {"linux": ["npm", "start"], "windows": ["cmd", "/c", "npm start"]},
       "ready_url": "http://127.0.0.1:{port}/"}


def _events(tmp_path: Path, launch) -> list:
    script = {"product": [product_spec()], "engineering": [delivery_turn(launch=launch)]}
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(script))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # 产品提交 PRD
    system.activate_once(run_id)  # 工程交付
    return system.store.list_events(run_id)


def test_a_web_launch_is_accepted_and_the_delivery_carries_it(tmp_path: Path) -> None:
    # 符合第 3.3 节的一项：接纳，delivery_accepted 带 launch（守 R2：交付说明的事实字段是合同）
    events = _events(tmp_path, [WEB])
    accepted = next(event for event in events if event.type == EventType.DELIVERY_ACCEPTED)
    assert accepted.payload["launch"] == [{**WEB, "ready_timeout_sec": None}]


def test_a_delivery_without_launch_is_still_accepted(tmp_path: Path) -> None:
    # 旧的交付说明没有 launch：照旧接纳，事件里没有这一项（守 R1：旧事件与旧定义照旧读得进来）
    events = _events(tmp_path, None)
    accepted = next(event for event in events if event.type == EventType.DELIVERY_ACCEPTED)
    assert accepted.payload.get("launch", []) == []


@pytest.mark.parametrize("launch, field", [
    ([WEB, {**WEB, "ready_url": "http://localhost:{port}/"}], "launch"),
    ([{**WEB, "commands": {}}], "launch[0].commands"),
    ([{**WEB, "commands": {"macos": ["npm", "start"]}}], "launch[0].commands"),
    ([{"name": "web", "kind": "web", "commands": {"linux": ["npm", "start"]}}], "launch[0].ready_url"),
    ([{**WEB, "ready_url": "http://example.com:{port}/"}], "launch[0].ready_url"),
    ([{**WEB, "ready_url": "http://127.0.0.1/"}], "launch[0].ready_url"),
    ([{"name": "app", "kind": "desktop", "commands": {"linux": ["run"]},
       "ready_url": "http://127.0.0.1:{port}/"}], "launch[0].ready_url"),
    ([{**WEB, "ready_timeout_sec": 5000}], "launch[0].ready_timeout_sec"),
    ([{**WEB, "extra": 1}], "launch[0].extra"),
])
def test_a_bad_launch_rejects_the_delivery_with_a_field_error(tmp_path: Path, launch, field: str) -> None:
    # 五类不符合都使交付被拒绝：名称重复、commands 为空或系统键不对、网页应用缺 ready_url、
    # 地址不在本机或不带 {port}、就绪时限超出上限（守 R3）
    events = _events(tmp_path, launch)
    rejected = next(event for event in events if event.type == EventType.PROPOSAL_REJECTED)
    assert field in [error["field"] for error in rejected.payload.get("errors", [])], rejected.payload


def test_launch_belongs_to_the_fact_part_of_the_delivery_contract() -> None:
    # 提案合同把 launch 标明为事实字段：质检在独立判断前就能读到（守 R2）
    contract = DEFINITIONS.proposal_contracts.roles["engineering"].kinds["delivery_spec"]
    assert "launch" in contract["optional"]
    assert "launch" in (contract.get("parts") or {}).get("facts", [])
    assert "launch" not in (contract.get("parts") or {}).get("explanation", [])
