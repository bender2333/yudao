# 一个事项里多个会话同时运行（工单 #557）：PRD 被接纳以后工程与质检各开始一轮工作，各自一个会话；
# 质检在预测性探索里按 PRD 起草测试用例，交付到达以后开始新一轮工作，核验并放行。
# 取消与暂停作用于事项的全部会话。

import json
import uuid
from pathlib import Path

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.environment import QA_TESTS_DIR, inspection_root
from harness.event_store import Command
from harness.models import EventType, json_dumps
from harness.projection import saved_decisions
from harness.proposals import (answer_turn, ask_turn, delivery, delivery_turn, product_spec,
                                product_spec_turn, review, review_turn)
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.helpers import guidance_reply, quality_turns

CHECKS = {"smoke": {"command": "python -c \"print('smoke ok')\""}}
ECHO = "import sys\nprint(sys.argv[1])\n"
TEST_FILE = f"{QA_TESTS_DIR}/test_echo.py"
TEST_CONTENT = "import sys\nprint('QA_TEST_DRAFTED')\nsys.exit(0)\n"


def _call(identity: str, name: str, arguments: dict) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _explore() -> FakeTurn:
    # 质检的预测性探索：按 PRD 起草测试用例，写进质检自己的测试材料；
    # 这一轮没有交付可以核验，提交的结论被拒绝
    return FakeTurn(
        writes={TEST_FILE: TEST_CONTENT},
        proposal=review("release", "按 PRD 起草了测试用例；还没有交付可以核验"),
    )


def _release():
    # 放行按请求里装配好的当前交付声明依据版本（工单 #471）
    return review_turn("release", "checks passed on the current snapshot", checks=CHECKS)


def _events(system: LoopSystem, run_id: str) -> list:
    return system.store.list_events(run_id)


def _position(events: list, event_type: str, department: str, *, name: str | None = None) -> int:
    for event in events:
        if event.type != event_type or event.department != department:
            continue
        if name is not None and (event.payload or {}).get("name") != name:
            continue
        return event.position
    raise AssertionError(f"no {event_type} event for {department}")


def test_engineering_and_quality_work_at_the_same_time(tmp_path: Path) -> None:
    # 交付到达以后质检核验并放行；工程写入与质检起草测试用例的事件交错出现
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [_explore(), _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"

    events = _events(system, run_id)
    sessions = {event.session_id for event in events if event.type == EventType.DEPARTMENT_ACTIVATED}
    # 三个部门各有一个会话
    assert len(sessions) == 3
    # 质检的预测性探索与工程的写入交错：质检写测试材料在工程写文件之后、工程提交交付之前
    engineering_write = _position(events, EventType.TOOL_CALLED, "engineering", name="write_file")
    quality_write = _position(events, EventType.TOOL_CALLED, "quality", name="write_file")
    delivery = _position(events, EventType.DELIVERY_ACCEPTED, "engineering")
    assert engineering_write < quality_write < delivery
    # 交付到达以后质检开始新一轮工作：质检有两个激活（预测性探索与核验）
    quality_activations = [event for event in events
                            if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == "quality"]
    assert len(quality_activations) == 2
    # 质检核验并放行
    assert [event.type for event in events if event.type == EventType.QA_SUBMITTED]
    assert projection.stop_reason == "released"


def test_predictive_exploration_reads_the_project_start_not_the_delivery(tmp_path: Path) -> None:
    # 第一份交付还不存在时，质检的检查工作区来自事项开始时的项目起点：
    # 读不到工程尚未交付的修改；质检写的测试保存为测试材料的一个版本
    def explore(call):
        # 先读工程写的文件：质检的检查工作区里没有它
        raw = prompt_part(call, "current_delivery_spec")
        return ModelResponse(output=[
            _call("read-1", "read_file", {"path": "src/echo.py"}),
            _call("write-1", "write_file", {"path": TEST_FILE, "content": TEST_CONTENT}),
            _call("submit-1", "submit_review", {
                "verdict": "release", "rationale": "按 PRD 起草了测试用例；还没有交付可以核验",
                "checks": ["smoke"], "defects": [], "basis_delivery_spec_hash": None}),
        ])

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [explore, _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"

    events = _events(system, run_id)
    read = next(event for event in events
                if event.type == EventType.TOOL_CALLED and event.department == "quality"
                and (event.payload or {}).get("name") == "read_file")
    assert read.payload.get("ok") is False, "质检的检查工作区里没有工程尚未交付的文件"
    # 质检写的测试保存为测试材料的一个版本
    saved = [event for event in events if event.type == EventType.QA_TESTS_SAVED]
    assert len(saved) == 1
    assert saved[0].payload["version"] == 1
    assert saved[0].payload["content_hash"]


def test_quality_cannot_write_into_the_runtime_workspace(tmp_path: Path) -> None:
    # 质检在预测性探索中写入运行工作区被拒绝：它只能写自己的测试材料
    def explore(call):
        return ModelResponse(output=[
            _call("write-runtime", "write_file", {"path": "src/echo.py", "content": ECHO}),
            _call("write-tests", "write_file", {"path": TEST_FILE, "content": TEST_CONTENT}),
            _call("submit-1", "submit_review", {
                "verdict": "release", "rationale": "按 PRD 起草了测试用例；还没有交付可以核验",
                "checks": ["smoke"], "defects": [], "basis_delivery_spec_hash": None}),
        ])

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [explore, _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    system.run_until_stop(run_id)

    events = _events(system, run_id)
    writes = {event.payload.get("id"): event for event in events
              if event.type == EventType.TOOL_CALLED and event.department == "quality"
              and (event.payload or {}).get("name") == "write_file"}
    assert set(writes) == {"write-runtime", "write-tests"}
    # 写入运行工作区被拒绝；写自己的测试材料被允许
    assert writes["write-runtime"].payload.get("ok") is False, "质检写入运行工作区被拒绝"
    assert writes["write-tests"].payload.get("ok") is True
    # 工程写的交付文件没有被质检改掉
    projection = system.project(run_id)
    assert projection.delivery_spec is not None


def test_cancel_stops_every_session(tmp_path: Path) -> None:
    # 取消事项时全部会话停止
    def explore(call):
        return ModelResponse(output=[
            _call("write-1", "write_file", {"path": TEST_FILE, "content": TEST_CONTENT}),
        ])

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [explore],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    system.activate_once(run_id)
    cancelled = system.cancel(run_id)
    assert (cancelled.status, cancelled.stop_reason) == ("failed", "cancelled")
    events = _events(system, run_id)
    finished = [event for event in events if event.type == EventType.ACTIVATION_FINISHED]
    # 已经开始的会话都结束了，没有一个会话还在进行
    assert {event.session_id for event in finished} == {event.session_id for event in events
                                                        if event.type == EventType.DEPARTMENT_ACTIVATED}
    # 取消以后结束的会话都记着取消这个原因
    assert all(event.payload.get("stop_reason") == "cancelled"
               for event in finished if event.department != "product")


def test_pause_and_continue_lets_each_session_resume_where_it_stopped(tmp_path: Path) -> None:
    # 暂停以后继续，各会话从停下的位置接着工作（工单 #557 验收第 8 条）：
    # 工程的会话连续只回复文字，运行以 no_tool_call 暂停；用户回答「继续」以后，
    # 工程从停下的位置接着工作——它下一步的请求里已经有暂停以前做过的步骤，
    # 交付里也有暂停以前写下的文件
    def text_only(call):
        return FakeTurn(transcript="我先想想。")

    adapter = FakeAdapter({
        "product": [product_spec()],
        # 先写文件，再连续只回复文字（运行因此暂停），继续以后交付
        "engineering": [
            FakeTurn(writes={"src/echo.py": ECHO}),
            text_only, text_only, text_only, text_only,
            delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS),
        ],
        "quality": [_explore(), _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    paused = system.run_until_stop(run_id)
    assert (paused.status, paused.stop_reason) == ("paused", "no_tool_call")

    events = _events(system, run_id)
    # 暂停以前工程写过文件：这一步的结果在这个会话的历史里
    written = [event for event in events
               if event.type == EventType.TOOL_CALLED and event.department == "engineering"
               and (event.payload or {}).get("name") == "write_file"]
    assert written, "暂停以前工程没有写文件"
    write_call_id = written[0].payload.get("id")

    # 用户回答「处理以后继续执行」
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1, [decision.decision_id for decision in decisions]
    [decision] = decisions
    assert decision.request["kind"] == "no_tool_call"
    command = Command(str(uuid.uuid4()), "decision.answer", "sha256:continue:1", "user:local")
    system.orchestrator.answer_decision(decision.decision_id, "continue", None,
                                        base_version=decision.version, command=command)
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    continued = next(event for event in events if event.type == EventType.RUN_CONTINUED)
    # 继续以后工程又发了请求：这个请求里有暂停以前那一步的结果（会话从停下的位置接着工作）
    resumed = [event for event in events
               if event.type == EventType.MODEL_REQUESTED and event.department == "engineering"
               and event.position > continued.position]
    assert resumed, "继续以后工程没有接着工作"
    request = next(call for call in adapter.invocations
                   if call.department == "engineering"
                   and call.activation_id == resumed[0].payload["activation_id"]
                   and call.step_id == resumed[0].payload["step_id"])
    outputs = [item for item in request.input_items
               if isinstance(item, dict) and item.get("type") == "function_call_output"
               and item.get("call_id") == write_call_id]
    assert outputs, "继续以后的请求里没有暂停以前那一步的结果"
    # 交付在继续以后到达，交付的内容是暂停以前写下的文件
    accepted = [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    assert accepted, "继续以后没有交付"
    assert accepted[0].position > continued.position
    released = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert released and released[0].payload.get("verdict") == "release"


def test_an_ask_branch_receives_the_new_prd_version_and_answers(tmp_path: Path) -> None:
    # 另一个会话修订了 PRD，进行中的询问分支在下一步收到 PRD 新版本的通知并接着回答，
    # 提问方拿到回答（工单 #558：删除「工作依据一变化就结束激活」的规则，
    # PRD 的新版本作为通知送达，循环结构第 5 节）
    holder: dict[str, object] = {}
    seen: dict[str, str | None] = {}

    def revise(call):
        # 分支会话工作期间，产品的另一个会话修订了 PRD：产品的指导让它的主线会话开始一轮工作，
        # 那一轮提交修订版的产品要求（同时运行的会话）
        holder["system"].add_guidance(call.run_id, "product", "请按新的要求修订产品要求。")
        for _ in range(200):
            if len(holder["system"].project(call.run_id).effective_contracts) >= 2:
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        # 这一步先做一件不结束分支的事：下一步收到通知以后再提交回答
        return ModelResponse(output=[_call("read-1", "list_files", {})])

    def answer(call):
        seen["notification"] = prompt_part(call, "work_notification")
        return answer_turn("已按新的要求修订产品要求。")(call)

    adapter = FakeAdapter({
        "product": [
            product_spec(),
            product_spec_turn(goal="Build an echo CLI v2",
                              requirements=["print the given argument to stdout"],
                              acceptance=["echo hello prints hello"],
                              change_record={
                                  "changed": ["The requirements are stated once"],
                                  "retained": ["The echo CLI scope"],
                                  "retired": [],
                                  "rationale": "The user asked for a revised contract.",
                              }),
            guidance_reply("已按新的要求修订产品要求。"),
        ],
        "engineering": [ask_turn(), delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "product:ask": [revise, answer],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    answered = [event for event in events if event.type == EventType.ASK_ANSWERED]
    assert len(answered) == 1
    payload = answered[0].payload
    assert payload["status"] == "answered", payload
    assert payload["answer"]
    # 分支在下一步收到了 PRD 新版本的通知（新版本号与改动）
    notification = json.loads(seen["notification"])
    assert [item["kind"] for item in notification] == ["product_spec_revised"]
    assert notification[0]["revision"] == 2
    assert notification[0]["change_record"]["changed"] == ["The requirements are stated once"]
    # 提问方拿到回答以后接着工作：交付到达，质检放行
    assert [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    released = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert released and released[0].payload.get("verdict") == "release"


def test_quality_receives_the_delivery_as_a_notification_and_rebuilds_its_workspace(tmp_path: Path) -> None:
    # 验收第 1 条：质检在一轮工作中收到第一份交付，下一步的请求包含交付到达的通知，
    # 检查工作区换成这份交付的内容，交付之前写的测试仍在；用这些测试运行 run_check，
    # 回执绑定交付快照与测试材料的版本。返工后收到第二份交付时相同。
    holder: dict[str, object] = {}
    seen: dict[str, str | None] = {}
    observed: dict[str, dict[str, str]] = {}

    def workspace_files():
        # 质检的检查工作区在事项结束时删除：内容在这一轮还在时记下来
        root = inspection_root(tmp_path / "workspaces" / run_id,
                               system.orchestrator.sessions.get(run_id, "quality").session_id)
        files: dict[str, str] = {}
        for path in root.rglob("*"):
            if path.is_file():
                files[str(path.relative_to(root)).replace("\\", "/")] = path.read_text(encoding="utf-8")
        return files

    def deliver(call, summary):
        # 工程等质检的测试材料保存以后再交付：交付在质检的一轮工作期间到达
        for _ in range(200):
            if holder["system"].project(call.run_id).qa_tests_version >= 1:
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        return delivery_turn(summary=summary, files={"src/echo.py": ECHO}, checks=CHECKS)(call)

    def first_delivery(call):
        return deliver(call, "implemented echo CLI")

    def second_delivery(call):
        return deliver(call, "revised echo CLI")

    def wait_for_delivery(call):
        # 质检这一步等交付到达：交付到达以后下一步的请求里才有通知
        for _ in range(200):
            if holder["system"].project(call.run_id).delivery_spec is not None:
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        return ModelResponse(output=[_call("read-1", "list_files", {})])

    def review(call, key, verdict, writes=None):
        seen[key] = prompt_part(call, "work_notification")
        if key == "second":
            observed["files"] = workspace_files()
        defects = ([{"severity": "major", "summary": "the sealed output misses a newline"}]
                   if verdict == "rework_engineering" else None)
        turn = review_turn(verdict, "checks passed on the current snapshot", checks=CHECKS,
                           defects=defects)
        result = turn(call)
        if writes:
            result = FakeTurn(writes=writes, proposal=result.proposal, checks=result.checks)
        return result

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [first_delivery, second_delivery],
        "quality": [
            # 预测性探索：起草测试用例（写进质检自己的测试材料），另写一个不在材料里的文件
            FakeTurn(writes={TEST_FILE: TEST_CONTENT, "scratch/marker.txt": "MARK\n"}),
            wait_for_delivery,
            # 这一轮开始时还没有交付，是预测性探索：结论被拒绝，这一轮到这里结束
            lambda call: review(call, "first", "release"),
            # 下一轮面对交付：核验并退回返工
            lambda call: review(call, "rework", "rework_engineering",
                                writes={"scratch/second.txt": "SECOND\n"}),
            # 返工后的新交付到达：这一轮核验并放行
            lambda call: review(call, "second", "release"),
        ],
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    deliveries = [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    assert len(deliveries) == 2, "两份交付都到达了"
    reviews = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert len(reviews) == 2

    # 下一步的请求包含交付到达的通知（新版本号与改动）
    notification = json.loads(seen["first"])
    assert [item["kind"] for item in notification] == ["delivery_arrived"]
    assert notification[0]["content_hash"] == deliveries[0].payload["content_hash"]
    notification = json.loads(seen["second"])
    assert [item["kind"] for item in notification] == ["delivery_arrived"]
    assert notification[0]["content_hash"] == deliveries[1].payload["content_hash"]

    # 检查工作区换成这份交付的内容：交付之前写的测试仍在（来自测试材料），
    # 不在测试材料里的那两个文件随重建消失
    files = observed["files"]
    assert files["src/echo.py"] == ECHO
    assert files[TEST_FILE] == TEST_CONTENT
    assert "scratch/marker.txt" not in files
    assert "scratch/second.txt" not in files

    # 回执绑定交付快照与测试材料的版本：两次检查都绑定各自的交付与当前的测试材料
    for review_event, delivery in zip(reviews, deliveries):
        [check] = review_event.payload["checks"]
        assert check["delivery_spec_hash"] == delivery.payload["content_hash"]
        assert check["qa_tests_hash"], "检查回执绑定测试材料的版本"
        assert check["exit_code"] == 0


def test_engineering_receives_the_new_prd_version_and_delivers_against_it(tmp_path: Path) -> None:
    # 验收第 3 条：质检在预测性探索中询问产品，产品在分支里修订 PRD；
    # 正在工作的工程在下一步收到通知并接着工作，随后提交的交付依据新版本
    holder: dict[str, object] = {}
    seen: dict[str, str | None] = {}

    def work_while_the_prd_changes(call):
        # 工程这一轮先写文件；产品在询问分支里修订 PRD 以后，
        # 工程在下一步收到通知并接着工作
        for _ in range(200):
            if len(holder["system"].project(call.run_id).effective_contracts) >= 2:
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        return FakeTurn(writes={"src/echo.py": ECHO})

    def deliver(call):
        seen["notification"] = prompt_part(call, "work_notification")
        return delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)(call)

    adapter = FakeAdapter({
        "product": [product_spec()],
        "product:ask": [answer_turn(
            answer="已补上空输入的验收标准。",
            requirements=["print the given argument to stdout"],
            acceptance=["empty input prints a blank line"],
            change_record={
                "changed": ["The empty input behavior"],
                "retained": ["The echo CLI scope"],
                "retired": [],
                "rationale": "Quality asked for the empty input behavior.",
            })],
        "engineering": [work_while_the_prd_changes, deliver],
        "quality": [ask_turn(recipient="product",
                             question="空输入的行为没有写进验收标准，请修订 PRD。"),
                    *quality_turns("release", "checks passed on the current snapshot")],
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    # 质检在预测性探索中询问产品，产品的分支修订了 PRD
    asked = [event for event in events if event.type == EventType.ASK_STARTED]
    assert asked and asked[0].payload["recipient"] == "product"
    specs = [event for event in events if event.type == EventType.SPEC_ACCEPTED]
    assert len(specs) == 2, "PRD 有了新版本"

    # 正在工作的工程在下一步收到 PRD 新版本的通知（新版本号与改动），然后接着工作
    notification = json.loads(seen["notification"])
    assert [item["kind"] for item in notification] == ["product_spec_revised"]
    assert notification[0]["revision"] == 2
    assert notification[0]["change_record"]["changed"] == ["The empty input behavior"]

    # 随后提交的交付依据新版本
    delivery = next(event for event in events if event.type == EventType.DELIVERY_ACCEPTED)
    assert delivery.payload["product_spec_hash"] == specs[1].payload["content_hash"]
    assert delivery.payload["effective_contract_hash"] == projection.effective_contract.content_hash
    released = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert released and released[0].payload.get("verdict") == "release"


def test_the_inspection_workspace_survives_the_ask_and_is_rebuilt_by_a_new_delivery(tmp_path: Path) -> None:
    # 验收第 7 条：质检在检查工作区写入一个文件、安装一个依赖以后询问产品并得到回答，
    # 下一步这个文件与依赖仍在；只有新交付封存以后检查工作区才重建
    holder: dict[str, object] = {}
    seen: dict[str, object] = {}

    def workspace_files():
        # 质检的检查工作区在事项结束时删除：内容在这一轮还在时记下来
        root = inspection_root(tmp_path / "workspaces" / run_id,
                               system.orchestrator.sessions.get(run_id, "quality").session_id)
        files: dict[str, str] = {}
        for path in root.rglob("*"):
            if path.is_file():
                files[str(path.relative_to(root)).replace("\\", "/")] = path.read_text(encoding="utf-8")
        return files

    def write_and_install(call):
        # 质检在自己的检查工作区里写一个文件、装一个依赖
        return ModelResponse(output=[
            _call("bash-1", "bash", {"command": "mkdir -p notes && printf 'FINDING\\n' > notes/finding.md"}),
            _call("bash-2", "bash", {"command": "mkdir -p vendor/lib && printf dep > vendor/lib/dep.txt"}),
        ])

    def ask_product(call):
        return ask_turn(recipient="product", question="验收标准要不要补上空输入？")

    def verify(call):
        # 询问以后的下一步：这个文件与依赖仍在
        seen["after_ask"] = workspace_files()
        holder["verified"] = True
        review = review_turn("release", "the exploration has no delivery to review", checks=CHECKS)(call)
        return ModelResponse(output=[
            _call("read-1", "read_file", {"path": "notes/finding.md"}),
            _call("bash-2", "bash", {"command": "cat vendor/lib/dep.txt"}),
            _call("submit-3", "submit_review",
                  {key: value for key, value in review.proposal.items() if key != "kind"}),
        ])

    def after_the_new_delivery(call):
        # 新的交付封存以后：通知送达，检查工作区从这份交付重建
        seen["notification"] = prompt_part(call, "work_notification")
        seen["after_delivery"] = workspace_files()
        return review_turn("release", "checks passed on the current snapshot", checks=CHECKS)(call)

    def deliver_after_the_check(call):
        for _ in range(200):
            if holder.get("verified"):
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        return delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)(call)

    adapter = FakeAdapter({
        "product": [product_spec()],
        "product:ask": [answer_turn("验收标准已经写明空输入。")],
        "engineering": [deliver_after_the_check],
        "quality": [write_and_install, ask_product, verify, after_the_new_delivery],
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    # 询问得到了回答
    answered = [event for event in events if event.type == EventType.ASK_ANSWERED]
    assert len(answered) == 1 and answered[0].payload["status"] == "answered"

    # 询问以后的下一步：文件与依赖仍在检查工作区里
    files = seen["after_ask"]
    assert files["notes/finding.md"] == "FINDING\n"
    assert files["vendor/lib/dep.txt"] == "dep"

    # 只有新交付封存以后检查工作区才重建：重建以后那份文件与依赖都不在了
    notification = json.loads(seen["notification"])
    assert [item["kind"] for item in notification] == ["delivery_arrived"]
    files = seen["after_delivery"]
    assert "notes/finding.md" not in files
    assert "vendor/lib/dep.txt" not in files
    assert files["src/echo.py"] == ECHO
