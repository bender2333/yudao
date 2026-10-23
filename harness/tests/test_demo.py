import pytest

from harness.__main__ import main
from harness.app.application import Application
from harness.app.project_queries import DepartmentWorkspace, ProjectFlow, WorkItemMaterials
from harness.demo import DEMO_CHANGE, DEMO_TASK, run_demo
from harness.tests.helpers import system_on_copy

# demo 的一次运行：module 作用域的夹具跑一次并保存数据目录，每项测试在自己的副本上读取与检查。
# 数据来自真实运行，登记为集成层。


@pytest.fixture(scope="module")
def saved_demo(tmp_path_factory):
    system, run_id = run_demo(tmp_path_factory.mktemp("demo"))
    system.close()
    return system.data_dir, run_id


@pytest.fixture
def demo_run(saved_demo, tmp_path):
    saved, run_id = saved_demo
    return system_on_copy(saved, tmp_path / "demo"), run_id


def test_demo_fills_four_views(demo_run):
    system, run_id = demo_run
    projection = system.project(run_id)
    assert projection.status == "done"
    assert projection.rework_count == 1
    assert projection.product_spec.revision == 3
    assert projection.input_version == projection.processed_input_version == 2
    assert [item.text for item in projection.inputs] == [DEMO_TASK, DEMO_CHANGE]
    assert projection.task == DEMO_TASK + DEMO_CHANGE
    assert projection.product_spec.input_version == 2
    assert projection.product_spec.change_record["retired"] == ["Unknown flags are rejected with exit 2"]
    assert projection.delivery_specs and projection.delivery_spec is not None
    assert projection.effective_contract is not None
    # 部门 Prompt 在项目部门设置中，run 内没有副本；demo 改过产品部门的 Prompt
    assert system.projects.read_department_setting(projection.project_id, "product")["version"] == 1
    assert projection.reviews[0].checks[0]["name"] == "usage"
    assert projection.reviews[0].checks[0]["exit_code"] != 0
    assert {item["name"] for item in projection.last_review.checks} == {"echo", "flags", "usage"}
    assert all(item["exit_code"] == 0 for item in projection.last_review.checks)
    assert projection.delivery_specs
    assert projection.manifests
    assert any(event.type == "ask_started" for event in system.store.list_events(run_id))
    assert any(event.type == "ask_answered" for event in system.store.list_events(run_id))
    # demo 的四个界面内容经应用层查询取得：流转的咨询记录、材料里的质检、部门工作间的上下文清单
    application = Application(system)
    flow = application.query("project.flow", ProjectFlow(
        project_id=projection.project_id, work_item=projection.work_item_id))
    consultations = [record for record in flow.data.records if record.kind == "询问"]
    assert {record.status for record in consultations} == {"已回答"}
    assert {record.direction_from for record in consultations} == {"product", "engineering", "quality"}
    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=projection.project_id, work_item=projection.work_item_id))
    assert materials.data.reviews
    workspace = application.query("department.workspace", DepartmentWorkspace(
        project_id=projection.project_id, department="product", work_item=projection.work_item_id))
    assert workspace.data.context["manifests"]
    # 产品部门在 demo 改 Prompt 之前的激活用内置默认（版本 0），之后用项目部门设置（版本 1）
    assert workspace.data.department_setting.used_version == 1


def test_the_demo_command_prints_the_api_start_command_for_the_same_data_directory(data_dir, capsys):
    # 旧 Web 控制台已删除（#78），演示的收尾一行给出接口服务的启动命令，写明同一个数据目录
    assert main(["demo", "--data-dir", str(data_dir)]) == 0
    printed = capsys.readouterr().out
    assert f"api: yudao api --data-dir {data_dir}" in printed
    assert "console" not in printed
