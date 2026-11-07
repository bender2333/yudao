# 最小投影的字段、默认值与边界（骨架与应用 docs/design/skeleton-and-application.md「最小投影」）：
# 直接用录好的骨架事件调用 fold_events / fold_more，检查折叠出的字段、缺字段时的默认值与边界。
# 守 R1（第三环的不变式：事实只经写入口写入、同样的事件重放出同样的状态、已用时间与次数跨重启连续）
# 与 R2（第二环的合同：接纳事件的统一字段与骨架事件带的可选字段，旧事件缺字段时按空值兼容）。
#
# 与 test_minimal_projection.py（同样直接调用模块）和 test_minimal_projection_baselines.py（集成层，
# 对事件序列基准逐项对照）分开，是因为变异检查按文件耗时分层：这一张要留在快层。

from dataclasses import FrozenInstanceError, replace

import pytest

from harness.minimal_projection import AcceptedArtifact, SessionState, UsedAmount, fold_events, fold_more
from harness.models import Event, EventType

RUN_STREAM = "run:run_824"


def _event(etype: str, version: int, *, payload: dict | None = None, session: str | None = None,
           department: str | None = None, stop_reason: str | None = None,
           state: str = "running", epoch: int | None = None) -> Event:
    # 一条 run 流的事件：位置与流内版本都按给出的顺序，时间与本次讨论无关
    return Event(
        event_id=f"evt_{version}", run_id="run_824", type=etype, role=None,
        parent_event_id=None, state_before=state, state_after=state, payload=payload or {},
        artifact_hashes=[], session_id=session, provider=None, model=None, context_digest=None,
        stop_reason=stop_reason, error=None, created_at="2026-10-27T00:00:00+00:00",
        position=version, stream=RUN_STREAM, stream_version=version,
        project_id="prj_824", work_item_id="wi_824", department=department, epoch=epoch,
    )


def _run_created(version: int = 1) -> Event:
    # 一条最小的事项创建事件：定义与参数版本、两个上限都有，没有快照与会话
    return _event(EventType.RUN_CREATED, version, payload={
        "kind": "change",
        "project_id": "prj_824",
        "work_item_id": "wi_824",
        "definitions_version": "sha256:definitions",
        "parameters_version": "sha256:parameters",
        "max_cycles": 7,
        "run_time_limit_sec": 900,
    })


def test_the_empty_projection_is_the_documented_empty_state():
    # 还没有读到事件时最小投影是设计里写的那份空事实（docs/design/skeleton-and-application.md「最小投影」）：
    # run_id 为空表示还没有 run_created，状态 running、种类 change、上限与已用量为零。
    # 期望值逐项写死，不拿同一份数据类的默认值当期望值：默认值本身也是被测的行为
    projection = fold_events([])
    assert projection.run_id == ""
    assert (projection.project_id, projection.work_item_id) == (None, None)
    assert projection.work_item_kind == "change"
    assert (projection.status, projection.stop_reason) == ("running", None)
    assert (projection.definitions_version, projection.parameters_version) == ("", "")
    assert (projection.mcp_servers_version, projection.max_cycles, projection.run_time_limit_sec) == (0, 0, 0)
    assert projection.execution_right == 0
    assert projection.stream_versions == {}
    assert projection.used == UsedAmount(settled_ms=0, activations=0, model_steps=0)
    assert projection.sessions == {}
    assert projection.artifacts == {}
    assert projection.versions == {}
    assert projection.accepted == {}
    assert projection.rounds == {}
    assert projection.pending_decisions == ()


def test_a_folded_projection_cannot_be_changed_in_place():
    # 折叠结果交给裁决以后只读（总图第二节「只由你批准」：事实只经写入口写入）：
    # 想就地改一改投影里的值，拿到的是 FrozenInstanceError，而不是悄悄改掉内存里的状态
    projection = fold_events([
        _run_created(),
        _event(EventType.DEPARTMENT_ACTIVATED, 2, session="ses_pro", department="product",
               payload={"activation_id": "act_1", "cycle": 1}, epoch=1),
        _event(EventType.SPEC_ACCEPTED, 3, session="ses_pro", department="product", payload={
            "content_hash": "sha256:spec1", "artifact_kind": "product_spec", "artifact_version": 1,
            "artifact_basis": {},
        }),
    ])
    with pytest.raises(FrozenInstanceError):
        projection.status = "done"
    with pytest.raises(FrozenInstanceError):
        projection.used.settled_ms = 1
    with pytest.raises(FrozenInstanceError):
        projection.sessions["ses_pro"].activations = 2
    with pytest.raises(FrozenInstanceError):
        projection.artifacts["product_spec"].version = 2


def test_a_session_recorded_at_creation_starts_empty_with_its_department():
    # 事项创建时记下的会话：每个部门一个主线会话，还没有激活的会话已用量为零（#857、#860）。
    # 逐项写死，不拿 SessionState() 当期望值：字段默认值本身也是被测的行为
    created = _event(EventType.RUN_CREATED, 1, payload={
        "kind": "change", "project_id": "prj_824", "work_item_id": "wi_824",
        "definitions_version": "sha256:definitions", "parameters_version": "sha256:parameters",
        "max_cycles": 7, "run_time_limit_sec": 900,
        "sessions": {"product": "ses_pro", "quality": "ses_qua"},
    })
    projection = fold_events([created])
    assert projection.sessions == {
        "ses_pro": SessionState(settled_ms=0, settled_steps=0, activations=0, model_steps=0,
                                round_id=None, department="product"),
        "ses_qua": SessionState(settled_ms=0, settled_steps=0, activations=0, model_steps=0,
                                round_id=None, department="quality"),
    }


def test_run_created_freezes_the_versions_and_the_limits_it_was_given():
    # 建 run 时冻结的定义与参数版本、MCP 服务器设置的版本与两个上限（工单 #236、#824）：
    # 最小投影只取 MCP 设置的版本，不取设置的内容；项目与事项的编号也在这条事件上
    projection = fold_events([_event(EventType.RUN_CREATED, 1, payload={
        "kind": "onboarding", "project_id": "prj_824", "work_item_id": "wi_824",
        "definitions_version": "sha256:definitions", "parameters_version": "sha256:parameters",
        "mcp_servers": {"version": 4, "servers": [{"name": "fs", "command": "npx"}]},
        "max_cycles": 7, "run_time_limit_sec": 900,
    })])
    assert projection.run_id == "run_824"
    assert (projection.project_id, projection.work_item_id, projection.work_item_kind) == (
        "prj_824", "wi_824", "onboarding")
    assert (projection.definitions_version, projection.parameters_version) == (
        "sha256:definitions", "sha256:parameters")
    assert projection.mcp_servers_version == 4
    assert (projection.max_cycles, projection.run_time_limit_sec) == (7, 900)


def test_the_optional_fields_of_run_created_fall_back_to_the_empty_values():
    # 旧事件没有 MCP 设置、也没有上限时按 0（空设置）；没有 kind 时按 change；
    # 两个版本缺失时为空串（最小投影与运行状态投影的旧事件兼容）
    projection = fold_events([_event(EventType.RUN_CREATED, 1, payload={
        "project_id": "prj_824", "work_item_id": "wi_824", "mcp_servers": {"servers": []},
    })])
    assert projection.work_item_kind == "change"
    assert (projection.definitions_version, projection.parameters_version) == ("", "")
    assert (projection.mcp_servers_version, projection.max_cycles, projection.run_time_limit_sec) == (0, 0, 0)
    assert projection.run_id == "run_824"


def test_the_run_status_events_change_the_status_and_the_stop_reason():
    # 运行状态只看事项的状态事件（docs/design/skeleton-and-application.md「最小投影」）：
    # 暂停、继续、失败、完成各给出状态与停止原因；继续以后已用量保持暂停时的值（#857）
    paused = fold_events([
        _run_created(),
        _event(EventType.DEPARTMENT_ACTIVATED, 2, session="ses_pro", department="product",
               payload={"activation_id": "act_1", "cycle": 1}, epoch=1),
        _event(EventType.MODEL_REQUESTED, 3, session="ses_pro", department="product"),
        _event(EventType.RUN_PAUSED, 4, stop_reason="max_cycles", state="paused"),
    ])
    assert (paused.status, paused.stop_reason) == ("paused", "max_cycles")
    continued = fold_more(paused, [_event(EventType.RUN_CONTINUED, 5)])
    assert (continued.status, continued.stop_reason) == ("running", None)
    # 继续不重置已用量：暂停时的一步仍然是已用量里的一步
    assert continued.used == UsedAmount(settled_ms=0, activations=1, model_steps=1)
    failed = fold_more(continued, [_event(EventType.RUN_FAILED, 6, stop_reason="cannot_verify")])
    assert (failed.status, failed.stop_reason) == ("failed", "cannot_verify")
    done = fold_more(failed, [_event(EventType.RUN_DONE, 7, stop_reason="released")])
    assert (done.status, done.stop_reason) == ("done", "released")


def test_usage_fields_missing_from_the_events_count_as_zero():
    # 事件里没有记的用量字段按 0（#857）：询问分支的激活不算轮次，缺 cycle、elapsed_ms 与
    # session_elapsed_ms 时不把缺的字段当成 1，也不把分支会话当成主线
    projection = fold_events([
        _run_created(),
        _event(EventType.DEPARTMENT_ACTIVATED, 2, session="ses_branch", department="quality", payload={}),
        _event(EventType.ACTIVATION_FINISHED, 3, session="ses_branch", department="quality", payload={}),
        _event(EventType.MODEL_REQUESTED, 4, session="ses_branch", department="quality"),
    ])
    assert projection.used.activations == 0
    assert projection.used.settled_ms == 0
    assert projection.rounds == {}
    session = projection.sessions["ses_branch"]
    assert (session.activations, session.model_steps) == (1, 1)
    assert (session.settled_ms, session.settled_steps) == (0, 0)
    assert session.round_id is None


def test_the_activation_count_takes_the_largest_round():
    # 询问分支沿用当前的轮次，所以事项一级的激活次数取出现过的最大轮次与主线会话的激活次数里
    # 较大的那一个（#857）：主线会话还没有激活时，轮次编号仍然算进激活次数
    projection = fold_events([
        _run_created(),
        _event(EventType.DEPARTMENT_ACTIVATED, 2, session="ses_pro", department="product",
               payload={"activation_id": "act_1", "cycle": 5}, epoch=1),
    ])
    assert projection.used.activations == 5
    assert projection.sessions["ses_pro"].activations == 1


def test_a_new_round_without_an_id_keeps_the_previous_round_number():
    # 一轮工作开始事件不带 activation_id 时，会话当前的轮次编号保持不变（#857、#860）：
    # 检查回执要来自这一轮，缺编号的那次激活不能把这一轮的编号清掉
    created = _event(EventType.RUN_CREATED, 1, payload={
        "kind": "change", "project_id": "prj_824", "work_item_id": "wi_824",
        "definitions_version": "sha256:definitions", "parameters_version": "sha256:parameters",
        "max_cycles": 7, "run_time_limit_sec": 900,
        "sessions": {"product": "ses_pro"},
    })
    projection = fold_events([
        created,
        _event(EventType.DEPARTMENT_ACTIVATED, 2, session="ses_pro", department="product",
               payload={"activation_id": "act_1", "cycle": 1}),
        _event(EventType.DEPARTMENT_ACTIVATED, 3, session="ses_pro", department="product",
               payload={"cycle": 2}),
    ])
    assert projection.sessions["ses_pro"].round_id == "act_1"
    assert projection.sessions["ses_pro"].activations == 2
    assert projection.rounds == {"product": "act_1"}


def test_a_model_request_without_a_session_counts_for_the_empty_session():
    # 模型请求没有会话列时按空会话记（docs/design/skeleton-and-application.md「最小投影」）：
    # 已用步数不能丢，也不能记到一个叫 None 的会话上
    projection = fold_events([_run_created(), _event(EventType.MODEL_REQUESTED, 2, session=None)])
    assert projection.used.model_steps == 1
    assert projection.sessions == {
        "": SessionState(settled_ms=0, settled_steps=0, activations=0, model_steps=1,
                         round_id=None, department=None),
    }


def test_an_acceptance_with_incomplete_fields_is_not_an_artifact():
    # 接纳事件的统一字段不全时不是成果接纳（没有种类、没有版本或没有内容摘要）：跳过这条事件，
    # 不留下半份成果（S1d；docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）
    created = _run_created()
    incomplete = (
        {"artifact_version": 1, "content_hash": "sha256:spec1"},
        {"artifact_kind": "product_spec", "content_hash": "sha256:spec1"},
        {"artifact_kind": "product_spec", "artifact_version": None, "content_hash": "sha256:spec1"},
        {"artifact_kind": "product_spec", "artifact_version": 1},
        {"artifact_kind": "", "artifact_version": 1, "content_hash": "sha256:spec1"},
        {"artifact_kind": "product_spec", "artifact_version": 1, "content_hash": None},
    )
    for payload in incomplete:
        projection = fold_events([created, _event(EventType.SPEC_ACCEPTED, 2, payload=payload)])
        assert projection.artifacts == {}, payload
        assert projection.accepted == {}, payload
        assert projection.versions == {}, payload


def test_acceptance_fields_that_are_not_objects_are_left_empty():
    # 依据与工件引用不是对象、作者部门与树摘要不是非空字符串时按没有处理：不把半份字段带进成果
    projection = fold_events([
        _run_created(),
        _event(EventType.SPEC_ACCEPTED, 2, session="ses_pro", department="product", payload={
            "content_hash": "sha256:spec1", "artifact_kind": "product_spec", "artifact_version": 1,
            "artifact_basis": ["product_spec", "sha256:spec0"], "artifact_ref": "run_824/prd.md",
            "artifact_issuer": None, "artifact_tree_digest": 7,
        }),
    ])
    assert projection.artifact("product_spec") == AcceptedArtifact(
        version=1, content_hash="sha256:spec1", issuer=None, tree_digest=None, basis={}, ref=None)


def test_the_snapshot_records_its_own_content_hash():
    # 建档快照有内容摘要时记它，没有时用树摘要（S1d）：通用条件 4 读树摘要，内容摘要另记一份
    with_hash = _event(EventType.RUN_CREATED, 1, payload={
        "kind": "onboarding", "project_id": "prj_824", "work_item_id": "wi_824",
        "snapshot": {"tree_digest": "sha256:tree1", "content_hash": "sha256:snapshot1"},
    })
    assert fold_events([with_hash]).artifact("snapshot") == AcceptedArtifact(
        version=1, content_hash="sha256:snapshot1", tree_digest="sha256:tree1")
    without_hash = replace(with_hash, payload={**with_hash.payload,
                                               "snapshot": {"tree_digest": "sha256:tree1"}})
    assert fold_events([without_hash]).artifact("snapshot") == AcceptedArtifact(
        version=1, content_hash="sha256:tree1", tree_digest="sha256:tree1")
    # 不是对象、没有树摘要、树摘要是空串或不是字符串：没有快照
    for snapshot in ("sha256:tree1", {"content_hash": "sha256:x"}, {"tree_digest": ""}, {"tree_digest": 7}):
        messy = replace(with_hash, payload={**with_hash.payload, "snapshot": snapshot})
        assert fold_events([messy]).artifact("snapshot") is None, snapshot


def test_a_stream_event_without_a_version_is_not_recorded():
    # 每条流的当前版本只在事件带流与版本时记下：缺一项的那条不覆盖已有的版本，也不记一个 0
    no_version = replace(_event(EventType.MODEL_REQUESTED, 2, session="ses_pro"), stream_version=0)
    no_stream = replace(_event(EventType.MODEL_REQUESTED, 3, session="ses_pro"), stream=None)
    assert fold_events([_run_created(), no_version, no_stream]).stream_versions == {RUN_STREAM: 1}


def test_an_invalidation_without_kind_or_version_changes_nothing():
    # 成果失效事件缺种类或版本时不是失效（S1b）：投影不变，也不留下一个空的清单项
    accepted = fold_events([
        _run_created(),
        _event(EventType.SPEC_ACCEPTED, 2, session="ses_pro", department="product", payload={
            "content_hash": "sha256:spec1", "artifact_kind": "product_spec", "artifact_version": 1,
            "artifact_basis": {},
        }),
    ])
    for payload in ({}, {"artifact_kind": "product_spec"}, {"artifact_version": 1},
                    {"artifact_kind": "", "artifact_version": 1},
                    {"artifact_kind": 7, "artifact_version": 1}):
        after = fold_more(accepted, [_event(EventType.ARTIFACT_INVALIDATED, 3, payload=payload)])
        assert after.artifact("product_spec") == accepted.artifact("product_spec"), payload
        assert after.versions == accepted.versions, payload


def _accepted_spec(version: int, content_hash: str, at: int) -> Event:
    # 一条接纳 PRD 的事件：种类、版本与内容摘要齐全
    return _event(EventType.SPEC_ACCEPTED, at, session="ses_pro", department="product", payload={
        "content_hash": content_hash, "artifact_kind": "product_spec", "artifact_version": version,
        "artifact_basis": {},
    })


def test_the_projection_reads_the_current_and_the_last_accepted_artifact():
    # 当前版本、最后一次接纳的那一版与当前版本的内容摘要（#860）：失效以后当前版本没有，
    # 最后接纳的那一版仍然记着，接下一版时由它给出上一版与版本号
    projection = fold_events([_run_created(), _accepted_spec(1, "sha256:spec1", 2)])
    assert projection.artifact("product_spec").version == 1
    assert projection.latest("product_spec").version == 1
    assert projection.artifact_hash("product_spec") == "sha256:spec1"
    # 没有接纳过的种类：三项都是 None
    assert projection.artifact("product_decision") is None
    assert projection.latest("product_decision") is None
    assert projection.artifact_hash("product_decision") is None
    invalidated = fold_more(projection, [_event(EventType.ARTIFACT_INVALIDATED, 3, payload={
        "artifact_kind": "product_spec", "artifact_version": 1})])
    assert invalidated.artifact("product_spec") is None
    assert invalidated.artifact_hash("product_spec") is None
    assert invalidated.latest("product_spec").version == 1


def test_invalidating_an_older_version_keeps_the_current_one():
    # 失效按版本去掉那一版（S1b）：失效旧的版本不碰当前的版本，也不从多版并存的清单里
    # 去掉别的版本；重复失效同一版不再改动任何东西
    events = [_run_created(), _accepted_spec(1, "sha256:spec1", 2), _accepted_spec(2, "sha256:spec2", 3)]
    projection = fold_events(events)
    older = fold_more(projection, [_event(EventType.ARTIFACT_INVALIDATED, 4, payload={
        "artifact_kind": "product_spec", "artifact_version": 1})])
    assert older.artifact("product_spec").content_hash == "sha256:spec2"
    assert [item.content_hash for item in older.versions_of("product_spec")] == ["sha256:spec2"]
    # 当前版本已经失效以后再失效同一版：当前版本仍然没有，清单与最后接纳的那一版不变
    twice = fold_more(older, [
        _event(EventType.ARTIFACT_INVALIDATED, 5, payload={
            "artifact_kind": "product_spec", "artifact_version": 2}),
        _event(EventType.ARTIFACT_INVALIDATED, 6, payload={
            "artifact_kind": "product_spec", "artifact_version": 2}),
    ])
    assert twice.artifact("product_spec") is None
    assert twice.versions_of("product_spec") == ()
    assert twice.latest("product_spec").content_hash == "sha256:spec2"
    # 失效一个从来没有接纳过的种类：这种成果仍然没有当前版本，已有的清单不受影响
    unknown = fold_more(twice, [_event(EventType.ARTIFACT_INVALIDATED, 7, payload={
        "artifact_kind": "product_decision", "artifact_version": 1})])
    assert unknown.artifact("product_decision") is None
    assert unknown.versions_of("product_decision") == ()
    assert unknown.versions_of("product_spec") == twice.versions_of("product_spec")


def test_answering_a_decision_that_is_not_pending_changes_nothing():
    # 回答或撤回一条不在待回答清单里的决定请求时什么都不做（按消息身份去重）：
    # 不能因为回答了一个不认识的编号就把别的请求从待回答清单里拿掉，也不能让折叠报错
    pending = fold_events([
        _run_created(),
        _event(EventType.DECISION_REQUESTED, 2, payload={"kind": "pause", "blocks": "run"}),
    ])
    assert pending.pending_decisions == ("evt_2",)
    for event in (
        _event(EventType.DECISION_ANSWERED, 3, payload={"decision_id": "evt_unknown"}),
        _event(EventType.DECISION_ANSWERED, 3, payload={}),
        _event(EventType.DECISION_WITHDRAWN, 3, payload={"decision_id": None}),
    ):
        assert fold_more(pending, [event]).pending_decisions == ("evt_2",)

