import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.artifacts import ArtifactStore
from harness.event_store import EventStore
from harness.models import ArtifactRef, EventType, canonical_hash, json_dumps
from harness.proposals import (answer_turn, ask_turn, delivery, delivery_turn,
                               product_spec, review, review_turn)
from harness.providers import ProviderFacade
from harness.providers.selection import ModelSelection
from harness.runtime import LoopSystem
from harness.smoke import EVAL_ENV_NAMES, isolation_fields, run_smoke, smoke_exit_code, summarize_run
from harness.tests.helpers import (compacted_runner, explore_turn, happy_script, recorded_context,
                                 run_scripted, system_on_copy)
from harness.tests.helpers import (compacted_runner, explore_turn, happy_script, recorded_context, run_scripted,
                                   system_on_copy)
from harness.tests.saved_rewrite import (delete_saved_events, rewrite_saved_event, rewrite_saved_events,
                                         rewrite_saved_projection)

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次完整循环并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上改写与检查。数据来自真实运行，这些文件登记为集成层。

def _by_department(adapter: FakeAdapter) -> FakeAdapter:
    # 假模型脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）。
    # compacted_runner 给的是一条共用的列表脚本（helpers.py 不在本工单的只改清单里），
    # 剧本项本身按请求的部门与目的分派：这里给每个部门（含询问分支）各一份同样的剧本，
    # 取用顺序就不再互相影响
    turns = list(adapter.script)
    adapter.script = []
    adapter.scripts = {key: list(turns) for key in
                       ("product", "engineering", "quality",
                        "product:ask", "engineering:ask", "quality:ask")}
    return adapter


@pytest.fixture(scope="module")
def saved_native(tmp_path_factory):
    # 一次本机流程走完的运行：产品给要求、工程写入、检查、交付、再检查、质检放行
    # 提交依据的版本由工厂从请求里的当前版本取（工单 #471）：脚本项是工厂而不是裸提交
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 质检在 PRD 被接纳以后还有一轮预测性探索，这一轮没有交付可以核验，提交的结论被拒绝
    # 提交依据的版本由工厂从请求里的当前版本取（工单 #471）：脚本项是工厂而不是裸提交。
    # 按部门给出（工单 #557：同时运行的会话各自取用自己的脚本），质检先起草测试材料
    script = {
        "product": [product_spec()],
        "engineering": [
            FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
            FakeTurn(checks={"smoke": 0}),
            delivery_turn(),
        ],
        "quality": [
            explore_turn(),
            FakeTurn(checks={"smoke": 0}),
            review_turn("release", "host checks passed"),
        ],
    }
    system, projection = run_scripted(tmp_path_factory.mktemp("native"), script)
    assert projection.status == "done"
    system.close()
    return system.data_dir, projection.run_id

@pytest.fixture
def native_run(saved_native, tmp_path):
    saved, run_id = saved_native
    return system_on_copy(saved, tmp_path / "native"), run_id

def test_smoke_requires_current_input_audit_and_host_receipts():
    base = {
        "status": "done",
        "stop_reason": "released",
        "replay_consistent": True,
        "context_isolated": True,
        "model_input_audit": {"status": "verified"},
        "check_receipts": [{"name": "smoke", "exit_code": 0}],
        "check_receipts_verified": True,
        "delivery_archive": {"status": "verified"},
        "git_audit": {"status": "verified"},
        "fake_used": False,
        "ask_audit": {"status": "verified", "pre_spec_ask": True, "requirements_revision": True},
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": base, "ask": base}}) == 0
    assert smoke_exit_code({"available": False, "scenarios": {}}) == 2
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, fake_used=True)}}) == 2
    for change in (
        {"check_receipts": []}, {"check_receipts_verified": False}, {"context_isolated": False},
        {"model_input_audit": None}, {"model_input_audit": {"status": "unverified"}},
        {"delivery_archive": None}, {"delivery_archive": {"status": "unverified"}},
        {"git_audit": None}, {"git_audit": {"status": "unverified"}},
    ):
        assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, **change)}}) == 1
    for audit in (None, {"status": "unverified"}, {"status": "verified", "pre_spec_ask": True},
                  {"status": "verified", "requirements_revision": True}):
        assert smoke_exit_code({"available": True, "scenarios": {
            "ask": dict(base, ask_audit=audit),
        }}) == 1

@pytest.fixture(scope="module")
def saved_ask(tmp_path_factory):
    from harness.demo import run_demo

    system, run_id = run_demo(tmp_path_factory.mktemp("ask"))
    # 记录装配上下文的检查要按 run 读回每一次请求：请求本身在调用清单里，清单随数据目录保存
    invocations = list(system.test_adapter.invocations)
    system.close()
    return system.data_dir, run_id, invocations

@pytest.fixture
def ask_run(saved_ask, tmp_path):
    saved, run_id, _invocations = saved_ask
    return system_on_copy(saved, tmp_path / "ask"), run_id

@pytest.fixture
def ask_invocations(saved_ask):
    # 保存的运行里每一次模型请求：检查装配上下文时按请求读回同一份清单
    _saved, _run_id, invocations = saved_ask
    return invocations

def test_native_audit_checks_every_step_and_actual_host_receipts(native_run):
    system, run_id = native_run
    summary = summarize_run(system, run_id, scenario="happy")
    assert summary["context_isolated"] is True, summary["context_isolation_notes"]
    assert summary["model_input_audit"]["status"] == "verified"
    assert summary["model_input_audit"]["request_count"] > 3
    # 三个部门都工作过（工单 #557：同时运行的会话各有一轮工作，激活的个数不再固定，
    # 这里断言的是做成了什么，不是数了几轮）
    activated = {event.department for event in system.store.list_events(run_id)
                 if event.type == EventType.DEPARTMENT_ACTIVATED}
    assert activated == {"product", "engineering", "quality"}
    assert summary["check_receipts_verified"] is True, summary["check_receipt_notes"]
    assert summary["delivery_archive"]["status"] == "verified", summary["delivery_archive"]
    assert summary["delivery_archive"]["tree_digest"] == system.project(run_id).delivery_spec.code_tree_digest
    assert summary["git_audit"]["status"] == "verified", summary["git_audit"]
    assert summary["git_audit"]["version_count"] == 4
    assert summary["replay_consistent"] is True
    assert summary["fake_used"] is True
    assert smoke_exit_code({"available": True, "scenarios": {"happy": summary}}) == 2

def test_directory_fake_protocol_is_flagged_and_never_passes_as_real(tmp_path):
    # fake 协议只在测试或演示方式启动的系统中可用（工单 #86）：本用例以测试方式启动，
    # fake 连接可以进入目录；它仍然不能作为真实工作通过
    facade = ProviderFacade(startup_mode="test")
    facade.store_document({
        "providers": [{"id": "fake-provider", "name": "Fake", "base_url": ""}],
        "models": [{"id": "fake-model", "provider_id": "fake-provider", "model": "fake-script",
                    "protocol": "fake",
                    "context_window": 32_000, "max_output_tokens": 4_096}],
        "bindings": {department: {"provider_id": "fake-provider", "model_id": "fake-model"}
                     for department in ("product", "engineering", "quality")},
    })
    system = LoopSystem(tmp_path, facade=facade)
    run_id = system.create_run("fake provider cannot submit real work")
    result = system.activate_once(run_id)
    summary = summarize_run(system, run_id, scenario="happy")

    assert result.status == "paused"
    assert summary["fake_used"] is True
    assert summary["provider_bindings"]["product"]["protocol"] == "fake"
    assert smoke_exit_code({"available": True, "scenarios": {"happy": summary}}) == 2

def test_git_audit_rejects_valid_same_run_commit_with_wrong_accepted_material(native_run):
    system, run_id = native_run
    assert summarize_run(system, run_id, scenario="happy")["git_audit"]["status"] == "verified"
    events = _saved_events(system, run_id)
    event = next(item for item in reversed(events) if item.type == EventType.QA_SUBMITTED)
    original = event.payload["git_version"]
    accepted_files = system.git_versions.read_files(run_id, original)
    wrong = system.git_versions.prepare(
        run_id, parent_commit=original["parent_commit"],
        updates={"specs/qa.json": accepted_files["specs/qa.json"], "PRD.md": b"Unrelated requirements\n"},
        message="A valid Git object that does not reproduce the accepted requirements",
    )
    system.git_versions.verify(run_id, wrong)
    event.payload["git_version"] = wrong
    rewrite_saved_event(system.store, event)
    assert summarize_run(system, run_id, scenario="happy")["git_audit"]["status"] == "unverified"

@pytest.mark.parametrize("changed", ["effective_contract"])
def test_receipt_audit_rejects_new_contract_even_with_unchanged_spec_and_tree(native_run, changed):
    system, run_id = native_run
    assert summarize_run(system, run_id, scenario="happy")["check_receipts_verified"] is True
    projection = system.project(run_id)
    changed_item = replace(getattr(projection, changed), content_hash=canonical_hash("new accepted content"))
    changed_projection = replace(projection, **{changed: changed_item})
    rewrite_saved_projection(system.store, run_id, changed_projection)
    summary = summarize_run(system, run_id, scenario="happy")
    assert summary["check_receipts"]
    assert summary["check_receipts_verified"] is False
    notes = summary["check_receipt_notes"]
    assert "engineering: no successful host check bound to the final contract and snapshot" in notes
    assert "quality: no successful host check bound to the final contract and snapshot" in notes

def test_archive_audit_restores_from_persisted_bytes_after_workspace_changes(native_run):
    # 交付以后工作区的文件改变：核对仍按封存的内容恢复，所以结果与交付时一致
    system, run_id = native_run
    system.workspace(run_id).write_file("src/echo.py", "changed after delivery\n")
    result = summarize_run(system, run_id, scenario="happy")["delivery_archive"]
    assert result["status"] == "verified", result
    assert result["files"] == 1

@pytest.mark.parametrize("damage", ["missing", "modified"])
def test_archive_audit_rejects_missing_or_modified_persisted_bytes(native_run, damage):
    system, run_id = native_run
    delivery = system.project(run_id).delivery_spec
    archive = json.loads(system.artifacts.get_for_run(run_id, delivery.tree_ref))
    blob = system.artifacts.root / archive["blobs"][0]["artifact"]["path"]
    if damage == "missing":
        blob.unlink()
    else:
        blob.write_bytes(b"changed artifact bytes")
    result = summarize_run(system, run_id, scenario="happy")["delivery_archive"]
    assert result["status"] == "unverified"
    assert result["notes"]

def test_archive_audit_rejects_unrelated_delivery_digest(native_run):
    system, run_id = native_run
    assert summarize_run(system, run_id, scenario="happy")["delivery_archive"]["status"] == "verified"
    projection = system.project(run_id)
    delivery = replace(projection.delivery_spec, code_tree_digest=canonical_hash("unrelated tree"))
    rewrite_saved_projection(system.store, run_id, replace(projection, delivery_spec=delivery))
    assert summarize_run(system, run_id, scenario="happy")["delivery_archive"]["status"] == "unverified"

def test_ask_audit_verifies_ask_pairs_and_revisions(ask_run):
    system, run_id = ask_run
    audit = summarize_run(system, run_id, scenario="ask")["ask_audit"]
    assert audit["status"] == "verified", audit
    assert audit["pre_spec_ask"] is True
    assert audit["requirements_revision"] is True
    assert audit["directions"] == ["product->engineering", "engineering->product", "quality->engineering"]


def test_ask_audit_rejects_missing_pre_spec_ask(ask_run):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    first_ask_start = next(e for e in events if e.type == EventType.ASK_STARTED)
    first_ask_ans = next(e for e in events if e.type == EventType.ASK_ANSWERED and e.session_id == first_ask_start.payload.get("branch_session_id"))
    delete_saved_events(system.store, [first_ask_start.event_id, first_ask_ans.event_id])
    audit = summarize_run(system, run_id, scenario="ask")["ask_audit"]
    assert audit["pre_spec_ask"] is False
    assert smoke_exit_code({"available": True, "scenarios": {"ask": {"status": "done", "stop_reason": "released", "replay_consistent": True, "context_isolated": True, "model_input_audit": {"status": "verified"}, "check_receipts": [{"name": "smoke"}], "check_receipts_verified": True, "delivery_archive": {"status": "verified"}, "git_audit": {"status": "verified"}, "fake_used": False, "ask_audit": audit}}}) == 1


def test_ask_audit_rejects_missing_revision_in_answer(ask_run):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    second_ask_ans = [e for e in events if e.type == EventType.ASK_ANSWERED][1]
    second_ask_ans.payload["with_spec_revision"] = False
    rewrite_saved_event(system.store, second_ask_ans)
    audit = summarize_run(system, run_id, scenario="ask")["ask_audit"]
    assert audit["requirements_revision"] is False
    assert smoke_exit_code({"available": True, "scenarios": {"ask": {"status": "done", "stop_reason": "released", "replay_consistent": True, "context_isolated": True, "model_input_audit": {"status": "verified"}, "check_receipts": [{"name": "smoke"}], "check_receipts_verified": True, "delivery_archive": {"status": "verified"}, "git_audit": {"status": "verified"}, "fake_used": False, "ask_audit": audit}}}) == 1


def test_ask_audit_rejects_mismatched_ask_parties_or_events(ask_run):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    ans = [e for e in events if e.type == EventType.ASK_ANSWERED][0]
    ans.payload["recipient"] = "other"
    rewrite_saved_event(system.store, ans)
    audit = summarize_run(system, run_id, scenario="ask")["ask_audit"]
    assert audit["status"] == "unverified"
    assert any("parties do not match" in note for note in audit["notes"])


def test_ask_audit_rejects_ask_still_in_progress(ask_run):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    last_start = [e for e in events if e.type == EventType.ASK_STARTED][-1]
    last_answer = next(e for e in events if e.type == EventType.ASK_ANSWERED
                       and e.session_id == last_start.payload["branch_session_id"])
    delete_saved_events(system.store, [last_answer.event_id])

    audit = summarize_run(system, run_id, scenario="ask")["ask_audit"]
    assert audit["status"] == "unverified"
    assert any("still in progress" in note for note in audit["notes"])
    assert _ask_smoke_exit_code(audit) == 1


def test_ask_audit_rejects_answer_before_start(ask_run):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    starts = [e for e in events if e.type == EventType.ASK_STARTED]
    answers = [e for e in events if e.type == EventType.ASK_ANSWERED]
    starts[-1].payload["branch_session_id"] = answers[0].session_id
    rewrite_saved_event(system.store, starts[-1])

    audit = summarize_run(system, run_id, scenario="ask")["ask_audit"]
    assert audit["status"] == "unverified"
    assert any("answer stream_version is not after start" in note for note in audit["notes"])
    assert _ask_smoke_exit_code(audit) == 1


def test_ask_audit_rejects_revision_outside_ask_window(ask_run):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    second_start = [e for e in events if e.type == EventType.ASK_STARTED][1]
    second_answer = [e for e in events if e.type == EventType.ASK_ANSWERED][1]
    accepted = next(e for e in events if e.type == EventType.SPEC_ACCEPTED
                    and second_start.stream_version < e.stream_version < second_answer.stream_version)
    delete_saved_events(system.store, [accepted.event_id])

    audit = summarize_run(system, run_id, scenario="ask")["ask_audit"]
    assert audit["requirements_revision"] is False
    assert _ask_smoke_exit_code(audit) == 1


def _ask_smoke_exit_code(audit):
    return smoke_exit_code({"available": True, "scenarios": {"ask": {
        "status": "done", "stop_reason": "released", "replay_consistent": True,
        "context_isolated": True, "model_input_audit": {"status": "verified"},
        "check_receipts": [{"name": "smoke"}], "check_receipts_verified": True,
        "delivery_archive": {"status": "verified"}, "git_audit": {"status": "verified"},
        "fake_used": False, "ask_audit": audit,
    }}})


def test_model_input_audit_tracks_new_input_and_prompt_versions(ask_run, ask_invocations):
    system, run_id = ask_run
    summary = summarize_run(system, run_id, scenario="ask")
    assert summary["model_input_audit"]["status"] == "verified", summary["model_input_audit"]
    assert summary["check_receipts_verified"] is True
    assert summary["delivery_archive"]["status"] == "verified"
    manifests = [(request.department, recorded_context(system, request).manifest)
                 for request in ask_invocations]
    assert {manifest.input_version for _department, manifest in manifests} == {1, 2}
    # demo 在事项进行中修改产品部门的部门 Prompt：修改前的请求用内置默认（版本 0），之后用项目设置（版本 1）
    assert {manifest.prompt_version for department, manifest in manifests if department == "product"} == {0, 1}
@pytest.mark.parametrize("field", ["input_version", "prompt_version", "prompt_hash"])
@pytest.mark.parametrize("event_type", [EventType.DEPARTMENT_ACTIVATED, EventType.CONTEXT_ASSEMBLED,
                                      EventType.MODEL_MESSAGE, EventType.TOOL_CALLED])
def test_model_input_audit_rejects_forged_adopted_versions(native_run, field, event_type):
    system, run_id = native_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = next(item for item in events if item.type == event_type and item.payload.get("activation_id"))
    event.payload[field] = "forged-prompt" if field == "prompt_hash" else 999
    rewrite_saved_event(system.store, event)
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified", audit
    assert any(field in note for note in audit["notes"])

@pytest.mark.parametrize("field", ["text", "byte_start", "byte_end"])
def test_model_input_audit_rejects_changed_received_original(ask_run, field):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = next(item for item in events if item.type == EventType.USER_INPUT_RECEIVED)
    event.payload[field] = "rewritten original" if field == "text" else 999
    rewrite_saved_event(system.store, event)
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified", audit
    assert any("input bytes or range" in note for note in audit["notes"])

def test_model_input_audit_uses_the_project_department_prompt(tmp_path):
    # 部门 Prompt 来自项目部门设置（run 内没有副本）：装配的请求正文用项目设置中的 Prompt，
    # 审计从项目部门设置取出同一个 Prompt 复核
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    project_id = system.projects.register("Audit", "目标")
    prompt = "  NEW_ENGINEERING_PROMPT\r\n"
    system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt=prompt), 0)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "echo")
    system.run_until_stop(run_id)
    versions = [recorded_context(system, request).manifest.prompt_version
                for request in system.test_adapter.invocations if request.department == "engineering"]
    assert versions and set(versions) == {1}
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "verified", audit

@pytest.mark.parametrize("event_type", [EventType.DEPARTMENT_ACTIVATED, EventType.CONTEXT_ASSEMBLED])
def test_model_input_audit_rejects_changed_work_basis(ask_run, event_type):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = next(item for item in events if item.type == event_type and item.payload.get("effective_contract_hash"))
    event.payload["effective_contract_hash"] = "wrong-effective_contract_hash"
    rewrite_saved_event(system.store, event)
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any("effective_contract_hash" in note for note in audit["notes"])

def test_model_input_audit_rejects_private_material_in_rehashed_pinned_text(ask_run):
    system, run_id = ask_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = [item for item in events if item.type == EventType.CONTEXT_ASSEMBLED and item.department == "quality"][-1]
    request = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["request_ref"])))
    request["input"][0]["content"] += "\n\n[private_engineering_transcript]\nUNRELATED_PRIVATE_HISTORY_CANARY"
    ref = system.artifacts.put(run_id, "model_request", json_dumps(request), media_type="application/json")
    event.payload["request_ref"] = asdict(ref)
    event.payload["digest"] = event.context_digest = canonical_hash(request)
    event.artifact_hashes = [ref.content_hash]
    attempted = next(item for item in events if item.type == EventType.MODEL_REQUESTED
                     and item.payload["activation_id"] == event.payload["activation_id"]
                     and item.payload["step_id"] == event.payload["step_id"])
    attempted.context_digest = event.context_digest
    rewrite_saved_events(system.store, [event, attempted])
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any("pinned developer input differs" in note for note in audit["notes"])

def test_model_input_audit_rejects_forged_injected_source_metadata(native_run):
    system, run_id = native_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = next(item for item in events if item.type == EventType.CONTEXT_ASSEMBLED)
    event.payload["injected"][0]["digest"] = canonical_hash("different source")
    rewrite_saved_event(system.store, event)
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any("injected source metadata" in note for note in audit["notes"])

def test_model_input_audit_rebuilds_summary_scope_after_contract_changes(tmp_path):
    system, adapter, run_id, _ = compacted_runner(tmp_path)
    # 脚本按部门给出（工单 #878）：这条用例走到 PRD 被接纳以后，共用的列表脚本要拆成按部门的
    _by_department(adapter)
    first = system.activate_once(run_id)
    assert first.compactions[-1]["effective_contract_hash"] is None
    system.activate_once(run_id)
    final = system.activate_once(run_id)
    later = [item for item in final.compactions if item["effective_contract_hash"] is not None]
    assert later and later[0]["previous_compaction_event_id"] is None
    assert adapter.invocations[-1].purpose == "work"
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "verified", audit["notes"]

def test_failed_run_without_requests_has_no_context_evidence(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    fields = isolation_fields(store, artifacts, "run")
    assert fields["manifest_boundary"] is False
    assert fields["model_input_audit"]["status"] == "unverified"
    assert fields["context_isolated"] is False

def _saved_events(system, run_id):
    # 审计读到的必须是事件库中保存的事件；测试改动以后写回事件行，再经公开接口运行审计
    return system.store.list_events(run_id)

@pytest.mark.parametrize("field,value", [
    ("request_ref", None), ("activation_id", "foreign-activation"),
    ("session_id", "foreign-session"), ("department", "quality"),
    ("step_id", 100), ("digest", "sha256:wrong"),
])
def test_unbound_or_missing_request_cannot_certify_run(native_run, field, value):
    system, run_id = native_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = next(item for item in events if item.type == EventType.CONTEXT_ASSEMBLED)
    event.payload[field] = value
    rewrite_saved_event(system.store, event)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert fields["model_input_audit"]["status"] == "unverified"

@pytest.mark.parametrize("mutation,expected", [
    ("foreign_history", "department's recorded outputs"), ("extra_tool", "actual tool schemas"),
    ("hidden_instructions", "unexpected model input fields"), ("changed_intend", "verbatim task"),
])
def test_actual_inputs_are_checked_even_when_artifact_hash_is_valid(native_run, mutation, expected):
    system, run_id = native_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = next(item for item in events if item.type == EventType.CONTEXT_ASSEMBLED)
    request = json.loads(system.artifacts.get_text(event.payload["request_ref"]["content_hash"]))
    if mutation == "foreign_history":
        request["input"].append({"role": "assistant", "content": "other department private history"})
    elif mutation == "extra_tool":
        request["tools"].append({"type": "function", "name": "write_file", "parameters": {}})
    elif mutation == "hidden_instructions":
        request["instructions"] = "untracked instructions"
    else:
        request["input"][0]["content"] = "Changed original task\n" + request["input"][0]["content"]
    ref = system.artifacts.put(run_id, "model_request", json_dumps(request), media_type="application/json")
    event.payload["request_ref"] = asdict(ref)
    event.payload["digest"] = canonical_hash(request)
    event.context_digest = canonical_hash(request)
    event.artifact_hashes = [ref.content_hash]
    attempted = next(item for item in events if item.type == EventType.MODEL_REQUESTED)
    attempted.context_digest = canonical_hash(request)
    rewrite_saved_events(system.store, [event, attempted])
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any(expected in note for note in fields["model_input_audit"]["notes"])

def test_tool_history_must_match_recorded_result(native_run):
    system, run_id = native_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    event = next(item for item in events if item.type == EventType.TOOL_CALLED and item.payload.get("input_item"))
    event.payload["input_item"]["output"] = json_dumps({"ok": True, "output": "unrecorded", "error": None})
    rewrite_saved_event(system.store, event)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any("recorded result" in note for note in fields["model_input_audit"]["notes"])

def test_consistently_relabelled_steps_must_still_match_activation_event(native_run):
    system, run_id = native_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    activated = next(event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED)
    identity = activated.payload["activation_id"]
    relabelled = []
    for event in events:
        if event.type != EventType.DEPARTMENT_ACTIVATED and event.payload.get("activation_id") == identity:
            event.payload["activation_id"] = "unrelated-activation"
            relabelled.append(event)
    rewrite_saved_events(system.store, relabelled)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any("department activation" in note for note in fields["model_input_audit"]["notes"])

def test_audit_does_not_replace_missing_run_artifact_with_another_runs_copy(native_run):
    system, run_id = native_run
    event = next(item for item in system.store.list_events(run_id) if item.type == EventType.CONTEXT_ASSEMBLED)
    original = system.artifacts.root / event.payload["request_ref"]["path"]
    system.artifacts.put("another-run", "model_request", original.read_bytes(), media_type="application/json")
    original.unlink()
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert fields["model_input_audit"]["status"] == "unverified"

# 同一个脚本被两项检查共用：请求让出以后回到产品部门，两项检查各在自己的副本上改写与检查
# 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本）
_PRODUCT_RETURN_SCRIPT = {
    "product": [product_spec()],
    "engineering": [ask_turn(recipient="product", question="Clarify flags?"), delivery_turn()],
    "product:ask": [answer_turn("The existing requirements do not distinguish flags.")],
    "quality": [explore_turn(), review_turn("release", "host checks passed")],
}

@pytest.fixture(scope="module")
def saved_product_return(tmp_path_factory):
    system, projection = run_scripted(tmp_path_factory.mktemp("product-return"), _PRODUCT_RETURN_SCRIPT)
    assert projection.status == "done"
    system.close()
    return system.data_dir, projection.run_id

@pytest.fixture
def product_return_run(saved_product_return, tmp_path):
    saved, run_id = saved_product_return
    return system_on_copy(saved, tmp_path / "product-return"), run_id

def test_audit_preserves_department_history_when_request_returns_to_product(product_return_run):
    system, run_id = product_return_run
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is True, fields["model_input_audit"]["notes"]
    # 产品的请求让出以后回到产品部门，产品又工作了一轮（这一轮本身就是被测的行为；
    # 激活的总数不再固定：工单 #557 以后同时运行的会话各有一轮工作）
    reactivated = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == "product"]
    assert len(reactivated) == 2

def test_audit_rejects_missing_new_work_message_after_product_reactivation(product_return_run):
    system, run_id = product_return_run
    projection = system.project(run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    events = _saved_events(system, run_id)
    assembled = [event for event in events if event.type == EventType.CONTEXT_ASSEMBLED and event.department == "product"][1]
    request = json.loads(system.artifacts.get_text(assembled.payload["request_ref"]["content_hash"]))
    assert request["input"][-1]["role"] == "user"
    request["input"].pop()
    ref = system.artifacts.put(projection.run_id, "model_request", json_dumps(request), media_type="application/json")
    assembled.payload["request_ref"] = asdict(ref)
    assembled.payload["digest"] = canonical_hash(request)
    assembled.context_digest = canonical_hash(request)
    assembled.artifact_hashes = [ref.content_hash]
    attempted = next(event for event in events if event.type == EventType.MODEL_REQUESTED
                     and event.payload["activation_id"] == assembled.payload["activation_id"]
                     and event.payload["step_id"] == assembled.payload["step_id"])
    attempted.context_digest = canonical_hash(request)
    rewrite_saved_events(system.store, [assembled, attempted])
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any("department's recorded outputs" in note for note in fields["model_input_audit"]["notes"])

@pytest.fixture(scope="module")
def saved_compacted(tmp_path_factory):
    # 上下文窗口只有 6000 的运行：压缩以后继续工程工作，保存到第一次压缩之后
    system, adapter, run_id, _original = compacted_runner(tmp_path_factory.mktemp("compacted"))
    # 脚本按部门给出（工单 #878）：compacted_runner 给的是一条共用的列表脚本
    _by_department(adapter)
    result = system.activate_once(run_id)
    assert has_new_work(result, "engineering")
    assert len(result.compactions) > 1
    system.close()
    return system.data_dir, run_id

@pytest.fixture
def compacted_run(saved_compacted, tmp_path):
    saved, run_id = saved_compacted
    return system_on_copy(saved, tmp_path / "compacted"), run_id

def test_compaction_audit_checks_partial_sources_and_resumed_input(compacted_run):
    system, run_id = compacted_run
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is True, fields["model_input_audit"]["notes"]
    assert fields["model_input_audit"]["compaction_count"] > 1

@pytest.mark.parametrize("mutation,expected", [
    ("source_ref", "recorded compaction plan"), ("coverage", "checkpoint coverage"),
    ("summary", "bounded model output"), ("work_input", "department's recorded outputs"),
])
def test_compaction_audit_rejects_invented_sources_summary_or_visible_history(compacted_run, mutation, expected):
    system, run_id = compacted_run
    events = _saved_events(system, run_id)
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    compacted = next(event for event in events if event.type == EventType.COMPACTION_RECORDED)
    mutated = [compacted]
    if mutation == "source_ref":
        compacted.payload["source_refs"][0]["event_id"] = "another-department-event"
    elif mutation == "coverage":
        compacted.payload["checkpoint"]["covered_digest"] = canonical_hash("unrelated history")
    elif mutation == "summary":
        ref = system.artifacts.put(run_id, "department_summary", "An invented summary", media_type="text/plain")
        compacted.payload["summary_ref"] = asdict(ref)
        compacted.artifact_hashes.append(ref.content_hash)
    else:
        assembled = next(event for event in reversed(events)
                         if event.type == EventType.CONTEXT_ASSEMBLED and event.payload["purpose"] == "work")
        request = json.loads(system.artifacts.get_text(assembled.payload["request_ref"]["content_hash"]))
        request["input"][1]["content"] = "Another department's unrelated summary"
        ref = system.artifacts.put(run_id, "model_request", json_dumps(request), media_type="application/json")
        assembled.payload["request_ref"] = asdict(ref)
        assembled.payload["digest"] = canonical_hash(request)
        assembled.context_digest = canonical_hash(request)
        assembled.artifact_hashes = [ref.content_hash]
        attempted = next(event for event in events if event.type == EventType.MODEL_REQUESTED
                         and event.payload["activation_id"] == assembled.payload["activation_id"]
                         and event.payload["step_id"] == assembled.payload["step_id"])
        attempted.context_digest = canonical_hash(request)
        mutated.extend([assembled, attempted])
    rewrite_saved_events(system.store, mutated)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any(expected in note for note in fields["model_input_audit"]["notes"])

def test_unmatched_host_receipt_does_not_pass(native_run):
    system, run_id = native_run
    assert summarize_run(system, run_id, scenario="happy")["check_receipts_verified"] is True
    events = _saved_events(system, run_id)
    delete_saved_events(system.store, [event.event_id for event in events
                                       if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "run_check"])
    summary = summarize_run(system, run_id, scenario="happy")
    assert summary["check_receipts_verified"] is False
    assert any("no matching host execution" in note for note in summary["check_receipt_notes"])

def test_smoke_does_not_merge_a_previous_runtime_report(tmp_path):
    (tmp_path / "smoke-report.json").write_text(json.dumps({"scenarios": {"old": {"status": "done"}}}), encoding="utf-8")
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({
        "providers": [{"id": "provider", "name": "Provider",
                       "base_url": "https://provider.example/v1", "credential_ref": "MISSING_KEY"}],
        "models": [{"id": "model", "provider_id": "provider", "model": "model",
                    "protocol": "responses",
                    "context_window": 32000, "max_output_tokens": 4096}],
        "bindings": {department: {"provider_id": "provider", "model_id": "model"}
                     for department in ("product", "engineering", "quality")},
    }), encoding="utf-8")
    report = run_smoke(tmp_path, provider_config=config)
    assert report["available"] is False
    assert report["scenarios"] == {}

def test_smoke_markdown_reports_model_input_audit(tmp_path):
    # smoke 报告的 Markdown 写出每个场景的模型输入核对、请求数、上下文隔离与检查回执的结论。
    # 模型目录使用 fake 协议，场景照常运行并写出报告
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({
        "providers": [{"id": "fake-provider", "name": "Fake", "base_url": ""}],
        "models": [{"id": "fake-model", "provider_id": "fake-provider", "model": "fake-script",
                    "protocol": "fake",
                    "context_window": 32_000, "max_output_tokens": 4_096}],
        "bindings": {department: {"provider_id": "fake-provider", "model_id": "fake-model"}
                     for department in ("product", "engineering", "quality")},
    }), encoding="utf-8")
    report = run_smoke(tmp_path / "smoke", provider_config=config, scenarios=["happy"],
                       startup_mode="test")
    scenario = report["scenarios"]["happy"]
    assert "model_input_audit" in scenario, scenario
    text = (tmp_path / "smoke" / "smoke-report.md").read_text(encoding="utf-8")
    assert f"model input audit: `{scenario['model_input_audit']['status']}`" in text
    assert f"model requests: `{scenario['model_input_audit']['request_count']}`" in text
    assert f"context isolated: `{scenario['context_isolated']}`" in text
    assert f"host receipts verified: `{scenario['check_receipts_verified']}`" in text
    assert "omp" not in text.lower()

def test_smoke_reads_the_catalog_in_its_data_directory(tmp_path, monkeypatch):
    # 没有明确给目录文件时 smoke 在自己的数据目录内读取（设计说明第 3.4 节）：
    # 同一目录先以空态报告缺失，写入目录文件后读取成功，证明读的位置随数据目录移动
    data_dir = tmp_path / "smoke"
    for name in EVAL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    missing = run_smoke(data_dir, scenarios=["happy"])
    assert missing["available"] is False and missing["stop_reason"] == "provider_config_missing"
    assert Path(missing["provider_config"]) == data_dir / "providers.json"
    (data_dir / "providers.json").write_text(json.dumps({
        "providers": [{"id": "fake-provider", "name": "Fake", "base_url": ""}],
        "models": [{"id": "fake-model", "provider_id": "fake-provider", "model": "fake-script",
                    "protocol": "fake",
                    "context_window": 32_000, "max_output_tokens": 4_096}],
        "bindings": {department: {"provider_id": "fake-provider", "model_id": "fake-model"}
                     for department in ("product", "engineering", "quality")},
    }), encoding="utf-8")
    report = run_smoke(data_dir, scenarios=["happy"], startup_mode="test")
    assert Path(report["provider_config"]) == data_dir / "providers.json", report
    assert report["available"] is True, report
