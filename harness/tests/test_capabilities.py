# 能力清单里每条查询登记的事件种类（应用层与接口层设计说明「页面的同步规则」）：
# 客户端按这份清单决定什么时候重新查询，漏掉一种就会让页面上对应的那一节停在旧值（工单 #674）。
# 查的是运行中的服务给出的能力清单，不是手抄的常量。

from harness.app.application import Application
from harness.models import EventType, ProjectEventType
from harness.runtime import LoopSystem


def _changed_by(system: LoopSystem, name: str) -> set[str]:
    capabilities = Application(system).capabilities("", access="local")
    query = next(item for item in capabilities.queries if item.name == name)
    return set(query.changed_by)


def test_the_project_settings_query_lists_the_events_that_change_what_it_shows(tmp_path):
    # 工单 #674：项目设置页显示部门设置、置顶与归档，改变它们的事件种类都要在清单里，
    # 否则保存以后页面不更新（要手动刷新）
    system = LoopSystem(tmp_path / "data")
    try:
        changed_by = _changed_by(system, "project.settings")
        assert {
            ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED,
            ProjectEventType.PROJECT_PINNED,
            ProjectEventType.PROJECT_ARCHIVED,
            ProjectEventType.PROJECT_RESTORED,
        } <= changed_by
    finally:
        system.close()


def test_the_coverage_query_and_its_overlay_are_listed_with_the_event_that_changes_them(tmp_path):
    # 工单 #399：检验覆盖的查询进能力清单，核验角色提交放行记录时重新查询；
    # 覆盖层「coverage」依赖这条查询，查询登记以后才列出
    system = LoopSystem(tmp_path / "data")
    try:
        capabilities = Application(system).capabilities("", access="local")
        assert "acceptance.coverage" in {item.name for item in capabilities.queries}
        assert _changed_by(system, "acceptance.coverage") == {"qa_submitted"}
        overlays = {item.name: list(item.queries) for item in capabilities.overlays}
        assert overlays["coverage"] == ["acceptance.coverage"]
    finally:
        system.close()


def test_the_queries_showing_department_settings_all_list_its_change(tmp_path):
    # 显示部门设置的两条查询都要带着这个事件种类：两处口径一致，改部门设置以后都更新
    system = LoopSystem(tmp_path / "data")
    try:
        for name in ("department.workspace", "project.settings"):
            assert ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED in _changed_by(system, name), name
    finally:
        system.close()


def test_the_tools_registry_lists_the_events_that_change_the_records_it_shows(tmp_path):
    # 工单 #1177：工具登记给出各项目最近的取回记录与每台服务器最近一次探测的状态。
    # 项目的出现与改名改变条目，服务器设置改变设置与工具清单，探测结果改变最近一次状态，
    # 取回动作（tool_started 起、tool_called 出结果）改变取回记录；漏一种页面就停在旧值
    system = LoopSystem(tmp_path / "data")
    try:
        assert _changed_by(system, "tools.registry") == {
            ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
            ProjectEventType.MCP_SERVERS_CONFIGURED, ProjectEventType.TOOL_SERVER_PROBE_FINISHED,
            EventType.TOOL_STARTED, EventType.TOOL_CALLED,
        }
    finally:
        system.close()
