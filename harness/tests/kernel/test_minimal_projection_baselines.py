# 最小投影与运行状态投影逐项一致（骨架与应用设计说明第 4 节，工单 #824 的验收第一条）：
# 对 harness/tests/event_sequences/ 下的每一份基准，把那个场景重跑一遍，从它的事件重算出最小投影，
# 再与 RunProjection 里对应的值逐项比较。守 R1（第三环的不变式：同样的事件重放出同样的状态）：
# 两份投影折的是同一组事件，对应项的结论必须相同。
#
# 全部基准上逐项一致，没有例外：当前交付的失效也由事件给出（工单 #858 的 S1b：成果失效事件
# artifact_invalidated），两份投影都只按那条事件折叠，不再从工具调用、PRD 与合同被接纳、返工结论推出。
# 其余各项同样要一致，包括契约（contract_accepted）算的一种成果、工件引用与已用量。

import pytest

from harness.event_store import run_stream
from harness.minimal_projection import fold_events
from harness.models import EventType
from harness.projection import replay_decisions
from harness.tests.event_scenarios import SCENARIOS
from harness.tests.event_sequence import BASELINE_DIR

BASELINES = sorted(path.stem for path in BASELINE_DIR.glob("*.json"))


@pytest.mark.parametrize("name", BASELINES)
def test_the_minimal_projection_matches_the_run_projection(name, data_dir):
    scenario = SCENARIOS[name]
    system, run_id, _replacements = scenario.run(data_dir)
    events = system.store.list_events(run_id)
    state = system.project(run_id)
    projection = fold_events(events)

    assert projection.run_id == state.run_id, name
    assert projection.project_id == state.project_id, name
    assert projection.work_item_id == state.work_item_id, name
    assert projection.work_item_kind == state.kind, name
    assert projection.status == state.status, name
    assert projection.stop_reason == state.stop_reason, name
    assert projection.definitions_version == state.definitions_version, name
    assert projection.parameters_version == state.parameters_version, name
    assert projection.max_cycles == state.max_cycles, name
    assert projection.run_time_limit_sec == state.run_time_limit_sec, name

    # 每条流的当前版本：这次重放只有一条 run 流
    assert projection.stream_versions == {run_stream(run_id): state.stream_version}, name

    # 已用的时间、激活次数与模型步数，事项一级
    assert projection.used.activations == state.cycle_count, name
    assert projection.used.model_steps == len(state.model_requests), name
    settled = [int((event.payload or {}).get("elapsed_ms") or 0)
               for event in events if event.type == EventType.ACTIVATION_FINISHED]
    assert projection.used.settled_ms == (max(settled) if settled else 0), name

    # 会话一级：激活次数、模型步数、已用时间与当前这一轮的编号
    activations = _count_by_session(events, EventType.DEPARTMENT_ACTIVATED)
    requests = _request_counts_by_session(events, state.model_requests)
    finished = _session_settled_ms(events)
    assert _session_values(projection, activations, "activations") == activations, name
    assert _session_values(projection, requests, "model_steps") == requests, name
    assert _session_values(projection, finished, "settled_ms") == finished, name
    rounds = {department: projection.sessions[record.session_id].round_id
              for department, record in state.sessions.items()}
    assert {department: value for department, value in rounds.items() if value} == state.last_activations, name

    # 待回答的决定请求：与决定请求的投影里还没有回答的那些相同
    pending = tuple(decision.decision_id for decision in replay_decisions(events).values()
                    if decision.status == "open")
    assert projection.pending_decisions == pending, name

    # 每种正式成果的当前版本与工件引用
    # 2026-10-27 补的字段（S1d，工单 #860）：作者部门与记下的树摘要，与运行状态投影里这些成果的字段一致
    assert _issuers(projection) == _expected_issuers(state), name
    assert _trees(projection) == _expected_trees(state), name
    # 按部门的本轮编号：主线会话这一轮的编号与运行状态投影记下的最近激活相同
    assert {department: value for department, value in projection.rounds.items() if value} == state.last_activations, name
    # 多版并存的清单：产品决定按接纳顺序都在清单里，单版的种类只有当前这一版
    assert [item.content_hash for item in projection.versions_of("product_decision")] == [
        item.content_hash for item in state.product_decisions], name
    for kind, items in projection.versions.items():
        if kind != "product_decision":
            assert [item.content_hash for item in items] == [projection.artifacts[kind].content_hash], name

    spec = state.product_spec
    _the_artifact_is(projection, "product_spec", spec and (spec.revision, spec.content_hash), name)
    contract = state.effective_contract
    _the_artifact_is(projection, "contract", contract and (contract.revision, contract.content_hash),
                     name, ref=contract and contract.prd_ref.content_hash)
    review = state.last_review
    _the_artifact_is(projection, "qa_review", review and (review.revision, review.content_hash), name,
                     ref=review and review.evidence_refs and review.evidence_refs[0].content_hash)
    structure = state.structure
    _the_artifact_is(projection, "structure",
                     structure and (structure["revision"], structure["content_hash"]), name,
                     ref=structure and structure["structure_ref"]["content_hash"])
    baseline = state.baseline_review
    _the_artifact_is(projection, "baseline_review",
                     baseline and (baseline["revision"], baseline["content_hash"]), name)
    decision = state.product_decisions[-1] if state.product_decisions else None
    _the_artifact_is(projection, "product_decision", decision and (1, decision.content_hash), name)
    # 当前交付：失效也是一条事件（成果失效，S1b），没有当前交付时最小投影里也没有它
    delivery = state.delivery_spec
    _the_artifact_is(projection, "delivery_spec",
                     delivery and (delivery.revision, delivery.content_hash), name,
                     ref=delivery and delivery.tree_ref.content_hash)
    # 事项创建事件里记下的代码树快照（S1d，工单 #860）：它不是运行状态投影里的一种成果，
    # 只提供通用条件 4 要的树摘要，这里单独核对以后从对照清单里取掉
    snapshot = state.snapshot
    if isinstance(snapshot, dict) and snapshot.get("tree_digest"):
        assert projection.artifacts.pop("snapshot", None) is not None, f"{name}: 快照没有折进最小投影"
    else:
        assert "snapshot" not in projection.artifacts, f"{name}: 最小投影里多出快照"
    # 每一种成果都有对应的运行状态项，没有多出来的
    assert projection.artifacts == {}, f"{name}: 最小投影里多出没有对照的成果 {sorted(projection.artifacts)}"


def _issuers(projection) -> dict[str, str | None]:
    # 最小投影里每种成果的作者部门
    return {kind: artifact.issuer for kind, artifact in projection.artifacts.items()}


def _expected_issuers(state) -> dict[str, str | None]:
    # 运行状态投影里这些成果各自的作者部门：接纳事件的统一字段与它们同一个来源
    expected: dict[str, str | None] = {}
    for kind, value in (("product_spec", state.product_spec), ("delivery_spec", state.delivery_spec),
                        ("qa_review", state.last_review), ("structure", state.structure),
                        ("baseline_review", state.baseline_review)):
        if value is not None:
            expected[kind] = value["issuer"] if isinstance(value, dict) else value.issuer
    if state.effective_contract is not None:
        # 合同由主机签发，没有作者部门这一项
        expected["contract"] = None
    return expected


def _trees(projection) -> dict[str, str | None]:
    # 最小投影里每种成果记下的树摘要
    return {kind: artifact.tree_digest for kind, artifact in projection.artifacts.items()}


def _expected_trees(state) -> dict[str, str | None]:
    # 运行状态投影里这些成果记下的树摘要：交付记代码树、建档记快照的树，其余为空
    expected: dict[str, str | None] = {}
    if state.product_spec is not None:
        expected["product_spec"] = None
    if state.effective_contract is not None:
        expected["contract"] = None
    if state.delivery_spec is not None:
        expected["delivery_spec"] = state.delivery_spec.code_tree_digest
    if state.last_review is not None:
        expected["qa_review"] = state.last_review.code_snapshot_hash
    if state.structure is not None:
        expected["structure"] = state.structure["code_tree_digest"]
    if state.baseline_review is not None:
        expected["baseline_review"] = state.baseline_review["code_snapshot_hash"]
    if isinstance(state.snapshot, dict) and state.snapshot.get("tree_digest"):
        expected["snapshot"] = state.snapshot["tree_digest"]
    return expected


def _the_artifact_is(projection, kind, expected, name, *, ref=None):
    # 最小投影里的一种成果：运行状态投影里没有这一种时（这个场景没接纳过它），最小投影里也不该有
    version, content_hash = expected if expected else (None, None)
    artifact = projection.artifacts.pop(kind, None)
    if content_hash is None:
        assert artifact is None, f"{name}: {kind} 在运行状态投影里没有，最小投影里却有 {artifact}"
        return
    assert artifact is not None, f"{name}: 运行状态投影有 {kind}，最小投影里没有"
    assert artifact.version == version, f"{name}: {kind} 的版本 {artifact.version} != {version}"
    assert artifact.content_hash == content_hash, f"{name}: {kind} 的内容摘要不同"
    if ref is not None:
        assert artifact.ref is not None, f"{name}: {kind} 没有工件引用"
        assert artifact.ref.get("content_hash") == ref, f"{name}: {kind} 的工件引用不同"


def _session_values(projection, expected, field):
    # 只比有这件事的会话：没有激活的会话在最小投影里也有一个位置，已用量为零
    return {session: getattr(projection.sessions[session], field) for session in expected}


def _count_by_session(events, event_type):
    counts = {}
    for event in events:
        if event.type == event_type:
            counts[event.session_id or ""] = counts.get(event.session_id or "", 0) + 1
    return counts


def _request_counts_by_session(events, model_requests):
    # 模型请求没有会话列：按它所属的激活找到会话（每一轮工作的开始事件记着两者）
    session_of_activation = {}
    for event in events:
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            activation_id = (event.payload or {}).get("activation_id")
            if activation_id:
                session_of_activation[activation_id] = event.session_id or ""
    counts = {}
    for request in model_requests:
        session = session_of_activation.get(request.get("activation_id"), "")
        counts[session] = counts.get(session, 0) + 1
    return counts


def _session_settled_ms(events):
    # 会话的已用时间是一轮工作结束时写下的累计值：取这个会话最后一次结算的值
    settled = {}
    for event in events:
        if event.type == EventType.ACTIVATION_FINISHED:
            session = event.session_id or ""
            settled[session] = max(settled.get(session, 0), int((event.payload or {}).get("session_elapsed_ms") or 0))
    return settled
