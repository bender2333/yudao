from harness.app.application import Application
from harness.app.project_queries import DepartmentWorkspace, ProjectFlow, WorkItemMaterials
from harness.demo import DEMO_CHANGE, DEMO_TASK, run_demo

def test_demo_fills_four_views(data_dir):
    system, run_id = run_demo(data_dir)
    projection = system.project(run_id)
    assert projection.phase == "DONE"
    assert projection.request_count == 3
    assert projection.rework_count == 1
    assert projection.product_spec.revision == 3
    assert projection.input_version == projection.processed_input_version == 2
    assert [item.text for item in projection.inputs] == [DEMO_TASK, DEMO_CHANGE]
    assert projection.task == DEMO_TASK + DEMO_CHANGE
    assert projection.product_spec.input_version == 2
    assert projection.product_spec.change_record["retired"] == ["Unknown flags are rejected with exit 2"]
    assert len(projection.engineering_plans) == 3
    assert projection.engineering_plans[0].effective_contract_hash != projection.engineering_plan.effective_contract_hash
    # 部门 Prompt 在项目部门设置中，run 内没有副本；demo 改过产品部门的 Prompt
    assert system.projects.read_department_setting(projection.project_id, "product")["version"] == 1
    assert projection.reviews[0].checks[0]["name"] == "usage"
    assert projection.reviews[0].checks[0]["exit_code"] != 0
    assert {item["name"] for item in projection.last_review.checks} == {"echo", "flags", "usage"}
    assert all(item["exit_code"] == 0 for item in projection.last_review.checks)
    assert projection.delivery_specs
    assert projection.manifests
    assert any(event.type == "collaboration_requested" for event in system.store.list_events(run_id))
    assert any(event.type == "collaboration_responded" for event in system.store.list_events(run_id))
    # demo 的四个界面内容经应用层查询取得：流转的咨询记录、材料里的质检、部门工作间的上下文清单
    application = Application(system)
    flow = application.query("project.flow", ProjectFlow(
        project_id=projection.project_id, work_item=projection.work_item_id))
    consultations = [record for record in flow.data.records if record.kind == "咨询"]
    assert {record.status for record in consultations} == {"已回应", "已完成"}
    assert {record.direction_from for record in consultations} == {"product", "engineering", "quality"}
    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=projection.project_id, work_item=projection.work_item_id))
    assert materials.data.reviews
    workspace = application.query("department.workspace", DepartmentWorkspace(
        project_id=projection.project_id, department="product", work_item=projection.work_item_id))
    assert workspace.data.context["manifests"]
    # 产品部门在 demo 改 Prompt 之前的激活用内置默认（版本 0），之后用项目部门设置（版本 1）
    assert workspace.data.department_setting.used_version == 1
