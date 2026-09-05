from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.context import ContextAssembler
from harness.models import RunProjection, SessionRecord
from harness.proposals import ask_request, delivery_turn, product_spec, reaction, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, run_scripted


def test_context_is_reassembled_from_projection_not_transcript(data_dir):
    marker = "PRODUCT_PRIVATE_MARKER_DO_NOT_LEAK"
    adapter = FakeAdapter(
        [
            FakeTurn(proposal=product_spec(), transcript=marker),
            ask_request(),
            reaction("accept", "keep the current spec"),
            delivery_turn(),
            review_turn("release", "ok"),
        ]
    )
    system = LoopSystem(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    later = [item for item in adapter.invocations if item.department != "product"]
    assert later
    for item in later:
        assert marker not in item.context.prompt_text
        sources = [part.source for part in item.context.manifest.injected]
        assert "other_department_transcript" not in sources
        assert "historical_transcript" not in sources
        excluded = {part.source for part in item.context.manifest.excluded}
        assert "other_department_transcript" in excluded
        assert "superseded_spec_fulltext" in excluded


def test_old_spec_full_text_is_not_injected_after_supersede(data_dir):
    unique = "UNIQUE_GOAL_V1_MUST_NOT_LEAK"
    v2 = product_spec(goal="Build echo v2", acceptance=["v2 works"])
    adapter = FakeAdapter(
        [
            product_spec(goal=unique),
            ask_request(),
            reaction("reply", "update the contract", spec_update=v2),
            delivery_turn(),
            review_turn("release", "v2"),
        ]
    )
    system = LoopSystem(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    assert projection.product_spec.goal == "Build echo v2"
    engineering_after = [item for item in adapter.invocations if item.department == "engineering"][-1]
    assert unique not in engineering_after.context.prompt_text
    assert "Build echo v2" in engineering_after.context.prompt_text
    injected = [part.source for part in engineering_after.context.manifest.injected]
    assert injected.count("current_product_spec") == 1


def test_each_department_has_its_own_session(data_dir):
    _, projection = run_scripted(data_dir, happy_script())
    sessions = projection.sessions
    assert set(sessions) == {"product", "engineering", "quality"}
    ids = {item.session_id for item in sessions.values()}
    assert len(ids) == 3
    assert sessions["product"].activations >= 1
    assert sessions["engineering"].activations >= 1
    assert sessions["quality"].activations >= 1


def test_product_and_quality_do_not_receive_write_tools(data_dir):
    adapter = FakeAdapter(happy_script())
    system = LoopSystem(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)
    by_dept = {item.department: item.tools for item in adapter.invocations}
    assert "write_file" not in by_dept["product"]
    assert "write_file" in by_dept["engineering"]
    assert "write_file" not in by_dept["quality"]


def test_proposal_contract_and_binding_refs_are_injected(data_dir):
    adapter = FakeAdapter(happy_script())
    system = LoopSystem(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)
    for item in adapter.invocations:
        sources = [part.source for part in item.context.manifest.injected]
        assert "proposal_contract" in sources
        assert "binding_refs" in sources
        assert "proposal_contract" in item.context.prompt_text
        excluded = {part.source for part in item.context.manifest.excluded}
        assert "omp_autodiscovery" in excluded
        assert "internal JSON 实现协议" not in item.context.prompt_text


def test_validation_feedback_is_injected_after_rejection(data_dir):
    adapter = FakeAdapter(
        [
            {"kind": "product_spec", "goal": "", "requirements": ["r"], "acceptance_criteria": ["a"]},
            product_spec(),
            delivery_turn(),
            review_turn("release", "ok"),
        ]
    )
    system = LoopSystem(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)
    product_calls = [item for item in adapter.invocations if item.department == "product"]
    assert len(product_calls) >= 2
    assert "validation_feedback" in product_calls[1].context.prompt_text
    assert "goal" in product_calls[1].context.prompt_text


def test_assembler_records_budget_and_digest():
    projection = RunProjection(
        run_id="run_x",
        task="task",
        phase="ENGINEERING",
        token_budget=1000,
        context_window=8000,
        sessions={"engineering": SessionRecord("ses_e", "engineering", "active")},
    )
    assembled = ContextAssembler().assemble(projection, department="engineering", session_id="ses_e", activation_id="act_1")
    assert assembled.manifest.budget == 8000
    assert assembled.manifest.digest.startswith("sha256:")
    assert assembled.manifest.token_estimate > 0
    assert any(item.source == "department_rules" for item in assembled.manifest.injected)
