# 关闭取回的启动参数（工单 #1172；网络与 MCP 设计说明第 5.1、12.4 节、评测场景设计说明第 3 节）：
# 以 `--no-fetch` 运行的服务里三个部门的请求都没有 `fetch_url` 与 `read_external_source`；
# 不带参数时三个部门都有。工具本身留在定义里，取舍发生在「给部门哪几个工具」这一步。
#
# 守 R1（测试分层设计说明第 13 节）：定义给部门的工具清单与主机的装配是同一条链路，
# 命令行的启动参数经它生效；这些用例在模块层跑一轮三个部门，不需要子进程或真实服务。

from __future__ import annotations

import pytest

from harness import __main__ as cli
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS, FETCH_TOOLS, configure_fetch
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem, configure_fetch_tools

DEPARTMENTS = ("product", "engineering", "quality")


@pytest.fixture(autouse=True)
def restore_fetch() -> None:
    # 取回是否可用是进程范围的启动设置：每条用例以后恢复默认，不把设置漏给后面的用例
    yield
    configure_fetch(True)


def tool_names(request) -> list[str]:
    return [item["name"] for item in request.tools]


def run_three_departments(data_dir) -> FakeAdapter:
    # 产品提交规约、工程提交交付、质检下一轮工作：三个部门的请求各记一条
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [review_turn("release", "checks passed", checks={"smoke": 0})],
    })
    system = LoopSystem.for_testing(data_dir, adapter)
    project_id = system.projects.register("取回", "把文本按行处理清楚")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "echo")
    for _ in range(3):
        system.activate_once(run_id)
    return adapter


def test_departments_have_both_fetch_tools_by_default():
    # 不带参数启动：三个部门都有取回工具（网络与 MCP 设计说明第 5.1 节）
    for department in DEPARTMENTS:
        names = DEFINITIONS.tools_for(department)
        assert set(FETCH_TOOLS) <= set(names), f"{department} 默认应有取回工具：{names}"


def test_no_fetch_removes_only_the_two_fetch_tools_from_every_department():
    # 关闭取回：三个部门的清单里都没有这两件，其余工具一个不少；工具定义本身还在（别的部分还引用它）
    before = {department: DEFINITIONS.tools_for(department) for department in DEPARTMENTS}
    configure_fetch(False)
    for department in DEPARTMENTS:
        after = DEFINITIONS.tools_for(department)
        assert not set(FETCH_TOOLS) & set(after), f"{department} 关闭取回以后不应有取回工具：{after}"
        assert set(after) == set(before[department]) - set(FETCH_TOOLS), department
    assert set(FETCH_TOOLS) <= set(DEFINITIONS.tools)


def test_no_fetch_leaves_no_fetch_tools_in_the_model_requests(tmp_path):
    # 不是只改参数名：关闭取回以后三个部门发出的请求里都没有这两件工具，
    # 而其余的读取工具还在（工具清单没有被整个清空）
    configure_fetch_tools(False)
    adapter = run_three_departments(tmp_path)
    assert {call.department for call in adapter.invocations} == set(DEPARTMENTS)
    for call in adapter.invocations:
        assert not set(FETCH_TOOLS) & set(tool_names(call)), f"{call.department} 的请求里还有取回工具"
    assert "read_file" in tool_names(adapter.invocations[0])


def test_requests_have_fetch_tools_when_the_flag_is_absent(tmp_path):
    # 对照：不带参数时三个部门的请求里都有这两件，差异来自这个启动参数
    adapter = run_three_departments(tmp_path)
    assert {call.department for call in adapter.invocations} == set(DEPARTMENTS)
    for call in adapter.invocations:
        assert set(FETCH_TOOLS) <= set(tool_names(call)), f"{call.department} 的请求里缺取回工具"


def test_cli_accepts_the_flag_before_and_after_the_subcommand():
    # 启动参数写在子命令前后都有效（与 --data-dir 等选项同一写法）；不写时不开
    parser = cli.build_parser()
    assert parser.parse_args(["api", "--no-fetch"]).no_fetch is True
    assert parser.parse_args(["--no-fetch", "api"]).no_fetch is True
    assert parser.parse_args(["api"]).no_fetch is False


def test_cli_hands_the_flag_to_the_assembly(tmp_path, monkeypatch):
    # 命令行把参数交给装配（工单 #1172 的接受标准第 2 条：服务的启动方式决定部门的工具）
    served: dict[str, object] = {}
    monkeypatch.setattr(cli, "serve_api", lambda factory, **options: served.update(options))
    monkeypatch.setattr(cli, "_lock_data_dir", lambda data_dir: object())
    monkeypatch.setattr(cli, "configure_logging", lambda data_dir: tmp_path / "yudao.log")
    monkeypatch.setattr(cli, "_stop_on_ctrl_c", lambda: None)
    assert cli.main(["api", "--no-fetch", "--data-dir", str(tmp_path)]) == 0
    assert served, "服务应当被启动"
    assert set(FETCH_TOOLS).isdisjoint(DEFINITIONS.tools_for("engineering"))
    # 再起一次不带参数：取回工具回到部门的清单里
    assert cli.main(["api", "--data-dir", str(tmp_path)]) == 0
    assert set(FETCH_TOOLS) <= set(DEFINITIONS.tools_for("engineering"))
