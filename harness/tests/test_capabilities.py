# 能力清单里每条查询登记的事件种类（应用层与接口层设计说明第 5.7 节）：
# 客户端按这份清单决定什么时候重新查询，漏掉一种就会让页面上对应的那一节停在旧值（工单 #674）。
# 查的是运行中的服务给出的能力清单，不是手抄的常量。

from harness.app.application import Application
from harness.models import ProjectEventType
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


def test_the_queries_showing_department_settings_all_list_its_change(tmp_path):
    # 显示部门设置的两条查询都要带着这个事件种类：两处口径一致，改部门设置以后都更新
    system = LoopSystem(tmp_path / "data")
    try:
        for name in ("department.workspace", "project.settings"):
            assert ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED in _changed_by(system, name), name
    finally:
        system.close()
