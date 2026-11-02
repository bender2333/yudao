import pytest

from harness.adapters.fake import prompt_part
from harness.projection import replay_events
from harness.proposals import answer_turn, ask_turn, delivery_turn, judgement_turn, product_spec, review_turn
from harness.tests.helpers import happy_script, run_scripted, system_on_copy

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次运行并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上检查重放。数据来自真实运行，登记为集成层。

_ASK_STATE = {"defect_recorded": False, "judged": None}


def _ask_quality_turn(call):
    # 质检的每一轮按当前有没有交付决定做什么（工单 #557：同时运行的会话轮数随交付到达变化）：
    # 没有交付时提交结论被拒绝；有交付时先交独立判断（工单 #358），再记下缺陷记录，
    # 返工以后的交付核验通过以后放行
    delivery = prompt_part(call, "current_delivery_spec")
    if not delivery:
        return review_turn("rework_engineering", "need a fix",
                           defects=[{"severity": "minor", "summary": "naming"}])(call)
    import json

    delivery_hash = json.loads(delivery).get("content_hash")
    if _ASK_STATE["judged"] != delivery_hash:
        _ASK_STATE["judged"] = delivery_hash
        return judgement_turn()(call)
    if not _ASK_STATE["defect_recorded"]:
        _ASK_STATE["defect_recorded"] = True
        return review_turn("rework_engineering", "need a fix",
                           defects=[{"severity": "minor", "summary": "naming"}])(call)
    return review_turn("release", "ok")(call)


ASK_SCRIPT = {
    "product": [product_spec()],
    "engineering": [
        ask_turn("product", "Should dash-prefixed input be supported?"),
        delivery_turn(summary="v1"),
        delivery_turn(summary="v2", files={"src/echo.py": "print('v2')\n"}),
    ],
    "product:ask": [
        answer_turn(
            "Dash-prefixed input is ordinary text.",
            requirements=["print the given argument to stdout", "dash-prefixed input is ordinary text"],
            acceptance=["prints -flag verbatim"],
            change_record={
                "changed": ["Clarify dash-prefixed input is ordinary text"],
                "retained": ["The echo CLI scope"],
                "retired": [],
                "rationale": "The CLI echoes arbitrary input.",
            },
        ),
    ],
    "quality": [_ask_quality_turn, _ask_quality_turn, _ask_quality_turn, _ask_quality_turn,
                _ask_quality_turn, _ask_quality_turn],
}

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
def saved_ask(tmp_path_factory):
    return _saved_run(tmp_path_factory.mktemp("ask"), ASK_SCRIPT, max_cycles=16)

@pytest.fixture
def ask_run(saved_ask, tmp_path):
    saved, run_id = saved_ask
    return system_on_copy(saved, tmp_path / "ask"), run_id

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

def test_replay_survives_asks_and_rework(ask_run):
    system, run_id = ask_run
    projection = system.project(run_id)
    replayed = system.replay(run_id)
    assert replayed.canonical_state() == projection.canonical_state()
    assert replayed.rework_count == 1
    assert replayed.status == "done"
    assert replayed.product_spec.revision == 2
    assert [item.status for item in replayed.delivery_specs] == ["superseded", "active"]
    assert replayed.delivery_specs[0].invalidation_reason == "qa_rework_engineering"
    assert replayed.delivery_spec.summary == "v2"
