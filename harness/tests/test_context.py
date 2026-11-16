import json
import uuid

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part, prompt_parts
from harness.context import Rules
from harness.decisions import ROLE_CHOICE
from harness.definitions import DEFAULT_FORM
from harness.event_store import Command, project_stream, run_stream
from harness.models import EventType, ProjectEventType
from harness.projection import saved_decisions
from harness.proposals import answer_turn, ask_turn, completion_turn, delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import FORM_REGISTRY, LoopSystem, SEVERAL_ROLES_DIRECT
from harness.tests.helpers import developer_text, explore_turn, quality_turns, recorded_context
from harness.write_path import NewEvent, NewProjectEvent

def _part(call, source: str):
    text = prompt_part(call, source)
    return None if text is None else json.loads(text)

def _sources(call) -> list[str]:
    return list(prompt_parts(call))

def test_context_is_reassembled_from_projection_not_transcript(data_dir):
    marker = "PRODUCT_PRIVATE_MARKER_DO_NOT_LEAK"
    adapter = FakeAdapter(
        {
            "product": [FakeTurn(proposal=product_spec(), transcript=marker)],
            "engineering": [ask_turn(), delivery_turn()],
            "product:ask": [answer_turn("The existing contract covers this input.")],
            "quality": [explore_turn(), judgement_turn(), review_turn("release", "ok")],
        }
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"
    later = [item for item in adapter.invocations if item.department != "product"]
    assert later
    for item in later:
        assert marker not in developer_text(item)
        manifest = recorded_context(system, item).manifest
        sources = [part.source for part in manifest.injected]
        assert "other_department_transcript" not in sources
        assert "historical_transcript" not in sources
        excluded = {part.source for part in manifest.excluded}
        assert "other_department_transcript" in excluded
        assert "superseded_spec_as_current" in excluded

def test_old_spec_full_text_is_not_injected_after_supersede(data_dir):
    unique = "UNIQUE_GOAL_V1_MUST_NOT_LEAK"
    v2_answer = answer_turn(
        answer="Updated the contract.",
        goal="Build echo v2",
        requirements=["print the given argument in uppercase to stdout"],
        acceptance=["v2 works"],
        change_record={
            "changed": ["Use the v2 goal and acceptance criteria"],
            "retained": ["The echo CLI scope"],
            "retired": ["The original goal and acceptance criteria"],
            "rationale": "The requested revision replaces v1.",
        },
    )
    adapter = FakeAdapter(
        {
            "product": [product_spec(goal=unique)],
            "engineering": [ask_turn(), delivery_turn()],
            "product:ask": [v2_answer],
            "quality": quality_turns("release", "v2"),
        }
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"
    assert projection.product_spec.goal == "Build echo v2"
    engineering_after = [item for item in adapter.invocations if item.department == "engineering"][-1]
    assert unique not in developer_text(engineering_after)
    assert "Build echo v2" in developer_text(engineering_after)
    injected = [part.source for part in recorded_context(system, engineering_after).manifest.injected]
    assert injected.count("current_product_spec") == 1


def test_superseded_delivery_is_not_injected_as_current(data_dir):
    # 工程发现要求说得不清楚，询问产品，产品在回答里修订 PRD（工单 #555）：
    # 旧交付被取代以后不再当作当前交付注入
    adapter = FakeAdapter(
        {
            "product": [product_spec(acceptance=["old behavior"])],
            "engineering": [
                delivery_turn(summary="OLD_DELIVERY_CANARY"),
                ask_turn(recipient="product", question="验收标准说得不清楚，请修订。"),
                delivery_turn(summary="NEW_DELIVERY_CANARY"),
            ],
            "quality": [
                explore_turn(),
                judgement_turn(),
                review_turn("rework_engineering", "the delivery misses an acceptance criterion",
                            defects=[{"severity": "major", "summary": "contract issue"}]),
                judgement_turn(),
                review_turn("release", "new delivery checked"),
            ],
            "product:ask": [answer_turn(
                answer="已按新的验收标准修订产品要求。",
                requirements=["print the given argument to stdout"],
                acceptance=["new behavior"],
                change_record={
                    "changed": ["Replace old behavior with new behavior"], "retained": ["The echo CLI scope"],
                    "retired": ["The old behavior acceptance criterion"], "rationale": "Address the quality contract defect.",
                })],
        }
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"
    assert [item.status for item in projection.delivery_specs] == ["superseded", "active"]
    assert projection.delivery_specs[0].invalidation_reason in {"qa_rework_engineering", "product_spec_changed"}
    assert projection.delivery_spec is not None
    assert projection.delivery_spec.summary == "NEW_DELIVERY_CANARY"
    assert projection.delivery_spec.status == "active"
    assert sum(1 for item in projection.delivery_specs if item.status == "active") == 1

    engineering_after_r2 = [
        item
        for item in adapter.invocations
        if item.department == "engineering" and "new behavior" in developer_text(item)
    ][0]
    assert _part(engineering_after_r2, "current_delivery_spec") is None
    prior = _part(engineering_after_r2, "prior_delivery")
    assert prior is not None
    assert prior["summary"] == "OLD_DELIVERY_CANARY"
    assert prior["status"] == "superseded"
    assert prior["purpose"] == "repair_basis"
    assert prior["invalidation_reason"]
    assert "current_delivery_spec" not in _sources(engineering_after_r2)
    excluded = {item.source for item in recorded_context(system, engineering_after_r2).manifest.excluded}
    assert "invalid_delivery_as_current" in excluded

    quality_calls = [item for item in adapter.invocations if item.department == "quality"]
    before_judgement = quality_calls[-2]
    current = _part(before_judgement, "current_delivery_spec")
    assert current is not None
    # 事实部分总在；解释部分（summary）在质检提交独立判断以前不给（工单 #554；#358：先判断后看解释，
    # 判断提交以后的请求才并入解释——这里的最后一次调用是判断以后的核验请求，解释已经在里面）
    assert current["content_hash"] == projection.delivery_spec.content_hash
    assert current["content_hash"] != projection.delivery_specs[0].content_hash
    assert "summary" not in current
    assert current["status"] == "active"
    assert _part(before_judgement, "prior_delivery") is None
    after_judgement = _part(quality_calls[-1], "current_delivery_spec")
    assert after_judgement is not None and "summary" in after_judgement


def test_each_assembled_request_records_the_rule_version_and_the_folded_rounds(data_dir):
    # 守 R2（合同）：每一步的上下文清单记下这一次按哪一版规则算出来的、折叠了哪几轮，
    # 重放时按同一份规则版本复原。规则全关时没有折叠任何一轮；模型的请求体（model_request 工件）
    # 仍然只有发给模型的那几部分，所以「同一份事件同一版规则装配两次逐字节相同」比的始终是同一份字节
    adapter = FakeAdapter({"product": [product_spec()]})
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    events = [event for event in system.store.list_events(run_id)
              if event.type == EventType.CONTEXT_ASSEMBLED]
    assert events
    for event in events:
        payload = event.payload
        assert payload["rules_version"] == Rules().version()
        assert payload["folded_rounds"] == []
        request = json.loads(system.artifacts.get_text(payload["request_ref"]["content_hash"]))
        assert set(request) <= {"input", "tools", "max_output_tokens"}
        # 部门材料那一条在请求的首位（docs/design/context-assembly.md「确定性（通过）」「材料恒在首位」）
        assert request["input"][0]["role"] == "developer"


def _sample_role_choice_questions(prefix: str) -> list[dict[str, object]]:
    return [
        {
            "id": f"{prefix}_fmt",
            "question": f"{prefix}: 优先支持哪种输出格式？",
            "options": [
                {"id": "json", "label": "JSON 结构输出"},
                {"id": "text", "label": "纯文本行输出"},
            ],
            "recommended": "json",
            "rationale": "便于脚本稳定解析",
        },
        {
            "id": f"{prefix}_dest",
            "question": f"{prefix}: 默认写往哪里？",
            "options": [
                {"id": "stdout", "label": "标准输出"},
                {"id": "file", "label": "独立文件"},
            ],
            "recommended": "stdout",
            "rationale": "默认符合命令行习惯",
        },
    ]


def _append_role_choice(system: LoopSystem, run_id: str, *, department: str, prefix: str,
                        input_version: int = 1, round_number: int = 1) -> str:
    before_ids = {item.decision_id for item in saved_decisions(system.store, statuses=("open",))[1]}
    questions = _sample_role_choice_questions(prefix)
    system.writes.transact(
        run_stream(run_id),
        lambda tx: tx.append(
            NewEvent(
                EventType.DECISION_REQUESTED,
                actor="system",
                department=department,
                state_before=tx.projection.status,
                state_after=tx.projection.status,
                payload={
                    "kind": ROLE_CHOICE.name,
                    "blocks": "round",
                    "options": [{"id": opt.id, "label": opt.label} for opt in ROLE_CHOICE.options],
                    "description": f"{department} 前沿分叉问题",
                    "facts": [],
                    "department": department,
                    "questions": questions,
                    "input_version": input_version,
                    "round": round_number,
                },
            )
        ),
    )
    created = [
        item for item in saved_decisions(system.store, statuses=("open",))[1]
        if item.run_id == run_id and item.decision_id not in before_ids
    ]
    assert len(created) == 1
    return created[0].decision_id


def test_user_decisions_shared_across_roles_ask_branches_and_judgement_ordered_by_answer_time(data_dir):
    # 守 R1（共享需求事实）与 R2（上下文段落契约）：已回答的 role_choice 决定按回答时间顺序进入
    # 全部职能主线、ask 询问分支与核验角色独立判断前后的只读 user_decisions 段落，同时保持 intend 原文不变；
    # 尚无已回答决定（或仅存在未答请求）时不注入空壳段落，并在 manifest.excluded 中记录原因。
    empty_adapter = FakeAdapter({"product": [product_spec()]})
    empty_system = LoopSystem.for_testing(data_dir / "empty", empty_adapter)
    empty_task = "保持原始意图的 echo 任务"
    empty_run = empty_system.create_run(empty_task)
    _append_role_choice(empty_system, empty_run, department="product", prefix="pending")
    empty_system.activate_once(empty_run)
    empty_call = empty_adapter.invocations[0]
    assert prompt_part(empty_call, "intend") == empty_task
    assert "user_decisions" not in _sources(empty_call)
    empty_manifest = recorded_context(empty_system, empty_call).manifest
    assert "user_decisions" in {item.source for item in empty_manifest.excluded}

    canary = "DELIVERY_EXPLANATION_CANARY_SHOULD_NOT_LEAK"
    original_task = "build echo CLI   with exact spacing\nand line breaks"
    adapter = FakeAdapter(
        {
            "product": [product_spec()],
            "engineering": [ask_turn(recipient="product", question="确认命令行输出边界。"), delivery_turn(summary=canary)],
            "product:ask": [answer_turn("按照已回答用户决定实现。")],
            "quality": [explore_turn(), judgement_turn(), review_turn("release", "ok")],
        }
    )
    system = LoopSystem.for_testing(data_dir / "answered", adapter)
    run_id = system.create_run(original_task)
    d1_id = _append_role_choice(system, run_id, department="product", prefix="p1", input_version=1, round_number=1)
    d2_id = _append_role_choice(system, run_id, department="engineering", prefix="e1", input_version=1, round_number=1)
    d3_open_id = _append_role_choice(system, run_id, department="product", prefix="p_open", input_version=1, round_number=2)

    # 先回答较后创建的 d2（全采用推荐），再回答较早创建的 d1（部分题号提交，未答题目按推荐补齐），d3 保持未答
    d2 = next(item for item in saved_decisions(system.store, statuses=("open",))[1] if item.decision_id == d2_id)
    system.orchestrator.answer_decision(
        d2.decision_id,
        "recommended",
        "先采用工程确认的推荐项",
        base_version=d2.version,
        command=Command(str(uuid.uuid4()), "decision.answer", f"sha256:recommended:{d2.version}", "user:local"),
    )
    d1 = next(item for item in saved_decisions(system.store, statuses=("open",))[1] if item.decision_id == d1_id)
    system.orchestrator.answer_decision(
        d1.decision_id,
        "submit",
        "输出需兼容纯文本管道",
        base_version=d1.version,
        answers={"p1_fmt": "text"},
        command=Command(str(uuid.uuid4()), "decision.answer", f"sha256:submit:{d1.version}", "user:local"),
    )

    system.run_until_stop(run_id)
    assert system.project(run_id).status == "done"

    product_call = next(c for c in adapter.invocations if c.department == "product" and not c.session_id.startswith("ses_ask_"))
    eng_call = next(c for c in adapter.invocations if c.department == "engineering" and not c.session_id.startswith("ses_ask_"))
    ask_call = next(c for c in adapter.invocations if c.department == "product" and c.session_id.startswith("ses_ask_"))
    quality_calls = [c for c in adapter.invocations if c.department == "quality"]
    assert len(quality_calls) >= 3
    qa_before_judgement = quality_calls[1]
    qa_after_judgement = quality_calls[-1]

    assert canary not in developer_text(qa_before_judgement)
    assert canary in developer_text(qa_after_judgement)

    for call in (product_call, eng_call, ask_call, qa_before_judgement, qa_after_judgement):
        assert prompt_part(call, "intend") == original_task
        manifest = recorded_context(system, call).manifest
        assert "user_decisions" in {item.source for item in manifest.injected}
        assert "user_decisions" not in {item.source for item in manifest.excluded}
        ud = _part(call, "user_decisions")
        assert isinstance(ud, list) and [item["decision_id"] for item in ud] == [d2_id, d1_id]
        assert all(item["decision_id"] != d3_open_id for item in ud)

        first, second = ud
        assert first["department"] == "engineering"
        assert first["input_version"] == 1
        assert first["note"] == "先采用工程确认的推荐项"
        assert first["answers"] == [
            {
                "id": "e1_fmt",
                "question": "e1: 优先支持哪种输出格式？",
                "selected_option_id": "json",
                "selected_option_label": "JSON 结构输出",
            },
            {
                "id": "e1_dest",
                "question": "e1: 默认写往哪里？",
                "selected_option_id": "stdout",
                "selected_option_label": "标准输出",
            },
        ]
        assert second["department"] == "product"
        assert second["input_version"] == 1
        assert second["note"] == "输出需兼容纯文本管道"
        assert second["answers"] == [
            {
                "id": "p1_fmt",
                "question": "p1: 优先支持哪种输出格式？",
                "selected_option_id": "text",
                "selected_option_label": "纯文本行输出",
            },
            {
                "id": "p1_dest",
                "question": "p1: 默认写往哪里？",
                "selected_option_id": "stdout",
                "selected_option_label": "标准输出",
            },
        ]


def test_user_decisions_shared_in_direct_form_and_preserves_intend(data_dir):
    # 守 R1 与 R2（直做形态装配边界）：直做形态主线入口角色与 ask 询问分支同样接收只读 user_decisions 且保持 intend 原文不变
    original_task = "直接实现 echo 工具"
    adapter = FakeAdapter(
        {
            "engineering": [ask_turn(recipient="product", question="边界由谁承担？"), completion_turn("done")],
            "product:ask": [answer_turn("由调用方传参，按已回答决定。")],
        }
    )
    system = LoopSystem.for_testing(data_dir / "direct", adapter, forms=FORM_REGISTRY, resume_on_startup=False)
    project_id = system.projects.register("直做共享用户决定", "goal")
    system.writes.append(
        project_stream(project_id),
        NewProjectEvent(
            ProjectEventType.PROJECT_FORM_SET,
            {"previous_form": DEFAULT_FORM, "form": SEVERAL_ROLES_DIRECT, "reason": ""},
            actor="user:local",
        ),
    )
    _work_item_id, run_id = system.projects.start_work_item(project_id, original_task)
    dec_id = _append_role_choice(system, run_id, department="engineering", prefix="d")
    dec = next(item for item in saved_decisions(system.store, statuses=("open",))[1] if item.decision_id == dec_id)
    system.orchestrator.answer_decision(
        dec.decision_id,
        "submit",
        "直做备注",
        base_version=dec.version,
        answers={"d_fmt": "text", "d_dest": "file"},
        command=Command(str(uuid.uuid4()), "decision.answer", f"sha256:submit:{dec.version}", "user:local"),
    )

    system.run_until_stop(run_id)
    eng_call = next(c for c in adapter.invocations if c.department == "engineering" and not c.session_id.startswith("ses_ask_"))
    ask_call = next(c for c in adapter.invocations if c.department == "product" and c.session_id.startswith("ses_ask_"))
    for call in (eng_call, ask_call):
        assert prompt_part(call, "intend") == original_task
        ud = _part(call, "user_decisions")
        assert len(ud) == 1
        assert ud[0]["decision_id"] == dec_id
        assert ud[0]["department"] == "engineering"
        assert ud[0]["note"] == "直做备注"
        assert ud[0]["answers"][0]["selected_option_label"] == "纯文本行输出"
        assert ud[0]["answers"][1]["selected_option_label"] == "独立文件"



