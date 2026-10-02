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
    from harness.views import run_payload

    payload = run_payload(system.store, run_id)
    assert payload["board"]["phase"] == "DONE"
    assert payload["timeline"]["requests"]
    assert payload["timeline"]["responses"]
    assert payload["evidence"]["reviews"]
    assert payload["context"]["manifests"]
    # 产品部门在 demo 改 Prompt 之前的激活用内置默认（版本 0），之后用项目部门设置（版本 1）
    assert {item["prompt_version"] for item in payload["prompts"]["activations"] if item["department"] == "product"} == {0, 1}
