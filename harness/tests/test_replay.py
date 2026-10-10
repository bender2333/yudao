import pytest

from harness.projection import replay_events
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_decision, product_spec, response_turn, review_turn
from harness.tests.helpers import happy_script, run_scripted, system_on_copy

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次运行并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上检查重放。数据来自真实运行，登记为集成层。

COLLABORATION_SCRIPT = [
    product_spec(),
    collaboration_request(request_type="action", action="revise_requirements"),
    product_decision("Dash-prefixed input is ordinary text.", "The CLI echoes arbitrary input."),
    response_turn("completed", "Published the required flag behavior.", result_types=["product_decision_accepted"]),
    plan_turn(),
    delivery_turn(summary="v1"),
    review_turn("rework_engineering", "need a fix", defects=[{"severity": "minor", "summary": "naming"}]),
    plan_turn(reason="Address the quality naming defect"),
    delivery_turn(summary="v2", files={"src/echo.py": "print('v2')\n"}),
    review_turn("release", "ok"),
]


def _saved_run(directory, script, **kwargs):
    system, projection = run_scripted(directory, script, **kwargs)
    system.close()
    return system.data_dir, projection.run_id


@pytest.fixture(scope="module")
def saved_happy(tmp_path_factory):
    return _saved_run(tmp_path_factory.mktemp("happy"), happy_script())


@pytest.fixture
def happy_run(saved_happy, tmp_path):
    saved, run_id = saved_happy
    return system_on_copy(saved, tmp_path / "happy"), run_id


@pytest.fixture(scope="module")
def saved_collaboration(tmp_path_factory):
    return _saved_run(tmp_path_factory.mktemp("collaboration"), COLLABORATION_SCRIPT, max_cycles=16)


@pytest.fixture
def collaboration_run(saved_collaboration, tmp_path):
    saved, run_id = saved_collaboration
    return system_on_copy(saved, tmp_path / "collaboration"), run_id


def test_replay_matches_live_projection(happy_run):
    system, run_id = happy_run
    projection = system.project(run_id)
    replayed = system.replay(run_id)
    assert replayed.canonical_state() == projection.canonical_state()
    events = system.store.list_events(run_id)
    folded = replay_events(events)
    assert folded.canonical_state() == projection.canonical_state()
    assert folded.product_spec.content_hash == projection.product_spec.content_hash
    assert folded.delivery_spec.code_tree_digest == projection.delivery_spec.code_tree_digest
    assert folded.last_review.verdict == "release"


def test_replay_survives_collaboration_and_rework(collaboration_run):
    system, run_id = collaboration_run
    projection = system.project(run_id)
    replayed = system.replay(run_id)
    assert replayed.canonical_state() == projection.canonical_state()
    assert replayed.request_count == 1
    assert replayed.rework_count == 1
    assert replayed.phase == "DONE"
    assert len(replayed.effective_decisions) == 1
    assert replayed.effective_decisions[0].statement == "Dash-prefixed input is ordinary text."
    assert replayed.effective_decisions[0].rationale == "The CLI echoes arbitrary input."
    assert replayed.effective_decisions[0].request_id == replayed.requests[0].id
    assert replayed.responses[0].result_event_ids == [replayed.effective_decisions[0].created_event_id]
    assert [item.status for item in replayed.delivery_specs] == ["superseded", "active"]
    assert replayed.delivery_specs[0].invalidation_reason == "qa_rework_engineering"
    assert replayed.delivery_spec.summary == "v2"
