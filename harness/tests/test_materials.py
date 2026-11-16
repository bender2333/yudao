from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import ProjectFlow, WorkItemMaterials
from harness.artifacts import ArtifactStore
from harness.materials import append_intend
from harness.models import hash_bytes
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_decision, product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import guidance_reply, quality_turns


def test_inputs_remain_verbatim_and_byte_spans_recover_every_source(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    texts = ["  \ufeffinitial\r\n", "\u4e2d\u6587 continuation\n\t", "next\x00input", "\nfinal  "]
    materials = []
    previous_ref = None
    combined = b""
    for text in texts:
        material = append_intend(store, "run", text, previous_ref=previous_ref)
        assert material.byte_start == len(combined)
        combined += text.encode("utf-8")
        assert material.byte_end == len(combined)
        assert store.get_for_run("run", material.input_ref) == text.encode("utf-8")
        assert store.get_for_run("run", material.intend_ref) == combined
        assert material.input_ref.kind == "user_input"
        assert material.intend_ref.kind == "intend"
        assert material.intend_ref.content_hash == hash_bytes(combined)
        materials.append(material)
        previous_ref = material.intend_ref
    for material, text in zip(materials, texts):
        assert combined[material.byte_start:material.byte_end] == text.encode("utf-8")
    assert materials[1].byte_end - materials[1].byte_start > len(texts[1])
    assert b"input_ref" not in combined and b"byte_start" not in combined


def test_new_snapshot_does_not_modify_previous_input_or_snapshot(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "run", "old")
    second = append_intend(store, "run", "new", previous_ref=first.intend_ref)
    assert store.get_for_run("run", first.input_ref) == b"old"
    assert store.get_for_run("run", first.intend_ref) == b"old"
    assert store.get_for_run("run", second.intend_ref) == b"oldnew"


def test_work_item_materials_returns_full_structured_prd_and_joins_flow_event_id(tmp_path):
    # R2：work_item.materials 在保留既有字段的同时返回完整结构化 PRD 与 spec_event_id（用于与流转记录连接），
    # 并携带产品决定与接纳来源原文
    adapter = FakeAdapter({
        "product": [
            product_spec(
                goal="支持结构化需求查看",
                requirements=["展示所有 PRD 分节", "标注尚未匹配验收条件的需求"],
                acceptance=["面板展示完整 PRD 分节"],
                non_goals=["不修改导出格式"],
                boundaries=["仅限当前事项查询与面板"],
                constraints=["保持已有合同字段兼容"],
                fatal_conditions=["遗漏验收条件列表"],
            ),
            product_decision("所有版本字段全部向后兼容。", "既有客户端依赖既有字段继续读取。"),
            guidance_reply("已记录决定。"),
        ],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    project_id = system.projects.register("结构化PRD", "完善事项详情展示")
    work_item_id, run_id = system.projects.start_work_item(project_id, "展示完整 PRD 各节")
    system.activate_once(run_id)

    application = Application(system)
    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id)).data
    flow = application.query("project.flow", ProjectFlow(
        project_id=project_id, work_item=work_item_id)).data

    assert len(materials.contracts) == 1
    first = materials.contracts[0]
    assert first.revision == 1
    assert first.status == "active"
    assert first.kind == "contract"
    assert first.summary == "目标：支持结构化需求查看；要求 2 条；边界 1 条"
    assert first.files == []
    assert first.content_hash
    flow_prd_events = {record.event_id for record in flow.records if record.kind == "PRD 新版本"}
    assert first.spec_event_id in flow_prd_events

    prd = first.prd
    assert prd is not None
    assert prd.spec_revision == 1
    assert prd.spec_status == "active"
    assert prd.spec_event_id == first.spec_event_id
    assert prd.input_version == 1
    assert [item.text for item in prd.accepted_inputs] == ["展示完整 PRD 各节"]
    assert prd.goal == "支持结构化需求查看"
    assert prd.non_goals == ["不修改导出格式"]
    assert prd.boundaries == ["仅限当前事项查询与面板"]
    assert prd.constraints == ["保持已有合同字段兼容"]
    assert prd.requirements == ["展示所有 PRD 分节", "标注尚未匹配验收条件的需求"]
    assert prd.acceptance_criteria == ["面板展示完整 PRD 分节"]
    assert len(prd.requirement_mapping) == 2
    assert prd.requirement_mapping[0].criteria == ["AC1"]
    assert prd.requirement_mapping[1].gap is not None
    assert prd.fatal_conditions == ["遗漏验收条件列表"]
    assert prd.decisions == []
    assert prd.decision_changes == []
    assert prd.change_record is None

    # 补充一次产品决定：合同升版，完整结构化 PRD 带有生效中的产品决定
    system.add_guidance(run_id, "product", "请明确兼容决定")
    system.activate_once(run_id)
    materials_after = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id)).data
    assert [entry.status for entry in materials_after.contracts] == ["superseded", "active"]
    decided = materials_after.contracts[1]
    assert decided.revision == 2
    assert decided.prd is not None
    assert decided.prd.spec_revision == 1
    assert [d.statement for d in decided.prd.decisions] == ["所有版本字段全部向后兼容。"]
    assert decided.prd.decisions[0].rationale == "既有客户端依赖既有字段继续读取。"


def test_work_item_materials_returns_revision_change_record_and_keeps_delivery_prd_empty(tmp_path):
    # R2：多版本 PRD 修订在 work_item.materials 中保留各自完整结构化各节与 change_record，
    # 工程交付条目不附带 prd 结构
    adapter = FakeAdapter({
        "product": [product_spec(goal="初始目标", requirements=["输出第一版"])],
        "engineering": [
            ask_turn(recipient="product", question="是否需要保留旧字段？"),
            delivery_turn(files={"src/app.py": "print('ok')\n"}),
        ],
        "product:ask": [
            answer_turn(
                answer="保留旧字段并补充新节。",
                goal="修订后目标",
                requirements=["输出第一版", "补充结构化分节"],
                acceptance=["第一版仍可用", "新分节可读"],
                change_record={
                    "changed": ["修订后目标", "补充结构化分节"],
                    "retained": ["输出第一版"],
                    "retired": [],
                    "rationale": "回应工程提问并补充新分节。",
                },
            ),
        ],
        "quality": quality_turns("release", "checks passed"),
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    project_id = system.projects.register("多版本PRD", "先立初版再按询问修订")
    work_item_id, run_id = system.projects.start_work_item(project_id, "完成两版 PRD 后交付")
    application = Application(system)

    for _ in range(10):
        materials = application.query("work_item.materials", WorkItemMaterials(
            project_id=project_id, work_item=work_item_id)).data
        if len(materials.contracts) >= 2 and len(materials.deliveries) >= 1:
            break
        system.activate_once(run_id)

    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id)).data
    flow = application.query("project.flow", ProjectFlow(
        project_id=project_id, work_item=work_item_id)).data
    flow_prd_events = {record.event_id for record in flow.records if record.kind == "PRD 新版本"}

    assert [entry.status for entry in materials.contracts] == ["superseded", "active"]
    v1, v2 = materials.contracts
    assert v1.prd is not None and v2.prd is not None
    assert v1.prd.spec_status == "superseded"
    assert v2.prd.spec_status == "active"
    assert v2.prd.spec_revision == 2
    assert v2.prd.parent_hash == v1.prd.spec_hash
    assert v1.spec_event_id in flow_prd_events and v2.spec_event_id in flow_prd_events
    assert v1.spec_event_id != v2.spec_event_id
    assert v2.prd.goal == "修订后目标"
    assert v2.prd.change_record is not None
    assert v2.prd.change_record.changed == ["修订后目标", "补充结构化分节"]
    assert v2.prd.change_record.retained == ["输出第一版"]
    assert v2.prd.change_record.rationale == "回应工程提问并补充新分节。"

    assert len(materials.deliveries) == 1
    assert materials.deliveries[0].prd is None
    assert materials.deliveries[0].files == ["src/app.py"]



