"""组合 run 的模型输入审计：连续输入 v2 + 部门指导 + 专家协作 + 最终独立 QA 放行。"""

import json
from dataclasses import asdict

import pytest

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.models import ArtifactRef, EventType, canonical_hash, json_dumps
from harness.proposals import (
    answer_turn, ask_turn, delivery_turn, guidance_response,
    product_spec, product_spec_turn,
)
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.smoke import isolation_fields
from harness.tests.helpers import quality_turns, recorded_context, system_on_copy
from harness.tests.saved_rewrite import rewrite_saved_event, rewrite_saved_events

INPUT_V2 = "Also print a status column in the export.\r\n"

# 等 PRD 第 2 版被接纳时让出的次数上限（每次让出 10 毫秒，最多两秒）
WAIT_LIMIT = 200

def _guidance_ids(request):
    return [item["id"] for item in json.loads(prompt_part(request, "department_guidance"))]

def _spec_revision(system, run_id):
    projection = system.project(run_id)
    return 0 if projection.product_spec is None else projection.product_spec.revision

def _list_files(request):
    return ModelResponse(output=[{
        "id": f"inspect-{request.step_id}", "call_id": f"inspect-{request.step_id}", "type": "function_call",
        "name": "list_files", "arguments": "{}",
    }])

# 需要一份真实运行记录的文件：module 作用域的夹具跑一次完整循环并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上改写与检查。数据来自真实运行，登记为集成层。

@pytest.fixture(scope="module")
def saved_combined(tmp_path_factory):
    # 一次走完的组合 run：连续输入 v2 + 部门指导 + 专家协作 + 质检放行。
    # 这项检查要读回请求的顺序：请求本身在调用清单里，清单随数据目录保存
    holder = {}

    def in_flight_changes(request):
        # 工程第一次请求在途时：两条工程指导 + 用户连续输入 v2；
        # 这一轮不因此结束（工单 #964），旧回复的 list_files 照常执行，下一步收到通知。
        system = holder["system"]
        system.add_guidance(request.run_id, "engineering", "请解释当前导出格式的处理边界。")
        system.add_guidance(request.run_id, "engineering", "请在交付文件头部标注导出格式。")
        system.add_input(request.run_id, INPUT_V2)
        # 等 PRD 第 2 版被接纳以后再交出这一轮的回答：工程处理指导的那一轮因此一定在第 2 版之后开始。
        # 这一轮跑出来的检查绑定的是它开始时的 PRD 版本（第 2 版），回执才会被采用；
        # 早于第 2 版开始的回执按当前 PRD 核对时算过时，guidance_results 为空，用例会报 StopIteration。
        # 等待写成生成器：逐条交出流式片段，把控制权还给事件循环，产品的那一轮才有机会跑完。
        for _ in range(WAIT_LIMIT):
            if _spec_revision(system, request.run_id) >= 2:
                break
            yield ModelStreamEvent(kind="stream_event", id="wait-for-spec-v2")
        assert _spec_revision(system, request.run_id) >= 2, "PRD 第 2 版没有被接纳"
        return _list_files(request)

    def remember_guidance_then_check(request):
        holder["guidance_ids"] = _guidance_ids(request)
        return FakeTurn(checks={"probe": 0})

    def explain_first(request):
        return FakeTurn(proposal=guidance_response(
            holder["guidance_ids"][0], status="explained", text="当前导出格式边界已由有效合同覆盖，无需改动。",
        ))

    def explain_second(request):
        return FakeTurn(proposal=guidance_response(
            _guidance_ids(request)[0], status="explained", text="将在交付时于文件头部标注导出格式。",
        ))

    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列。
    # 共用一个队列时哪个部门拿到哪一项随请求先后变化，脚本项会串部门）
    adapter = FakeAdapter({
        "product": [
            product_spec(),
            product_spec_turn(
                requirements=["print the given argument to stdout", "print a status column in the export"],
                change_record={
                    "changed": ["The export includes a status column"],
                    "retained": ["Ordinary input is printed unchanged"],
                    "retired": [],
                    "rationale": "The user's additional original input asks for a status column.",
                },
            ),
        ],
        "engineering": [
            in_flight_changes,
            remember_guidance_then_check, explain_first,
            explain_second,
            ask_turn("product", "Is the status column part of the acceptance criteria?",
                     background="Engineering is planning the export.",
                     expected="Confirm the acceptance basis without changing files."),
            delivery_turn(files={"src/echo.py": "# export-format: csv\nimport sys\nprint(sys.argv[1])\n"}),
        ],
        # 询问分支的会话按被询问的部门区分（工单 #557）
        "product:ask": [
            answer_turn("The status column is part of the accepted requirements."),
        ],
        # 质检关注「PRD 被接纳」：PRD 的每一次修订与每一份新交付都让质检开始一轮工作。
        # 每一轮按这一轮开始时有没有交付决定做什么（预测性探索或核验）
        "quality": quality_turns("release", "Independent quality check passed on the current delivery."),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path_factory.mktemp("combined"), adapter)
    holder["system"] = system
    run_id = system.create_run("build an export CLI", max_cycles=20)
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"
    invocations = list(adapter.invocations)
    system.close()
    return system.data_dir, run_id, projection, invocations

@pytest.fixture
def combined_run(saved_combined, tmp_path):
    # 每项测试在自己的数据目录副本上改写与检查
    saved, run_id, projection, invocations = saved_combined
    return system_on_copy(saved, tmp_path / "combined"), run_id, projection, invocations

def test_combined_run_shape(combined_run):
    system, run_id, projection, invocations = combined_run
    assert projection.status == "done" and projection.stop_reason == "released", (projection.stop_reason, projection.error)
    assert projection.input_version == projection.processed_input_version == 2
    assert projection.product_spec.revision == 2
    assert [item.status for item in projection.department_guidance] == ["explained", "explained"]
    events = system.store.list_events(run_id)
    ask_answered = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered) == 1 and ask_answered[0].payload["status"] == "answered"
    # 工单 #964：输入到达不再结束工程这一轮，旧回复里的只读调用照常执行（部门接着工作）
    assert any(event.type == EventType.TOOL_CALLED and event.payload.get("name") == "list_files"
               for event in events)
    # 指导进了工程的模型输入（设计说明第 6 节），由工程回答：
    # 同时运行以后这一轮是不是「只回应指导」的一轮取决于别的部门有没有先做完，
    # 这里断言的是指导的处理结果，不断言是哪一轮处理的
    guidance_requests = [request for request in invocations
                         if (text := prompt_part(request, "department_guidance")) and json.loads(text)]
    assert guidance_requests and {request.department for request in guidance_requests} == {"engineering"}
    answered = [event for event in events if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert len(answered) == 2
    # 处理指导的那一轮里跑的是检查，不是写入
    results = next(json.loads(text) for request in invocations
                   if (text := prompt_part(request, "guidance_results")) and json.loads(text))
    assert {item["name"] for item in results} == {"run_check"}

def test_model_input_audit_verifies_combined_run(combined_run):
    system, run_id, _projection, invocations = combined_run
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["model_input_audit"]["status"] == "verified", fields["model_input_audit"]["notes"]
    assert fields["context_isolated"] is True
    # 审计覆盖每一次发过请求的激活：同时运行以后激活的个数随运行变化，不写死
    assert fields["model_input_audit"]["activation_count"] == len({r.activation_id for r in invocations})

def test_snapshot_gated_guidance_results_after_a_no_op_write_are_verified(tmp_path):
    """写操作之后、下一次检查之前仍有待处理指导且检查结果可认领：审计靠记录下来的快照重建，而不是推断。"""

    holder = {}
    code = "import sys\nprint(sys.argv[1])\n"

    def remember_guidance_write_and_check(request):
        holder["guidance_ids"] = _guidance_ids(request)
        return FakeTurn(writes={"src/echo.py": code}, checks={"probe": 0})

    adapter = FakeAdapter([product_spec(),])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")

    system.add_guidance(run_id, "engineering", "请先核对当前文件，再说明处理边界。")
    adapter.script.extend([
        remember_guidance_write_and_check,
        FakeTurn(writes={"src/echo.py": code}),  # 内容相同的再次写入：树不变，但它是最后一次成功的工具操作
        lambda request: FakeTurn(proposal=guidance_response(
            holder["guidance_ids"][0], status="explained", text="已核对文件与检查结果，边界无需变更。",
        )),
    ])
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status == "explained"
    last = adapter.invocations[-1]
    assert recorded_context(system, last).manifest.guidance_only is False and last.step_id == 3
    results = json.loads(prompt_part(last, "guidance_results"))
    assert {item["name"] for item in results} == {"write_file", "run_check"}
    assembled = [event for event in system.store.list_events(run_id) if event.type == EventType.CONTEXT_ASSEMBLED]
    assert all(isinstance(event.payload.get("snapshot_hash"), str) and event.payload["snapshot_hash"] for event in assembled)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["model_input_audit"]["status"] == "verified", fields["model_input_audit"]["notes"]

@pytest.mark.parametrize("mutation,expected", [
    ("other_snapshot", "pinned developer input differs"),
    ("missing_snapshot", "does not record the workspace snapshot"),
])
def test_model_input_audit_rejects_tampered_or_missing_snapshot_record(combined_run, mutation, expected):
    system, run_id, _projection, _invocations = combined_run
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    events = _saved_events(system, run_id)
    assembled = next(
        event for event in events if event.type == EventType.CONTEXT_ASSEMBLED
        and any(part["source"] == "guidance_results" and json.loads(part["text"])
                for part in json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["parts_ref"]))))
    )
    if mutation == "other_snapshot":
        assembled.payload["snapshot_hash"] = canonical_hash("another workspace")
    else:
        del assembled.payload["snapshot_hash"]
    rewrite_saved_event(system.store, assembled)
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any(expected in note for note in audit["notes"]), audit["notes"]

def _saved_events(system, run_id):
    # 审计读到的必须是事件库中保存的事件；测试改动以后写回事件行，再经公开接口运行审计
    return system.store.list_events(run_id)

def _rehash_request(system, events, assembled, request):
    ref = system.artifacts.put(assembled.run_id, "model_request", json_dumps(request), media_type="application/json")
    assembled.payload["request_ref"] = asdict(ref)
    assembled.payload["digest"] = assembled.context_digest = canonical_hash(request)
    assembled.artifact_hashes = [ref.content_hash]
    attempted = next(item for item in events if item.type == EventType.MODEL_REQUESTED
                     and item.payload["activation_id"] == assembled.payload["activation_id"]
                     and item.payload["step_id"] == assembled.payload["step_id"])
    attempted.context_digest = assembled.context_digest
    rewrite_saved_events(system.store, [assembled, attempted])

@pytest.mark.parametrize("mutation,expected", [
    ("private_text_in_guidance", "pinned developer input differs"),
    ("guidance_only_flag", "guidance_only does not match"),
])
def test_model_input_audit_rejects_tampered_guidance_request(combined_run, mutation, expected):
    system, run_id, _projection, _invocations = combined_run
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    events = _saved_events(system, run_id)
    if mutation == "private_text_in_guidance":
        # 处理指导的那一次激活：它的固定输入里有指导的内容
        activated = next(event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED
                         and event.payload.get("guidance_ids"))
        assembled = next(event for event in events if event.type == EventType.CONTEXT_ASSEMBLED
                         and event.payload["activation_id"] == activated.payload["activation_id"]
                         and event.payload["step_id"] == 1)
        request = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**assembled.payload["request_ref"])))
        request["input"][0]["content"] = request["input"][0]["content"].replace(
            "[department_guidance]\n", "[department_guidance]\n[product_private_transcript] PRIVATE_PRODUCT_CANARY\n", 1,
        )
        _rehash_request(system, events, assembled, request)
    else:
        # 把一次普通激活记成「只回应指导」的一轮：审计按事件重新判定，对不上
        activated = next(event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED
                         and event.payload.get("guidance_only") is False)
        activated.payload["guidance_only"] = True
        rewrite_saved_event(system.store, activated)
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any(expected in note for note in audit["notes"]), audit["notes"]
